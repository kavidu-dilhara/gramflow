#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU Affero General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU Affero General Public License for more details.
#  You should have received a copy of the GNU Affero General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""
Lightweight, dependency-free JSON state store for GramFlow.

Used for two independent purposes:
  1. Resume/skip tracking - a record of files that were already
     uploaded successfully in a previous run of the *same* upload
     job, so re-running after a crash/Ctrl+C doesn't re-upload
     everything from scratch.
  2. Whole-batch progress - running totals (files done/failed/total,
     bytes done/total) so a single status message can show batch-wide
     progress instead of only per-file progress.

Design notes:
  - Nothing here touches upload timing, concurrency, or sleep
    intervals. This module only records/reads state; it never decides
    how fast anything uploads.
  - Writes are atomic (write to a temp file in the same directory,
    then os.replace) so a crash mid-write cannot corrupt the on-disk
    file - the reader either sees the old complete file or the new
    complete file, never a half-written one.
  - All reads/writes are best-effort: a corrupt or unreadable state
    file is treated as "no state yet" rather than crashing the whole
    upload. Resume/progress tracking is a convenience feature and
    must never be the reason an upload fails.
"""

import json
import os
import tempfile
import time

from .config import BASE_DIR

STATE_DIR = os.path.join(BASE_DIR, "state")


def _job_key(dir_path: str, dest_chat) -> str:
    """ Build a stable, filesystem-safe key identifying one "upload
    job" - a specific (source directory, destination chat) pair.
    Re-running the same job (same folder, same chat) resumes; a
    different folder or a different destination starts fresh.
    """
    raw = f"{os.path.abspath(dir_path)}::{dest_chat}"
    # BUG-SAFE: avoid pulling in hashlib just for a filename; a simple
    # stable numeric hash is enough since this is only ever used as a
    # local cache-file name, not for anything security-sensitive.
    digest = 0
    for ch in raw:
        digest = (digest * 131 + ord(ch)) & 0xFFFFFFFFFFFF
    return f"job-{digest:012x}"


def _state_path(dir_path: str, dest_chat) -> str:
    return os.path.join(STATE_DIR, f"{_job_key(dir_path, dest_chat)}.json")


def _atomic_write_json(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix=".tmp-", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
        os.replace(tmp_path, path)
    except Exception:
        # Best-effort: if the write fails partway, don't leave a
        # stray temp file behind, and don't let this crash the caller.
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except OSError:
            pass


class UploadState:
    """ Tracks resume records and batch progress for one upload job
    (one directory -> one destination chat). Not shared across
    concurrent jobs; each job gets its own state file.
    """

    def __init__(self, dir_path: str, dest_chat):
        self.path = _state_path(dir_path, dest_chat)
        self._data = self._load()

    def _load(self) -> dict:
        default = {
            "version": 1,
            "dir_path": None,
            "dest_chat": None,
            "created_at": time.time(),
            "completed": {},   # "path|size|mtime" -> True
            "failed": [],      # list of paths that failed last run
        }
        if not os.path.exists(self.path):
            return default
        try:
            with open(self.path, "r") as f:
                data = json.load(f)
            if not isinstance(data, dict) or "completed" not in data:
                # Unexpected shape (e.g. from a future/older version)
                # - treat as no usable state rather than crash.
                return default
            return data
        except (json.JSONDecodeError, OSError, ValueError):
            # Corrupt state file. Never let this break the upload -
            # just start fresh, as if nothing had been uploaded yet.
            print(
                f"[warn] resume state at {self.path} is unreadable, "
                f"starting this job fresh"
            )
            return default

    @staticmethod
    def _file_fingerprint(file_path: str) -> str:
        try:
            stat = os.stat(file_path)
            return f"{os.path.abspath(file_path)}|{stat.st_size}|{int(stat.st_mtime)}"
        except OSError:
            return os.path.abspath(file_path)

    def is_done(self, file_path: str) -> bool:
        return self._file_fingerprint(file_path) in self._data["completed"]

    def mark_done(self, file_path: str):
        self._data["completed"][self._file_fingerprint(file_path)] = True
        if file_path in self._data["failed"]:
            self._data["failed"].remove(file_path)
        self._save()

    def mark_failed(self, file_path: str):
        if file_path not in self._data["failed"]:
            self._data["failed"].append(file_path)
        self._save()

    def _save(self):
        # Best-effort persistence - a failure here should never abort
        # an upload that otherwise succeeded.
        try:
            _atomic_write_json(self.path, self._data)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] could not save resume state: {e!r}")

    def has_unresolved_failures(self) -> bool:
        """ True if this job has files recorded as failed in a
        previous or the current run. Used to decide whether the
        on-disk resume state should be kept around after a batch
        finishes (kept if there's something to retry, discarded if
        the whole job completed cleanly).
        """
        return bool(self._data.get("failed"))

    def clear(self):
        """ Wipe all resume records for this job (used by --fresh). """
        self._data["completed"] = {}
        self._data["failed"] = []
        self._save()

    def discard_file(self):
        """ Remove the on-disk state file entirely once a job finishes
        with nothing left to resume. Keeps ~/.config/gramflow/state/
        from accumulating one file per historical upload forever.
        """
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass


class BatchProgress:
    """ Tracks whole-batch counts/bytes so a single status message can
    show overall progress ("12/47 uploaded, 2 failed, 1.2/4.8 GB")
    instead of only per-file progress. Purely additive - does not
    replace or alter the existing per-file progress callback.
    """

    def __init__(self, total_files: int, total_bytes: int):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.done_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.done_bytes = 0
        self.started_at = time.time()

    def file_done(self, size: int):
        self.done_files += 1
        self.done_bytes += size

    def file_failed(self):
        self.failed_files += 1

    def file_skipped(self, size: int):
        self.skipped_files += 1
        self.done_bytes += size

    @property
    def processed_files(self) -> int:
        return self.done_files + self.failed_files + self.skipped_files

    def summary_line(self) -> str:
        from .humanbytes import humanbytes
        pct = (
            (self.done_bytes / self.total_bytes * 100)
            if self.total_bytes else 100.0
        )
        # BUG-SAFE: humanbytes(0) intentionally returns "NaN" (it's
        # designed for reporting transfer sizes, where 0 usually means
        # "unknown"), which would look like an error at the very start
        # of a batch when done_bytes/total_bytes are legitimately 0.
        done_str = humanbytes(self.done_bytes) if self.done_bytes else "0 B"
        total_str = humanbytes(self.total_bytes) if self.total_bytes else "0 B"
        parts = [
            f"<b>Batch progress:</b> {self.processed_files}/{self.total_files} files",
            f"({done_str} / {total_str}, {pct:.1f}%)",
        ]
        if self.skipped_files:
            parts.append(f"- {self.skipped_files} skipped (resumed)")
        if self.failed_files:
            parts.append(f"- {self.failed_files} failed")
        return " ".join(parts)

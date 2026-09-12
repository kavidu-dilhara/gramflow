#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is licensed under the MIT License.
#  You may use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of this software subject to the terms of the MIT License.
#  The software is provided "AS IS", without warranty of any kind, express or
#  implied. See the LICENSE file for the complete license text.

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
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("completed"), dict)
                or not isinstance(data.get("failed", []), list)
            ):
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
        # BUG FIX (resume fingerprint precision): previously used
        # `int(stat.st_mtime)`, truncating to whole seconds. Two
        # distinct modifications to the same file within the same
        # second produced an identical fingerprint, so a file that
        # was overwritten (bad upload, corrupted download, edited
        # again) right after a previous successful upload could be
        # wrongly treated as "already done" and silently skipped on
        # resume. `st_mtime_ns` (nanosecond precision, available on
        # all platforms Python's os.stat supports) makes two distinct
        # writes reliably produce different fingerprints.
        try:
            stat = os.stat(file_path)
            return (
                f"{os.path.abspath(file_path)}|{stat.st_size}|"
                f"{stat.st_mtime_ns}"
            )
        except OSError:
            return os.path.abspath(file_path)

    @staticmethod
    def _legacy_file_fingerprint(file_path: str) -> str:
        """ The pre-fix fingerprint format (integer-second mtime).
        Used only to check old resume records during the one-time
        migration in _load(), so upgrading GramFlow does not silently
        forget every file a user already uploaded.
        """
        try:
            stat = os.stat(file_path)
            return (
                f"{os.path.abspath(file_path)}|{stat.st_size}|"
                f"{int(stat.st_mtime)}"
            )
        except OSError:
            return os.path.abspath(file_path)

    def is_done(self, file_path: str) -> bool:
        if self._file_fingerprint(file_path) in self._data["completed"]:
            return True
        # MIGRATION: a record written by a pre-fix version of GramFlow
        # will be keyed by the old (second-precision) fingerprint. If
        # the file's *current* legacy-format fingerprint matches an
        # old record, honour it as done, rather than re-uploading
        # every previously-completed file after an upgrade. The record
        # is then rewritten under the new, more precise key so future
        # checks no longer need this fallback for this file.
        legacy_key = self._legacy_file_fingerprint(file_path)
        if legacy_key in self._data.get("completed", {}):
            new_key = self._file_fingerprint(file_path)
            self._data["completed"][new_key] = True
            del self._data["completed"][legacy_key]
            self._save()
            return True
        return False

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
        """Return True only for failed files that still exist.

        A user may delete a failed file between runs. Such a path is no
        longer actionable and should not keep the resume-state file alive
        forever.
        """
        failed = self._data.get("failed", [])
        live_failed = [p for p in failed if os.path.exists(p)]
        if live_failed != failed:
            self._data["failed"] = live_failed
            self._save()
        return bool(live_failed)

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

    BUG FIX (processed > total): oversized files used to be excluded
    from `total_files`/`total_bytes` (computed up-front by a walk that
    filters them out) but then counted via `file_failed()` once the
    main loop actually reached them - inflating `processed_files`
    past `total_files` (e.g. "11/10 files"). Oversized files are now
    tracked in their own `oversized_files` bucket, included in
    `total_files`/`total_bytes` from the start (matching the walk in
    upload._count_files_and_bytes, which now includes them too), so
    `processed_files` can never exceed `total_files`.
    """

    def __init__(self, total_files: int, total_bytes: int):
        self.total_files = total_files
        self.total_bytes = total_bytes
        self.done_files = 0
        self.failed_files = 0
        self.skipped_files = 0
        self.oversized_files = 0
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

    def file_oversized(self, size: int):
        """ File exceeds Telegram's max upload size for this account.
        Counted toward `total_files`/`total_bytes` (it was included
        there from the start) and toward `processed_files`, but kept
        separate from `failed_files` since it isn't a failure of the
        upload attempt - the file was never attempted.
        """
        self.oversized_files += 1
        self.done_bytes += size

    @property
    def processed_files(self) -> int:
        return (
            self.done_files + self.failed_files
            + self.skipped_files + self.oversized_files
        )

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
        if self.oversized_files:
            parts.append(f"- {self.oversized_files} skipped (too large)")
        if self.failed_files:
            parts.append(f"- {self.failed_files} failed")
        return " ".join(parts)

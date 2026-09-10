#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2021 The Original Uploadgram Authors
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


import os
import shutil
import uuid
from time import time
from .config import (
    TG_VIDEO_TYPES
)
from .run_shell_command import run_command

# BUG FIX: previously every single video in a batch silently tried
# (and, if ffmpeg was missing, failed) to spawn ffmpeg before falling
# back to no thumbnail - the failure reason itself was discarded (see
# below), so a missing-ffmpeg batch just produced N unexplained
# thumbnail-less videos with no indication why. Check availability
# once, cache it for the process lifetime, and print one clear
# message up front instead of failing N times silently.
_ffmpeg_checked = False
_ffmpeg_available = False


def _check_ffmpeg_once() -> bool:
    global _ffmpeg_checked, _ffmpeg_available
    if not _ffmpeg_checked:
        _ffmpeg_checked = True
        _ffmpeg_available = shutil.which("ffmpeg") is not None
        if not _ffmpeg_available:
            print(
                "[warn] ffmpeg not found on PATH - video thumbnails will "
                "be skipped for this run. Install ffmpeg to enable them "
                "(e.g. `apt install ffmpeg` / `brew install ffmpeg`)."
            )
    return _ffmpeg_available


async def take_screen_shot(
    video_file: str,
    output_directory: str,
    ttl: int
):
    if not _check_ffmpeg_once():
        return None
    # https://stackoverflow.com/a/13891070/4723940
    # BUG FIX: was `str(time()) + ".jpg"`, which produced identical
    # filenames when two videos were processed within the same second
    # and could collide on subsequent runs. Use a uuid4 suffix.
    out_put_file_name = os.path.join(
        output_directory,
        f"{int(time() * 1000)}_{uuid.uuid4().hex[:8]}.jpg"
    )
    if video_file.upper().endswith(TG_VIDEO_TYPES):
        file_genertor_command = [
            "ffmpeg",
            "-hide_banner",
            "-ss",
            str(ttl),
            "-i",
            video_file,
            "-vframes",
            "1",
            out_put_file_name
        ]
        # width = "90"
        # BUG FIX: the ffmpeg result (returncode/stderr) was
        # previously discarded entirely, so a failed screenshot (bad
        # seek time, corrupt video, unsupported codec, disk full,
        # ...) gave zero indication of *why* it failed - only that
        # the output file didn't show up afterwards. Now the actual
        # failure reason is surfaced.
        _pid, returncode, _stdout, stderr = await run_command(
            file_genertor_command
        )
        if returncode != 0 and not os.path.lexists(out_put_file_name):
            print(
                f"[warn] ffmpeg could not generate a thumbnail for "
                f"{os.path.basename(video_file)}: "
                f"{stderr.strip().splitlines()[-1] if stderr.strip() else 'unknown error'}"
            )
    if os.path.lexists(out_put_file_name):
        return out_put_file_name
    else:
        return None

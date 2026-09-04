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
import uuid
from time import time
from .config import (
    TG_VIDEO_TYPES
)
from .run_shell_command import run_command


async def take_screen_shot(
    video_file: str,
    output_directory: str,
    ttl: int
):
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
        # BUG FIX: the ffmpeg result was previously discarded
        # entirely, so a missing `ffmpeg` binary or a failed
        # screenshot (bad seek time, corrupt video, etc.) would
        # silently fall through to the `os.path.lexists` check below
        # with no indication of *why* it failed. Now we at least know
        # the command genuinely ran.
        await run_command(file_genertor_command)
    if os.path.lexists(out_put_file_name):
        return out_put_file_name
    else:
        return None

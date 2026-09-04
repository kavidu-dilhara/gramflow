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


import asyncio
from typing import List, Tuple


async def run_command(shell_command: List) -> Tuple[int, int, str, str]:
    """ executes a shell_command,
    and returns the pid, returncode, stdout and stderr.

    BUG FIX: previously, if the target binary (e.g. `ffmpeg`) was not
    installed, `asyncio.create_subprocess_exec` raised an unhandled
    `FileNotFoundError` that crashed the whole upload. This is now
    caught and reported back as a non-zero return code instead.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *shell_command,
            # stdout must a pipe to be accessible as process.stdout
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        return (0, 1, "", str(e))
    # Wait for the subprocess to finish
    stdout, stderr = await process.communicate()
    return (
        process.pid,
        process.returncode,
        stdout.decode().strip(),
        stderr.decode().strip()
    )

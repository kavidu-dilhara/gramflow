#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2021 The Original Uploadgram Authors
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is licensed under the MIT License.
#  You may use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of this software subject to the terms of the MIT License.
#  The software is provided "AS IS", without warranty of any kind, express or
#  implied. See the LICENSE file for the complete license text.


import asyncio
from typing import List, Optional, Tuple


async def run_command(
    shell_command: List,
    timeout: Optional[int] = None,
) -> Tuple[int, int, str, str]:
    """ executes a shell_command,
    and returns the pid, returncode, stdout and stderr.

    `timeout` (seconds) bounds how long the subprocess may run.
    Previously a hung ffmpeg (corrupt/large video) blocked the upload
    forever; now a timeout kills the process and reports returncode
    124 so callers treat it as a normal, handled failure.

    NOTE: stdout/stderr are decoded as latin-1 (a 1:1 byte<->char
    mapping) so binary output (e.g. ffmpeg rawvideo) survives the
    round-trip without corruption - callers that expect text get
    identical text, and callers that need bytes can .encode("latin-1").
    """
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *shell_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except FileNotFoundError as e:
        return (0, 1, "", str(e))
    except asyncio.TimeoutError:
        if process is not None:
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
        return (0, 124, "", f"command timed out after {timeout}s")
    return (
        process.pid,
        process.returncode,
        stdout.decode("latin-1").strip(),
        stderr.decode("latin-1").strip(),
    )

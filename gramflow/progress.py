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

""" progress helper """


import math
from asyncio import sleep
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import Message
from time import time
from .humanbytes import humanbytes
from .time_formatter import time_formatter


async def progress_for_pyrogram(
    current: int,
    total: int,
    message: Message,
    sfw: int,
    pbar: "tqdm | None",
    ud_type: str,
):
    now = time()
    diff = now - sfw
    if pbar is not None:
        # BUG FIX: this used to call
        # `pbar.update((current / total) * 1024 * 1024)`, which is not
        # a byte delta at all - it multiplied a 0..1 fraction by 1 MiB
        # on every single progress callback, so the console bar's
        # internal counter had no real relationship to the file size
        # and would frequently blow past `total` or look stuck.
        # tqdm.update() wants the *increase* since the last call, and
        # pyrogram's progress callback gives us the *absolute* bytes
        # transferred so far, so the delta is `current - pbar.n`.
        delta = current - pbar.n
        if delta > 0:
            pbar.update(delta)
        if current >= total:
            pbar.set_description("uploaded")
    else:
        # BUG FIX: was `round(diff % 10.00) == 0 or current == total`,
        # which also evaluated True for small fractional remainders
        # (e.g. round(0.04) == 0), causing an immediate edit on the
        # first callback. Use the integer-second 10-second boundary
        # instead so we edit roughly once every 10 s, plus always on
        # the final callback.
        if (int(diff) > 0 and int(diff) % 10 == 0) or current == total:
            try:
                percentage = current * 100 / total
            except ZeroDivisionError:
                percentage = 0
            elapsed_time = round(diff)
            if elapsed_time == 0:
                return
            speed = current / elapsed_time
            time_to_completion = round((total - current) / speed) if speed else 0
            estimated_total_time = elapsed_time + time_to_completion

            elapsed_time = time_formatter(elapsed_time)
            estimated_total_time = time_formatter(estimated_total_time)

            progress = "[{0}{1}] \nP: {2}%\n".format(
                "".join(["\u25AC" for _ in range(math.floor(percentage / 5))]),
                "".join(["\u2591" for _ in range(20 - math.floor(percentage / 5))]),
                round(percentage, 2),
            )

            tmp = progress + "{0} of {1}\nSpeed: {2}/s\nETA: {3}\n".format(
                humanbytes(current),
                humanbytes(total),
                humanbytes(speed),
                estimated_total_time
                if estimated_total_time != ""
                else "0 seconds",
            )
            try:
                await message.edit_text(text=f"{ud_type}\n {tmp}")
            except FloodWait as e:
                await sleep(e.value)
            except MessageNotModified:
                # BUG FIX: the previous bare `except:` swallowed
                # everything, including Ctrl+C (KeyboardInterrupt) and
                # asyncio.CancelledError, since those subclass
                # BaseException, not Exception. Only the genuinely
                # expected "nothing changed" case is ignored now.
                pass

#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2021 The Original Uploadgram Authors
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is licensed under the MIT License.
#  You may use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of this software subject to the terms of the MIT License.
#  The software is provided "AS IS", without warranty of any kind, express or
#  implied. See the LICENSE file for the complete license text.

""" progress helper """


import math
from asyncio import sleep
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import Message
from time import time
from .humanbytes import humanbytes
from .time_formatter import time_formatter

# BUG FIX (item 8 - progress update throttling): previously throttled
# with `int(diff) % 10 == 0`, where `diff` is the time elapsed since
# the transfer *started* - not since the last update. Multiple
# progress callbacks landing within the same integer second (common
# for fast transfers/small chunks) could all satisfy that check and
# each trigger a separate Telegram message edit for the same instant.
# A real last-update timestamp, keyed per Message so concurrent
# uploads/progress messages don't share state, fixes this: an edit
# only happens once at least PROGRESS_UPDATE_INTERVAL seconds have
# actually passed since the previous edit for THAT message.
PROGRESS_UPDATE_INTERVAL = 10  # seconds
_last_update_by_message: "dict[int, float]" = {}


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
        is_final = current >= total
        # BUG FIX (item 8): key last-update time by the target
        # Message's id, not a single module-level scalar, so two
        # uploads progressing concurrently (e.g. if this project ever
        # adds bounded concurrency) don't stomp on each other's
        # throttling state and both still get their own periodic
        # updates and their own guaranteed final update.
        msg_key = getattr(message, "id", id(message))
        last_update = _last_update_by_message.get(msg_key, 0.0)
        # BUG FIX: the final 100% update must always be sent
        # regardless of the interval, so the status message never
        # gets stuck showing a stale in-progress percentage.
        if not is_final and (now - last_update) < PROGRESS_UPDATE_INTERVAL:
            return
        _last_update_by_message[msg_key] = now
        if is_final:
            # Done with this message's progress reporting - drop its
            # throttling entry so `_last_update_by_message` doesn't
            # grow forever across a long batch of many files.
            _last_update_by_message.pop(msg_key, None)

        try:
            percentage = current * 100 / total
        except ZeroDivisionError:
            percentage = 0
        elapsed_time = round(diff)
        if elapsed_time == 0 and not is_final:
            # BUG FIX: this used to return unconditionally, so a fast
            # upload finishing in under a second never got its final
            # 100% update and the status message stayed stuck on a
            # stale in-progress percentage. Only skip mid-flight
            # updates; the final one always goes through (speed/ETA
            # gracefully show 0 in that case).
            return
        speed = current / elapsed_time if elapsed_time > 0 else 0
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
            try:
                await message.edit_text(text=f"{ud_type}\n {tmp}")
            except (FloodWait, MessageNotModified):
                pass
        except MessageNotModified:
            # BUG FIX: the previous bare `except:` swallowed
            # everything, including Ctrl+C (KeyboardInterrupt) and
            # asyncio.CancelledError, since those subclass
            # BaseException, not Exception. Only the genuinely
            # expected "nothing changed" case is ignored now.
            pass

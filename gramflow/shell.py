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
from typing import Union
from .gramflow import GramFlow
from .upload import upload_dir_contents


async def upload(
    client: GramFlow,
    files: str,
    to: Union[str, int],
    delete_on_success: bool = False,
    thumbnail_file: str = None,
    force_document: bool = False,
    custom_caption: str = None,
    console_progress: bool = False,
    message_thread_id: int = None,
):
    # sent a message to verify write permission in the "to"
    status_message = await client.send_message(
        chat_id=to,
        text=".",
        message_thread_id=message_thread_id
    )

    # get the max tg file_size that is allowed for this account
    tg_max_file_size = 4194304000 if client.me.is_premium else 2097152000

    await upload_dir_contents(
        tg_max_file_size,
        files,
        delete_on_success,
        thumbnail_file,
        force_document,
        custom_caption,
        status_message,
        console_progress
    )

    await status_message.delete()


def _parse_chat_id(dest_chat: str) -> Union[str, int]:
    """ Telegram chat ids can be:
      - a plain user id: "123456789"
      - a supergroup/channel id: "-1001234567890"
      - a legacy basic-group id: "-123456789" (no "-100" prefix)
      - a @username or invite-style string
    BUG FIX: the old check was
        `dest_chat.isnumeric() or dest_chat.startswith("-100")`
    `str.isnumeric()` is `False` for anything starting with "-", so a
    plain (non "-100"-prefixed) negative chat id such as a basic
    group's "-123456789" was never converted to `int` and was instead
    sent to `get_chat()` as a raw string, which pyrogram/kurigram
    rejects for numeric-looking ids that aren't actual `int`s.
    """
    try:
        return int(dest_chat)
    except (TypeError, ValueError):
        return dest_chat


async def moin(
    args
):
    client = GramFlow()
    await client.start()

    try:
        # BUG FIX: chat_id and dir_path are declared as required
        # positional args in argparse, so the previous `if not
        # dest_chat: input(...)` / `while not os.path.exists(...)`
        # fallbacks were dead code. argparse itself now rejects
        # missing required args with a clear usage error.
        dest_chat = args.chat_id
        dest_chat = _parse_chat_id(dest_chat)
        # BUG FIX: get_chat only accepts a single (chat_id) argument;
        # the trailing `False` was an invalid positional that raised
        # a TypeError. Resolve the chat so usernames get translated to
        # the real numeric id (and write permission is implicitly
        # verified by get_me on start).
        dest_chat = (
            await client.get_chat(dest_chat)
        ).id

        dir_path = args.dir_path
        if not os.path.exists(dir_path):
            raise FileNotFoundError(
                f"path does not exist: {dir_path}"
            )
        dir_path = os.path.abspath(dir_path)

        await upload(
            client,
            dir_path,
            dest_chat,
            delete_on_success=args.delete_on_success,
            thumbnail_file=args.t,
            force_document=args.fd,
            custom_caption=args.caption,
            console_progress=args.progress,
            message_thread_id=args.topic
        )
    finally:
        # BUG FIX: previously `client.stop()` was only reached if
        # nothing above raised. Any error mid-upload (network hiccup,
        # a bad chat id, Ctrl+C, ...) left the pyrogram session
        # running/locked, so the *next* run would fail to start with
        # a "database is locked" style error until the process was
        # killed. Now the session is always stopped.
        await client.stop()


def main():
    import asyncio
    import argparse
    from . import __version__
    parser = argparse.ArgumentParser(
        prog="GramFlow",
        description="Upload to Telegram, from the Terminal."
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.add_argument(
        "chat_id",
        type=str,
        help="chat id for this bot to send the message to",
    )
    parser.add_argument(
        "dir_path",
        type=str,
        help="enter path to upload to Telegram",
    )
    # BUG FIX: these three flags used to be declared with
    # `nargs="?", type=bool`. argparse's `type=bool` does NOT parse
    # "true"/"false" strings - it just calls `bool(x)`, so *any*
    # non-empty string (including the literal text "false") evaluates
    # to True, and passing the bare flag with no value invoked
    # `bool()` with no args -> False, the opposite of what a bare
    # `--fd` should mean. `action="store_true"` is the correct,
    # unambiguous way to express an on/off CLI flag.
    parser.add_argument(
        "--delete_on_success",
        action="store_true",
        help="delete file on successful upload",
    )
    parser.add_argument(
        "--fd",
        action="store_true",
        help="force uploading as documents",
    )
    parser.add_argument(
        "--t",
        type=str,
        help="thumbnail for the upload",
        default=None,
        required=False
    )
    parser.add_argument(
        "--caption",
        type=str,
        help=(
            "custom caption for the files. By default, files are sent "
            "without a caption. Use --caption \"text\" to set one."
        ),
        default=None,
        required=False
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="show upload progress in terminal",
    )
    parser.add_argument(
        "--topic",
        type=int,
        help="Unique identifier of the forum topic. This is a temporary type for uploading messages into a specific topic in a chat.",
        default=None,
        required=False
    )
    args = parser.parse_args()
    # BUG FIX: `asyncio.get_event_loop()` outside of a running loop is
    # deprecated since Python 3.10 and emits a DeprecationWarning (and
    # is slated for removal), plus it doesn't reliably close the loop
    # afterwards. `asyncio.run()` is the modern, correct entry point.
    asyncio.run(moin(args))


if __name__ == "__main__":
    main()
        

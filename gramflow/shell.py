#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2021 The Original Uploadgram Authors
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is licensed under the MIT License.
#  You may use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of this software subject to the terms of the MIT License.
#  The software is provided "AS IS", without warranty of any kind, express or
#  implied. See the LICENSE file for the complete license text.


import logging
import os
from typing import Union
from .gramflow import GramFlow
from .upload import upload_dir_contents, _count_files_and_bytes
from .state import UploadState, BatchProgress
from .config import SESSION_FILE

# BUG FIX: kurigram logs every FloodWait auto-retry (e.g. from
# "upload.SaveBigFilePart" during large uploads) at INFO level, which
# floods the terminal with repeated "Waiting for 1 seconds before
# continuing..." lines. This is expected/normal behaviour during big
# uploads, not an actual error - raise pyrogram's own logger threshold
# so only warnings/errors are shown, without touching root logging
# (so real errors elsewhere are unaffected).
logging.getLogger("pyrogram").setLevel(logging.WARNING)


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
    use_resume: bool = True,
    fresh: bool = False,
    use_albums: bool = True,
):
    # sent a message to verify write permission in the "to"
    status_message = await client.send_message(
        chat_id=to,
        text=".",
        message_thread_id=message_thread_id
    )

    # get the max tg file_size that is allowed for this account
    tg_max_file_size = 4194304000 if client.me.is_premium else 2097152000

    upload_state = UploadState(files, to) if use_resume else None
    if upload_state is not None and fresh:
        upload_state.clear()

    # RESUME/PROGRESS: size the whole batch up-front (read-only) so
    # BatchProgress can report "X/Y files, N/M GB" from the very first
    # status update, instead of only discovering totals as it goes.
    # This is a plain os.walk with no network calls, so it does not
    # affect upload throughput.
    total_files, total_bytes = _count_files_and_bytes(files, tg_max_file_size)
    batch_progress = BatchProgress(total_files, total_bytes)

    if use_resume and upload_state is not None:
        resumed_note = (
            " (resuming - previously uploaded files in this folder "
            "will be skipped)"
        )
    else:
        resumed_note = ""
    print(
        f"[GramFlow] Starting batch: {total_files} file(s), "
        f"{total_bytes} bytes{resumed_note}"
    )

    try:
        await upload_dir_contents(
            tg_max_file_size,
            files,
            delete_on_success,
            thumbnail_file,
            force_document,
            custom_caption,
            status_message,
            console_progress,
            upload_state=upload_state,
            batch_progress=batch_progress,
            use_albums=use_albums,
        )
    finally:
        # Whole batch finished (or was interrupted) - if nothing is
        # left unresolved, there is no reason to keep the per-job
        # resume-state file around forever.
        if upload_state is not None and not upload_state.has_unresolved_failures():
            upload_state.discard_file()

    print(
        f"[GramFlow] Batch finished: {batch_progress.done_files} uploaded, "
        f"{batch_progress.skipped_files} skipped (resumed), "
        f"{batch_progress.oversized_files} skipped (too large), "
        f"{batch_progress.failed_files} failed "
        f"(total {batch_progress.total_files})"
    )

    try:
        await status_message.delete()
    except Exception:  # noqa: BLE001 - best-effort cleanup of the status msg
        pass


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


async def do_upload(args):
    client = GramFlow()
    started = False
    try:
        try:
            await client.start()
            started = True
        except Exception as e:
            # A failed start can still partially initialize the client.
            # Keep cleanup in one finally block so resources are released
            # whenever the underlying library reports a partial startup.
            print(f"[error] could not connect to Telegram: {e!r}")
            print(
                "If this persists, try `gramflow logout` followed by "
                "`gramflow login` to re-authenticate."
            )
            return

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
        try:
            dest_chat = (await client.get_chat(dest_chat)).id
        except Exception as e:
            print(f"[error] could not resolve destination chat: {e!r}")
            print(
                "Check that the chat id/username is correct and that "
                "this account can send messages there."
            )
            return

        dir_path = args.dir_path
        if not os.path.exists(dir_path):
            print(f"[error] path does not exist: {dir_path}")
            return
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
            message_thread_id=args.topic,
            use_resume=not args.no_resume,
            fresh=args.fresh,
            use_albums=not args.no_albums,
        )
    finally:
        # BUG FIX: previously `client.stop()` was only reached if
        # nothing above raised. Any error mid-upload (network hiccup,
        # a bad chat id, Ctrl+C, ...) left the pyrogram session
        # running/locked, so the *next* run would fail to start with
        # a "database is locked" style error until the process was
        # killed. Now the session is always stopped.
        if started:
            try:
                await client.stop()
            except Exception:  # noqa: BLE001 - already shutting down
                pass


async def do_login():
    """ `gramflow login` - authenticate once and store the session.
    pyrogram/kurigram already prompt for phone number / login code /
    2FA password interactively the first time a Client with no
    existing session calls start() - this subcommand just gives that
    flow an explicit, discoverable name instead of it only happening
    as a side effect of the first real upload.
    """
    if os.path.exists(SESSION_FILE):
        print(
            "A session already exists. Run `gramflow logout` first if "
            "you want to log in as a different account."
        )
        return
    client = GramFlow()
    try:
        await client.start()
    except Exception as e:
        print(f"[error] login failed: {e!r}")
        return
    try:
        print(f"Logged in as {client.me.first_name} (id: {client.me.id}).")
    finally:
        await client.stop()


async def do_logout():
    """ `gramflow logout` - revoke the session with Telegram and
    remove the local session file, so a stale/unwanted session can
    never be reused by mistake.
    """
    if not os.path.exists(SESSION_FILE):
        print("Not logged in - nothing to do.")
        return
    client = GramFlow()
    revoked = False
    started = False
    try:
        await client.start()
        started = True
        # BUG-SAFE: log_out() tells Telegram's servers to invalidate
        # this session (so it can no longer be used even if the local
        # file were somehow copied elsewhere). If this fails (e.g. no
        # network), we still remove the local file below so the CLI
        # is at least locally logged out and `gramflow login` can
        # create a fresh session.
        await client.log_out()
        revoked = True
    except Exception as e:
        print(f"[warn] could not reach Telegram to revoke the session: {e!r}")
    finally:
        # BUG FIX (item 4 - logout client cleanup): previously there
        # was no client.stop() call anywhere in this function. If
        # client.start() succeeded but log_out() then raised (network
        # drop mid-call, unexpected server error, etc.) the client was
        # left connected with its background network tasks still
        # running for the rest of the process's lifetime - a real
        # resource leak, distinct from the local session *file*
        # cleanup below.
        #
        # NOTE: on a *successful* log_out(), pyrogram/kurigram already
        # stops the client internally as part of invalidating the
        # session - calling stop() again would raise "client is
        # already terminated". Rather than depend on that internal
        # behaviour staying the same across kurigram versions, the
        # stop() call itself is wrapped so an "already stopped" error
        # here is treated the same as any other already-shutting-down
        # condition: harmless, and not reported to the user.
        if started:
            try:
                await client.stop()
            except Exception:  # noqa: BLE001 - already shutting down
                pass
        # log_out() already deletes pyrogram's own session file on
        # success; guard against it not existing any more before we
        # try to remove it ourselves, and never let a missing file be
        # reported as an error.
        for path in (SESSION_FILE, f"{SESSION_FILE}-journal"):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError as e:
                print(f"[warn] could not remove {path}: {e!r}")
    if revoked:
        print("Logged out and revoked the session.")
    else:
        print("Removed the local session. (Could not confirm server-side revocation.)")


def main():
    import asyncio
    import argparse
    import sys
    from . import __version__

    # BUG-SAFE: argparse subparsers are themselves a positional
    # argument, so adding a `login`/`logout` subparser *and* keeping
    # chat_id/dir_path as plain (optional) positionals on the same
    # parser causes argparse to try to match the subparser choices
    # against the first token - breaking the existing
    # `gramflow <chat_id> <dir_path>` invocation entirely (a numeric
    # chat_id would be rejected as "not a valid command"). Dispatch on
    # the first token manually instead, before argparse ever sees it,
    # so `login`/`logout` and the original upload invocation can
    # coexist without changing the existing command-line shape.
    argv = sys.argv[1:]
    if argv and argv[0] in ("login", "logout") and "--help" not in argv and "-h" not in argv:
        if argv[0] == "login":
            try:
                asyncio.run(do_login())
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\nCancelled by user.")
        else:
            try:
                asyncio.run(do_logout())
            except (KeyboardInterrupt, asyncio.CancelledError):
                print("\nCancelled by user.")
        return

    parser = argparse.ArgumentParser(
        prog="GramFlow",
        description=(
            "Upload to Telegram, from the Terminal. "
            "Also supports `gramflow login` / `gramflow logout`."
        )
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
    # BUG FIX: these flags used to be declared with `nargs="?",
    # type=bool`. argparse's `type=bool` does NOT parse "true"/"false"
    # strings - it just calls `bool(x)`, so *any* non-empty string
    # (including the literal text "false") evaluates to True, and
    # passing the bare flag with no value invoked `bool()` with no
    # args -> False, the opposite of what a bare `--fd` should mean.
    # `action="store_true"` is the correct, unambiguous way to express
    # an on/off CLI flag.
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
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help=(
            "do not skip files uploaded in a previous run of this same "
            "folder/destination - upload everything from scratch"
        ),
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "clear any saved resume progress for this folder/destination "
            "before starting"
        ),
    )
    parser.add_argument(
        "--no-albums",
        action="store_true",
        help=(
            "disable grouping consecutive photos/videos into Telegram "
            "media groups (albums) - send every file as its own message"
        ),
    )
    args = parser.parse_args()

    # BUG FIX: `asyncio.get_event_loop()` outside of a running loop is
    # deprecated since Python 3.10 and emits a DeprecationWarning (and
    # is slated for removal), plus it doesn't reliably close the loop
    # afterwards. `asyncio.run()` is the modern, correct entry point.
    #
    # BUG FIX: pressing Ctrl+C mid-upload used to print a long,
    # confusing traceback (KeyboardInterrupt racing with an in-flight
    # `asyncio.sleep(10)` inside upload_dir_contents, which surfaces as
    # asyncio.CancelledError chained to the original KeyboardInterrupt).
    # Both are the user's own cancellation, not a bug - catch them here
    # at the single top-level entry point and exit quietly instead of
    # letting the traceback spill out. client.stop() is still called
    # normally on this path because it lives in `do_upload`'s `finally`.
    try:
        asyncio.run(do_upload(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\nCancelled by user.")


if __name__ == "__main__":
    main()

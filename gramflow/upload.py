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
import os
import re
from time import time
from asyncio import sleep
from tqdm import tqdm
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pyrogram.types import Message, InputMediaPhoto, InputMediaVideo
from pyrogram.errors import RPCError
from .config import TG_AUDIO_TYPES, TG_IMAGE_TYPES, TG_VIDEO_TYPES
from .progress import progress_for_pyrogram
from .take_screen_shot import take_screen_shot
from .run_shell_command import run_command
from .state import UploadState, BatchProgress


async def _probe_video_duration(file_path: str):
    """ Duration (seconds) via ffprobe, or None.

    Hachoir (the pure-python parser used as the primary source) is
    known to fail or stall on very large/multi-GB containers - which
    is exactly the case where the caller would otherwise fall back to
    ttl=0 and grab the (usually black) first frame. ffprobe is robust
    on those same files and costs one quick metadata probe. Only runs
    when the primary read failed, so the common path is untouched. """
    try:
        _pid, rc, stdout, _stderr = await run_command(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                file_path,
            ],
            timeout=60,
        )
        if rc == 0 and stdout:
            return float(stdout.splitlines()[0].strip())
    except (ValueError, OSError):
        pass
    return None


def _natural_sort_key(value: str):
    """Split a filename into (text, number, text, number, ...) tuples
    so ['1.mp4', '10.mp4', '2.mp4'] sorts as ['1.mp4', '2.mp4', '10.mp4'].
    Non-digit chunks sort normally; digit chunks sort numerically.
    """
    parts = re.split(r"(\d+)", value)
    return tuple(
        int(part) if part.isdigit() else part.lower()
        for part in parts
    )


_DOTFILE_RE = re.compile(r"^\.")

# Telegram allows at most 10 items in a single media group (album).
MEDIA_GROUP_MAX = 10


def _count_files_and_bytes(dir_path: str, tg_max_file_size: int):
    """ Walk the tree up-front (read-only, no uploads) purely to size
    the batch for BatchProgress. Mirrors the dotfile-skip rule in
    upload_dir_contents.

    NOTE: `tg_max_file_size` is intentionally unused now (kept in the
    signature for call-site/API stability) - see the BUG FIX note
    below for why oversized files are no longer excluded here.

    BUG FIX (processed > total): oversized files are now INCLUDED in
    the totals (counted as part of the batch, sized by their real
    file size) rather than excluded - they are still skipped rather
    than uploaded, but the main loop marks them via
    BatchProgress.file_oversized(), which now correctly has a
    corresponding slot in total_files/total_bytes. Previously this
    function excluded them while the main loop counted them anyway,
    which could push processed_files above total_files (e.g. "11/10").
    """
    total_files = 0
    total_bytes = 0
    if not os.path.isdir(dir_path):
        if os.path.exists(dir_path):
            return 1, os.stat(dir_path).st_size
        return 0, 0
    for root, dirs, files in os.walk(dir_path, followlinks=False):
        # Never descend into symlinked directories. They may point outside
        # the requested tree or back to an ancestor and create recursion.
        real_dirs = []
        for name in dirs:
            full = os.path.join(root, name)
            if _DOTFILE_RE.match(name):
                continue
            if os.path.islink(full):
                total_files += 1
                try:
                    total_bytes += os.lstat(full).st_size
                except OSError:
                    pass
                continue
            real_dirs.append(name)
        dirs[:] = real_dirs
        for name in files:
            if _DOTFILE_RE.match(name):
                continue
            full = os.path.join(root, name)
            try:
                size = os.lstat(full).st_size if os.path.islink(full) else os.stat(full).st_size
            except OSError:
                continue
            total_files += 1
            total_bytes += size
    return total_files, total_bytes


def _is_album_eligible(file_path: str, force_document: bool) -> str:
    """ Returns 'photo', 'video', or '' (not album-eligible). Audio and
    generic documents are never grouped into Telegram media groups the
    way photos/videos are (media groups are strictly photo/video). """
    if force_document:
        return ""
    upper_name = file_path.upper()
    if upper_name.endswith(TG_IMAGE_TYPES):
        return "photo"
    if upper_name.endswith(TG_VIDEO_TYPES):
        return "video"
    return ""


async def upload_dir_contents(
    tg_max_file_size: int,
    dir_path: str,
    delete_on_success: bool,
    thumbnail_file: str,
    force_document: bool,
    custom_caption: str,
    bot_sent_message: Message,
    console_progress: bool,
    upload_state: UploadState = None,
    batch_progress: BatchProgress = None,
    use_albums: bool = True,
):
    dir_contents = []
    if not os.path.isdir(dir_path):
        if os.path.exists(dir_path):
            dir_contents.append(dir_path)
        else:
            return False
    else:
        dir_contents = os.listdir(dir_path)
    # BUG FIX: previously dotfiles (.DS_Store, .Thumbs.db, etc.) were
    # uploaded as documents, cluttering the destination chat. Also
    # sort with a natural ordering so numbered files (file1, file2,
    # ..., file10) come out in human-expected order rather than
    # lexicographic (file1, file10, file2).
    dir_contents = [
        name for name in dir_contents if not _DOTFILE_RE.match(name)
    ]
    dir_contents.sort(key=_natural_sort_key)

    # Batch same-type (photo/photo or video/video) *consecutive* files
    # into groups of up to MEDIA_GROUP_MAX for a single media-group
    # send, instead of one Telegram message per file. Only consecutive
    # runs are grouped so the destination chat keeps the same overall
    # ordering as before; a document or a differently-typed file
    # always flushes the pending group first.
    pending_group: list = []
    pending_group_kind = None

    async def flush_group():
        nonlocal pending_group, pending_group_kind
        if not pending_group:
            return
        group = pending_group
        pending_group = []
        pending_group_kind = None
        if len(group) == 1:
            # A "group" of one file is just a normal single upload -
            # no reason to use send_media_group for it.
            await _upload_one(group[0])
            return
        await _upload_group(group)

    async def _mark_result(file_path: str, size: int, ok: bool):
        if ok:
            if upload_state is not None:
                upload_state.mark_done(file_path)
            if batch_progress is not None:
                batch_progress.file_done(size)
            if delete_on_success:
                try:
                    os.remove(file_path)
                except OSError as e:
                    print(f"[warn] could not delete {file_path}: {e!r}")
        else:
            if upload_state is not None:
                upload_state.mark_failed(file_path)
            if batch_progress is not None:
                batch_progress.file_failed()
        await _maybe_update_batch_status()

    _last_status_update = {"t": 0.0}

    async def _maybe_update_batch_status():
        # BUG-SAFE / NOTE: this status message is entirely separate
        # from the existing per-file progress bar/message, and is
        # rate-limited to roughly once every 5 seconds (or on the very
        # first/last update) so it never adds meaningful extra
        # Telegram API traffic or affects upload throughput.
        if batch_progress is None:
            return
        now = time()
        is_last = batch_progress.processed_files >= batch_progress.total_files
        if not is_last and (now - _last_status_update["t"]) < 5:
            return
        _last_status_update["t"] = now
        try:
            await bot_sent_message.edit_text(batch_progress.summary_line())
        except RPCError:
            pass
        except Exception:  # noqa: BLE001 - status update is best-effort
            pass

    # BUG FIX (item 6): centralise the post-upload rate-limit pause in
    # one place so every upload path (single file, group, and group
    # -> individual fallback) goes through the same mechanism instead
    # of each call site having its own `await sleep(10)`. This doesn't
    # change the actual delay - a 10s pause still happens once per
    # file actually sent to Telegram - it just makes "one pause per
    # send" an explicit invariant instead of something that happened
    # to be true by coincidence across two different functions.
    async def _rate_limit_pause():
        await sleep(10)

    async def _upload_one(file_path: str):
        size = os.stat(file_path).st_size if os.path.exists(file_path) else 0
        try:
            response_message = await upload_single_file(
                file_path,
                thumbnail_file,
                force_document,
                custom_caption,
                bot_sent_message,
                console_progress,
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"[error] failed to upload {file_path}: {e!r}")
            try:
                await bot_sent_message.reply_text(
                    text=(
                        f"failed to upload "
                        f"<code>{os.path.basename(file_path)}</code> "
                        f"- {e}"
                    ),
                )
            except Exception:  # noqa: BLE001 - best-effort notice
                pass
            response_message = False
        await _mark_result(file_path, size, isinstance(response_message, Message))
        await _rate_limit_pause()

    async def _upload_group(file_paths: list):
        media = []
        sizes = {}
        # BUG FIX (item 1 - album thumbnails ignored): InputMediaVideo
        # DOES support a `thumb` parameter in pyrogram/kurigram (this
        # is a real, supported capability - InputMediaPhoto has none,
        # since Telegram always auto-thumbnails photos itself, so this
        # only applies to the video items in a group). Previously
        # every InputMediaVideo() in a group was built with no `thumb`
        # at all, so --t was silently dropped for any video that
        # ended up in an album, even though the exact same file
        # uploaded alone would have used it correctly.
        #
        # Auto-generated screenshots are also now attempted for
        # videos in a group when no --t was given, for parity with
        # single-video uploads. Each is a separate temp file (ffmpeg
        # can't target the same output path concurrently) and all of
        # them are cleaned up in the `finally` below, whether the
        # group send succeeds, fails, or falls back to individual
        # uploads.
        generated_thumbs = []
        try:
            for i, fp in enumerate(file_paths):
                sizes[fp] = os.stat(fp).st_size if os.path.exists(fp) else 0
                # Only the first item in a media group carries the
                # caption; Telegram/pyrogram apply it to the group as
                # a whole.
                cap = (
                    custom_caption
                    if (custom_caption is not None and i == 0) else ""
                )
                kind = _is_album_eligible(fp, force_document)
                if kind == "photo":
                    media.append(InputMediaPhoto(fp, caption=cap))
                    continue
                thumb_for_this = thumbnail_file
                if not thumb_for_this:
                    # BUG FIX: this used to pass ttl=0, i.e. always
                    # capture the FIRST frame of the video - which is
                    # black for any video with a fade-in/intro, so
                    # every video in an album got a black thumbnail.
                    # Use the same duration/2 seek as single uploads.
                    _dur = 0
                    try:
                        _md = extractMetadata(createParser(fp))
                        if _md and _md.has("duration"):
                            _dur = _md.get("duration").seconds
                    except Exception:
                        _dur = 0
                    if not _dur:
                        _probed = await _probe_video_duration(fp)
                        if _probed:
                            _dur = int(_probed)
                    try:
                        thumb_for_this = await take_screen_shot(
                            fp, os.path.dirname(os.path.abspath(fp)),
                            (_dur / 2),
                        )
                        if thumb_for_this:
                            generated_thumbs.append(thumb_for_this)
                    except Exception as e:
                        print(
                            f"[warn] could not generate a thumbnail for "
                            f"{fp} in album ({e!r}), uploading without one"
                        )
                        thumb_for_this = None
                media.append(
                    InputMediaVideo(fp, caption=cap, thumb=thumb_for_this)
                )
            try:
                sent = await bot_sent_message.reply_media_group(media=media)
                # NOTE: Telegram media groups are sent as a single
                # atomic call - pyrogram/kurigram gives no per-item
                # success/failure signal, only success-or-exception
                # for the whole group. If we got here without an
                # exception, every file in the group is considered
                # uploaded.
                for fp in file_paths:
                    await _mark_result(fp, sizes[fp], bool(sent))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                # IMPORTANT: do not automatically retry an album as
                # individual messages after an ambiguous Telegram/network
                # exception. The server may have accepted the album while
                # the client failed to receive the response; retrying here
                # can therefore duplicate every item in the group. Mark the
                # whole group failed and let the normal resume mechanism
                # retry it on a later explicit run.
                print(
                    f"[error] media group upload failed ({e!r}); "
                    "the group was not retried automatically to avoid duplicates"
                )
                for fp in file_paths:
                    await _mark_result(fp, sizes[fp], False)
                await _rate_limit_pause()
                return
        finally:
            for path in generated_thumbs:
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass
        await _rate_limit_pause()

    for dir_cntn in dir_contents:
        current_name = os.path.join(dir_path, dir_cntn)

        if os.path.islink(current_name):
            print(f"[skip] symlink is not supported: {current_name}")
            try:
                size = os.lstat(current_name).st_size
            except OSError:
                size = 0
            if batch_progress is not None:
                batch_progress.file_failed()
                await _maybe_update_batch_status()
            if upload_state is not None:
                upload_state.mark_failed(current_name)
            continue

        if os.path.isdir(current_name):
            # A subdirectory boundary always flushes any pending
            # group first, so albums never straddle directories.
            await flush_group()
            await upload_dir_contents(
                tg_max_file_size,
                current_name,
                delete_on_success,
                thumbnail_file,
                force_document,
                custom_caption,
                bot_sent_message,
                console_progress,
                upload_state=upload_state,
                batch_progress=batch_progress,
                use_albums=use_albums,
            )
            continue

        if not os.path.exists(current_name):
            continue

        if os.stat(current_name).st_size > tg_max_file_size:
            await flush_group()
            # BUG FIX: previously an oversized file was skipped with
            # zero feedback, which looked like the upload "silently
            # missed" some files. Now we say so, both in the console
            # and in the status message chat.
            skip_notice = (
                f"skipping <code>{os.path.basename(current_name)}</code> "
                f"- larger than the account's max upload size"
            )
            print(f"[skip] {current_name} is larger than the allowed limit")
            try:
                await bot_sent_message.reply_text(text=skip_notice)
            except Exception:  # noqa: BLE001 - purely a best-effort notice
                pass
            # BUG FIX (item 2 - processed > total): this used to call
            # batch_progress.file_failed(), which is counted toward
            # processed_files without ever having had a matching slot
            # in total_files (oversized files were excluded from the
            # up-front count). Oversized files are now included in
            # the total (see _count_files_and_bytes) and tracked in
            # their own bucket here, so the math always stays
            # consistent (processed_files can never exceed
            # total_files) and the final summary can distinguish
            # "too large to send" from an actual upload failure.
            if batch_progress is not None:
                batch_progress.file_oversized(
                    os.stat(current_name).st_size
                )
                await _maybe_update_batch_status()
            continue

        # RESUME: skip files already recorded as uploaded in a
        # previous run of this exact (directory, destination) job.
        # This never affects files being uploaded for the first time
        # or upload speed/ordering - it only prevents re-sending a
        # file whose path+size+mtime exactly match a completed record.
        if upload_state is not None and upload_state.is_done(current_name):
            if batch_progress is not None:
                batch_progress.file_skipped(os.stat(current_name).st_size)
                await _maybe_update_batch_status()
            continue

        kind = _is_album_eligible(current_name, force_document) if use_albums else ""

        if kind and kind == pending_group_kind:
            pending_group.append(current_name)
            if len(pending_group) >= MEDIA_GROUP_MAX:
                await flush_group()
            continue

        # Either not album-eligible, or a different kind than the
        # pending group - flush whatever was pending first.
        await flush_group()

        if kind:
            pending_group = [current_name]
            pending_group_kind = kind
        else:
            await _upload_one(current_name)

    await flush_group()


async def upload_single_file(
    file_path: str,
    thumbnail_file: str,
    force_document: bool,
    custom_caption: str,
    bot_sent_message: Message,
    console_progress: bool,
):
    if not os.path.exists(file_path):
        return False
    usr_sent_message = bot_sent_message
    start_time = time()
    # BUG FIX: the default used to be `f"<code>{os.path.basename(file_path)}</code>"`,
    # which meant every upload sent the file name as the caption -
    # which the user explicitly did not want. The new default is an
    # empty caption: files are sent without a caption unless the user
    # passes `--caption "something"`.
    caption_al_desc = ""
    if custom_caption is not None:
        caption_al_desc = custom_caption

    pbar = None
    if console_progress:
        pbar = tqdm(
            total=os.path.getsize(file_path),
            unit="iB",
            unit_scale=True,
            desc="uploading",
            colour="green",
            unit_divisor=1024,
            miniters=1,
        )

    try:
        upper_name = file_path.upper()

        if upper_name.endswith(TG_IMAGE_TYPES) and not force_document:
            # BUG FIX: photos previously had no dedicated branch at
            # all, so every image file fell through to
            # `upload_as_document` unconditionally - even without
            # --fd - and was sent as a generic file/document instead
            # of an actual Telegram photo.
            return await upload_as_photo(
                usr_sent_message,
                bot_sent_message,
                file_path,
                caption_al_desc,
                start_time,
                pbar,
            )

        if upper_name.endswith(TG_VIDEO_TYPES) and not force_document:
            return await upload_as_video(
                usr_sent_message,
                bot_sent_message,
                file_path,
                caption_al_desc,
                thumbnail_file,
                start_time,
                pbar,
            )

        if upper_name.endswith(TG_AUDIO_TYPES) and not force_document:
            return await upload_as_audio(
                usr_sent_message,
                bot_sent_message,
                file_path,
                caption_al_desc,
                thumbnail_file,
                start_time,
                pbar,
            )

        return await upload_as_document(
            usr_sent_message,
            bot_sent_message,
            file_path,
            caption_al_desc,
            thumbnail_file,
            start_time,
            pbar,
        )
    finally:
        # BUG FIX: the tqdm progress bar was created but never
        # closed, which on some terminals leaves a stray/garbled
        # progress line behind once the next file's bar starts.
        if pbar is not None:
            pbar.close()


async def upload_as_document(
    usr_sent_message: Message,
    bot_sent_message: Message,
    file_path: str,
    caption_rts: str,
    thumbnail_file: str,
    start_time: int,
    pbar: tqdm,
):

    return await usr_sent_message.reply_document(
        document=file_path,
        caption=caption_rts,
        # BUG FIX / API MIGRATION: kurigram (unlike the old
        # pyrotgfork dependency) does not have a
        # `disable_content_type_detection` parameter on
        # reply_document/send_document any more - it was renamed to
        # `force_document`. Passing the old name now raises a
        # TypeError instead of silently doing nothing, so this had to
        # be updated, not just copy-pasted.
        force_document=True,
        thumb=thumbnail_file,
        progress=progress_for_pyrogram,
        progress_args=(
            bot_sent_message,
            start_time,
            pbar,
            f"Uploading {os.path.basename(file_path)} as <b>DOCUMENT</b>"
        ),
    )


async def upload_as_photo(
    usr_sent_message: Message,
    bot_sent_message: Message,
    file_path: str,
    caption_rts: str,
    start_time: int,
    pbar: tqdm,
):
    """ new: uploads image files as an actual Telegram photo
    (compressed, shown inline in chat) instead of always falling back
    to a generic document. """
    try:
        return await usr_sent_message.reply_photo(
            photo=file_path,
            caption=caption_rts,
            progress=progress_for_pyrogram,
            progress_args=(
                bot_sent_message,
                start_time,
                pbar,
                f"Uploading {os.path.basename(file_path)} as <b>PHOTO</b>"
            ),
        )
    except Exception as e:
        # Telegram rejects some "image" files as a photo (e.g. huge
        # resolution, corrupt/unsupported encodings, CMYK JPEGs).
        # Rather than crashing the whole batch, fall back to sending
        # it as a document so the user still gets the file.
        print(
            f"[warn] {file_path} could not be sent as a photo ({e!r}), "
            f"sending as a document instead"
        )
        return await upload_as_document(
            usr_sent_message,
            bot_sent_message,
            file_path,
            caption_rts,
            None,
            start_time,
            pbar,
        )


async def upload_as_video(
    usr_sent_message: Message,
    bot_sent_message: Message,
    file_path: str,
    caption_rts: str,
    thumbnail_file: str,
    start_time: int,
    pbar: tqdm,
):
    duration = 0
    width = 0
    height = 0
    thumb_nail_img = None

    # BUG FIX (item 5 - hachoir failure must not turn a valid video
    # into a document): previously, ANY exception while reading the
    # source video's metadata (including take_screen_shot's own
    # already-handled failures, since they used to live inside this
    # same try block) caused the whole file to be re-routed to
    # upload_as_document - even though a hachoir parse failure says
    # nothing about whether Telegram/ffmpeg can actually handle the
    # file as a video. Hachoir not recognising an exotic/truncated
    # container, or choking on a valid-but-unusual video, is common
    # and does not mean the file itself is broken. Metadata extraction
    # is now isolated in its own try/except: on failure it logs a
    # diagnostic and falls back to safe defaults (duration/width/
    # height = 0), but ALWAYS proceeds to attempt the actual video
    # upload below. Only a genuine failure from reply_video() itself
    # (Telegram/pyrogram rejecting the file) still falls back to
    # upload_as_document, via the try/finally around that call.
    try:
        metadata = extractMetadata(createParser(file_path))
        if metadata:
            # BUG FIX: width/height used to be read from the
            # *thumbnail JPEG* instead of the video itself - a mismatched
            # or oddly-encoded thumbnail could make Telegram stretch the
            # video. Read dimensions from the video's own metadata (same
            # single hachoir parse, zero extra cost); the thumbnail only
            # needs to exist, its own metadata is irrelevant.
            if metadata.has("duration"):
                duration = metadata.get("duration").seconds
            if metadata.has("width"):
                width = metadata.get("width")
            if metadata.has("height"):
                height = metadata.get("height")
    except Exception as e:
        print(
            f"[warn] could not read metadata for "
            f"{os.path.basename(file_path)} ({e!r}); uploading as a "
            f"video anyway with default duration=0"
        )
    if not duration:
        # BUG FIX: hachoir commonly fails on very large videos, which
        # used to leave duration=0 - and ttl=0 screenshots the first
        # frame (black on most recordings). Fall back to ffprobe so
        # the thumbnail seek still lands mid-video. One quick probe,
        # only on the failure path.
        _probed_duration = await _probe_video_duration(file_path)
        if _probed_duration:
            duration = int(_probed_duration)

    # BUG FIX: a screenshot used to be generated with ffmpeg on
    # *every* video upload, even when the caller already supplied
    # an explicit --t thumbnail file. That's a wasted ffmpeg
    # subprocess (and a stray temp .jpg) for no reason - only
    # generate one if we actually need it.
    if not thumbnail_file:
        try:
            thumb_nail_img = await take_screen_shot(
                file_path,
                os.path.dirname(os.path.abspath(file_path)),
                (duration / 2),
            )
        except Exception as e:
            # BUG FIX: previously any failure inside take_screen_shot
            # (missing ffmpeg, a corrupt/odd video the ffmpeg build
            # can't read, no disk space for the temp .jpg, etc.) was
            # not handled here at all, so thumb_nail_img silently
            # stayed None and the video upload later crashed trying
            # to build a thumbnail out of nothing (see the guard
            # below). A missing thumbnail should never block the
            # actual video upload - Telegram accepts a video with no
            # thumbnail just fine.
            print(
                f"[warn] could not generate a thumbnail for "
                f"{file_path} ({e!r}), uploading without one"
            )
            thumb_nail_img = None

    # BUG FIX: this is the actual crash reported previously - if no
    # explicit --t thumbnail was given AND take_screen_shot
    # failed/returned nothing, thumb_nail_img is None here. The old
    # code unconditionally called `createParser(thumbnail_file if
    # thumbnail_file else thumb_nail_img)`, i.e. `createParser(None)`,
    # which hachoir does not handle cleanly (it can crash even in its
    # own error-cleanup path). Only attempt to read thumbnail metadata
    # if we actually have a thumbnail path.
    # Width/height were already taken from the VIDEO metadata above;
    # the thumbnail path alone is passed to Telegram here.
    thumb_path = thumbnail_file if thumbnail_file else thumb_nail_img
    try:
        try:
            _tmp_m = await usr_sent_message.reply_video(
                video=file_path,
                thumb=thumb_path,
                duration=duration,
                width=width,
                height=height,
                supports_streaming=True,
                caption=caption_rts,
                progress=progress_for_pyrogram,
                progress_args=(
                    bot_sent_message,
                    start_time,
                    pbar,
                    f"Uploading {os.path.basename(file_path)} as <b>VIDEO</b>"
                ),
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # BUG FIX (item 5, part 2): THIS is the correct place for
            # a document fallback - an actual rejection of the video
            # by Telegram/pyrogram (unsupported codec/container,
            # corrupt stream data, etc.), as opposed to hachoir merely
            # failing to *describe* the file above. The fallback
            # itself is unchanged from before; what changed is that a
            # hachoir metadata-read failure no longer reaches this
            # path at all.
            print(
                f"[warn] {file_path} could not be sent as a video "
                f"({e!r}), sending as a document instead"
            )
            _tmp_m = await upload_as_document(
                usr_sent_message,
                bot_sent_message,
                file_path,
                caption_rts,
                thumbnail_file,
                start_time,
                pbar,
            )
    finally:
        # BUG FIX: previously the generated thumbnail was only deleted
        # on the *success* path of reply_video. If the upload raised
        # (FloodWait, network error, ...) the .jpg was leaked into the
        # source directory. Now it is always cleaned up.
        if thumb_nail_img and os.path.exists(thumb_nail_img):
            os.remove(thumb_nail_img)
    return _tmp_m


async def upload_as_audio(
    usr_sent_message: Message,
    bot_sent_message: Message,
    file_path: str,
    caption_rts: str,
    thumbnail_file: str,
    start_time: int,
    pbar: tqdm,
):
    # BUG FIX: this parse used to be unguarded (unlike the video
    # path), so a corrupt/odd audio file raised here and was marked
    # "failed" instead of falling back to a document upload. Match
    # the video behaviour: metadata failure logs a warning and
    # proceeds with defaults.
    try:
        metadata = extractMetadata(createParser(file_path))
    except Exception as e:
        print(
            f"[warn] could not read metadata for "
            f"{os.path.basename(file_path)} ({e!r}); uploading as "
            f"audio anyway with default tags"
        )
        metadata = None
    duration = 0
    title = None
    performer = None
    if metadata:
        # some audio files might cause errors
        # don't fail, and just
        # upload the file with zero (0) duration
        if metadata.has("duration"):
            duration = metadata.get("duration").seconds
        if metadata.has("title"):
            title = metadata.get("title")
        if metadata.has("artist"):
            performer = metadata.get("artist")
        if not performer:
            if metadata.has("author"):
                performer = metadata.get("author")
        if not performer:
            if metadata.has("album"):
                performer = metadata.get("album")

    return await usr_sent_message.reply_audio(
        audio=file_path,
        caption=caption_rts,
        duration=duration,
        performer=performer,
        title=title,
        thumb=thumbnail_file,
        progress=progress_for_pyrogram,
        progress_args=(
            bot_sent_message,
            start_time,
            pbar,
            f"Uploading {os.path.basename(file_path)} as <b>AUDIO</b>"
        ),
    )
    

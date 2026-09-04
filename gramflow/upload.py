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
import re
from time import time
from asyncio import sleep
from tqdm import tqdm
from hachoir.metadata import extractMetadata
from hachoir.parser import createParser
from pyrogram.types import Message
from .config import TG_AUDIO_TYPES, TG_IMAGE_TYPES, TG_VIDEO_TYPES
from .progress import progress_for_pyrogram
from .take_screen_shot import take_screen_shot


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


async def upload_dir_contents(
    tg_max_file_size: int,
    dir_path: str,
    delete_on_success: bool,
    thumbnail_file: str,
    force_document: bool,
    custom_caption: str,
    bot_sent_message: Message,
    console_progress: bool,
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
    for dir_cntn in dir_contents:
        current_name = os.path.join(dir_path, dir_cntn)
        uploaded = False

        if os.path.isdir(current_name):
            await upload_dir_contents(
                tg_max_file_size,
                current_name,
                delete_on_success,
                thumbnail_file,
                force_document,
                custom_caption,
                bot_sent_message,
                console_progress,
            )

        elif os.stat(current_name).st_size <= tg_max_file_size:
            response_message = await upload_single_file(
                current_name,
                thumbnail_file,
                force_document,
                custom_caption,
                bot_sent_message,
                console_progress,
            )
            if isinstance(response_message, Message) and delete_on_success:
                os.remove(current_name)
            uploaded = True

        else:
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
                await bot_sent_message.reply_text(
                    text=skip_notice,
                )
            except Exception:  # noqa: BLE001 - purely a best-effort notice
                pass

        # BUG FIX: previously the 10-second rate-limit pause ran after
        # *every* iteration, including when we just skipped an
        # oversized file. We now only sleep after an actual upload
        # attempt - skip-notices and pure-directory recursion don't
        # need to wait.
        if uploaded:
            await sleep(10)


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
    try:
        metadata = extractMetadata(createParser(file_path))
        if metadata and metadata.has("duration"):
            duration = metadata.get("duration").seconds
        # BUG FIX: a screenshot used to be generated with ffmpeg on
        # *every* video upload, even when the caller already supplied
        # an explicit --t thumbnail file. That's a wasted ffmpeg
        # subprocess (and a stray temp .jpg) for no reason - only
        # generate one if we actually need it.
        if not thumbnail_file:
            thumb_nail_img = await take_screen_shot(
                file_path,
                os.path.dirname(os.path.abspath(file_path)),
                (duration / 2),
            )
    except AssertionError:
        return await upload_as_document(
            usr_sent_message,
            bot_sent_message,
            file_path,
            caption_rts,
            thumbnail_file,
            start_time,
            pbar,
        )
    try:
        metadata = extractMetadata(createParser(
            thumbnail_file if thumbnail_file else thumb_nail_img
        ))
        if metadata and metadata.has("width"):
            width = metadata.get("width")
        if metadata and metadata.has("height"):
            height = metadata.get("height")
    except AssertionError:
        pass
    try:
        _tmp_m = await usr_sent_message.reply_video(
            video=file_path,
            thumb=thumbnail_file if thumbnail_file else thumb_nail_img,
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
    metadata = extractMetadata(createParser(file_path))
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

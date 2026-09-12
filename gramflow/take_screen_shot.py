#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2021 The Original Uploadgram Authors
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is licensed under the MIT License.
#  You may use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of this software subject to the terms of the MIT License.
#  The software is provided "AS IS", without warranty of any kind, express or
#  implied. See the LICENSE file for the complete license text.


import os
import shutil
import uuid
from time import time
from .config import (
    TG_VIDEO_TYPES
)
from .run_shell_command import run_command

# ffmpeg availability is checked once per process - see below.
_ffmpeg_checked = False
_ffmpeg_available = False

# A frame whose average luma is below this is considered "black"
# (solid black = 0, pure white = 255). 8 is comfortably below any
# real video content while catching fade-from-black intros.
_BLACK_LUMA_THRESHOLD = 8
# How long one ffmpeg grab may take before it is killed. Grabbing a
# single frame is normally sub-second; large files with slow storage
# get generous headroom, but a corrupt file can no longer stall the
# upload indefinitely.
_FFMPEG_GRAB_TIMEOUT = 180


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


async def _frame_is_black(image_path: str) -> bool:
    """ Cheap solid-black check: scale the frame to 8x8, dump it as
    raw gray bytes, and look at the mean luma. ~64 bytes of data, so
    this costs tens of milliseconds and never touches the network.
    Returns False (i.e. "treat as fine") if the check itself fails -
    a skipped check is better than discarding a good thumbnail. """
    try:
        _pid, rc, stdout, _stderr = await run_command(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error",
                "-i", image_path,
                "-vf", "scale=8:8",
                "-f", "rawvideo", "-pix_fmt", "gray", "-",
            ],
            timeout=30,
        )
        if rc != 0 or not stdout:
            return False
        pixels = stdout.encode("latin-1")
        if not pixels:
            return False
        mean_luma = sum(pixels) / len(pixels)
        return mean_luma < _BLACK_LUMA_THRESHOLD
    except Exception:  # noqa: BLE001 - check is best-effort by design
        return False


async def take_screen_shot(
    video_file: str,
    output_directory: str,
    ttl: int
):
    """ Grab a thumbnail frame from a video.

    ROOT-CAUSE FIX for "black thumbnail on large videos":
    1. `-ss` now comes AFTER `-i`. With `-ss` before `-i` ffmpeg does
       a *keyframe* seek - it jumps to the nearest keyframe at or
       before the requested time and grabs whatever is there. Large
       videos have sparse keyframes (5-30+ s apart) and frequently
       start from a black/faded-in frame, so the old fast seek
       silently produced solid-black thumbnails. Seeking after `-i`
       is frame-accurate: ffmpeg decodes at most one GOP (a few
       seconds of video) to reach the exact requested frame. That
       costs well under a couple of seconds per video and happens
       BEFORE the upload starts - upload throughput is unchanged.
    2. If the requested moment (or a bad/zero duration) still yields
       a black frame, we retry at a few earlier candidates (50%,
       25%, 1s) and verify each frame with a cheap luma check, so a
       fade-from-black intro can no longer poison the thumbnail.
    3. The output is scaled to at most 320 px wide (Telegram's own
       thumbnail limit), which makes the encode near-instant.
    4. Every ffmpeg call is bounded by a timeout, so a corrupt file
       degrades to "no thumbnail" instead of hanging the upload.
    """
    if not _check_ffmpeg_once():
        return None
    out_put_file_name = os.path.join(
        output_directory,
        f"{int(time() * 1000)}_{uuid.uuid4().hex[:8]}.jpg"
    )
    if not video_file.upper().endswith(TG_VIDEO_TYPES):
        return None

    # Candidate seek points: requested time first, then earlier
    # fallbacks for fade-from-black intros / bad duration reads.
    # Deduplicated, non-negative, ordered.
    candidates = []
    for c in (ttl, (ttl or 0) / 2, (ttl or 0) / 4, 1):
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if c < 0 or c in candidates:
            continue
        candidates.append(c)

    last_error = "unknown error"
    for seek in candidates:
        file_genertor_command = [
            "ffmpeg",
            "-hide_banner",
            "-y",
            "-i",
            video_file,
            "-ss",
            str(seek),
            "-vframes",
            "1",
            "-vf",
            "scale='min(320,iw)':-2",
            out_put_file_name,
        ]
        _pid, returncode, _stdout, stderr = await run_command(
            file_genertor_command, timeout=_FFMPEG_GRAB_TIMEOUT,
        )
        if returncode != 0:
            last_error = (
                stderr.strip().splitlines()[-1] if stderr.strip()
                else f"ffmpeg exited with {returncode}"
            )
            continue
        if not os.path.lexists(out_put_file_name):
            last_error = "ffmpeg produced no output file"
            continue
        if await _frame_is_black(out_put_file_name):
            # Black frame (fade-in / sparse keyframe recording) -
            # try an earlier candidate instead.
            last_error = f"candidate {seek}s produced a black frame"
            continue
        return out_put_file_name

    print(
        f"[warn] ffmpeg could not generate a usable thumbnail for "
        f"{os.path.basename(video_file)}: {last_error}"
    )
    # Clean up any partial/black output so callers never see it.
    try:
        if os.path.lexists(out_put_file_name):
            os.remove(out_put_file_name)
    except OSError:
        pass
    return None

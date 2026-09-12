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
from dotenv import load_dotenv
from .get_config import get_config


BASE_DIR = os.path.expanduser("~/.config/gramflow/")
OLD_CONFIG_FILE = os.path.join(BASE_DIR, "config.ini")
CONFIG_FILE = os.path.join(BASE_DIR, "config.env")
# BUG FIX: pyrogram/kurigram names session files "<name>.session", not
# just "<name>" - this constant previously pointed at a file that
# never actually existed, which would have made any code relying on
# it (e.g. checking "is there a session?" or deleting it on logout)
# silently no-op.
SESSION_FILE = os.path.join(BASE_DIR, "GramFlow.session")
TG_VIDEO_TYPES = (
    "M4V", "MP4", "MOV", "FLV", "WMV", "3GP", "MPEG", "MKV", "WEBM"
)
TG_AUDIO_TYPES = (
    "MP3", "M4A", "M4B", "FLAC", "WAV", "AIF", "OGG", "AAC", "DTS"
)
# BUG FIX: photo/image files used to have no dedicated type, so they
# always fell through to `upload_as_document`, even when the user did
# not pass --fd (force_document). Telegram only accepts JPEG/PNG/WEBP
# as an actual "photo" (compressed) upload - anything else (e.g. GIF,
# BMP, TIFF) is sent as a document/animation regardless.
TG_IMAGE_TYPES = (
    "JPG", "JPEG", "PNG", "WEBP"
)


def _secure_chmod(path: str):
    """ Best-effort lock-down of a credentials file to owner
    read/write only (0600). Never raises - some platforms/filesystems
    (notably Windows, and some network/FAT-style mounts) don't support
    POSIX permission bits at all, and this must not crash the CLI on
    those. """
    try:
        os.chmod(path, 0o600)
    except (OSError, NotImplementedError):
        # chmod unsupported or refused on this platform/filesystem -
        # nothing more we can safely do here without breaking the CLI.
        pass


def _valid_credentials(app_id, api_hash):
    try:
        int(str(app_id).strip())
    except (TypeError, ValueError):
        return False
    return bool(str(api_hash).strip())


def write_default_config():
    """ write the default config.env file (or load an existing one)
    """
    # BUG FIX: the env-var short-circuit below used to run *before*
    # the legacy config.ini cleanup, so a user who had GF_TG_APP_ID /
    # GF_TG_API_HASH already set as real environment variables (while
    # also having a leftover config.ini from the old uploadgram days)
    # would return immediately and the old config.ini was never
    # touched - it just sat there unused forever. The one-time
    # migration cleanup now always runs first, regardless of which
    # path returns afterwards.
    if os.path.exists(OLD_CONFIG_FILE) and not os.path.lexists(CONFIG_FILE):
        os.remove(OLD_CONFIG_FILE)
    # If both credentials are already in the environment, there is
    # nothing to migrate and nothing to prompt for - just load any
    # existing config.env and return.
    env_app_id = os.environ.get("GF_TG_APP_ID")
    env_api_hash = os.environ.get("GF_TG_API_HASH")
    if env_app_id or env_api_hash:
        if _valid_credentials(env_app_id, env_api_hash):
            return load_dotenv(CONFIG_FILE)
        raise ValueError(
            "GF_TG_APP_ID and GF_TG_API_HASH must contain valid Telegram API credentials"
        )
    if os.path.lexists(CONFIG_FILE):
        # BUG FIX (item 7 - stale insecure permissions): previously
        # 0600 was only applied at the moment config.env was first
        # created. A file that already existed - e.g. created by an
        # older GramFlow version before this fix, restored from a
        # backup, or copied in manually - kept whatever permissions it
        # already had, potentially readable by other users on a
        # shared machine, forever. Re-assert 0600 on every run for an
        # existing file too, not just on creation.
        _secure_chmod(CONFIG_FILE)
        load_dotenv(CONFIG_FILE)
        if _valid_credentials(
            os.environ.get("GF_TG_APP_ID"), os.environ.get("GF_TG_API_HASH")
        ):
            return True
        print("[warn] existing config.env is missing or invalid Telegram API credentials; recreating it")
        try:
            os.remove(CONFIG_FILE)
        except OSError:
            pass
    os.makedirs(BASE_DIR, exist_ok=True)
    print(
        "Go to https://my.telegram.org (or @useTGxBot) "
        "and create a app in API development tools"
    )
    # BUG FIX: the config names used to be passed with a trailing
    # space ("app_id ", "api_hash ") which leaked into the prompt text
    # shown to the user ("enter app_id 's value: ").
    app_id = int(get_config("app_id", should_prompt=True))
    api_hash = get_config("api_hash", should_prompt=True)
    # SECURITY FIX: config.env holds the Telegram api_hash in plaintext.
    # Write it atomically (temp file -> chmod 0600 -> os.replace) so a
    # crash mid-write can never leave a truncated config OR a window
    # where the credentials file exists with default (possibly world-
    # readable) permissions. os.replace is atomic on POSIX and Windows.
    _tmp_config = CONFIG_FILE + ".tmp"
    with open(_tmp_config, "w") as f:
        f.write(f"GF_TG_APP_ID={app_id}\n")
        f.write(f"GF_TG_API_HASH={api_hash}\n\n")
    # chmod the temp file BEFORE it takes the real name.
    _secure_chmod(_tmp_config)
    os.replace(_tmp_config, CONFIG_FILE)
    return load_dotenv(CONFIG_FILE)


# BUG FIX: previously this module called `write_default_config()` at
# the bottom of the file, so *any* import of gramflow.config (e.g.
# `python -m gramflow.shell --help`, or `from gramflow import
# config` from another tool) immediately prompted the user for
# Telegram API credentials. That made the package unusable for
# read-only/CLI-help flows and crashed on stdin-less invocations.
# The wizard now runs lazily - it is invoked by `GramFlow.__init__`
# in gramflow/gramflow.py, which is the only place that actually
# needs the credentials.

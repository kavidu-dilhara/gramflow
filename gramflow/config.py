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
    if os.environ.get("GF_TG_APP_ID") and os.environ.get("GF_TG_API_HASH"):
        return load_dotenv(CONFIG_FILE)
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
        return load_dotenv(CONFIG_FILE)
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
    with open(CONFIG_FILE, "w") as f:
        f.write(f"GF_TG_APP_ID={app_id}\n")
        f.write(f"GF_TG_API_HASH={api_hash}\n\n")
    # SECURITY FIX: config.env holds the Telegram api_hash in plaintext.
    # It was previously written with the process's default umask, which
    # can leave it world- or group-readable on shared/multi-user
    # machines. Lock it down to owner read/write only (0600). Uses the
    # same best-effort helper as the "already exists" path above so
    # platforms without chmod support can't crash the CLI here either.
    _secure_chmod(CONFIG_FILE)
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

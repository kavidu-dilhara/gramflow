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


import inspect

# `kurigram` is installed as the pip package "kurigram" but, being a
# drop-in replacement for pyrogram, it is still imported as `pyrogram`.
# https://github.com/KurimuzonAkuma/kurigram
from pyrogram import Client, __version__
from pyrogram.enums import ParseMode, ClientPlatform
from .config import write_default_config, BASE_DIR
from .get_config import get_config


class GramFlow(Client):
    """ modded client """

    def __init__(self):
        # BUG FIX: invoke the config wizard here, *lazily*, instead
        # of having it run at module-import time in gramflow/config.
        # That way `--help`, programmatic imports, and any read-only
        # use of the package do NOT trigger a stdin prompt for
        # Telegram API credentials.
        write_default_config()
        wanted_kwargs = dict(
            name="GramFlow",
            # BUG FIX: `workdir` was never passed, so pyrogram/kurigram
            # defaulted to writing "GramFlow.session" into whatever
            # directory the CLI happened to be *run from* - not
            # ~/.config/gramflow/ where SESSION_FILE/BASE_DIR already
            # assumed it would live. In practice this meant running
            # gramflow from a different folder created a brand new,
            # separate (logged-out) session every time, and there was
            # no single reliable place for `gramflow logout` to find
            # and delete the session file.
            workdir=BASE_DIR,
            api_id=int(get_config("GF_TG_APP_ID")),
            api_hash=get_config("GF_TG_API_HASH"),
            parse_mode=ParseMode.HTML,
            sleep_threshold=int(get_config("GF_TG_ST", 10)),
            workers=int(get_config("GF_TG_WS", 10)),
            # NOTE (item 12 - concurrency audit): `max_concurrent_transmissions`
            # is a REAL pyrogram/kurigram setting - it bounds how many
            # concurrent network transmissions the client's own
            # connection pool will run. However, GramFlow's own
            # upload_dir_contents() in upload.py processes files
            # strictly sequentially (a plain `for` loop with `await`
            # on every iteration, no asyncio.gather()), so at the
            # GramFlow level there is never more than one file's
            # reply_video/reply_document/reply_photo call in flight at
            # a time. This setting therefore only affects the internal
            # chunking of a SINGLE large file's upload (pyrogram can
            # transmit multiple parts of one big file concurrently up
            # to this limit) - it does NOT make GramFlow upload
            # multiple different files at once. File-to-file uploads
            # are intentionally sequential: the existing resume-state
            # bookkeeping (state.py), the 10s post-upload rate-limit
            # pause, and the single shared batch-progress status
            # message are all written assuming one file completes
            # (and is recorded) before the next one starts. Making
            # file-to-file uploads concurrent would require bounding
            # concurrency, making UploadState writes safe under
            # concurrent access, and reworking the rate-limit pause -
            # a larger, separate change, not attempted here per the
            # audit's explicit instruction not to blindly add
            # concurrency.
            max_concurrent_transmissions=int(get_config("GF_TG_MCTS", 4)),
            no_updates=True,
            device_model="Samsung SM-G998B",
            app_version="10.11.2 (4665)",
            system_version="SDK 31",
            lang_pack="",
            lang_code="en",
            system_lang_code="en",
            # BUG FIX: these previously defaulted to 0, which disables
            # pyrogram/kurigram's message cache entirely. GramFlow's
            # whole upload flow is built on `usr_sent_message.reply_*()`
            # calls, which rely on that cache to resolve the parent
            # message without an extra round trip - a size of 0 can
            # cause intermittent reply failures under load. Restored to
            # pyrogram's own sane defaults; still overridable via env.
            max_message_cache_size=int(get_config("GF_TG_MMC", 10000)),
            max_business_user_connection_cache_size=int(
                get_config("GF_TG_MBUC", 200)
            ),
            client_platform=ClientPlatform.ANDROID,
        )
        # BUG FIX / FUTURE-PROOFING: forks like kurigram move fast and
        # occasionally rename/drop constructor kwargs between releases.
        # The old code passed every kwarg unconditionally, so a single
        # renamed parameter (e.g. across a pyrogram -> kurigram or a
        # future kurigram major bump) would crash on startup with a
        # bare TypeError. We now only pass kwargs that the installed
        # Client actually accepts, and quietly drop anything else
        # rather than dying.
        supported = set(
            inspect.signature(Client.__init__).parameters.keys()
        )
        kwargs = {
            key: value
            for key, value in wanted_kwargs.items()
            if key in supported
        }
        super().__init__(**kwargs)

    async def start(self):
        await super().start()
        # SECURITY/PRIVACY HARDENING (items 14/17): previously printed
        # the full `self.me` object - a verbose JSON-like dump
        # including the account's numeric id, username, phone-linked
        # flags, and other account metadata. This is not a credential
        # (no api_hash/session token is in it), so it is not a
        # "secret" under item 7/17's definition, but it is
        # unnecessary account-identifying information to leave sitting
        # in terminal scrollback or copy-pasted into a support/bug
        # report verbatim - which is exactly how it showed up in a
        # real user-submitted log during this project's development.
        # A short, non-identifying confirmation is enough for the
        # CLI's purposes.
        name = getattr(self.me, "first_name", None) or "account"
        print(f"Connected as {name} (Kurigram/pyrogram v{__version__}).")

    async def stop(self, *args):
        name = getattr(self.me, "first_name", None) or "account"
        await super().stop()
        print(f"Disconnected ({name}). Bye.")

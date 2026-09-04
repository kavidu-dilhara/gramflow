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
from .config import write_default_config
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
            api_id=int(get_config("GF_TG_APP_ID")),
            api_hash=get_config("GF_TG_API_HASH"),
            parse_mode=ParseMode.HTML,
            sleep_threshold=int(get_config("GF_TG_ST", 10)),
            workers=int(get_config("GF_TG_WS", 10)),
            max_concurrent_transmissions=int(get_config("GF_TG_MCTS", 4)),
            no_updates=True,
            device_model="Samsung SM-G998B",
            app_version="10.11.2 (4665)",
            system_version="SDK 31",
            lang_pack="",
            lang_code="en",
            system_lang_code="en",
            max_message_cache_size=int(get_config("GF_TG_MMC", 0)),
            max_business_user_connection_cache_size=int(
                get_config("GF_TG_MBUC", 0)
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
        print(
            f"{self.me} based on Kurigram (pyrogram) v{__version__} started."
        )

    async def stop(self, *args):
        usr_bot_me = self.me
        await super().stop()
        print(f"{usr_bot_me} stopped. Bye.")

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

""" human bytes """


def humanbytes(size: int) -> str:
    """ converts integer to string
    """
    # https://stackoverflow.com/a/49361727/4723940
    # 2**10 = 1024
    if not size:
        return "NaN"
    power = 2 ** 10
    n = 0
    dic_power_n = {
        0: " ",
        1: "Ki",
        2: "Mi",
        3: "Gi",
        4: "Ti",
        5: "Pi",
    }
    # BUG FIX: was `while size > power`, which meant a value of exactly
    # 1024 (or 1024**2, etc.) stayed unconverted and printed as
    # "1024.0  B" instead of "1.0 KiB". Also guard against `n` running
    # past the last defined unit for absurdly large sizes instead of
    # raising a KeyError.
    while size >= power and n < max(dic_power_n):
        size /= power
        n += 1
    return str(round(size, 2)) + " " + dic_power_n[n] + "B"

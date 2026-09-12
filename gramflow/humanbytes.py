#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2021 The Original Uploadgram Authors
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is licensed under the MIT License.
#  You may use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of this software subject to the terms of the MIT License.
#  The software is provided "AS IS", without warranty of any kind, express or
#  implied. See the LICENSE file for the complete license text.

""" human bytes """


def humanbytes(size: int) -> str:
    """ converts integer to string
    """
    # https://stackoverflow.com/a/49361727/4723940
    # 2**10 = 1024
    if size is None:
        return "NaN"
    if size == 0:
        # BUG FIX: humanbytes(0) used to return "NaN", which showed up
        # as "NaN/s" for zero-speed edges instead of a sensible "0 B".
        return "0 B"
    power = 2 ** 10
    n = 0
    dic_power_n = {
        0: "",
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

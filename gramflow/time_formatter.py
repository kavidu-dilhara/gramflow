#!/usr/bin/env python3
#  -*- coding: utf-8 -*-
#  Copyright (C) 2021 The Original Uploadgram Authors
#  Copyright (C) 2026 Kavidu Dilhara
#  This program is licensed under the MIT License.
#  You may use, copy, modify, merge, publish, distribute, sublicense,
#  and/or sell copies of this software subject to the terms of the MIT License.
#  The software is provided "AS IS", without warranty of any kind, express or
#  implied. See the LICENSE file for the complete license text.

""" time formatter """


def time_formatter(seconds: int) -> str:
    """ converts integer to string """
    result = ""
    v_m = 0
    remainder = seconds
    r_ange_s = {
        "days": (24 * 60 * 60),
        "hours": (60 * 60),
        "minutes": 60,
        "seconds": 1
    }
    for age in r_ange_s:
        divisor = r_ange_s[age]
        v_m, remainder = divmod(remainder, divisor)
        v_m = int(v_m)
        if v_m != 0:
            result += f" {v_m} {age} "
    return result

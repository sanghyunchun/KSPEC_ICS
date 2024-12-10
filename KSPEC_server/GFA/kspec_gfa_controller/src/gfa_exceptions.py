#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2023-12-06
# @Filename: exceptions.py
# @License: BSD 3-clause (http://www.opensource.org/licenses/BSD-3-Clause)

from __future__ import annotations


class GFAError(Exception):
    """A general ``GFA`` error."""

    def __init__(self, e: str):
        super().__init__(f"{e}")


class GFAinitError(Exception):
    """A general ``GFA`` error."""

    def __init__(self, e: str):
        super().__init__(f"{e}")


class GFAConfigError(Exception):
    """A general ``GFA`` error."""

    def __init__(self, e: str):
        super().__init__(f"{e}")


class GFACamNumError(Exception):
    """A general ``GFA`` error."""

    def __init__(self, e: str):
        super().__init__(f"{e}")


class GFAPingError(Exception):
    """A general ``GFA`` error."""

    def __init__(self, e: str):
        super().__init__(f"{e}")

"""Bounded LIKE translation and validation by the actual Rust/Polars engine."""

import re

import polars as pl

from xp_libs_analytics.errors import AnalyticsError
from xp_libs_analytics.policy import Limits


def like_regex(value: str) -> str:
    result, escaped = [], False
    for char in value:
        if escaped:
            if char not in "%_\\":
                raise AnalyticsError("MATCH_PATTERN_INVALID")
            result.append(re.escape(char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            result.append(".*" if char == "%" else "." if char == "_" else re.escape(char))
    if escaped:
        raise AnalyticsError("MATCH_PATTERN_INVALID")
    return r"(?s)\A" + "".join(result) + r"\z"


def regex_flags(pattern: str) -> list[str]:
    """Inspect flag groups, respecting escaped characters and bracket classes."""
    flags, escaped, depth = [], False, 0
    for index, char in enumerate(pattern):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[":
            depth += 1
        elif char == "]" and depth:
            depth -= 1
        elif char == "(" and not depth and pattern[index : index + 2] == "(?":
            end = index + 2
            while end < len(pattern) and (
                pattern[end].isascii() and pattern[end].isalpha() or pattern[end] == "-"
            ):
                end += 1
            if end > index + 2 and end < len(pattern) and pattern[end] in ":)":
                flags.append(pattern[index + 2 : end])
    return flags


def validate_regex(
    pattern: str, limits: Limits, *, translated: bool = False, wrapper_bytes: int = 0
) -> None:
    budget = (
        limits.max_match_literal_chars * 8 + 32
        if translated
        else limits.max_regex_bytes + wrapper_bytes
    )
    if len(pattern.encode("utf-8")) > budget:
        raise AnalyticsError("MATCH_REGEX_POLICY")
    if not translated:
        # This checks only a bounded policy syntax; it never executes user regex in Python.
        if any(flag != "i" for flag in regex_flags(pattern)):
            raise AnalyticsError("MATCH_REGEX_POLICY")
    try:
        pl.Series([""]).str.contains(pattern, literal=False, strict=True)
    except pl.exceptions.ComputeError:
        raise AnalyticsError("MATCH_REGEX_INVALID") from None
    if not limits.allow_match_catch_all:
        if pl.Series([""]).str.contains(pattern, literal=False, strict=True)[0]:
            raise AnalyticsError("MATCH_REGEX_POLICY")

"""Versioned Unicode preprocessing over bounded distinct strings, never row UDFs."""

import unicodedata
from typing import Literal, cast

from .models import Normalization

VERSION = "unicode-" + unicodedata.unidata_version + ":normalize-trim-casefold/v1"


def normalize(value: str, config: Normalization) -> str:
    if config.unicode != "none":
        value = unicodedata.normalize(cast(Literal["NFC", "NFKC"], config.unicode.upper()), value)
    if config.trim:
        value = value.strip()
    return value if config.case_sensitive else value.casefold()

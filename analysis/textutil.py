from __future__ import annotations

import re
import unicodedata

_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip most punctuation (keep letters/digits)."""
    value = unicodedata.normalize("NFKC", text or "")
    value = value.casefold()
    value = _URL_RE.sub(" ", value)
    value = _PUNCT_RE.sub(" ", value)
    value = _SPACE_RE.sub(" ", value).strip()
    return value


def contains_phrase(normalized: str, phrase: str) -> bool:
    needle = normalize_text(phrase)
    if not needle:
        return False
    return f" {needle} " in f" {normalized} "


def any_phrase(normalized: str, phrases: list[str]) -> bool:
    return any(contains_phrase(normalized, phrase) for phrase in phrases)


def strip_urls_for_length(text: str) -> str:
    value = _URL_RE.sub(" ", text or "")
    return _SPACE_RE.sub(" ", value).strip()

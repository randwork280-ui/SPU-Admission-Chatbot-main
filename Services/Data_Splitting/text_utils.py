from __future__ import annotations

import re
import unicodedata


ARABIC_DIACRITICS_RE = re.compile(r"[\u0610-\u061A\u064B-\u065F\u0670\u06D6-\u06ED]")
TATWEEL = "\u0640"

PUNCTUATION_TRANSLATION = str.maketrans(
    {
        "\u060c": ",",
        "\u061b": ";",
        "\u061f": "?",
        "\u066a": "%",
        "\u066b": ".",
        "\u066c": ",",
    }
)


def normalize_arabic_text(text: str, remove_diacritics: bool = True) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = normalized.replace(TATWEEL, "")
    normalized = normalized.translate(PUNCTUATION_TRANSLATION)
    if remove_diacritics:
        normalized = ARABIC_DIACRITICS_RE.sub("", normalized)
    normalized = re.sub(r"[ \t\r\f\v]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()

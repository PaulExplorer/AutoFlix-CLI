"""Normalization of the language tags returned by subtitle providers.

Providers are inconsistent: one returns ISO 639-1 (``fr``), another ISO
639-2/B (``fre``), a third a full English name (``French``) or a BCP-47 tag
(``pt-BR``). Comparing those strings naively is a source of bugs -- for
instance ``"en" in "french"`` is ``True``. Every tag therefore funnels through
:func:`normalize_language`, which returns a single canonical ISO 639-1 code.
"""

from __future__ import annotations

# canonical ISO 639-1 code -> English display name.
LANGUAGE_LABELS: dict[str, str] = {
    "ar": "Arabic",
    "bn": "Bengali",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "en": "English",
    "es": "Spanish",
    "fa": "Persian",
    "fi": "Finnish",
    "fr": "French",
    "he": "Hebrew",
    "hi": "Hindi",
    "hr": "Croatian",
    "hu": "Hungarian",
    "id": "Indonesian",
    "it": "Italian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "nl": "Dutch",
    "no": "Norwegian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sr": "Serbian",
    "sv": "Swedish",
    "ta": "Tamil",
    "te": "Telugu",
    "th": "Thai",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ur": "Urdu",
    "vi": "Vietnamese",
    "zh": "Chinese",
}

# (canonical code, extra aliases). The code itself and the lowercased label
# are always registered automatically.
_ALIASES_SOURCE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ar", ("ara",)),
    ("bn", ("ben",)),
    ("cs", ("cze", "ces")),
    ("da", ("dan",)),
    ("de", ("ger", "deu")),
    ("el", ("gre", "ell")),
    ("en", ("eng",)),
    ("es", ("spa", "castilian")),
    ("fa", ("per", "fas")),
    ("fi", ("fin",)),
    ("fr", ("fre", "fra")),
    ("he", ("heb", "iw")),
    ("hi", ("hin",)),
    ("hr", ("hrv",)),
    ("hu", ("hun",)),
    ("id", ("ind",)),
    ("it", ("ita",)),
    ("ja", ("jpn",)),
    ("ko", ("kor",)),
    ("ms", ("may", "msa")),
    ("nl", ("dut", "nld")),
    ("no", ("nor",)),
    ("pl", ("pol",)),
    ("pt", ("por", "pob", "pt-br", "pt-pt")),
    ("ro", ("rum", "ron")),
    ("ru", ("rus",)),
    ("sk", ("slo", "slk")),
    ("sr", ("srp",)),
    ("sv", ("swe",)),
    ("ta", ("tam",)),
    ("te", ("tel",)),
    ("th", ("tha",)),
    ("tr", ("tur",)),
    ("uk", ("ukr",)),
    ("ur", ("urd",)),
    ("vi", ("vie",)),
    ("zh", ("chi", "zho", "zh-cn", "zh-tw", "zh-hans", "zh-hant", "mandarin")),
)


def _build_aliases() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for code, extras in _ALIASES_SOURCE:
        aliases[code] = code
        aliases[LANGUAGE_LABELS[code].lower()] = code
        for extra in extras:
            aliases[extra] = code
    return aliases


_ALIASES = _build_aliases()


def normalize_language(value: object) -> str | None:
    """Return the canonical ISO 639-1 code for ``value``, or ``None``.

    Accepts ISO 639-1/2 codes, English names and BCP-47 tags. ``"French"``,
    ``"fre"``, ``"fra"`` and ``"fr-FR"`` all normalize to ``"fr"``.
    """
    if not value:
        return None
    token = str(value).strip().lower().replace("_", "-")
    if not token:
        return None
    if token in _ALIASES:
        return _ALIASES[token]
    # Drop a regional suffix: "pt-br" -> "pt", "zh-hant" -> "zh".
    base = token.split("-", 1)[0]
    return _ALIASES.get(base)


def language_label(code: str | None) -> str:
    """Human readable name for a canonical code (``"fr"`` -> ``"French"``)."""
    if not code:
        return "Unknown"
    return LANGUAGE_LABELS.get(code, code)


def languages_match(candidate: object, wanted: object) -> bool:
    """Whether ``candidate`` and ``wanted`` refer to the same language."""
    wanted_code = normalize_language(wanted)
    if wanted_code is None:
        return True
    return normalize_language(candidate) == wanted_code

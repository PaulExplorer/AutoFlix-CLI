from typing import Dict, Any

LANGUAGES: Dict[str, Dict[str, str]] = {
    "fr": {"display": "Français", "label": "French", "flag": "🇫🇷"},
    "en": {"display": "English", "label": "English", "flag": "🇺🇸"},
}


def get_language_label(code: str, default: str = "Selected Language") -> str:
    """Returns the label (English name) for a language code."""
    return LANGUAGES.get(code, {}).get("label", default)


def get_language_display(code: str, default: str = "Not Set") -> str:
    """Returns the display name (e.g. 'Français') for a language code."""
    return LANGUAGES.get(code, {}).get("display", default)


def get_language_flag(code: str, default: str = "") -> str:
    """Returns the flag emoji for a language code."""
    return LANGUAGES.get(code, {}).get("flag", default)


def get_language_aliases() -> Dict[str, str]:
    """Returns a mapping of code to lowercase label for subtitle filtering."""
    return {code: lang["label"].lower() for code, lang in LANGUAGES.items()}


def get_all_languages():
    """Returns all registered languages as a list of tuples (code, display_with_flag)."""
    return [
        (code, f"{lang['flag']} {lang['display']}") for code, lang in LANGUAGES.items()
    ]

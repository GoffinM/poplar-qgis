"""Translatable messages of the engine (spec §15).

The engine never builds user-facing sentences directly: it produces a
:class:`Message` (a code and its values), rendered later in the language
chosen by the user. Catalogs are JSON files in ``locales/<language>.json``;
a missing translation falls back to French, then to the code itself.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Dict

DEFAULT_LANGUAGE = "fr"
LOCALES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locales")

# Thousands and decimal separators by language.
NUMBER_FORMATS = {
    "fr": (" ", ","),
    "en": (",", "."),
    "es": (".", ","),
    "pt": (".", ","),
    "ru": (" ", ","),
    "uk": (" ", ","),
    "ar": (",", "."),
    "sw": (",", "."),
    "rw": (",", "."),
    "rn": (",", "."),
}


@dataclass(frozen=True)
class Message:
    code: str
    values: Dict[str, Any] = field(default_factory=dict)

    def render(self, language: str = DEFAULT_LANGUAGE) -> str:
        if self.code == "scenario_missing_key":  # name the setting and its tab rather than the JSON key
            label = catalog(language).get(f"input_{self.values.get('key')}") or \
                catalog(DEFAULT_LANGUAGE).get(f"input_{self.values.get('key')}")
            if label:
                return translate("scenario_missing_input", language, input=label)
        return translate(self.code, language, **self.values)

    def to_dict(self, language: str = DEFAULT_LANGUAGE) -> Dict[str, Any]:
        return {"code": self.code, "values": self.values, "text": self.render(language)}


def message(code: str, **values: Any) -> Message:
    return Message(code, values)


@lru_cache(maxsize=None)
def catalog(language: str) -> Dict[str, str]:
    path = os.path.join(LOCALES_DIR, f"{language}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def available_languages():
    return sorted(name[:-5] for name in os.listdir(LOCALES_DIR) if name.endswith(".json"))


def translate(code: str, language: str = DEFAULT_LANGUAGE, **values: Any) -> str:
    template = catalog(language).get(code) or catalog(DEFAULT_LANGUAGE).get(code) or code
    formatted = {key: _format_value(value, language) for key, value in values.items()}
    try:
        return template.format(**formatted)
    except (KeyError, IndexError):
        return template


def format_number(value: float, language: str = DEFAULT_LANGUAGE, decimals: int = None) -> str:
    """Number with the separators of the language.

    Without ``decimals``: whole numbers are shown without decimals, small
    non-whole numbers with up to two decimals, large ones rounded.
    """
    thousands, decimal = NUMBER_FORMATS.get(language, NUMBER_FORMATS["en"])
    if decimals is None:
        if abs(value - round(value)) < 1e-9 or abs(value) >= 100:
            decimals = 0
        else:
            decimals = 2
    text = f"{value:,.{decimals}f}"
    if decimals and "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(",", "\x00").replace(".", decimal).replace("\x00", thousands)


def _format_value(value: Any, language: str) -> Any:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return format_number(float(value), language)
    return value

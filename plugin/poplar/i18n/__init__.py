"""Interface translations.

The plugin uses the same mechanism as the engine: JSON catalogs per
language (``i18n/<language>.json``), keyed by an identifier. The language
follows the QGIS locale; a missing text falls back to French, then to the
identifier itself. Adding a language means adding a catalog file.
"""

import json
import os
from functools import lru_cache

DEFAULT = "fr"
HERE = os.path.dirname(os.path.abspath(__file__))


def current_language() -> str:
    try:
        from qgis.core import QgsSettings

        locale = QgsSettings().value("locale/userLocale", "") or ""
    except Exception:  # outside QGIS
        locale = ""
    language = str(locale)[:2].lower()
    return language if os.path.exists(os.path.join(HERE, f"{language}.json")) else DEFAULT


@lru_cache(maxsize=None)
def _catalog(language: str) -> dict:
    path = os.path.join(HERE, f"{language}.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def tr(key: str, language: str = None, **values) -> str:
    language = language or current_language()
    text = _catalog(language).get(key) or _catalog(DEFAULT).get(key) or key
    return text.format(**values) if values else text


def tip(key: str, language: str = None) -> str:
    """Tooltip as rich text: a bold title and an explanation (catalog keys ``<key>.tip.title`` / ``.tip``)."""
    title = tr(f"{key}.tip.title", language)
    body = tr(f"{key}.tip", language)
    return f"<b>{title}</b><br>{body}"

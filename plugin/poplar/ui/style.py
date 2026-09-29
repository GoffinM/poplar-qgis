"""Graphic charter of the plugin (validated 29/09/2026): petrol and ochre, from the icon.

Only a Qt style sheet and the system font: nothing to install, same look on
QGIS 3.40 (Qt5) and QGIS 4 (Qt6). A dark variant follows dark QGIS themes
(« Night Mapping »).
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap

LIGHT = {
    "window": "#ffffff", "panel": "#f6f8f7", "line": "#d5dedc", "ink": "#1d2b2a", "muted": "#5c6e6c",
    "teal": "#1f6f6a", "teal_soft": "#dcecea", "ochre": "#c98a36", "ochre_soft": "#f6e7cf", "on_teal": "#ffffff",
}
DARK = {
    "window": "#1e2626", "panel": "#242e2e", "line": "#36443f", "ink": "#e4ecea", "muted": "#9aaeab",
    "teal": "#4fa9a1", "teal_soft": "#22403d", "ochre": "#e0a85a", "ochre_soft": "#3f3322", "on_teal": "#0f1c1b",
}
STATES = ("ok", "warn", "empty")


def is_dark(widget) -> bool:
    return widget.palette().color(widget.backgroundRole()).lightness() < 128


def tokens(widget):
    return DARK if is_dark(widget) else LIGHT


def stylesheet(t) -> str:
    return f"""
QFrame#header {{ background: {t['teal']}; border: none; }}
QFrame#header QLabel {{ color: {t['on_teal']}; background: transparent; }}
QLabel#title {{ font-size: 15px; font-weight: 600; }}
QLabel#subtitle {{ font-size: 12px; }}
QToolButton#help {{ color: {t['on_teal']}; border: 1px solid {t['on_teal']}; border-radius: 11px;
    min-width: 20px; min-height: 20px; font-weight: 600; background: transparent; }}
QToolButton#help:hover {{ background: rgba(255, 255, 255, 40); }}

QListWidget#tabs {{ background: {t['panel']}; border: none; border-right: 1px solid {t['line']};
    color: {t['ink']}; outline: 0; padding-top: 6px; }}
QListWidget#tabs::item {{ padding: 7px 10px; border-left: 3px solid transparent; }}
QListWidget#tabs::item:selected {{ background: {t['teal_soft']}; color: {t['ink']};
    border-left: 3px solid {t['teal']}; font-weight: 600; }}
QListWidget#tabs::item:disabled {{ color: {t['muted']}; }}

QToolButton#browse::menu-indicator {{ image: none; width: 0px; }}
QToolButton#browse {{ padding: 0 6px; }}

QFrame#footer {{ background: {t['panel']}; border-top: 1px solid {t['line']}; }}

QGroupBox {{ border: 1px solid {t['line']}; border-radius: 4px; margin-top: 18px; padding: 10px 8px 8px 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top left; left: 8px; padding: 0 4px;
    color: {t['teal']}; font-weight: 700; }}

QPushButton#primary {{ background: {t['teal']}; color: {t['on_teal']}; border: 1px solid {t['teal']};
    border-radius: 3px; padding: 5px 14px; font-weight: 600; }}
QPushButton#primary:hover {{ background: {t['ink'] if t is DARK else '#185a56'}; }}
QPushButton#primary:disabled {{ background: {t['line']}; border-color: {t['line']}; color: {t['muted']}; }}

QLabel#chip {{ background: {t['teal_soft']}; color: {t['teal']}; border-radius: 9px; padding: 2px 9px;
    font-weight: 600; }}
QLabel#chip[state="warn"] {{ background: {t['ochre_soft']}; color: {t['ochre']}; }}

QHeaderView::section {{ background: {t['panel']}; color: {t['muted']}; border: none;
    border-bottom: 1px solid {t['line']}; border-right: 1px solid {t['line']}; padding: 4px 6px; font-weight: 600; }}
"""


def state_icon(state: str, t) -> QIcon:
    """Small dot: complete (petrol), to check (ochre), empty (outline)."""
    size = 16
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if state == "empty":
        painter.setPen(QColor(t["muted"]))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    else:
        colour = QColor(t["teal"] if state == "ok" else t["ochre"])
        painter.setPen(colour)
        painter.setBrush(colour)
    painter.drawEllipse(4, 4, 8, 8)
    painter.end()
    return QIcon(pixmap)

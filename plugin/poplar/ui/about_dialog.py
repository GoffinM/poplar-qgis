"""« À propos » card: who made the tool, how and why (spec §14.1)."""

import configparser
import os

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ..i18n import tr

METADATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "metadata.txt")


def version() -> str:
    parser = configparser.ConfigParser()
    parser.read(METADATA, encoding="utf-8")
    return parser.get("general", "version", fallback="?")


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("about.title"))
        layout = QVBoxLayout(self)
        text = QLabel(tr("about.text", version=version()))
        text.setWordWrap(True)
        text.setOpenExternalLinks(True)
        text.setMinimumWidth(520)
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

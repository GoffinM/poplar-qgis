"""Navigable help, shipped with the plugin (works offline), in the language of QGIS."""

import os
import re

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem, QTextBrowser, QVBoxLayout,
)

from ..i18n import DEFAULT, current_language, tr

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "help")
ORDER = ["prise_en_main", "parametres_et_scenario", "strates", "calage", "croissance_plafonds_migration", "non_convergence",
         "resultats_et_indicateurs"]


def help_folder(language=None) -> str:
    language = language or current_language()
    folder = os.path.join(HELP_DIR, language)
    return folder if os.path.isdir(folder) else os.path.join(HELP_DIR, DEFAULT)


def pages(language=None):
    """[(name, title, text)] of the help pages, in reading order."""
    folder = help_folder(language)
    names = [n[:-5] for n in os.listdir(folder) if n.endswith(".html")] if os.path.isdir(folder) else []
    names.sort(key=lambda n: (ORDER.index(n) if n in ORDER else len(ORDER), n))
    result = []
    for name in names:
        with open(os.path.join(folder, f"{name}.html"), encoding="utf-8") as handle:
            html = handle.read()
        match = re.search(r"<h1>(.*?)</h1>", html, re.S)
        text = re.sub(r"<[^>]+>", " ", html)
        result.append((name, re.sub(r"<[^>]+>", "", match.group(1)) if match else name, text))
    return result


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("help.title"))
        self.resize(900, 640)
        layout = QVBoxLayout(self)
        body = QHBoxLayout()
        side = QVBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("help.search"))
        self.search.textChanged.connect(self._filter)
        side.addWidget(self.search)
        self.toc = QListWidget()
        self.toc.setFixedWidth(240)
        self.toc.currentItemChanged.connect(lambda item, _: item and self._open(item.data(256)))
        side.addWidget(self.toc)
        body.addLayout(side)
        self.browser = QTextBrowser()
        self.browser.setOpenLinks(True)
        self.browser.setOpenExternalLinks(True)
        body.addWidget(self.browser, 1)
        layout.addLayout(body, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)
        self.entries = pages()
        for name, title, _ in self.entries:
            item = QListWidgetItem(title)
            item.setData(256, name)
            self.toc.addItem(item)

    def show_page(self, name):
        for i in range(self.toc.count()):
            if self.toc.item(i).data(256) == name:
                self.toc.setCurrentRow(i)
                break
        else:
            if self.toc.count():
                self.toc.setCurrentRow(0)
        self.show()
        self.raise_()

    def _open(self, name):
        self.browser.setSource(QUrl.fromLocalFile(os.path.join(help_folder(), f"{name}.html")))

    def _filter(self, text):
        text = text.lower().strip()
        for i, (_, _, content) in enumerate(self.entries):
            self.toc.item(i).setHidden(bool(text) and text not in content.lower())

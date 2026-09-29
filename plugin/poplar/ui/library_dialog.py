"""Library of scenarios: start from a saved scenario, or add the current one (decision of 29/09/2026)."""

import os

from qgis.core import QgsApplication, QgsSettings
from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDialog, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout,
)

from ..engine.library import list_library, save_to_library
from ..i18n import tip, tr

SETTING = "poplar/library_folder"


def library_folder() -> str:
    default = os.path.join(QgsApplication.qgisSettingsDirPath(), "poplar", "library")
    return QgsSettings().value(SETTING, default) or default


def set_library_folder(folder: str) -> None:
    QgsSettings().setValue(SETTING, folder)


class LibraryDialog(QDialog):
    """Lists the scenarios of the library; ``chosen`` holds the file to open after « Open »."""

    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.chosen = None
        self.entries = []
        self.setWindowTitle(tr("library.title"))
        self.resize(760, 440)
        layout = QVBoxLayout(self)

        row = QHBoxLayout()
        self.folder = QLabel()
        self.folder.setWordWrap(True)
        row.addWidget(self.folder, 1)
        change = QPushButton(tr("library.change"))
        change.setToolTip(tip("library.change"))
        change.clicked.connect(self._change_folder)
        show = QPushButton(tr("results.open_folder"))
        show.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(library_folder())))
        row.addWidget(change)
        row.addWidget(show)
        layout.addLayout(row)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("library.name"), tr("library.description"), tr("library.modified")])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.cellDoubleClicked.connect(lambda *args: self.open_selected())
        layout.addWidget(self.table, 1)
        self.empty = QLabel(tr("library.empty"))
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)

        buttons = QHBoxLayout()
        add = QPushButton(tr("library.add"))
        add.setToolTip(tip("library.add"))
        add.clicked.connect(self.add_current)
        buttons.addWidget(add)
        buttons.addStretch(1)
        close = QPushButton(tr("common.close"))
        close.clicked.connect(self.reject)
        self.open_button = QPushButton(tr("library.open"))
        self.open_button.setObjectName("primary")
        self.open_button.setToolTip(tip("library.open"))
        self.open_button.clicked.connect(self.open_selected)
        buttons.addWidget(close)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)
        self.refresh()

    def refresh(self):
        folder = library_folder()
        self.folder.setText(tr("library.folder", folder=folder))
        self.entries = list_library(folder)
        self.table.setRowCount(len(self.entries))
        for row, entry in enumerate(self.entries):
            for column, text in enumerate((entry.name, entry.description, entry.modified)):
                item = QTableWidgetItem(text)
                item.setToolTip(entry.path)
                self.table.setItem(row, column, item)
        if self.entries:
            self.table.selectRow(0)
        self.empty.setVisible(not self.entries)
        self.open_button.setEnabled(bool(self.entries))

    def _change_folder(self):
        folder = QFileDialog.getExistingDirectory(self, tr("library.change"), library_folder())
        if folder:
            set_library_folder(folder)
            self.refresh()

    def open_selected(self):
        row = self.table.currentRow()
        if 0 <= row < len(self.entries):
            self.chosen = self.entries[row].path
            self.accept()

    def add_current(self, name=None, description=None):
        """Save the scenario shown in the main window into the library (asks a name and a description)."""
        data = self.main.collect()
        if name is None:
            dialog = QDialog(self)
            dialog.setWindowTitle(tr("library.add"))
            form = QFormLayout(dialog)
            name_edit = QLineEdit(data.get("name", ""))
            description_edit = QLineEdit(data.get("description", ""))
            form.addRow(tr("library.name"), name_edit)
            form.addRow(tr("library.description"), description_edit)
            ok = QPushButton(tr("library.save"))
            ok.clicked.connect(dialog.accept)
            form.addRow("", ok)
            if dialog.exec() != QDialog.DialogCode.Accepted or not name_edit.text().strip():
                return None
            name, description = name_edit.text().strip(), description_edit.text().strip()
        path = save_to_library(library_folder(), data, name, description or "")
        self.refresh()
        return path

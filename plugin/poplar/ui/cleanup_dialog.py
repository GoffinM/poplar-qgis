"""Clean-up of the run folders (decision of 29/09/2026).

Every run writes its own time-stamped folder; the runs not marked as kept
are proposed for deletion, in one go, instead of file by file.
"""

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHeaderView, QLabel, QMessageBox, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from ..engine import runs
from ..i18n import tip, tr
from ..results import release_layers

COLUMNS = ["run", "scenario", "status", "years", "size", "kept", "delete"]
KEPT, DELETE = COLUMNS.index("kept"), COLUMNS.index("delete")


def run_title(run) -> str:
    """« 2026-09-29 14:48 » (and the label given by the user, if any)."""
    title = run.created.replace("T", " ")[:16] if run.created else run.folder_name
    return f"{title} – {run.label}" if run.label else title


def format_size(size_bytes: int) -> str:
    megabytes = size_bytes / 1e6
    text = f"{megabytes:,.0f}".replace(",", " ") if megabytes >= 10 else f"{megabytes:.1f}".replace(".", ",")
    return tr("cleanup.size", size=text)


class CleanupDialog(QDialog):
    def __init__(self, root, parent=None, intro_key="cleanup.intro"):
        super().__init__(parent)
        self.root = root
        self.runs = list(reversed(runs.list_runs(root)))  # newest first
        self.sizes = {r.directory: r.size_bytes() for r in self.runs}
        self.deleted = []
        self.failed = []
        self.setWindowTitle(tr("cleanup.title"))
        self.resize(920, 420)

        layout = QVBoxLayout(self)
        intro = QLabel(tr(intro_key, folder=root))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.table = QTableWidget(len(self.runs), len(COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(f"cleanup.column.{c}") for c in COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        proposed = runs.default_deletion(self.runs)
        for row, run in enumerate(self.runs):
            texts = [run_title(run), run.name, tr(f"cleanup.status.{run.status}"),
                     f"{run.years[0]}–{run.years[-1]}" if run.years else "–", format_size(self.sizes[run.directory])]
            for column, text in enumerate(texts):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
            self.table.item(row, 0).setToolTip(run.directory)
            for column, checked in ((KEPT, run.kept), (DELETE, run.directory in proposed)):
                item = QTableWidgetItem()
                item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self.table.setItem(row, column, item)
        self.table.itemChanged.connect(self._changed)
        layout.addWidget(self.table, 1)

        self.all = QCheckBox(tr("cleanup.all"))
        self.all.setToolTip(tip("cleanup.all"))
        self.all.setChecked(True)
        self.all.toggled.connect(self._check_all)
        layout.addWidget(self.all)
        self.total = QLabel()
        layout.addWidget(self.total)

        buttons = QDialogButtonBox()
        self.delete_button = buttons.addButton(tr("cleanup.delete"), QDialogButtonBox.ButtonRole.DestructiveRole)
        self.delete_button.setToolTip(tip("cleanup.delete"))
        keep = buttons.addButton(tr("cleanup.close"), QDialogButtonBox.ButtonRole.RejectRole)
        self.delete_button.clicked.connect(self.delete_selected)
        keep.clicked.connect(self.reject)
        layout.addWidget(buttons)
        self._update_total()

    # --- selection ----------------------------------------------------------------

    def _checked(self, row, column) -> bool:
        return self.table.item(row, column).checkState() == Qt.CheckState.Checked

    def _set(self, row, column, checked):
        self.table.item(row, column).setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)

    def selected(self):
        """Folders checked for deletion."""
        return [r.directory for i, r in enumerate(self.runs) if self._checked(i, DELETE)]

    def _changed(self, item):
        row, column = item.row(), item.column()
        if column == KEPT:
            kept = self._checked(row, KEPT)
            runs.set_kept(self.runs[row].directory, kept)
            self.runs[row].kept = kept
            if kept and self._checked(row, DELETE):
                self._set(row, DELETE, False)
        elif column == DELETE and self._checked(row, DELETE) and self._checked(row, KEPT):
            self._set(row, DELETE, False)  # a kept run is never deleted
        self._update_total()

    def _check_all(self, checked):
        proposed = runs.default_deletion(self.runs) if checked else set()
        self.table.blockSignals(True)
        for row, run in enumerate(self.runs):
            self._set(row, DELETE, run.directory in proposed)
        self.table.blockSignals(False)
        self._update_total()

    def _update_total(self):
        selected = self.selected()
        size = sum(self.sizes[d] for d in selected)
        self.total.setText(tr("cleanup.total", count=len(selected), size=format_size(size)))
        self.delete_button.setEnabled(bool(selected))

    # --- deletion -----------------------------------------------------------------

    def delete_selected(self):
        for directory in self.selected():
            release_layers(directory)
            try:
                failed = runs.delete_run(directory)
            except (OSError, ValueError) as error:
                failed = [str(error)]
            if failed:
                self.failed.extend(failed)
            else:
                self.deleted.append(directory)
        if self.failed:
            QMessageBox.warning(self, tr("cleanup.title"),
                                tr("cleanup.failed", files="\n".join(os.path.basename(f) for f in self.failed[:10])))
        self.accept()

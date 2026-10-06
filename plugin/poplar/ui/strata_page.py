"""Strata tab: polygons that are planned (fixed) or free (they grow by colonisation), fiche §3.5.

Layout validated on 06/10/2026 (docs/maquette_strates.html). The tab reads and writes the ``strata``
block of the scenario and the two colonisation parameters of each stratum (minimum export and share at
capacity). In planned mode only the choice of the mode and the preparation of the built-up patches are
active; the other settings are kept for when the free mode is chosen again.
"""

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPushButton, QRadioButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..engine.patches import ORIGINAL, revert_patches
from ..i18n import tip, tr
from .pages import Page, _box, _spin
from .parameter_table import field_values
from .widgets import add_row, choice_combo, set_combo_value

PLANNED, FREE = "planned", "free"
SHARE, INHABITANTS = "share_of_capacity", "inhabitants"
INFLOW, SATURATION = "colonization_min_inflow", "saturation_share"
DEFAULTS = {INFLOW: 0.1, SATURATION: 0.8}
NUCLEI = {"enabled": False, "stratum": None, "min_cells": 16, "enclave_km2": 5.0, "migration_share": 0.5}
COLUMNS = ("class", "rank", "colonizable", "urban", "inflow", "saturation")


class StrataPage(Page):
    key = "strata"

    def __init__(self, dialog):
        super().__init__()
        self.dialog = dialog
        self.kept = {}                     # parameters given as series or by zones: kept as they are
        self.extra = {}                    # keys of the strata block this tab does not show (patches_original…)
        layout = QVBoxLayout(self)

        box = QGroupBox(tr("strata.mode"))
        inner = QVBoxLayout(box)
        self.modes = QButtonGroup(self)
        for value in (PLANNED, FREE):
            button = QRadioButton(tr(f"strata.mode.{value}"))
            button.setToolTip(tip(f"strata.mode.{value}"))
            button.setProperty("mode", value)
            self.modes.addButton(button)
            inner.addWidget(button)
            text = QLabel(tr(f"strata.mode.{value}.text"))
            text.setWordWrap(True)
            text.setContentsMargins(22, 0, 0, 4)
            inner.addWidget(text)
        self.modes.buttonClicked.connect(lambda *args: self._mode_changed())
        self.warning = QLabel(tr("strata.free_warning"))
        self.warning.setObjectName("chip")
        self.warning.setProperty("state", "warn")
        self.warning.setWordWrap(True)
        inner.addWidget(self.warning)
        layout.addWidget(box)

        box = QGroupBox(tr("strata.start"))
        inner = QVBoxLayout(box)
        row = QHBoxLayout()
        self.typology = QLabel()
        self.typology.setWordWrap(True)
        row.addWidget(self.typology, 1)
        self.prepare = QPushButton(tr("strata.prepare"))
        self.prepare.setToolTip(tip("strata.prepare"))
        self.prepare.clicked.connect(self._prepare)
        row.addWidget(self.prepare)
        inner.addLayout(row)
        row = QHBoxLayout()
        self.patches_chip = QLabel()
        self.patches_chip.setObjectName("chip")
        row.addWidget(self.patches_chip)
        self.revert = QPushButton(tr("strata.revert"))
        self.revert.setToolTip(tip("strata.revert"))
        self.revert.clicked.connect(self._revert)
        row.addWidget(self.revert)
        row.addStretch(1)
        inner.addLayout(row)
        hint = QLabel(tr("strata.start.hint"))
        hint.setWordWrap(True)
        inner.addWidget(hint)
        layout.addWidget(box)

        self.strata_box = QGroupBox(tr("strata.table"))
        inner = QVBoxLayout(self.strata_box)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels([tr(f"strata.column.{c}") for c in COLUMNS])
        for i, column in enumerate(COLUMNS):
            self.table.horizontalHeaderItem(i).setToolTip(tip(f"strata.column.{column}"))
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setMinimumSectionSize(60)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(140)
        inner.addWidget(self.table)
        hint = QLabel(tr("strata.table.hint"))
        hint.setWordWrap(True)
        inner.addWidget(hint)
        layout.addWidget(self.strata_box)

        self.rules_box, form = _box("strata.rules")
        self.neighbours = _spin(0, 8, 3)
        add_row(form, "strata.min_neighbors", self.neighbours)
        self.membership = _spin(50, 100, 50)
        self.membership.setSuffix(" %")
        add_row(form, "strata.membership", self.membership)
        self.inflow_unit = choice_combo([(SHARE, tr("strata.inflow_unit.share")),
                                         (INHABITANTS, tr("strata.inflow_unit.inhabitants"))])
        self.inflow_unit.currentIndexChanged.connect(lambda *args: self._inflow_unit_changed())
        add_row(form, "strata.inflow_unit", self.inflow_unit)
        self.urban_rank = QComboBox()
        add_row(form, "strata.urban_rank", self.urban_rank)
        layout.addWidget(self.rules_box)

        self.nuclei_box = QGroupBox(tr("strata.nuclei"))
        form = QFormLayout(self.nuclei_box)
        self.nuclei = QCheckBox(tr("strata.nuclei.enabled"))
        self.nuclei.setToolTip(tip("strata.nuclei.enabled"))
        self.nuclei.toggled.connect(lambda *args: self._enable())
        form.addRow(self.nuclei)
        self.nucleus_stratum = QComboBox()
        add_row(form, "strata.nuclei.stratum", self.nucleus_stratum)
        self.min_cells = _spin(1, 10000, 16)
        self.min_cells.setSuffix(tr("strata.nuclei.cells_suffix"))
        add_row(form, "strata.nuclei.min_cells", self.min_cells)
        self.enclave = _spin(0, 10000, 5, decimals=1, step=1)
        self.enclave.setSuffix(" km²")
        add_row(form, "strata.nuclei.enclave", self.enclave)
        self.migration_share = _spin(0, 100, 50)
        self.migration_share.setSuffix(" %")
        add_row(form, "strata.nuclei.migration_share", self.migration_share)
        layout.addWidget(self.nuclei_box)

        self.outputs_box, form = _box("strata.outputs")
        self.smoothing = _spin(0, 5, 2)
        add_row(form, "strata.smoothing", self.smoothing)
        self.min_patch = _spin(0, 1000, 0.0625, decimals=4, step=0.0625)
        self.min_patch.setSuffix(" km²")
        add_row(form, "strata.min_patch", self.min_patch)
        layout.addWidget(self.outputs_box)
        layout.addStretch(1)

    # --- state ----------------------------------------------------------------------

    def mode(self) -> str:
        button = self.modes.checkedButton()
        return button.property("mode") if button is not None else PLANNED

    def _mode_changed(self):
        self._enable()

    def _enable(self):
        free = self.mode() == FREE
        self.warning.setVisible(free)
        for widget in (self.strata_box, self.rules_box, self.nuclei_box, self.outputs_box):
            widget.setEnabled(free)
        for widget in (self.nucleus_stratum, self.min_cells, self.enclave, self.migration_share):
            widget.setEnabled(free and self.nuclei.isChecked())

    def _inflow_unit_changed(self):
        share = self.inflow_unit.currentData() == SHARE
        for row in range(self.table.rowCount()):
            spin = self.table.cellWidget(row, 4)
            if isinstance(spin, QDoubleSpinBox):
                spin.setSuffix(" %" if share else tr("strata.inhabitants_suffix"))
                spin.setMaximum(100 if share else 1e9)

    def classes(self):
        """Classes of the typology chosen in the Data tab, then those named in the scenario."""
        data_page = self.dialog.page("data")
        names = field_values(data_page.typology.currentLayer(), data_page.typology_field.currentField())
        for name in self._rows_names():
            if name not in names:
                names.append(name)
        return names

    def _rows_names(self):
        return [self.table.item(row, 0).text() for row in range(self.table.rowCount()) if self.table.item(row, 0)]

    def refresh(self):
        """Classes of the typology may have changed in the Data tab: rows added, values kept."""
        data = {}
        self.store(data)
        self._fill(data, self.classes())
        self._describe_typology(self.dialog.data)

    # --- load and store ---------------------------------------------------------------

    def load(self, data):
        self.table.setRowCount(0)
        self._fill(data, None)
        self._describe_typology(data)

    def _fill(self, data, names):
        strata = dict(data.get("strata") or {})
        self.extra = {k: v for k, v in strata.items() if k == ORIGINAL}
        mode = strata.get("mode", PLANNED)
        for button in self.modes.buttons():
            button.setChecked(button.property("mode") == mode)
        classes = dict(strata.get("classes") or {})
        parameters = data.get("parameters") or {}
        if names is None:
            names = list(classes)
            try:
                names = self.classes() if not names else names + [n for n in self.classes() if n not in names]
            except Exception:  # pragma: no cover - no typology layer yet
                pass
        unit = strata.get("min_inflow_unit", SHARE)
        set_combo_value(self.inflow_unit, unit)
        values = {}
        self.kept = {}
        for name in (INFLOW, SATURATION):
            spec = parameters.get(name)
            if isinstance(spec, (int, float)):
                values[name] = {"*": float(spec)}
            elif isinstance(spec, dict) and all(isinstance(v, (int, float)) for v in spec.values()):
                values[name] = {str(k): float(v) for k, v in spec.items()}
            else:
                values[name] = {}
                if spec is not None:
                    self.kept[name] = spec
        self.table.setRowCount(0)
        for name in sorted(names, key=lambda n: (classes.get(n, {}).get("rank") is None,
                                                  classes.get(n, {}).get("rank") or 0, n)):
            rules = classes.get(name) or {}
            self._add_row(name, rules.get("rank"), rules.get("colonizable", True),
                          values[INFLOW].get(name, values[INFLOW].get("*", DEFAULTS[INFLOW])),
                          values[SATURATION].get(name, values[SATURATION].get("*", DEFAULTS[SATURATION])), unit)
        self.neighbours.setValue(int(strata.get("min_neighbors", 3)))
        self.membership.setValue(int(round(100 * float(strata.get("cell_membership_share", 0.5)))))
        self._fill_ranks(strata.get("urban_rank"))
        nuclei = {**NUCLEI, **dict(strata.get("new_nuclei") or {})}
        self.nuclei.setChecked(bool(nuclei["enabled"]))
        set_combo_value(self.nucleus_stratum, nuclei["stratum"])
        self.min_cells.setValue(int(nuclei["min_cells"]))
        self.enclave.setValue(float(nuclei["enclave_km2"]))
        self.migration_share.setValue(int(round(100 * float(nuclei["migration_share"]))))
        self.smoothing.setValue(int(strata.get("smoothing_passes", 2)))
        area = strata.get("min_patch_area_km2")
        cell = float(data.get("cell_size", 250.0) or 250.0)
        self.min_patch.setValue(float(area) if area is not None else cell * cell / 1e6)
        self._enable()

    def _add_row(self, name, rank, colonizable, inflow, saturation, unit):
        row = self.table.rowCount()
        self.table.insertRow(row)
        item = QTableWidgetItem(name)
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 0, item)
        spin = QSpinBox()
        spin.setRange(-1, 99)
        spin.setSpecialValueText("–")
        spin.setValue(-1 if rank is None else int(rank))
        spin.valueChanged.connect(lambda *args: self._ranks_changed())
        self.table.setCellWidget(row, 1, spin)
        box = QCheckBox()
        box.setChecked(bool(colonizable))
        self.table.setCellWidget(row, 2, box)
        urban = QTableWidgetItem("")
        urban.setFlags(urban.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.table.setItem(row, 3, urban)
        for column, name_, value in ((4, INFLOW, inflow), (5, SATURATION, saturation)):
            if name_ in self.kept:
                kept = QTableWidgetItem(tr("strata.series"))
                kept.setFlags(kept.flags() & ~Qt.ItemFlag.ItemIsEditable)
                kept.setToolTip(tip("strata.series"))
                self.table.setItem(row, column, kept)
                continue
            spin = QDoubleSpinBox()
            percent = name_ == SATURATION or unit == SHARE
            spin.setDecimals(1 if percent else 0)
            spin.setRange(0, 100 if percent else 1e9)
            spin.setSuffix(" %" if percent else tr("strata.inhabitants_suffix"))
            spin.setValue(100 * value if percent else value)
            self.table.setCellWidget(row, column, spin)

    def _ranks(self):
        ranks = {}
        for row in range(self.table.rowCount()):
            value = self.table.cellWidget(row, 1).value()
            if value >= 0:
                ranks[self.table.item(row, 0).text()] = value
        return ranks

    def _fill_ranks(self, urban_rank=None):
        ranks = self._ranks()
        current = self.urban_rank.currentData() if urban_rank is None else urban_rank
        self.urban_rank.blockSignals(True)
        self.urban_rank.clear()
        self.urban_rank.addItem(tr("strata.urban_rank.auto"), None)
        for rank in sorted(set(ranks.values())):
            names = ", ".join(n for n, r in ranks.items() if r == rank)
            self.urban_rank.addItem(tr("strata.urban_rank.item", rank=rank, names=names), rank)
        set_combo_value(self.urban_rank, current)
        self.urban_rank.blockSignals(False)
        stratum = self.nucleus_stratum.currentText()
        self.nucleus_stratum.clear()
        for name in self._rows_names():
            self.nucleus_stratum.addItem(name, name)
        if stratum:
            set_combo_value(self.nucleus_stratum, stratum)
        else:
            set_combo_value(self.nucleus_stratum, "Urbain2")
        self._mark_urban()

    def _ranks_changed(self):
        self._fill_ranks()

    def _mark_urban(self):
        ranks = sorted(set(self._ranks().values()))
        chosen = self.urban_rank.currentData()
        threshold = chosen if chosen is not None else (ranks[1] if len(ranks) > 1 else None)
        for row in range(self.table.rowCount()):
            rank = self.table.cellWidget(row, 1).value()
            urban = threshold is not None and rank >= 0 and rank >= threshold
            self.table.item(row, 3).setText(tr("common.yes") if urban else "–")

    def store(self, data):
        if self.table.rowCount() == 0 and self.mode() == PLANNED and not self.extra:
            data.pop("strata", None)
            return
        classes = {}
        inflow, saturation = {}, {}
        share = self.inflow_unit.currentData() == SHARE
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            rank = self.table.cellWidget(row, 1).value()
            colonizable = self.table.cellWidget(row, 2).isChecked()
            if rank >= 0 or not colonizable:
                classes[name] = {**({"rank": rank} if rank >= 0 else {}),
                                 **({} if colonizable else {"colonizable": False})}
            if rank < 0:
                continue
            for column, target, percent in ((4, inflow, share), (5, saturation, True)):
                spin = self.table.cellWidget(row, column)
                if isinstance(spin, QDoubleSpinBox):
                    target[name] = round(spin.value() / 100.0, 6) if percent else spin.value()
        strata = {"mode": self.mode()}
        if classes:
            strata["classes"] = classes
        nondefault = {
            "min_neighbors": (self.neighbours.value(), 3),
            "cell_membership_share": (self.membership.value() / 100.0, 0.5),
            "min_inflow_unit": (self.inflow_unit.currentData(), SHARE),
            "urban_rank": (self.urban_rank.currentData(), None),
            "smoothing_passes": (self.smoothing.value(), 2),
        }
        for key, (value, default) in nondefault.items():
            if value != default:
                strata[key] = value
        cell = float(data.get("cell_size", 250.0) or 250.0)
        if abs(self.min_patch.value() - cell * cell / 1e6) > 1e-9:
            strata["min_patch_area_km2"] = self.min_patch.value()
        nuclei = {"enabled": self.nuclei.isChecked(), "stratum": self.nucleus_stratum.currentData(),
                  "min_cells": self.min_cells.value(), "enclave_km2": self.enclave.value(),
                  "migration_share": self.migration_share.value() / 100.0}
        if nuclei["enabled"]:
            strata["new_nuclei"] = nuclei
        strata.update(self.extra)
        if strata == {"mode": PLANNED}:
            data.pop("strata", None)
        else:
            data["strata"] = strata
        parameters = data.setdefault("parameters", {})
        for name, values in ((INFLOW, inflow), (SATURATION, saturation)):
            if name in self.kept:
                parameters[name] = self.kept[name]
            elif values:
                parameters[name] = values
            else:
                parameters.pop(name, None)

    # --- typology and built-up patches -------------------------------------------------

    def _describe_typology(self, data):
        typology = data.get("typology") or {}
        source = typology.get("source") or "—"
        import os

        name = os.path.basename(source.split("|")[0]) if source != "—" else source
        count = self.table.rowCount()
        self.typology.setText(tr("strata.typology", name=name, field=typology.get("field") or "—", count=count))
        original = (data.get("strata") or {}).get(ORIGINAL)
        self.patches_chip.setVisible(original is not None)
        self.revert.setVisible(original is not None)
        if original is not None:
            self.patches_chip.setProperty("state", "")
            self.patches_chip.setText(tr("strata.patches_applied"))
        self.patches_chip.style().unpolish(self.patches_chip)
        self.patches_chip.style().polish(self.patches_chip)

    def _prepare(self):
        from .patches_dialog import PatchesDialog

        dialog = PatchesDialog(self.dialog)
        dialog.exec()

    def _revert(self):
        answer = QMessageBox.question(self, tr("strata.revert"), tr("strata.revert.confirm"))
        if answer != QMessageBox.StandardButton.Yes:
            return
        data = revert_patches(self.dialog.collect())
        self.dialog.reload(data)

"""Choice offered when the population no longer fits (spec §7.2)."""

from qgis.PyQt.QtWidgets import QButtonGroup, QDialog, QDialogButtonBox, QLabel, QRadioButton, QVBoxLayout

from ..i18n import current_language, tr


class NonConvergenceDialog(QDialog):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.setWindowTitle(tr("nc.title", year=f"{result.failure_year:g}"))
        language = current_language()
        layout = QVBoxLayout(self)
        message = QLabel("\n".join(m.render(language) for m in result.failure.messages))
        message.setWordWrap(True)
        layout.addWidget(message)

        self.group = QButtonGroup(self)
        self.options = {}
        proposal = result.failure.proposal
        if proposal is not None:
            text = tr("nc.raise", increase=f"{proposal.increase_percent:g}",
                      minimal=f"{(proposal.minimal_factor - 1) * 100:.1f}")
            self._option("raise", text, {"policy": "raise_dmax", "max_auto_increase": proposal.factor - 1.0})
        self._option("sink", tr("nc.sink"), {"policy": "sink"})
        self._option("unallocated", tr("nc.unallocated"), {"policy": "unallocated"})
        for button in self.group.buttons()[:1]:
            button.setChecked(True)
        for key in self.options:
            layout.addWidget(self.options[key][0])
        note = QLabel(tr("nc.note"))
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        apply = buttons.addButton(tr("nc.apply"), QDialogButtonBox.ButtonRole.AcceptRole)
        stop = buttons.addButton(tr("nc.stop"), QDialogButtonBox.ButtonRole.RejectRole)
        apply.clicked.connect(self.accept)
        stop.clicked.connect(self.reject)
        layout.addWidget(buttons)

    def _option(self, key, text, settings):
        button = QRadioButton(text)
        self.group.addButton(button)
        self.options[key] = (button, settings)

    def choice(self) -> dict:
        for button, settings in self.options.values():
            if button.isChecked():
                return settings
        return {"policy": "stop"}

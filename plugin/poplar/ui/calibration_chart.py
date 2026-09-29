"""Chart of the Calibration tab: roof areas, class limits and inhabitants per roof (validated mock-up, 29/09/2026).

Two views: the distribution of the roof areas (bars, 1 m² wide) with the
curve of inhabitants per roof, or the cumulated shares of the roofs and of
the population. Inner class limits can be dragged with the mouse; the
chart then emits ``edgesChanged`` with the new limits. Drawn with QPainter
only: no plotting library is needed.
"""

import numpy as np
from qgis.PyQt.QtCore import QPointF, QRectF, Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor, QPainter, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QSizePolicy, QWidget

from .style import tokens

DISTRIBUTION, CUMULATIVE = "distribution", "cumulative"


class CalibrationChart(QWidget):
    edgesChanged = pyqtSignal(list)

    MARGINS = (46, 14, 50, 34)  # left, top, right, bottom

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)
        self.view = DISTRIBUTION
        self.areas = np.empty(0)
        self.weights = np.empty(0)
        self.edges = []
        self.values = []
        self.legacy = None
        self.drag = None
        self.xmax = 150.0
        self.labels = {"area": "m²", "people": "hab.", "roofs": "toits", "population": "population"}

    # --- data -----------------------------------------------------------------------

    def set_data(self, areas, weights, edges, values, legacy=None):
        self.areas = np.asarray(areas, dtype=float)
        self.weights = np.asarray(weights, dtype=float) if weights is not None else np.ones(len(self.areas))
        self.edges = [float(e) for e in edges]
        self.values = [float(v) for v in values]
        self.legacy = legacy
        top = self.edges[-1] * 1.3 if self.edges else 150.0
        if len(self.areas):
            top = min(max(top, float(np.percentile(self.areas, 95))), float(np.percentile(self.areas, 99.5)) + 5)
        self.xmax = max(20.0, float(np.ceil(top / 10.0) * 10))
        self.update()

    def set_view(self, view):
        self.view = view
        self.update()

    def per_roof(self, areas):
        """Inhabitants of roofs of the given areas, by class (steps), as the engine counts them."""
        if not self.edges:
            return np.zeros(len(areas))
        values = np.maximum.accumulate(np.asarray(self.values, dtype=float))
        index = np.clip(np.searchsorted(self.edges, areas, side="right") - 1, 0, len(values) - 1)
        return np.where(areas < self.edges[0], 0.0, values[index])

    # --- geometry -------------------------------------------------------------------

    def _plot(self):
        left, top, right, bottom = self.MARGINS
        return QRectF(left, top, max(self.width() - left - right, 10), max(self.height() - top - bottom, 10))

    def _x(self, area):
        rect = self._plot()
        return rect.left() + area / self.xmax * rect.width()

    def _area(self, x):
        rect = self._plot()
        return (x - rect.left()) / rect.width() * self.xmax

    # --- drawing --------------------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802
        t = tokens(self)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(t["window"]))
        rect = self._plot()
        muted, line = QColor(t["muted"]), QColor(t["line"])
        painter.setPen(QPen(line, 1))
        for i in range(6):
            y = rect.bottom() - i / 5 * rect.height()
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
        painter.setPen(muted)
        step = 10 if self.xmax <= 200 else 50
        for x in np.arange(0, self.xmax + 1, step):
            painter.drawText(QRectF(self._x(x) - 20, rect.bottom() + 4, 40, 14), Qt.AlignmentFlag.AlignCenter, f"{x:g}")
        painter.drawText(QRectF(rect.left(), rect.bottom() + 18, rect.width(), 14), Qt.AlignmentFlag.AlignCenter,
                         self.labels["area"])
        if len(self.areas):
            if self.view == CUMULATIVE:
                self._draw_cumulative(painter, rect, t)
            else:
                self._draw_distribution(painter, rect, t)
        self._draw_edges(painter, rect, t)
        painter.end()

    def _draw_distribution(self, painter, rect, t):
        bins = np.arange(0, self.xmax + 1, 1.0)
        counts, _ = np.histogram(self.areas, bins)
        top = max(counts.max(), 1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t["teal_soft"]))
        width = rect.width() / len(counts)
        for i, count in enumerate(counts):
            if count:
                h = count / top * rect.height()
                painter.drawRect(QRectF(rect.left() + i * width, rect.bottom() - h, max(width - 0.6, 0.5), h))
        ymax = max(max(self.values, default=1) + 1, 5)
        painter.setPen(QColor(t["muted"]))
        for i in range(6):
            value = ymax * i / 5
            painter.drawText(QRectF(rect.right() + 4, rect.bottom() - i / 5 * rect.height() - 7, 44, 14),
                             Qt.AlignmentFlag.AlignLeft, f"{value:.0f}")
        painter.drawText(QRectF(rect.right() + 4, rect.top() - 14, 46, 14), Qt.AlignmentFlag.AlignLeft,
                         self.labels["people"])

        def y(value):
            return rect.bottom() - value / ymax * rect.height()

        if self.legacy is not None:
            pen = QPen(QColor(t["ochre"]), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            xs = np.arange(0, self.xmax, 0.5)
            path = QPainterPath(QPointF(self._x(xs[0]), y(max(self.legacy(xs[0]), 0))))
            for x in xs[1:]:
                path.lineTo(QPointF(self._x(x), y(max(self.legacy(x), 0))))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.setPen(QPen(QColor(t["teal"]), 2.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        xs = np.arange(0, self.xmax, 0.5)
        values = self.per_roof(xs)
        path = QPainterPath(QPointF(self._x(xs[0]), y(values[0])))
        for x, value in zip(xs[1:], values[1:]):
            path.lineTo(QPointF(self._x(x), y(value)))
        painter.drawPath(path)

    def _draw_cumulative(self, painter, rect, t):
        order = np.argsort(self.areas)
        areas = self.areas[order]
        population = self.per_roof(areas) * self.weights[order]
        xs = np.arange(0, self.xmax + 1, 1.0)
        roofs = np.searchsorted(areas, xs, side="right") / max(len(areas), 1)
        cumulated = np.concatenate([[0.0], np.cumsum(population)])
        people = cumulated[np.searchsorted(areas, xs, side="right")] / max(cumulated[-1], 1e-12)
        painter.setPen(QColor(t["muted"]))
        for i in range(6):
            painter.drawText(QRectF(rect.right() + 4, rect.bottom() - i / 5 * rect.height() - 7, 44, 14),
                             Qt.AlignmentFlag.AlignLeft, f"{i * 20} %")
        for share, colour, width in ((roofs, t["muted"], 2), (people, t["teal"], 2.5)):
            painter.setPen(QPen(QColor(colour), width))
            path = QPainterPath(QPointF(self._x(xs[0]), rect.bottom() - share[0] * rect.height()))
            for x, value in zip(xs[1:], share[1:]):
                path.lineTo(QPointF(self._x(x), rect.bottom() - value * rect.height()))
            painter.drawPath(path)
        # share of roofs / of population of each class, above the plot
        total_people = max(population.sum(), 1e-12)
        painter.setPen(QColor(t["muted"]))
        for k in range(len(self.edges) - 1):
            low, high = self.edges[k], (self.edges[k + 1] if k < len(self.edges) - 2 else np.inf)
            members = (areas >= low) & (areas < high)
            text = f"{100 * members.mean():.0f} / {100 * population[members].sum() / total_people:.0f} %"
            middle = min((low + min(self.edges[k + 1], self.xmax)) / 2, self.xmax - 2)
            painter.drawText(QRectF(self._x(middle) - 30, rect.top() + (k % 2) * 12, 60, 12),
                             Qt.AlignmentFlag.AlignCenter, text)

    def _draw_edges(self, painter, rect, t):
        for i, edge in enumerate(self.edges):
            if edge > self.xmax:
                continue
            inner = 0 < i < len(self.edges) - 1
            pen = QPen(QColor(t["ochre"]), 2 if inner else 1, Qt.PenStyle.SolidLine if inner else Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(QPointF(self._x(edge), rect.top()), QPointF(self._x(edge), rect.bottom()))

    # --- dragging the inner class limits --------------------------------------------------

    def _handle_at(self, x):
        for i in range(1, len(self.edges) - 1):
            if abs(self._x(self.edges[i]) - x) <= 6:
                return i
        return None

    def mousePressEvent(self, event):  # noqa: N802
        self.drag = self._handle_at(event.position().x() if hasattr(event, "position") else event.x())

    def mouseMoveEvent(self, event):  # noqa: N802
        x = event.position().x() if hasattr(event, "position") else event.x()
        if self.drag is None:
            self.setCursor(Qt.CursorShape.SizeHorCursor if self._handle_at(x) is not None else Qt.CursorShape.ArrowCursor)
            return
        low, high = self.edges[self.drag - 1] + 1, self.edges[self.drag + 1] - 1
        self.edges[self.drag] = float(round(min(max(self._area(x), low), high)))
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if self.drag is not None:
            self.drag = None
            self.edgesChanged.emit(list(self.edges))

    def move_edge(self, index, area):
        """Same as dragging a limit (used by the tests)."""
        self.drag = index
        low, high = self.edges[index - 1] + 1, self.edges[index + 1] - 1
        self.edges[index] = float(round(min(max(area, low), high)))
        self.drag = None
        self.edgesChanged.emit(list(self.edges))

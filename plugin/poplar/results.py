"""Load the rasters of a run into the QGIS project, with ready-made styles."""

import os
import re

from qgis.core import (
    QgsColorRampShader, QgsGradientColorRamp, QgsProject, QgsRasterBandStats, QgsRasterLayer, QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor

QUANTITIES = ["population", "density", "capacity", "unallocated", "water_domestic", "water_consumption_mean",
              "water_production_mean", "water_production_peak_day", "water_peak_hour"]
RAMPS = {
    "population": ("#fbf3d6", "#7c2f2a"),
    "density": ("#fbf3d6", "#7c2f2a"),
    "capacity": ("#eef4f3", "#1f6f6a"),
    "unallocated": ("#fde2dc", "#a3322a"),
}
WATER_RAMP = ("#e6f1f8", "#154f7a")
PATTERN = re.compile(r"^(?P<quantity>[a-z_]+)_(?P<year>\d{4}(?:\.\d+)?)\.tif$")


def available_outputs(directory):
    """{quantity: [years]} for the rasters found in an output directory."""
    found = {}
    if not directory or not os.path.isdir(directory):
        return found
    for name in os.listdir(directory):
        match = PATTERN.match(name)
        if match and match.group("quantity") in QUANTITIES:
            found.setdefault(match.group("quantity"), []).append(match.group("year"))
    return {q: sorted(years, key=float) for q, years in found.items()}


def load_rasters(directory, quantities, years, group_name):
    """Add the chosen rasters to a layer group (created or reused) and style them."""
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(group_name) or root.insertGroup(0, group_name)
    loaded = []
    for quantity in quantities:
        for year in years:
            path = os.path.join(directory, f"{quantity}_{year}.tif")
            if not os.path.exists(path):
                continue
            layer = QgsRasterLayer(path, f"{quantity} {year}")
            if not layer.isValid():
                continue
            style_layer(layer, quantity)
            project.addMapLayer(layer, False)
            group.insertLayer(0, layer)
            loaded.append(layer)
    return loaded


def style_layer(layer, quantity, classes=6):
    """Graduated colours between the minimum and maximum of the raster; nodata stays transparent."""
    provider = layer.dataProvider()
    stats = provider.bandStatistics(1, QgsRasterBandStats.Min | QgsRasterBandStats.Max)
    low, high = stats.minimumValue, stats.maximumValue
    if high <= low:
        high = low + 1
    start, end = RAMPS.get(quantity, WATER_RAMP)
    ramp = QgsGradientColorRamp(QColor(start), QColor(end))
    shader_function = QgsColorRampShader(low, high)
    shader_function.setColorRampType(QgsColorRampShader.Interpolated)
    items = []
    for i in range(classes):
        value = low + (high - low) * i / (classes - 1)
        items.append(QgsColorRampShader.ColorRampItem(value, ramp.color(i / (classes - 1)), f"{value:,.0f}".replace(",", " ")))
    shader_function.setColorRampItemList(items)
    shader = QgsRasterShader()
    shader.setRasterShaderFunction(shader_function)
    renderer = QgsSingleBandPseudoColorRenderer(provider, 1, shader)
    renderer.setClassificationMin(low)
    renderer.setClassificationMax(high)
    layer.setRenderer(renderer)
    layer.triggerRepaint()

"""Load the rasters of a run into the QGIS project, with ready-made styles."""

import os
import re

from qgis.core import (
    QgsColorRampShader, QgsGradientColorRamp, QgsProject, QgsRasterBandStats, QgsRasterLayer, QgsRasterShader,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtGui import QColor

from .i18n import tr

QUANTITIES = ["population", "density", "capacity", "unallocated", "water_domestic", "water_consumption_mean",
              "water_production_mean", "water_production_peak_day", "water_peak_hour", "statut", "polygon_id"]
STATUS = [(0, "#e5ece9", "status.0"), (1, "#1f6f6a", "status.1"), (2, "#c98a36", "status.2"),
          (3, "#a4452a", "status.3"), (9, "#9aaeab", "status.9")]
"""Codes of the urban status rasters (fiche §3.4) and their colours."""
RANK_COLOURS = ["#dfe7e4", "#f1dfbd", "#e0a85a", "#c98a36", "#1f6f6a", "#14504c", "#0c3431"]
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


def load_rasters(directory, quantities, years, group_name, visible=None):
    """Add the chosen rasters to a layer group (created or reused) and style them.

    The latest year ends up on top. With ``visible`` (a list of years), only those
    layers are ticked, so that the map stays readable when many years are loaded.
    """
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
            if quantity == "polygon_id":
                layer.loadNamedStyle(os.path.splitext(path)[0] + ".qml")    # written by the run
            elif quantity == "statut":
                style_status(layer)
            else:
                style_layer(layer, quantity)
            project.addMapLayer(layer, False)
            node = group.insertLayer(0, layer)
            if visible is not None:
                node.setItemVisibilityChecked(year in visible)
            loaded.append(layer)
    return loaded


def load_grid_layer(directory, group_name, prefer=None):
    """Add the cell layer of a run (mailles.gpkg, else mailles.shp) to its group, unticked and unfilled.

    It holds every result of every output year: open its attribute table, or style it on any field.
    """
    from qgis.core import QgsFillSymbol, QgsVectorLayer

    choices = [("mailles.gpkg", "mailles.gpkg|layername=mailles"), ("mailles.shp", "mailles.shp")]
    if prefer == "shp":
        choices.reverse()
    for name, uri in choices:
        path = os.path.join(directory, name)
        if os.path.exists(path):
            break
    else:
        return None
    project = QgsProject.instance()
    source = os.path.normcase(os.path.abspath(path))
    for layer in project.mapLayers().values():                    # already loaded (Results tab, second time)
        if os.path.normcase(os.path.abspath(layer.source().split("|")[0])) == source:
            return layer
    layer = QgsVectorLayer(os.path.join(directory, uri), tr("results.grid_layer_name"), "ogr")
    if not layer.isValid():
        return None
    layer.renderer().setSymbol(QgsFillSymbol.createSimple(
        {"style": "no", "outline_color": "120,120,120,120", "outline_width": "0.1"}))
    project.addMapLayer(layer, False)
    root = project.layerTreeRoot()
    group = root.findGroup(group_name) or root.insertGroup(0, group_name)
    node = group.addLayer(layer)                                  # at the bottom: rasters stay on top
    node.setItemVisibilityChecked(False)
    return layer


def release_grid_layer(directory):
    """Remove from the project the cell layer of a run, so that its file can be written again (Windows)."""
    project = QgsProject.instance()
    ids = []
    for layer_id, layer in project.mapLayers().items():
        path = layer.source().split("|")[0]
        if os.path.basename(path).startswith("mailles.") and _inside(path, directory):
            ids.append(layer_id)
    if ids:
        project.removeMapLayers(ids)
    return len(ids)


def _inside(path, directory):
    path = os.path.normcase(os.path.abspath(path))
    directory = os.path.normcase(os.path.abspath(directory))
    return path == directory or path.startswith(directory + os.sep)


def release_layers(directory):
    """Remove from the project every layer read from ``directory``.

    Windows forbids deleting a file that QGIS has open ("permission denied"),
    so the layers go first. Groups left empty are removed too.
    """
    project = QgsProject.instance()
    ids = []
    for layer_id, layer in project.mapLayers().items():
        source = layer.source().split("|")[0]
        if source and _inside(source, directory):
            ids.append(layer_id)
    if ids:
        project.removeMapLayers(ids)
    root = project.layerTreeRoot()
    for group in root.findGroups():
        if group.name().startswith("Poplar") and not group.children():
            root.removeChildNode(group)
    return len(ids)


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


def style_status(layer):
    """Paletted colours of the urban status (0 not urban … 9 exclusion)."""
    from qgis.core import QgsPalettedRasterRenderer

    classes = [QgsPalettedRasterRenderer.Class(code, QColor(colour), tr(label)) for code, colour, label in STATUS]
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1, classes))
    layer.triggerRepaint()


def load_polygon_layers(directory, group_name, year):
    """Free strata mode: smoothed polygons of ``year`` (ticked), extensions and year of colonisation (not ticked).

    Returns the layers added (none when the run was in planned mode).
    """
    import csv

    from qgis.core import (QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory, QgsVectorLayer)

    path = os.path.join(directory, "polygones.gpkg")
    if not os.path.exists(path):
        return []
    ranks = {}
    legend = os.path.join(directory, "polygones_legende.csv")
    if os.path.exists(legend):
        with open(legend, encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle, delimiter=";"):
                ranks[row["strate"]] = int(row["rang"])
    project = QgsProject.instance()
    root = project.layerTreeRoot()
    group = root.findGroup(group_name) or root.insertGroup(0, group_name)
    added = []
    polygons = QgsVectorLayer(f"{path}|layername=polygones", tr("results.polygons_layer", year=year), "ogr")
    if polygons.isValid():
        polygons.setSubsetString(f'"annee" = {int(float(year))}')
        order = sorted(set(ranks.values()))
        categories = []
        for stratum, rank in sorted(ranks.items(), key=lambda item: item[1]):
            colour = RANK_COLOURS[min(order.index(rank), len(RANK_COLOURS) - 1)] if rank in order else "#dfe7e4"
            symbol = QgsFillSymbol.createSimple({"color": colour, "outline_color": "60,60,60,160",
                                                 "outline_width": "0.2"})
            categories.append(QgsRendererCategory(stratum, symbol, stratum))
        if categories:
            polygons.setRenderer(QgsCategorizedSymbolRenderer("strate", categories))
        project.addMapLayer(polygons, False)
        group.insertLayer(0, polygons)
        added.append(polygons)
    extensions = QgsVectorLayer(f"{path}|layername=extensions", tr("results.extensions_layer"), "ogr")
    if extensions.isValid():
        extensions.renderer().setSymbol(QgsFillSymbol.createSimple(
            {"color": "201,138,54,140", "outline_color": "164,69,42,200", "outline_width": "0.3"}))
        project.addMapLayer(extensions, False)
        group.insertLayer(1, extensions).setItemVisibilityChecked(False)
        added.append(extensions)
    years = os.path.join(directory, "annee_colonisation.tif")
    if os.path.exists(years):
        layer = QgsRasterLayer(years, tr("results.colonisation_year_layer"))
        if layer.isValid():
            from qgis.core import QgsRasterRange

            layer.dataProvider().setUserNoDataValue(1, [QgsRasterRange(0, 0)])     # 0: never colonised
            style_layer(layer, "annee_colonisation")
            project.addMapLayer(layer, False)
            group.insertLayer(2, layer).setItemVisibilityChecked(False)
            added.append(layer)
    return added

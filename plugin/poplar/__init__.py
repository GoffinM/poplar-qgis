"""QGIS plugin entry point."""


def classFactory(iface):  # noqa: N802 (name required by QGIS)
    from .plugin import PoplarPlugin

    return PoplarPlugin(iface)

"""Download of building footprints from public online sources (roofs for the calibration).

Nothing here imports QGIS: the plugin passes its own fetcher (which follows the
proxy and authentication set in QGIS); outside QGIS, ``urllib`` is used.
"""

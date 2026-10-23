"""Run with QGIS's Python and QT_QPA_PLATFORM=offscreen."""

import tempfile
from pathlib import Path
from types import SimpleNamespace

from osgeo import gdal, osr
from qgis.core import QgsApplication, QgsProject
from qgis.PyQt.QtWidgets import QMainWindow

from autostacgis_qgis.model import CAPABILITIES
from autostacgis_qgis.plugin import CatalogDock

app = QgsApplication([], False)
app.initQgis()
window = QMainWindow()
dock = CatalogDock(SimpleNamespace(mainWindow=lambda: window))
dock.client = SimpleNamespace(url="http://127.0.0.1:8080/")
plugins = [
    {
        "id": "backward_chain",
        "capability": "solver",
        "requires": [],
        "defaults": {},
        "settings_schema": {"type": "object"},
    },
    {
        "id": "metadata-value",
        "capability": "goal",
        "requires": ["backward_chain"],
        "defaults": {},
        "settings_schema": {"type": "object"},
    },
]
descriptor = {
    "plugins": plugins,
    "default_configuration": {
        "catalog": {
            "version": "1.0.0",
            "plugins": [{"use": "metadata-value", "settings": {"path": "properties.ready", "value": True}}],
        },
        "request": {"goal": {"output": {}}},
    },
}
dock.load_plugins(descriptor, dock.client.url)
from autostacgis_qgis.json_editor import JsonEditor
editor = JsonEditor('{"ready":false,"list":[1,null]}')
row = editor.tree.topLevelItem(0).child(0)
row.setText(2, 'true')
assert __import__('json').loads(editor.toPlainText())['ready'] is True
editor.setPlainText('{broken')
assert not editor.tabs.isTabEnabled(0)
editor.setPlainText('{"fixed":true}')
assert editor.tabs.isTabEnabled(0)
editor.close()
assert dock.tabs.count() == len(CAPABILITIES) + 5
assert {entry["use"] for entry in dock.configuration()["catalog"]["plugins"]} == {
    "backward_chain",
    "metadata-value",
}
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "image.tif"
    dataset = gdal.GetDriverByName("GTiff").Create(str(path), 2, 2, 1, gdal.GDT_Byte)
    dataset.SetGeoTransform((0, 0.5, 0, 1, 0, -0.5))
    spatial = osr.SpatialReference()
    spatial.ImportFromEPSG(4326)
    dataset.SetProjection(spatial.ExportToWkt())
    dataset.GetRasterBand(1).Fill(1)
    dataset = None
    item = {
        "type": "Feature",
        "id": "image",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
        "properties": {},
        "assets": {"data": {"href": path.as_uri(), "type": "image/tiff"}},
    }
    dock.show_results({"type": "FeatureCollection", "features": [item]}, "http://127.0.0.1:8080/search")
    dock.items.topLevelItem(0).child(0).setSelected(True)
    dock.add_assets()
    assert len(QgsProject.instance().mapLayers()) == 1, dock.status.text()
    dock.add_footprints()
    assert len(QgsProject.instance().mapLayers()) == 2
    QgsProject.instance().clear()
QgsProject.instance().clear()
dock.close()
dock.deleteLater()
window.close()
app.processEvents()
print(
    "QGIS smoke passed: all capability tabs, goal/solver dependency, raster and footprints on the main project"
)

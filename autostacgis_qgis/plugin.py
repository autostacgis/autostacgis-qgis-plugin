import json
from pathlib import Path
from urllib.parse import quote

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsJsonUtils,
    QgsPointCloudLayer,
    QgsProject,
    QgsRasterLayer,
    QgsSettings,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .compat import QAction, qt_enum
from .json_editor import JsonEditor
from .model import CAPABILITIES, asset_provider, configuration, next_page, resolve_item
from .network import Client


class AutoSTACGISPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None

    def initGui(self):
        self.action = QAction("AutostacGIS", self.iface.mainWindow())
        self.action.triggered.connect(self.show)
        self.iface.addPluginToMenu("AutostacGIS", self.action)
        self.iface.addToolBarIcon(self.action)

    def show(self):
        if self.dock is None:
            self.dock = CatalogDock(self.iface)
            self.iface.addDockWidget(qt_enum(Qt, "DockWidgetArea", "RightDockWidgetArea"), self.dock)
        self.dock.show()
        self.dock.raise_()

    def unload(self):
        self.iface.removePluginMenu("AutostacGIS", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dock:
            self.dock.close_requests()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
        self.action.deleteLater()


class CatalogDock(QDockWidget):
    def __init__(self, iface):
        super().__init__("AutostacGIS", iface.mainWindow())
        self.iface = iface
        self.setObjectName("AutostacGIS")
        self.resize(550, 850)
        self.client = None
        self.plugins = []
        self.editors = {}
        self.document = {
            "solver": {"backward_chain": {}},
            "goal": {"metadata-value": {"path": "properties.ready", "value": True}},
        }
        self.syncing = False
        self.workflow_dirty = False
        self.active_workflow = None
        self.pagination = None
        self.search_body = {}
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        form = QFormLayout()
        self.url = QLineEdit(QgsSettings().value("autostacgis/url", "http://127.0.0.1:8080"))
        self.token = QLineEdit()
        self.token.setEchoMode(qt_enum(QLineEdit, "EchoMode", "Password"))
        form.addRow("STAC API URL", self.url)
        form.addRow("API token (session only)", self.token)
        layout.addLayout(form)
        layout.addWidget(self.button("Connect", self.connect_api))
        self.status = QLabel("Connect to a STAC API. Processing controls require an AutostacGIS backend.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.make_search()
        self.capability_tabs = {}
        for capability in CAPABILITIES:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            widget = QWidget()
            panel = QVBoxLayout(widget)
            panel.addWidget(QLabel("Connect to load installed plugins."))
            scroll.setWidget(widget)
            self.capability_tabs[capability] = scroll
            self.tabs.addTab(scroll, capability)
        self.make_registry()
        self.make_structure()
        self.make_workflow()
        self.make_jobs()
        self.tabs.currentChanged.connect(self.change_tab)

    def button(self, label, callback):
        widget = QPushButton(label)
        widget.clicked.connect(callback)
        return widget

    def message(self, value):
        self.status.setText(str(value))

    def guarded(self, operation):
        try:
            return operation()
        except Exception as exc:
            self.message(exc)
            return None

    def make_search(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.collections = QLineEdit()
        self.collections.setPlaceholderText("Collection IDs, comma separated")
        self.datetime = QLineEdit()
        self.datetime.setPlaceholderText("STAC datetime or start/end")
        self.bbox = QLineEdit()
        self.bbox.setPlaceholderText("west,south,east,north (WGS84)")
        for field in (self.collections, self.datetime, self.bbox):
            layout.addWidget(field)
        layout.addWidget(self.button("Use main map extent", lambda: self.guarded(self.map_extent)))
        self.search_json = JsonEditor('{"limit": 50}')
        self.search_json.setMinimumHeight(220)
        layout.addWidget(QLabel("Additional STAC search parameters (JSON)"))
        layout.addWidget(self.search_json)
        row = QHBoxLayout()
        row.addWidget(self.button("Search", lambda: self.guarded(self.search)))
        self.next_button = self.button("Next page", lambda: self.guarded(self.more))
        self.next_button.setEnabled(False)
        row.addWidget(self.next_button)
        layout.addLayout(row)
        self.items = QTreeWidget()
        self.items.setHeaderLabels(["Item / asset", "Type"])
        self.items.setSelectionMode(qt_enum(QAbstractItemView, "SelectionMode", "ExtendedSelection"))
        self.items.itemDoubleClicked.connect(lambda *_: self.guarded(self.add_assets))
        layout.addWidget(self.items)
        layout.addWidget(self.button("Add selected assets to QGIS", lambda: self.guarded(self.add_assets)))
        layout.addWidget(
            self.button("Add result footprints to QGIS", lambda: self.guarded(self.add_footprints))
        )
        self.tabs.addTab(widget, "Catalog")

    def connect_api(self):
        def connect():
            if self.client:
                self.client.close()
            self.client = Client(self.url.text(), self.token.text())
            QgsSettings().setValue("autostacgis/url", self.client.url)
            self.client.request(
                "",
                lambda value, url: self.message(value.get("title", value.get("id", "Connected"))),
                self.message,
            )
            self.client.request("collections", self.show_collections, self.message)
            self.client.request(
                "autostacgis/plugins",
                self.load_plugins,
                lambda error: self.message(
                    "STAC browsing available; AutostacGIS controls unavailable: " + error
                ),
            )

        self.guarded(connect)

    def show_collections(self, value, url):
        self.collections.setToolTip(
            "Available: " + ", ".join(row["id"] for row in value.get("collections", []))
        )

    def map_extent(self):
        canvas = self.iface.mapCanvas()
        transform = QgsCoordinateTransform(
            canvas.mapSettings().destinationCrs(),
            QgsCoordinateReferenceSystem("EPSG:4326"),
            QgsProject.instance(),
        )
        bounds = transform.transformBoundingBox(canvas.extent())
        self.bbox.setText(
            ",".join(
                str(value)
                for value in (bounds.xMinimum(), bounds.yMinimum(), bounds.xMaximum(), bounds.yMaximum())
            )
        )

    def search(self):
        if not self.client:
            raise ValueError("Connect first")
        value = json.loads(self.search_json.toPlainText())
        if self.collections.text().strip():
            value["collections"] = [
                part.strip() for part in self.collections.text().split(",") if part.strip()
            ]
        if self.datetime.text().strip():
            value["datetime"] = self.datetime.text().strip()
        if self.bbox.text().strip():
            bbox = [float(part) for part in self.bbox.text().split(",")]
            if len(bbox) != 4:
                raise ValueError("A bbox needs four numbers")
            value["bbox"] = bbox
        self.search_body = value
        self.client.request("search", self.show_results, self.message, "POST", value)

    def more(self):
        if self.pagination:
            url, method, body = self.pagination
            self.search_body = body
            self.client.request(url, self.show_results, self.message, method, body)

    def show_results(self, value, url):
        self.items.clear()
        self.results = [resolve_item(item, url) for item in value.get("features", [])]
        for item in self.results:
            root = QTreeWidgetItem([item["id"], item.get("collection", "")])
            root.setData(0, qt_enum(Qt, "ItemDataRole", "UserRole"), (item, None))
            self.items.addTopLevelItem(root)
            for key, asset in item.get("assets", {}).items():
                child = QTreeWidgetItem([key, asset.get("type", "")])
                child.setData(0, qt_enum(Qt, "ItemDataRole", "UserRole"), (item, key))
                root.addChild(child)
        self.items.expandAll()
        self.pagination = next_page(value, url, self.search_body)
        self.next_button.setEnabled(self.pagination is not None)
        self.message(f"{len(self.results)} items. Select an asset to add it to the main QGIS map.")

    def selected_items(self):
        result = {}
        for row in self.items.selectedItems():
            item, _ = row.data(0, qt_enum(Qt, "ItemDataRole", "UserRole"))
            result[json.dumps([item.get("collection"), item["id"]])] = item
        return list(result.values())

    def add_assets(self):
        chosen = []
        for row in self.items.selectedItems():
            item, key = row.data(0, qt_enum(Qt, "ItemDataRole", "UserRole"))
            if key is not None:
                chosen.append((item, key))
            else:
                chosen.extend(
                    (item, name)
                    for name, asset in item.get("assets", {}).items()
                    if "data" in asset.get("roles", ["data"])
                )
        seen = set()
        errors = []
        for item, key in chosen:
            asset = item["assets"][key]
            if asset["href"] in seen:
                continue
            seen.add(asset["href"])
            try:
                kind, uri = asset_provider(asset)
                name = item["id"] + " / " + key
                layer = (
                    QgsRasterLayer(uri, name, "gdal")
                    if kind == "raster"
                    else QgsPointCloudLayer(uri, name, "pdal")
                    if kind == "pointcloud"
                    else QgsVectorLayer(uri, name, "ogr")
                )
                if not layer.isValid():
                    raise ValueError("QGIS could not open " + name)
                QgsProject.instance().addMapLayer(layer)
            except Exception as exc:
                errors.append(str(exc))
        self.message("; ".join(errors) if errors else f"Added {len(seen)} selected assets to QGIS.")

    def add_footprints(self):
        groups = {}
        for item in getattr(self, "results", []):
            parsed = QgsJsonUtils.stringToFeatureList(json.dumps(item))
            if not parsed:
                continue
            geometry = parsed[0].geometry()
            if geometry.isNull():
                continue
            pending = [geometry]
            while pending:
                current = pending.pop()
                family = int(current.type())
                if family not in (0, 1, 2):
                    pending.extend(current.asGeometryCollection())
                    continue
                current.convertToMultiType()
                groups.setdefault(family, []).append((item, current))
        if not groups:
            raise ValueError("No valid result footprints")
        for family, features in groups.items():
            kind = ("MultiPoint", "MultiLineString", "MultiPolygon")[family]
            layer = QgsVectorLayer(
                kind + "?crs=EPSG:4326&field=stac_id:string&field=collection:string",
                "STAC search footprints",
                "memory",
            )
            values = []
            for item, geometry in features:
                feature = QgsFeature(layer.fields())
                feature.setGeometry(geometry)
                feature.setAttributes([item["id"], item.get("collection", "")])
                values.append(feature)
            success, _ = layer.dataProvider().addFeatures(values)
            if not success:
                raise ValueError("QGIS could not create the footprint layer")
            layer.updateExtents()
            QgsProject.instance().addMapLayer(layer)

    def load_plugins(self, value, url):
        self.plugins = value["plugins"]
        self.syncing = True
        if "default_configuration" in value:
            self.document = value["default_configuration"]
        self.editors = {}
        selected = {
            name: parameters
            for capability in CAPABILITIES
            for name, parameters in self.document.get(capability, {}).items()
        }
        for capability, scroll in self.capability_tabs.items():
            body = QWidget()
            layout = QVBoxLayout(body)
            for plugin in self.plugins:
                if plugin["capability"] != capability:
                    continue
                group = QGroupBox(plugin["id"])
                panel = QVBoxLayout(group)
                enabled = QCheckBox("Enabled")
                enabled.setChecked(plugin["id"] in selected)
                enabled.toggled.connect(lambda checked, name=plugin["id"]: self.select_solver(name, checked))
                panel.addWidget(enabled)
                description = QLabel(plugin.get("description", ""))
                description.setWordWrap(True)
                panel.addWidget(description)
                panel.addWidget(QLabel("Requires: " + ", ".join(plugin["requires"])))
                editor = JsonEditor(
                    json.dumps(selected.get(plugin["id"], plugin["defaults"]), indent=2),
                    schema=plugin["settings_schema"],
                )
                editor.setMinimumHeight(100)
                editor.setMaximumHeight(240)
                panel.addWidget(editor)
                if plugin["id"] in ("apscheduler", "watchdog"):
                    panel.addWidget(
                        self.button(
                            "Start trigger",
                            lambda _, name=plugin["id"]: self.guarded(lambda: self.invoke("jobs", name)),
                        )
                    )
                schema = JsonEditor(json.dumps(plugin["settings_schema"], indent=2))
                schema.setReadOnly(True)
                schema.hide()
                toggle = QPushButton("Parameter contract")
                toggle.clicked.connect(lambda _, widget=schema: widget.setVisible(not widget.isVisible()))
                panel.addWidget(toggle)
                panel.addWidget(schema)
                self.editors[plugin["id"]] = (enabled, editor)
                editor.text.textChanged.connect(self.sync_plugins)
                layout.addWidget(group)
            layout.addStretch()
            scroll.setWidget(body)
        self.request_json.setPlainText(json.dumps(self.document, indent=2))
        self.structure_json.setPlainText(
            json.dumps(
                self.document.get("metadata_structure", {}),
                indent=2,
            )
        )
        self.syncing = False
        self.workflow_dirty = False
        self.message(f"Loaded {len(self.plugins)} plugins across {len(CAPABILITIES)} capability tabs.")

    def select_solver(self, name, checked):
        plugin = next((plugin for plugin in self.plugins if plugin["id"] == name), None)
        if checked and plugin and plugin["capability"] in ("solver", "trigger"):
            for other in self.plugins:
                if (
                    other["capability"] == plugin["capability"]
                    and other["id"] != name
                    and other["id"] in self.editors
                ):
                    self.editors[other["id"]][0].setChecked(False)
        self.sync_plugins()

    def make_structure(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        description = QLabel(
            "Declare STAC Item schema URLs in schemas and additional fields in the inline Item JSON Schema. Strict mode rejects undeclared metadata."
        )
        description.setWordWrap(True)
        layout.addWidget(description)
        self.structure_json = JsonEditor('{"schemas": [], "inline": {}, "strict": true}')
        layout.addWidget(self.structure_json)
        self.structure_json.text.textChanged.connect(self.sync_plugins)
        self.tabs.addTab(widget, "Metadata Structure")

    def make_registry(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        notice = QLabel(
            "Install reviewed Python code on the connected backend. Plugins run with its permissions."
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.available_plugins = QTreeWidget()
        self.available_plugins.setHeaderLabels(["Plugin", "Version", "Capability"])
        layout.addWidget(self.available_plugins)
        layout.addWidget(self.button("Refresh online catalog", lambda: self.guarded(self.refresh_registry)))
        layout.addWidget(
            self.button("Install selected version", lambda: self.guarded(self.install_published))
        )
        layout.addWidget(self.button("Install Python file", lambda: self.guarded(self.install_file)))
        self.registry_client = None
        self.registry_index = self.tabs.addTab(widget, "Plugin Registry")

    def refresh_registry(self):
        def loaded(value, url):
            if value.get("format_version") != 1:
                raise ValueError("Unsupported plugin manifest")
            self.available_plugins.clear()
            for row in value["plugins"]:
                self.available_plugins.addTopLevelItem(
                    QTreeWidgetItem([row["id"], row["version"], row["capability"]])
                )
            self.message(f"{len(value['plugins'])} plugins published online")

        if self.client:
            self.client.request("autostacgis/plugins/available", loaded, self.message)
        else:
            self.message("Connect to an AutostacGIS backend first")

    def installed_plugin(self, value, url):
        # Preserve the current workflow/settings while refreshing the installed contracts.
        self.document = self.configuration()
        self.client.request(
            "autostacgis/plugins",
            lambda value, url: self.load_plugins({"plugins": value["plugins"]}, url),
            self.message,
        )
        self.message("Plugin installed")

    def install_published(self):
        if not self.client:
            raise ValueError("Connect to a backend first")
        row = self.available_plugins.currentItem()
        if not row:
            raise ValueError("Select a published plugin version")
        self.client.request(
            "autostacgis/plugins/install",
            self.installed_plugin,
            self.message,
            "POST",
            {"name": row.text(0), "version": row.text(1)},
        )

    def install_file(self):
        if not self.client:
            raise ValueError("Connect to a backend first")
        filename, _ = QFileDialog.getOpenFileName(self, "Install Python plugin", "", "Python (*.py)")
        if filename:
            self.client.request(
                "autostacgis/plugins/install-file",
                self.installed_plugin,
                self.message,
                "POST",
                {"filename": Path(filename).name, "source": Path(filename).read_text()},
            )

    def make_workflow_library(self, layout):
        layout.addWidget(QLabel("Published workflows"))
        self.published_workflows = QComboBox()
        layout.addWidget(self.published_workflows)
        layout.addWidget(
            self.button("Activate published workflow", lambda: self.guarded(self.activate_published_workflow))
        )
        layout.addWidget(QLabel("Saved workflows"))
        self.saved_workflows = QComboBox()
        layout.addWidget(self.saved_workflows)
        for label, method in (
            ("Refresh workflows", self.refresh_workflows),
            ("Activate saved workflow", self.activate_saved_workflow),
            ("Save a copy", self.copy_workflow),
            ("Rename saved workflow", self.rename_workflow),
            ("Delete saved workflow", self.delete_workflow),
        ):
            layout.addWidget(self.button(label, lambda _, method=method: self.guarded(method)))
        self.update_workflow_button = self.button(
            "Update saved workflow", lambda: self.guarded(self.update_workflow)
        )
        self.update_workflow_button.setEnabled(False)
        layout.addWidget(self.update_workflow_button)

    def refresh_workflows(self):
        if not self.client:
            raise ValueError("Connect first")

        def published(value, url):
            self.published_workflows.clear()
            for row in value["workflows"]:
                self.published_workflows.addItem(f"{row['id']} · {row['version']}", row)
                self.published_workflows.setItemData(
                    self.published_workflows.count() - 1,
                    row["description"],
                    qt_enum(Qt, "ItemDataRole", "ToolTipRole"),
                )

        def saved(value, url):
            self.saved_workflows.clear()
            for row in value:
                self.saved_workflows.addItem(row["id"], row)

        self.client.request("autostacgis/workflows/available", published, self.message)
        self.client.request("autostacgis/workflows", saved, self.message)

    def activate_workflow(self, document, name=None):
        self.document = document
        self.active_workflow = name
        self.config_name.setText(name or "Unsaved workflow")
        self.update_workflow_button.setEnabled(name is not None)
        self.load_plugins({"plugins": self.plugins}, "")
        self.message("Workflow activated")

    def activate_published_workflow(self):
        row = self.published_workflows.currentData()
        if not row:
            raise ValueError("Choose a published workflow")
        self.client.request(
            "autostacgis/workflows/published/" + quote(row["id"], safe=""),
            lambda value, url: self.activate_workflow(value["document"]),
            self.message,
        )

    def activate_saved_workflow(self):
        row = self.saved_workflows.currentData()
        if not row:
            raise ValueError("Choose a saved workflow")
        self.activate_workflow(row["document"], row["id"])

    def workflow_saved(self, value, url):
        self.active_workflow = value["id"]
        self.config_name.setText(value["id"])
        self.update_workflow_button.setEnabled(True)
        self.refresh_workflows()
        self.message("Workflow saved")

    def copy_workflow(self):
        name, accepted = QInputDialog.getText(
            self,
            "Save workflow copy",
            "Workflow name",
            text=(self.active_workflow + " copy") if self.active_workflow else "My workflow",
        )
        if accepted and name.strip():
            self.client.request(
                "autostacgis/workflows",
                self.workflow_saved,
                self.message,
                "POST",
                {"name": name, "document": self.configuration()},
            )

    def update_workflow(self):
        if not self.active_workflow:
            raise ValueError("Activate a saved workflow first")
        self.client.request(
            "autostacgis/workflows/" + quote(self.active_workflow, safe=""),
            self.workflow_saved,
            self.message,
            "PUT",
            self.configuration(),
        )

    def rename_workflow(self):
        row = self.saved_workflows.currentData()
        if not row:
            raise ValueError("Choose a saved workflow")
        name, accepted = QInputDialog.getText(self, "Rename workflow", "Workflow name", text=row["id"])
        if accepted and name.strip():

            def renamed(value, url):
                if self.active_workflow == row["id"]:
                    self.active_workflow = value["id"]
                    self.config_name.setText(value["id"])
                self.refresh_workflows()
                self.message("Workflow renamed")

            self.client.request(
                "autostacgis/workflows/" + quote(row["id"], safe=""),
                renamed,
                self.message,
                "PATCH",
                {"name": name},
            )

    def delete_workflow(self):
        row = self.saved_workflows.currentData()
        if not row:
            raise ValueError("Choose a saved workflow")

        def deleted(value, url):
            if self.active_workflow == row["id"]:
                self.active_workflow = None
                self.config_name.setText("Unsaved workflow")
                self.update_workflow_button.setEnabled(False)
            self.refresh_workflows()
            self.message("Workflow deleted")

        self.client.request(
            "autostacgis/workflows/" + quote(row["id"], safe=""), deleted, self.message, "DELETE"
        )

    def make_workflow(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.config_name = QLineEdit("Unsaved workflow")
        self.config_name.setReadOnly(True)
        layout.addWidget(self.config_name)
        self.request_json = JsonEditor(json.dumps(self.document, indent=2))
        self.request_json.text.textChanged.connect(self.workflow_changed)
        layout.addWidget(QLabel("Workflow configuration"))
        layout.addWidget(self.request_json)
        for label, callback in (
            ("Validate", lambda: self.invoke("validate")),
            ("Plan selected items / discover", lambda: self.invoke("plan")),
            ("Run selected items / discover", lambda: self.invoke("jobs")),
            ("Export configuration", self.export_configuration),
            ("Import configuration", self.import_configuration),
        ):
            layout.addWidget(self.button(label, lambda _, function=callback: self.guarded(function)))
        self.output = JsonEditor()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)
        self.make_workflow_library(layout)
        self.workflow_index = self.tabs.addTab(widget, "Workflow")

    def configuration(self):
        return json.loads(self.request_json.toPlainText())

    def workflow_changed(self):
        if not self.syncing:
            self.workflow_dirty = True

    def sync_plugins(self):
        if self.syncing:
            return
        try:
            settings = {
                name: json.loads(editor.toPlainText())
                for name, (enabled, editor) in self.editors.items()
                if enabled.isChecked()
            }
            document = configuration(self.configuration(), list(settings), settings, self.plugins)
            structure = json.loads(self.structure_json.toPlainText())
            if structure:
                document["metadata_structure"] = structure
            else:
                document.pop("metadata_structure", None)
            self.syncing = True
            self.document = document
            self.request_json.setPlainText(json.dumps(document, indent=2))
        except ValueError as exc:
            self.message(exc)
        finally:
            self.syncing = False

    def change_tab(self, index):
        if self.workflow_dirty and index != self.workflow_index and self.plugins:
            try:
                self.document = self.configuration()
                self.load_plugins({"plugins": self.plugins}, "")
            except ValueError as exc:
                self.message(exc)
        if index == self.registry_index:
            self.guarded(self.refresh_registry)

    def invoke(self, operation, trigger=None):
        if not self.client:
            raise ValueError("Connect first")
        value = {"configuration": self.configuration()}
        items = self.selected_items()
        if trigger:
            value["trigger"] = trigger
        elif items:
            value["inputs"] = items
        self.client.request(
            "autostacgis/" + operation,
            lambda value, url: self.output.setPlainText(json.dumps(value, indent=2)),
            self.message,
            "POST",
            value,
        )

    def export_configuration(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Export configuration", "autostacgis.json", "JSON (*.json)"
        )
        if filename:
            Path(filename).write_text(json.dumps(self.configuration(), indent=2))

    def import_configuration(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Import configuration", "", "JSON (*.json)")
        if filename:
            self.document = json.loads(Path(filename).read_text())
            self.load_plugins({"plugins": self.plugins}, self.client.url if self.client else "")

    def make_jobs(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.jobs = QTreeWidget()
        self.jobs.setHeaderLabels(["Job", "State", "Error"])
        layout.addWidget(self.jobs)
        for label, callback in (
            ("Refresh", self.refresh_jobs),
            ("View result footprints", self.job_result),
            ("Cancel selected job", self.cancel_job),
        ):
            layout.addWidget(self.button(label, lambda _, function=callback: self.guarded(function)))
        self.tabs.addTab(widget, "Jobs")

    def refresh_jobs(self):
        def loaded(value, url):
            self.jobs.clear()
            for job in value:
                self.jobs.addTopLevelItem(QTreeWidgetItem([job["id"], job["state"], job.get("error") or ""]))

        self.client.request("autostacgis/jobs", loaded, self.message)

    def job_result(self):
        row = self.jobs.currentItem()
        if row:

            def loaded(value, url):
                if value.get("result"):
                    self.show_results(value["result"], url)
                    self.add_footprints()
                    self.tabs.setCurrentIndex(0)
                else:
                    self.message("Job has no completed output yet")

            self.client.request("autostacgis/jobs/" + row.text(0), loaded, self.message)

    def cancel_job(self):
        row = self.jobs.currentItem()
        if row:
            self.client.request(
                "autostacgis/jobs/" + row.text(0), lambda *_: self.refresh_jobs(), self.message, "DELETE"
            )

    def close_requests(self):
        if self.registry_client:
            self.registry_client.close()
        if self.client:
            self.client.close()

"""Reusable JSON tree/text editor. Both views edit the same JSON document."""

import json

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .compat import qt_enum


class JsonEditor(QWidget):
    def __init__(self, text="{}", parent=None, schema=None):
        super().__init__(parent)
        self.schema = schema or {}
        self.readonly = False
        self.updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.mode = QComboBox()
        self.mode.addItems(["GUI", "Text"])
        self.mode.setAccessibleName("JSON editing mode")
        layout.addWidget(self.mode)
        self.tabs = QStackedWidget()
        self.mode.currentIndexChanged.connect(self.tabs.setCurrentIndex)
        gui = QWidget()
        tree_layout = QVBoxLayout(gui)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Field", "Type", "Value"])
        tree_layout.addWidget(self.tree)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add field / item")
        self.remove_button = QPushButton("Remove")
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        tree_layout.addLayout(row)
        self.text = QPlainTextEdit()
        self.tabs.addWidget(gui)
        self.tabs.addWidget(self.text)
        layout.addWidget(self.tabs)
        self.error = QLabel()
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        self.text.textChanged.connect(self.refresh)
        self.tree.itemChanged.connect(self.changed)
        self.add_button.clicked.connect(self.add)
        self.remove_button.clicked.connect(self.remove)
        self.setPlainText(text)

    def toPlainText(self):
        return self.text.toPlainText()

    def setPlainText(self, value):
        self.text.setPlainText(value or "{}")

    def setReadOnly(self, readonly):
        self.readonly = readonly
        self.text.setReadOnly(readonly)
        self.add_button.setEnabled(not readonly)
        self.remove_button.setEnabled(not readonly)
        self.refresh()

    @staticmethod
    def kind(value):
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, dict):
            return "object"
        if isinstance(value, list):
            return "array"
        if isinstance(value, (int, float)):
            return "number"
        return "string"

    def refresh(self):
        if self.updating:
            return
        try:
            value = json.loads(self.toPlainText())
        except ValueError as exc:
            self.error.setText("Invalid JSON: " + str(exc))
            self.mode.setCurrentIndex(1)
            self.mode.model().item(0).setEnabled(False)
            return
        self.error.clear()
        self.mode.model().item(0).setEnabled(True)
        self.updating = True
        self.tree.clear()

        def append(parent, key, value, schema):
            kind = self.kind(value)
            row = QTreeWidgetItem(
                [
                    str(key),
                    kind,
                    ""
                    if kind in ("object", "array")
                    else str(value)
                    if kind == "string"
                    else json.dumps(value),
                ]
            )
            row.setData(0, qt_enum(Qt, "ItemDataRole", "UserRole"), schema)
            description = (
                "Type: " + str(schema.get("type", "JSON")) + "\n" + schema.get("description", "")
            ).strip()
            for column in range(3):
                row.setToolTip(column, description)
            if not self.readonly:
                row.setFlags(row.flags() | qt_enum(Qt, "ItemFlag", "ItemIsEditable"))
            parent.addChild(row) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(row)
            if isinstance(value, (dict, list)):
                for name, child in value.items() if isinstance(value, dict) else enumerate(value):
                    append(
                        row,
                        name,
                        child,
                        schema.get("properties", {}).get(str(name), {})
                        if isinstance(value, dict)
                        else schema.get("items", {}),
                    )
            row.setExpanded(True)

        append(self.tree, "$", value, self.schema)
        self.updating = False

    def value(self, row):
        kind = row.text(1)
        if kind == "object":
            keys = [row.child(i).text(0) for i in range(row.childCount())]
            if len(set(keys)) != len(keys):
                raise ValueError("Object field names must be unique")
            return {row.child(i).text(0): self.value(row.child(i)) for i in range(row.childCount())}
        if kind == "array":
            return [self.value(row.child(i)) for i in range(row.childCount())]
        if kind == "string":
            return row.text(2)
        if kind == "null":
            return None
        value = json.loads(row.text(2))
        if kind not in ("number", "boolean") or self.kind(value) != kind:
            raise ValueError(
                "Choose object, array, string, number, boolean, or null, and enter a matching value"
            )
        return value

    def changed(self, *_):
        if self.updating:
            return
        try:
            value = self.value(self.tree.topLevelItem(0))

            def validate(value, schema):
                expected = schema.get("type")
                actual = self.kind(value)
                if isinstance(expected, str) and actual != ("number" if expected == "integer" else expected):
                    raise ValueError(f"Expected {expected}")
                if expected == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
                    raise ValueError("Expected integer")
                if "enum" in schema and value not in schema["enum"]:
                    raise ValueError("Choose a declared value: " + str(schema["enum"]))
                if isinstance(value, dict):
                    for key, child in value.items():
                        if (
                            key not in schema.get("properties", {})
                            and schema.get("additionalProperties") is False
                        ):
                            raise ValueError("Unknown parameter: " + key)
                        validate(child, schema.get("properties", {}).get(key, {}))
                elif isinstance(value, list):
                    for child in value:
                        validate(child, schema.get("items", {}))

            validate(value, self.schema)
            self.updating = True
            self.text.setPlainText(json.dumps(value, indent=2, allow_nan=False))
            self.updating = False
            self.error.clear()
        except (ValueError, TypeError) as exc:
            self.updating = False
            self.error.setText(str(exc))

    def add(self):
        row = self.tree.currentItem() or self.tree.topLevelItem(0)
        if row.text(1) not in ("object", "array"):
            self.error.setText("Select an object or array to add a field or item")
            return
        schema = row.data(0, qt_enum(Qt, "ItemDataRole", "UserRole")) or {}
        key = str(row.childCount())
        definition = schema.get("items", {})
        if row.text(1) == "object":
            fields = schema.get("properties", {})
            existing = [row.child(i).text(0) for i in range(row.childCount())]
            choices = [name for name in fields if name not in existing]
            if choices:
                key, accepted = QInputDialog.getItem(
                    self,
                    "Add parameter",
                    "Parameter",
                    choices,
                    0,
                    schema.get("additionalProperties") is not False,
                )
            elif schema.get("additionalProperties") is False:
                self.error.setText("All declared parameters have been added")
                return
            else:
                key, accepted = QInputDialog.getText(self, "Add field", "Field name")
            definition = fields.get(key, {})
            if not accepted or not key:
                return
            if key in [row.child(i).text(0) for i in range(row.childCount())]:
                self.error.setText("That field already exists")
                return
        defaults = {"string": "", "integer": 0, "number": 0, "boolean": False, "object": {}, "array": []}
        value = definition.get(
            "default", (definition.get("enum") or [defaults.get(definition.get("type"))])[0]
        )
        document = json.loads(self.toPlainText())
        path = []
        current = row
        while current.parent():
            path.append(current.text(0))
            current = current.parent()
        container = document
        for part in reversed(path):
            container = container[int(part)] if isinstance(container, list) else container[part]
        if isinstance(container, list):
            container.append(value)
        else:
            container[key] = value
        self.setPlainText(json.dumps(document, indent=2))

    def remove(self):
        row = self.tree.currentItem()
        if row and row.parent():
            row.parent().removeChild(row)
            self.changed()

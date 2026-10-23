"""Reusable JSON tree/text editor. Both views edit the same JSON document."""

import json

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .compat import qt_enum


class JsonEditor(QWidget):
    def __init__(self, text="{}", parent=None):
        super().__init__(parent)
        self.readonly = False
        self.updating = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
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
        self.tabs.addTab(gui, "GUI")
        self.tabs.addTab(self.text, "Text")
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
            self.tabs.setCurrentIndex(1)
            self.tabs.setTabEnabled(0, False)
            return
        self.error.clear()
        self.tabs.setTabEnabled(0, True)
        self.updating = True
        self.tree.clear()

        def append(parent, key, value):
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
            if not self.readonly:
                row.setFlags(row.flags() | qt_enum(Qt, "ItemFlag", "ItemIsEditable"))
            parent.addChild(row) if isinstance(parent, QTreeWidgetItem) else parent.addTopLevelItem(row)
            if isinstance(value, (dict, list)):
                for name, child in value.items() if isinstance(value, dict) else enumerate(value):
                    append(row, name, child)
            row.setExpanded(True)

        append(self.tree, "$", value)
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
        key = str(row.childCount())
        if row.text(1) == "object":
            key, accepted = QInputDialog.getText(self, "Add field", "Field name")
            if not accepted or not key:
                return
            if key in [row.child(i).text(0) for i in range(row.childCount())]:
                self.error.setText("That field already exists")
                return
        self.updating = True
        child = QTreeWidgetItem([key, "null", "null"])
        child.setFlags(child.flags() | qt_enum(Qt, "ItemFlag", "ItemIsEditable"))
        row.addChild(child)
        self.updating = False
        self.changed()

    def remove(self):
        row = self.tree.currentItem()
        if row and row.parent():
            row.parent().removeChild(row)
            self.changed()

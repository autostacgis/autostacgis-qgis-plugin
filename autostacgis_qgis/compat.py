"""Scoped Qt enums and actions across QGIS's Qt 5 and Qt 6 builds."""

try:
    from qgis.PyQt.QtGui import QAction as QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction as QAction


def qt_enum(owner, namespace, name):
    scoped = getattr(owner, namespace, None)
    if scoped is not None and hasattr(scoped, name):
        return getattr(scoped, name)
    return getattr(owner, name)

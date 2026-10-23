def classFactory(iface):
    from .plugin import AutoSTACGISPlugin

    return AutoSTACGISPlugin(iface)

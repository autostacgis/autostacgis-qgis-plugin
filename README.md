# AutostacGIS QGIS plugin

Search any STAC API and load its data into the main QGIS map. Connect to AutostacGIS PostgreSQL to edit plugin settings, plan workflows, queue/cancel runs and open their results. There is no second embedded map.

## Install

Run `python scripts/package.py`, then QGIS **Plugins → Manage and Install Plugins → Install from ZIP** and select `dist/autostacgis-qgis.zip`. Enable AutostacGIS and open its toolbar/menu action. QGIS 3.34+ and QGIS 4 are supported through `qgis.PyQt`. The plugin uses QGIS's native networking and providers; it does not install the scientific engine into QGIS's Python environment.

## Use

Enter a STAC API root URL and optional Bearer token. Tokens remain in memory for this session; the last API URL is saved. Search collections, bbox, datetime or raw STAC/CQL2 JSON. Use the main map extent for the AOI, navigate pagination, select an asset and add it with QGIS's GDAL, OGR or PDAL provider. COG, GeoTIFF, GeoJSON, GeoPackage, Parquet and LAS/LAZ assets are supported when the installed provider supports that format. Footprints are ordinary QGIS vector layers. A raster bbox/footprint is not a pixel preview; selected raster assets are opened in the main map.

Every capability has a tab, and every installed plugin has its own settings panel, parameter contract and enable switch. Settings are raw JSON so upstream parameters remain available. Dependencies are included automatically and conflicting solver dependencies are rejected. The Workflow tab edits the native request/goal, validates, plans or runs selected catalog Items (or discovers when none are selected), and saves/loads configurations on the backend or imports/exports JSON. The Jobs tab refreshes states, cancels work and opens completed outputs from the same STAC catalog.

Any standard STAC API works for browsing; AutostacGIS endpoints are optional. Network requests are asynchronous, preserve signed asset URLs and refuse cross-origin pagination rather than forwarding credentials to another host. Use QGIS's own authentication configurations for protected asset providers where needed.

Run `pytest` for protocol/configuration helpers. `tests/qgis_smoke.py` exercises the dock in a real QGIS Python environment. Build the installable ZIP with `scripts/package.py`.


Plugin Registry fetches published names, versions and capabilities online. It uses the connected backend's configured registry or the public GitHub Pages manifest when disconnected. Install a selected version or a local Python file on the backend; the write token is required. Plugins execute Python with the backend's permissions. See the plugins repository's CONTRIBUTING.md to publish through a PR.

Metadata Structure edits the shared configuration section with schema URLs, an inline Item JSON Schema, and strict unknown-field validation. Core STAC fields are automatic; declare extensions and custom nested metadata explicitly. Every JSON editor offers GUI and Text views, including settings, search, requests and contracts. GUI fields retain JSON types and structure. Invalid text remains available for correction.

## Workflow library and plugin parameters

Workflows use one JSON document with plugin types as the top-level sections. The smallest explicit selection is `{"solver":{"backward_chain":{}},"goal":{"metadata-value":{"path":"properties.ready","value":true}}}`. Plugin dependencies and runtime defaults are resolved in Python. At most one trigger is active; omission runs immediately. Use `now`, `apscheduler`, or `watchdog` to choose how a workflow starts. See the [core configuration guide](https://github.com/autostacgis/autostacgis-python/blob/main/docs/workflows.md).

Plugin descriptions come from the required Python module docstring. Defaults, parameter descriptions and schemas are supplied by the library. Both JSON views edit the same document; the GUI offers declared optional parameters with their defaults. Unsupported complex annotations remain editable as JSON.

The workflow library lists published workflows and saved copies on the connected backend. Activate loads the JSON into the workflow editor. Published workflows can be saved as named copies; saved workflows can be updated, copied, renamed or deleted. Discovery and downloads use `autostacgis.workflow_manager.WorkflowManager`, sharing HTTPS and checksum verification with plugin installation. The backend exposes `/autostacgis/workflows`, `/workflows/available`, and `/workflows/published/{id}`. Save-copy is POST, update is PUT, rename is PATCH and delete is DELETE. `AUTOSTACGIS_WORKFLOW_REGISTRY_URL` selects another registry.

Workflows use capability sections in one configuration document. Old catalog/request documents and separate configuration overlays are rejected.

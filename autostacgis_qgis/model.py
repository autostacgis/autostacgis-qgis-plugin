"""STAC/configuration helpers independent of Qt and the native processing engine."""

from copy import deepcopy
from urllib.parse import urljoin, urlsplit
from urllib.request import url2pathname

CAPABILITIES = (
    "trigger",
    "data_in",
    "metadata_in",
    "checks",
    "sequence",
    "data_transfer",
    "checkpoint",
    "encode",
    "process",
    "data_out",
    "metadata_out",
    "goal",
    "solver",
    "services",
    "extensions",
)


def api_url(value):
    parsed = urlsplit(value)
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an HTTP(S) STAC API root URL without embedded credentials, query or fragment")
    return value.rstrip("/") + "/"


def same_origin(left, right):
    a, b = urlsplit(left), urlsplit(right)
    return (a.scheme, a.hostname, a.port or (443 if a.scheme == "https" else 80)) == (
        b.scheme,
        b.hostname,
        b.port or (443 if b.scheme == "https" else 80),
    )


def resolve_item(item, base):
    item = deepcopy(item)
    for asset in item.get("assets", {}).values():
        asset["href"] = urljoin(base, asset["href"])
    for link in item.get("links", []):
        link["href"] = urljoin(base, link["href"])
    return item


def next_page(page, url, body):
    link = next((link for link in page.get("links", []) if link.get("rel") == "next"), None)
    if not link:
        return None
    target = urljoin(url, link["href"])
    if not same_origin(url, target):
        raise ValueError("Pagination must remain on the connected API origin")
    if link.get("method", "GET").upper() not in ("GET", "POST"):
        raise ValueError("STAC pagination only supports GET and POST")
    payload = {**(body or {}), **link.get("body", {})} if link.get("merge") else link.get("body")
    return target, link.get("method", "GET").upper(), payload


def asset_provider(asset):
    href = asset["href"]
    parsed = urlsplit(href)
    if parsed.scheme == "file":
        href = url2pathname(parsed.path)
        if parsed.netloc and parsed.netloc != "localhost":
            href = "//" + parsed.netloc + href
    suffix = parsed.path.lower()
    media = asset.get("type", "").lower()
    if parsed.scheme not in ("", "file", "http", "https", "s3", "gs"):
        raise ValueError("This asset is not a loadable local or remote data file")
    if any(suffix.endswith(ext) for ext in (".las", ".laz")) or "laszip" in media:
        return "pointcloud", href
    if (
        any(suffix.endswith(ext) for ext in (".tif", ".tiff", ".vrt", ".jp2", ".img"))
        or "image/tiff" in media
    ):
        prefixes = {"http": "/vsicurl/", "https": "/vsicurl/", "s3": "/vsis3/", "gs": "/vsigs/"}
        if parsed.scheme in ("s3", "gs"):
            href = prefixes[parsed.scheme] + parsed.netloc + parsed.path
        elif parsed.scheme in prefixes:
            href = prefixes[parsed.scheme] + href
        return "raster", href
    if (
        any(
            suffix.endswith(ext) for ext in (".geojson", ".json", ".gpkg", ".fgb", ".parquet", ".shp", ".csv")
        )
        or "geo+json" in media
        or "parquet" in media
    ):
        return "vector", href
    raise ValueError("Choose a supported raster, vector, table or point-cloud asset")


def configuration(document, selected, settings, plugins):
    result = deepcopy(document)
    definitions = {plugin["id"]: plugin for plugin in plugins}
    for capability in CAPABILITIES:
        for name in document.get(capability, {}):
            if name not in definitions or definitions[name]["capability"] != capability:
                raise ValueError(f"Unavailable {capability} plugin {name}")
    for capability in CAPABILITIES:
        result.pop(capability, None)
    result.pop("catalog", None)
    result.pop("request", None)
    enabled = set(selected)
    pending = list(selected)
    while pending:
        name = pending.pop()
        for dependency in definitions[name].get("requires", []):
            if dependency not in enabled:
                enabled.add(dependency)
                pending.append(dependency)
    for capability in ("solver", "trigger"):
        if sum(definitions[name]["capability"] == capability for name in enabled) > 1:
            raise ValueError(f"Select only one {capability}")
    for name in selected:
        plugin = definitions[name]
        result.setdefault(plugin["capability"], {})[name] = deepcopy(
            settings.get(name, plugin.get("defaults", {}))
        )
    solvers = [name for name in enabled if definitions[name]["capability"] == "solver"]
    if solvers and "solver" not in result:
        result["solver"] = {solvers[0]: {}}
    return result

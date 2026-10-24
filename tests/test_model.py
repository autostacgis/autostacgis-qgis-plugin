import pytest

from autostacgis_qgis.model import api_url, asset_provider, configuration, next_page, resolve_item


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/a",
        "https://user:secret@example.test",
        "javascript:alert(1)",
        "https://example.test/?token=x",
    ],
)
def test_api_roots_reject_unsafe_schemes_or_embedded_credentials(url):
    with pytest.raises(ValueError):
        api_url(url)


def test_signed_asset_urls_and_relative_search_links_are_preserved():
    uri = "https://example.test/a.tif?signature=abc%2Fdef"
    assert asset_provider({"href": uri}) == ("raster", "/vsicurl/" + uri)
    item = resolve_item(
        {"assets": {"data": {"href": "../a.tif?signature=abc%2Fdef"}}}, "https://example.test/v1/search"
    )
    assert item["assets"]["data"]["href"] == uri
    page = {
        "links": [
            {"rel": "next", "href": "search", "method": "POST", "merge": True, "body": {"token": "next"}}
        ]
    }
    assert next_page(page, "https://example.test/v1/search", {"bbox": [0, 0, 1, 1]}) == (
        "https://example.test/v1/search",
        "POST",
        {"bbox": [0, 0, 1, 1], "token": "next"},
    )
    with pytest.raises(ValueError):
        next_page(
            {"links": [{"rel": "next", "href": "https://evil.test/"}]}, "https://example.test/search", {}
        )


def test_capability_settings_include_dependencies_and_enforce_one_solver():
    plugins = [
        {"id": "goal", "capability": "goal", "requires": ["backward_chain"]},
        {"id": "backward_chain", "capability": "solver", "requires": []},
        {"id": "other", "capability": "solver", "requires": []},
    ]
    result = configuration({"request": {"goal": {"output": {}}}}, ["goal"], {"goal": {"value": 1}}, plugins)
    assert result == {"solver": {"backward_chain": {}}, "goal": {"goal": {"value": 1}}}
    with pytest.raises(ValueError):
        configuration({}, ["goal", "other"], {}, plugins)

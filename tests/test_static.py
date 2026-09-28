import pytest

from ialauncher.web import static


def test_assets_with_their_type():
    assert static.find("/js/main.js")[1].startswith("text/javascript")
    assert static.find("/css/themes/cyber.css")[1].startswith("text/css")


@pytest.mark.parametrize("path", ["/../engines.json", "/css/../../ialauncher/config.py", "/nope.js", "/js",
                                  "/index.html"])
def test_nothing_outside_web_missing_or_not_an_asset(path):
    assert static.find(path) is None

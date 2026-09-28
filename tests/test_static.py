import pytest

from ialauncher.web import static


@pytest.mark.parametrize("path", ["/", "/modeles", "/index.html"])
def test_every_view_gets_the_page(path):
    body, ctype = static.find(path)
    assert ctype.startswith("text/html") and b'<script type="module" src="/js/main.js">' in body


def test_assets_with_their_type():
    assert static.find("/js/main.js")[1].startswith("text/javascript")
    assert static.find("/css/themes/cyber.css")[1].startswith("text/css")


@pytest.mark.parametrize("path", ["/../engines.json", "/css/../../ialauncher/config.py", "/nope.js", "/js"])
def test_nothing_outside_web_or_missing(path):
    assert static.find(path) is None

import pytest

from hominfer.errors import LaunchError
from hominfer.services import folders


def test_lists_folders_only(tmp_path):
    for name in ("b", "A", ".hidden"):
        (tmp_path / name).mkdir()
    (tmp_path / "file.gguf").write_text("x")
    d = folders.browse(str(tmp_path))
    assert d["path"] == str(tmp_path) and d["parent"] == str(tmp_path.parent)
    assert d["dirs"] == ["A", "b"]
    assert d["shortcuts"][-1] == "/"


def test_root_has_no_parent():
    assert folders.browse("/")["parent"] is None


@pytest.mark.parametrize("path", ["relative/dir", "/no/such/folder"])
def test_not_a_folder(path):
    with pytest.raises(LaunchError, match="Not a folder"):
        folders.browse(path)


def test_file_is_not_a_folder(tmp_path):
    (tmp_path / "f").write_text("x")
    with pytest.raises(LaunchError, match="Not a folder"):
        folders.browse(str(tmp_path / "f"))

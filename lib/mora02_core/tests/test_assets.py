from pathlib import Path

from mora02_core import Asset


def test_asset_defaults_user_id():
    a = Asset(id="x1", type="image", path=Path("/tmp/foo.png"))
    assert a.user_id == "default"


def test_asset_filename():
    a = Asset(id="x1", type="image", path=Path("/tmp/foo.png"))
    assert a.filename == "foo.png"


def test_asset_url_comfyui_wip():
    a = Asset(
        id="x1",
        type="image",
        path=Path("/opt/mora02/output/_default/comfyui/wip/foo.png"),
    )
    assert a.url == "http://mora02.local:8092/comfyui-wip/foo.png"


def test_asset_url_other_default_output():
    a = Asset(
        id="x2",
        type="video",
        path=Path("/opt/mora02/output/_default/clipper/clip1.mp4"),
    )
    assert a.url == "http://mora02.local:8092/clipper/clip1.mp4"


def test_asset_url_external_path_is_file_url():
    a = Asset(id="x3", type="text", path=Path("/tmp/somewhere/note.txt"))
    assert a.url == "file:///tmp/somewhere/note.txt"


def test_asset_metadata_independent_per_instance():
    a = Asset(id="a", type="text", path=Path("/tmp/a"))
    b = Asset(id="b", type="text", path=Path("/tmp/b"))
    a.metadata["x"] = 1
    assert "x" not in b.metadata


def test_asset_custom_user_id():
    a = Asset(id="x", type="audio", path=Path("/tmp/x.wav"), user_id="alice")
    assert a.user_id == "alice"

from pathlib import Path

from mora02_core import Asset
from mora02_core.assets import url_for_ref, path_for_ref


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


# url_for_ref — store-aware public URLs (each store knows its nginx path).
def test_url_for_ref_comfyui():
    assert url_for_ref("asset://comfyui/img_1.png") == \
        "http://mora02.local:8092/comfyui/wip/img_1.png"


def test_url_for_ref_tool_assets():
    # gifer/clipper/typer/tts are served under /tool-assets/<store>/
    assert url_for_ref("asset://typer/txt_z.png") == \
        "http://mora02.local:8092/tool-assets/typer/txt_z.png"
    assert url_for_ref("asset://tts/vox_q.wav") == \
        "http://mora02.local:8092/tool-assets/tts/vox_q.wav"


def test_url_for_ref_store_without_base_is_file_url():
    # a store with no public URL base (e.g. scriptbot) falls back to file://
    assert url_for_ref("asset://scriptbot/sess/file.txt").startswith("file://")


# path_for_ref — host-less nginx path (used to feed an asset back into ComfyUI).
def test_path_for_ref_comfyui_and_tools():
    assert path_for_ref("asset://comfyui/img.png") == "/comfyui/wip/img.png"
    assert path_for_ref("asset://gifer/g.gif") == "/tool-assets/gifer/g.gif"


def test_path_for_ref_unknown_store_is_none():
    assert path_for_ref("asset://scriptbot/sess/file.txt") is None

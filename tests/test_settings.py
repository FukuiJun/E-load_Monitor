"""設定の保持（F-09）"""

import json

import settings


def test_defaults_when_missing(app_dir):
    s = settings.load()
    assert s.host == "192.168.10.2" and s.port == 5025
    assert s.current == 1.0 and s.cutoff == 3.0 and s.interval == 1.0
    assert s.folder


def test_roundtrip_only_allowed_keys(app_dir, tmp_path):
    s = settings.Settings(host="10.0.0.5", port=5026, folder=str(tmp_path), current=2.0, cutoff=2.75,
                          interval=0.5)
    assert settings.save(s)
    data = json.loads((app_dir / "sdl_logger_settings.json").read_text(encoding="utf-8"))
    assert set(data) == {"host", "port", "folder", "current", "cutoff", "interval"}
    assert settings.load() == s


def test_broken_or_out_of_range_values_fall_back(app_dir):
    (app_dir / "sdl_logger_settings.json").write_text(
        json.dumps({"host": "", "port": 70000, "folder": "/存在しない", "current": 9, "cutoff": "3",
                    "interval": 0.1}), encoding="utf-8")
    s = settings.load()
    assert s.host == "192.168.10.2" and s.port == 5025
    assert s.current == 1.0 and s.cutoff == 3.0 and s.interval == 1.0
    (app_dir / "sdl_logger_settings.json").write_text("{壊れた", encoding="utf-8")
    assert settings.load().host == "192.168.10.2"


def test_icon_files():
    """アイコン（デザイン案B）：exe 用の ico に 16〜256 px、ウィンドウ用の PNG がある"""
    from PIL import Image

    import paths

    ico = paths.icon_ico()
    assert ico.exists()
    sizes = Image.open(ico).info["sizes"]
    assert {(16, 16), (32, 32), (48, 48), (256, 256)} <= set(sizes)
    for p in paths.icon_pngs():
        assert p.exists(), p

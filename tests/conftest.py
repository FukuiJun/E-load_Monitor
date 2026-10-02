"""テスト共通：src と tools をインポートパスに加え、シミュレータのフィクスチャを用意する"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from fake_sdl import FakeSDL  # noqa: E402


@pytest.fixture
def fake():
    """空きポートで動くシミュレータ（テスト終了時に停止）"""
    sdl = FakeSDL(port=0).start()
    yield sdl
    sdl.stop()


@pytest.fixture(autouse=True)
def app_dir(tmp_path_factory, monkeypatch):
    """設定ファイル・ログの置き場所をテスト用の一時フォルダにする（保存先の tmp_path とは別）"""
    d = tmp_path_factory.mktemp("app")
    monkeypatch.setenv("SDL_LOGGER_APP_DIR", str(d))
    monkeypatch.setenv("SDL_LOGGER_SCALE", "1")  # 画面の拡大率は 100% で確かめる（個別のテストで変える）
    return d

"""ファイルの置き場所"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SETTINGS_FILE = "sdl_logger_settings.json"
LOG_FILE = "sdl_logger.log"


def app_dir() -> Path:
    """設定ファイル・ログを置くフォルダ（exe と同じフォルダ）。

    開発時（python で直接実行）は sdl_discharge_logger フォルダ。環境変数 SDL_LOGGER_APP_DIR で変更可。
    """
    override = os.environ.get("SDL_LOGGER_APP_DIR")
    if override:
        return Path(override)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def settings_path() -> Path:
    return app_dir() / SETTINGS_FILE


def log_path() -> Path:
    return app_dir() / LOG_FILE


def desktop_dir() -> Path:
    """デスクトップのフォルダ（OneDrive に移動されている場合も含む）"""
    if sys.platform == "win32":
        try:
            import ctypes

            buf = ctypes.create_unicode_buffer(260)
            # CSIDL_DESKTOPDIRECTORY = 0x10
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    desktop = Path.home() / "Desktop"
    return desktop if desktop.is_dir() else Path.home()

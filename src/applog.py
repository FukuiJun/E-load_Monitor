"""ログ（exe と同じフォルダの sdl_logger.log、1MB でローテーション・3 世代）"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import paths

MAX_BYTES = 1024 * 1024
BACKUP_COUNT = 3
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup(path: Path | None = None, level: int = logging.INFO) -> logging.Handler | None:
    """ログの出力先を設定する。書けないフォルダのときはログを出さずに動く"""
    root = logging.getLogger()
    root.setLevel(level)
    path = path or paths.log_path()
    try:
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
                                                       encoding="utf-8")
    except OSError:
        root.addHandler(logging.NullHandler())
        return None
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    # matplotlib のフォント探索などの細かいログは出さない
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    return handler

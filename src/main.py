"""SDL放電ロガー エントリポイント（GUI）"""

from __future__ import annotations

import atexit
import logging
import sys
import threading
from pathlib import Path

# exe でなく python src/main.py で実行したときも src 内のモジュールを読めるようにする
sys.path.insert(0, str(Path(__file__).resolve().parent))

import applog  # noqa: E402
import sdl_client  # noqa: E402

VERSION = "1.0.0"
log = logging.getLogger("sdl.main")


def _emergency_off() -> None:
    """負荷 ON のまま終了しようとしているときは負荷 OFF を送る（可能な範囲で）"""
    try:
        sdl_client.emergency_load_off_all()
    except Exception:  # noqa: BLE001
        log.exception("終了時の負荷 OFF に失敗")


def _excepthook(exc_type, exc, tb) -> None:
    log.critical("想定外のエラーで終了します", exc_info=(exc_type, exc, tb))
    _emergency_off()


def _thread_excepthook(args) -> None:
    log.error("スレッド %s で想定外のエラー", args.thread.name if args.thread else "?",
              exc_info=(args.exc_type, args.exc_value, args.exc_traceback))


def main() -> int:
    applog.setup()
    log.info("起動 SDL放電ロガー %s", VERSION)
    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    atexit.register(_emergency_off)

    import tkinter as tk
    from tkinter import messagebox

    import gui

    root = tk.Tk()
    try:
        gui.App(root)
        root.mainloop()
    except BaseException as e:
        log.critical("想定外のエラーで終了します", exc_info=True)
        _emergency_off()
        try:
            messagebox.showerror(gui.APP_TITLE, f"想定外のエラーで終了します:\n{e}")
        except Exception:  # noqa: BLE001
            pass
        return 1
    finally:
        _emergency_off()
    return 0


if __name__ == "__main__":
    sys.exit(main())

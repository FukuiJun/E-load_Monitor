"""PyInstaller で単一 exe（dist/SDL放電ロガー.exe）を作る（build.bat から呼ぶ）

PyInstaller には ASCII 名（SDLDischargeLogger）でビルドさせ、最後に日本語名へ変更する
（作業フォルダ名などに日本語を通さないため。1 ファイル形式の exe は名前を変えても動く）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent
ASCII_NAME = "SDLDischargeLogger"
EXE_NAME = "SDL放電ロガー"
EXCLUDES = ["PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi", "IPython", "jupyter", "notebook",
            "pytest", "scipy", "pandas", "sphinx"]


def main() -> int:
    ext = ".exe" if sys.platform == "win32" else ""
    dist = ROOT / "dist"
    args = [
        str(ROOT / "src" / "main.py"),
        "--onefile", "--windowed", "--noconfirm", "--clean",
        "--name", ASCII_NAME,
        "--paths", str(ROOT / "src"),
        "--distpath", str(dist),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    PyInstaller.__main__.run(args)

    built = dist / f"{ASCII_NAME}{ext}"
    target = dist / f"{EXE_NAME}{ext}"
    if target.exists():
        target.unlink()
    os.replace(built, target)
    print(f"作成しました: {target}（{target.stat().st_size / 1024 / 1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

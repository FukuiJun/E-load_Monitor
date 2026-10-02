"""PyInstaller で単一 exe（dist/SDL_Monitor.exe）を作る（build.bat から呼ぶ）

exe のファイル名は EXE_NAME。画面のタイトル（SDL放電ロガー）とは別に決めている。
"""

from __future__ import annotations

import sys
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent
EXE_NAME = "SDL_Monitor"
EXCLUDES = ["PyQt5", "PyQt6", "PySide2", "PySide6", "wx", "gi", "IPython", "jupyter", "notebook",
            "pytest", "scipy", "pandas", "sphinx"]


def main() -> int:
    ext = ".exe" if sys.platform == "win32" else ""
    dist = ROOT / "dist"
    args = [
        str(ROOT / "src" / "main.py"),
        "--onefile", "--windowed", "--noconfirm", "--clean",
        "--name", EXE_NAME,
        "--paths", str(ROOT / "src"),
        "--distpath", str(dist),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
    ]
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    PyInstaller.__main__.run(args)

    target = dist / f"{EXE_NAME}{ext}"
    print(f"作成しました: {target}（{target.stat().st_size / 1024 / 1024:.1f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

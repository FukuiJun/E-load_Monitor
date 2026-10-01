"""画面デザイン案A「本体カラー」の色とフォント（docs/design/DESIGN.md 5 章・6 章）

色はすべてここで定義し、各部品はここを参照する（DESIGN.md D-AC-02）。
"""

from __future__ import annotations

# DESIGN.md 5 章のトークン名をそのままキーにする
COLORS = {
    "chassis": "#cfd3d7",
    "panel": "#e3e6e9",
    "panel-border": "#b9bec3",
    "key": "#eef0f2",
    "key-border": "#b4bac0",
    "input-bg": "#f6f7f8",
    "input-border": "#a9afb5",
    "text": "#1f2326",
    "text-sub": "#3b4146",
    "text-disabled": "#6a7076",
    "bezel": "#2a2d30",
    "lcd-bg": "#050505",
    "lcd-value": "#ffe14a",
    "lcd-white": "#ffffff",
    "lcd-label": "#d0d0d0",
    "lcd-tick": "#bdbdbd",
    "lcd-grid": "#262626",
    "lcd-frame": "#3a3a3a",
    "lcd-rule": "#e8892b",
    "lcd-cutoff": "#ff9a4a",
    "lcd-accent": "#5fb4ff",
    "lcd-warn": "#ff9a4a",
    "lcd-dim": "#5a5a5a",
    "accent-blue": "#1d5fa8",
    "danger": "#b3261e",
    "ok": "#5ad16a",
    "warn": "#e8892b",
    "idle": "#8a9096",
    # 4 章・8 章・10.2 で値が直接書かれている色
    "mode-chip": "#3a3a3a",       # ②-1 の「CC」の地
    "chip-border": "#5a5a5a",     # ②-6 条件チップの枠
    "button-disabled": "#e9ebed", # 無効ボタンの背景
    "button-stop": "#111111",     # 停止・保存ボタン
    "memo-bg": "#ffffff",         # 備考の背景
    "message-warn": "#8a5300",    # メッセージ欄の警告
    "png-bg": "#ffffff",
    "png-grid": "#e3e6e9",
    "png-text": "#1f2326",
    "png-voltage": "#1d5fa8",
    "png-current": "#c4620a",
    "png-cutoff": "#b3261e",
}
C = COLORS

# 6 章のフォント。先頭から順に、入っているものを使う
UI_FAMILIES = ["BIZ UDPゴシック", "BIZ UDPGothic", "Yu Gothic UI", "Meiryo UI", "IPAPGothic", "IPAGothic",
               "Noto Sans CJK JP"]
NUM_FAMILIES = ["Consolas", "DejaVu Sans Mono", "Courier New"]
# matplotlib 用（フォントファイル内の英語名）
MPL_UI_FAMILIES = ["BIZ UDPGothic", "Yu Gothic", "Meiryo", "MS Gothic", "IPAPGothic", "IPAGothic",
                   "Noto Sans CJK JP"]
MPL_NUM_FAMILIES = ["Consolas", "DejaVu Sans Mono"]


def pick_family(available: set[str], candidates: list[str], fallback: str) -> str:
    for name in candidates:
        if name in available:
            return name
    return fallback


class Fonts:
    """tkinter のフォント。大きさは px（tk の負の値）で指定する"""

    def __init__(self, root):
        from tkinter import font as tkfont

        available = set(tkfont.families(root))
        self.ui = pick_family(available, UI_FAMILIES, "TkDefaultFont")
        self.num = pick_family(available, NUM_FAMILIES, "TkFixedFont")

    def ui_px(self, px: int, bold: bool = False):
        return (self.ui, -px, "bold") if bold else (self.ui, -px)

    def num_px(self, px: int, bold: bool = False):
        return (self.num, -px, "bold") if bold else (self.num, -px)

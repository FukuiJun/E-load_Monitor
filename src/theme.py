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
    # ON/OFF キー（SDL1020X-E 本体の ON/OFF キーを模す。負荷 ON の間は外枠と文字が黄緑に光り、キーは緑がかった黒になる）
    "onoff-frame": "#c9cdd1",     # キーまわりの明るい灰色の縁
    "onoff-key": "#17191b",       # キー（黒）
    "onoff-text": "#ffffff",
    "onoff-lit": "#c4d65c",       # 負荷 ON の間の外枠と文字（黄緑）
    "onoff-key-lit": "#0d1a09",   # 負荷 ON の間のキー（緑がかった黒）
    "onoff-off-text": "#8a9096",  # 押せないとき（未接続など）
    "akane": "#b7282e",           # グラフ保存（押せるとき）。茜色
    "akane-border": "#8c1d22",
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


# 画面の拡大率。DESIGN.md の寸法（px）はすべて 100% のときの値で、Windows の表示倍率（125%・150% など）に
# 合わせてこの倍率をかけて描く（ぼやけないように、アプリを高 DPI 対応にしたうえで自分で拡大する）
SCALE = 1.0


def set_scale(value: float) -> None:
    global SCALE
    SCALE = value


def px(value: float) -> int:
    """DESIGN.md の寸法 → 実際の画面の px"""
    if value == 0:
        return 0
    scaled = round(value * SCALE)
    return scaled if scaled != 0 else (1 if value > 0 else -1)


def pick_family(available: set[str], candidates: list[str], fallback: str) -> str:
    for name in candidates:
        if name in available:
            return name
    return fallback


class Fonts:
    """tkinter のフォント。大きさは DESIGN.md の px で指定する（拡大率をかけて tk の負の値＝px にする）"""

    def __init__(self, root):
        from tkinter import font as tkfont

        available = set(tkfont.families(root))
        self.ui = pick_family(available, UI_FAMILIES, "TkDefaultFont")
        self.num = pick_family(available, NUM_FAMILIES, "TkFixedFont")

    def ui_px(self, size: int, bold: bool = False):
        return (self.ui, -px(size), "bold") if bold else (self.ui, -px(size))

    def num_px(self, size: int, bold: bool = False):
        return (self.num, -px(size), "bold") if bold else (self.num, -px(size))

"""グラフ（上段: 電圧、下段: 電流、横軸: 経過時間）の描画と PNG 保存

pyplot は使わず matplotlib.figure.Figure を直接使う（画面用とは別の Figure で PNG を作れるため、
測定スレッドから保存しても画面の描画とぶつからない）。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

MAX_PLOT_POINTS = 5000
PNG_SIZE_INCH = (16, 10)  # 100 dpi で 1600×1000 px
PNG_DPI = 100

COLOR_VOLTAGE = "#2a78d6"
COLOR_CURRENT = "#eb6834"
COLOR_CUTOFF = "#52514e"
COLOR_GRID = "#e4e3df"
COLOR_TEXT = "#0b0b0b"
COLOR_TEXT_SUB = "#52514e"

_JP_FONTS = ["Yu Gothic", "Meiryo", "MS Gothic", "BIZ UDGothic", "IPAexGothic", "IPAGothic",
             "Noto Sans CJK JP", "Noto Sans JP", "TakaoGothic"]
_fonts_ready = False


def setup_fonts() -> None:
    """日本語が表示できるフォントを使う（Windows では Yu Gothic / Meiryo）"""
    global _fonts_ready
    if _fonts_ready:
        return
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    names = [n for n in _JP_FONTS if n in available]
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = names + list(matplotlib.rcParams["font.sans-serif"])
    matplotlib.rcParams["axes.unicode_minus"] = False
    _fonts_ready = True


def decimate(xs: Sequence[float], ys: Sequence[float], max_points: int = MAX_PLOT_POINTS):
    """表示点数を max_points 以下に間引く（等間隔に抜き出し、最後の点は必ず残す）"""
    n = len(xs)
    if n <= max_points:
        return list(xs), list(ys)
    step = math.ceil(n / (max_points - 1))
    out_x, out_y = list(xs[::step]), list(ys[::step])
    if (n - 1) % step:
        out_x.append(xs[n - 1])
        out_y.append(ys[n - 1])
    return out_x, out_y


def time_axis(max_elapsed_s: float) -> tuple[float, str]:
    """横軸の単位。60 分未満は分、以上は時間"""
    if max_elapsed_s < 3600:
        return 60.0, "経過時間 [分]"
    return 3600.0, "経過時間 [時間]"


def make_title(base: str | None, model: str, current: float | None, cutoff: float | None) -> str:
    parts = [base or "（未開始）"]
    if model:
        parts.append(f"型番 {model}")
    if current is not None:
        parts.append(f"放電電流 {current:.3f} A")
    if cutoff is not None:
        parts.append(f"終止電圧 {cutoff:.3f} V")
    return "   ".join(parts)


class DischargePlot:
    """2 段のグラフ。画面用（FigureCanvasTkAgg）と PNG 用（Agg）で共通に使う"""

    def __init__(self, figure: Figure):
        setup_fonts()
        self.figure = figure
        self.ax_v, self.ax_i = figure.subplots(2, 1, sharex=True)
        for ax in (self.ax_v, self.ax_i):
            ax.grid(True, color=COLOR_GRID, linewidth=0.8)
            ax.set_axisbelow(True)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            for side in ("left", "bottom"):
                ax.spines[side].set_color(COLOR_TEXT_SUB)
            ax.tick_params(colors=COLOR_TEXT_SUB, labelcolor=COLOR_TEXT_SUB)
        self.ax_v.set_ylabel("電圧 [V]", color=COLOR_TEXT)
        self.ax_i.set_ylabel("電流 [A]", color=COLOR_TEXT)
        (self.line_v,) = self.ax_v.plot([], [], color=COLOR_VOLTAGE, linewidth=1.6)
        (self.line_i,) = self.ax_i.plot([], [], color=COLOR_CURRENT, linewidth=1.6)
        self.cutoff_line = self.ax_v.axhline(float("nan"), color=COLOR_CUTOFF, linewidth=1.2,
                                             linestyle=(0, (6, 4)))
        self.cutoff_label = self.ax_v.text(1.0, 0, "", transform=self.ax_v.get_yaxis_transform(),
                                           ha="right", va="bottom", color=COLOR_TEXT_SUB, fontsize=9)
        self.title = figure.suptitle("", color=COLOR_TEXT, fontsize=11)
        self.ax_i.set_xlabel(time_axis(0)[1], color=COLOR_TEXT)
        figure.subplots_adjust(left=0.08, right=0.98, top=0.92, bottom=0.09, hspace=0.12)
        self.update([], [], [], None)

    def set_title(self, text: str) -> None:
        self.title.set_text(text)

    def update(self, elapsed: Sequence[float], voltage: Sequence[float], current: Sequence[float],
               cutoff: float | None) -> None:
        max_t = elapsed[-1] if len(elapsed) else 0.0
        scale, label = time_axis(max_t)
        xs_v, ys_v = decimate(elapsed, voltage)
        xs_i, ys_i = decimate(elapsed, current)
        self.line_v.set_data([x / scale for x in xs_v], ys_v)
        self.line_i.set_data([x / scale for x in xs_i], ys_i)
        self.ax_i.set_xlabel(label, color=COLOR_TEXT)

        if cutoff is not None:
            self.cutoff_line.set_ydata([cutoff, cutoff])
            self.cutoff_label.set_position((1.0, cutoff))
            self.cutoff_label.set_text(f"終止電圧 {cutoff:.3f} V")
        else:
            self.cutoff_line.set_ydata([float("nan")] * 2)
            self.cutoff_label.set_text("")

        self.ax_v.set_xlim(0, max_t / scale * 1.02 if max_t else 1.0)

        # 縦軸は全期間で自動スケール。電圧は終止電圧の線も入るようにする
        if ys_v:
            lo, hi = min(ys_v), max(ys_v)
        else:
            lo, hi = (cutoff if cutoff is not None else 3.0), 4.2
        if cutoff is not None:
            lo, hi = min(lo, cutoff), max(hi, cutoff)
        pad = max((hi - lo) * 0.08, 0.05)
        self.ax_v.set_ylim(lo - pad, hi + pad)

        if ys_i:
            lo_i, hi_i = min(ys_i), max(ys_i)
        else:
            lo_i, hi_i = 0.0, 1.0
        pad_i = max((hi_i - lo_i) * 0.08, 0.05 * max(abs(hi_i), 0.1))
        self.ax_i.set_ylim(min(0.0, lo_i - pad_i), hi_i + pad_i)


def render_png(path: Path, elapsed: Sequence[float], voltage: Sequence[float], current: Sequence[float],
               cutoff: float | None, title: str) -> None:
    """1600×1000 px の PNG を保存する（画面のグラフとは別の Figure で描く）"""
    fig = Figure(figsize=PNG_SIZE_INCH, dpi=PNG_DPI, facecolor="white")
    FigureCanvasAgg(fig)
    plot = DischargePlot(fig)
    plot.set_title(title)
    plot.update(elapsed, voltage, current, cutoff)
    fig.savefig(str(path), dpi=PNG_DPI, format="png", facecolor="white")

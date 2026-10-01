"""グラフ（上段: 電圧、下段: 電流、横軸: 経過時間）の描画と PNG 保存

画面は液晶スタイル（黒背景、docs/design/DESIGN.md 10.1）、PNG は報告書向けの白背景（10.2）。
pyplot は使わず matplotlib.figure.Figure を直接使う（PNG は画面とは別の Figure で描くので、
測定スレッドから保存しても画面の描画とぶつからない）。横軸のデータの単位は「時間」。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Sequence

import matplotlib
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator, FuncFormatter

from theme import C, MPL_NUM_FAMILIES, MPL_UI_FAMILIES

MAX_PLOT_POINTS = 5000
PNG_SIZE_INCH = (16, 10)  # 100 dpi で 1600×1000 px
PNG_DPI = 100
CUTOFF_DASH = (0, (6, 5))  # 線 6・間隔 5

# 画面のグラフの余白 [px]
LCD_LEFT = 40
LCD_RIGHT = 2
LCD_TOP = 22          # 電圧グラフの上（見出し「電圧 [V]」の分）
LCD_BOTTOM = 20       # 時間軸の目盛り数字の分
LCD_GAP = 28          # 電圧グラフと電流グラフの間（見出し「電流 [A]」の分）
LCD_CURRENT_H = 92    # 電流グラフの高さ

_fonts: dict[str, list[str]] = {}


def setup_fonts() -> None:
    """日本語（BIZ UDPGothic）と数値（Consolas）のフォントを入っているものから選ぶ"""
    if _fonts:
        return
    from matplotlib import font_manager

    available = {f.name for f in font_manager.fontManager.ttflist}
    ui = [n for n in MPL_UI_FAMILIES if n in available] + ["DejaVu Sans"]
    num = [n for n in MPL_NUM_FAMILIES if n in available] + ui
    _fonts["ui"] = ui
    _fonts["num"] = num
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = ui
    matplotlib.rcParams["axes.unicode_minus"] = False


def px_to_pt(px: float, dpi: float) -> float:
    return px * 72.0 / dpi


# ---- 間引き・軸の範囲 ----
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


def time_axis(max_elapsed_s: float) -> tuple[float, float]:
    """横軸の (上限, 目盛り間隔)［時間］。

    上限は max(1 時間, 経過時間 × 1.2) を 30 分単位で切り上げ。目盛りは 30 分ごと、
    6 時間超は 1 時間、12 時間超は 2 時間、24 時間超は 4 時間ごと。
    """
    hours = max(1.0, max_elapsed_s / 3600 * 1.2)
    xmax = math.ceil(hours * 2 - 1e-9) / 2
    if xmax > 24:
        step = 4.0
    elif xmax > 12:
        step = 2.0
    elif xmax > 6:
        step = 1.0
    else:
        step = 0.5
    if step > 0.5:
        xmax = math.ceil(xmax / step - 1e-9) * step  # 最後の目盛りが右端に来るようにする
    return xmax, step


def format_hmm(hours: float) -> str:
    total = int(round(hours * 60))
    return f"{total // 60}:{total % 60:02d}"


def voltage_ylim(cutoff: float | None, voltages: Sequence[float]) -> tuple[float, float]:
    """下限 = min(終止電圧 − 0.2, データ最小 − 0.05)、上限 = max(4.3, データ最大 + 0.05)"""
    c = 3.0 if cutoff is None else cutoff
    lo, hi = c - 0.2, 4.3
    if len(voltages):
        lo = min(lo, min(voltages) - 0.05)
        hi = max(hi, max(voltages) + 0.05)
    return lo, hi


def voltage_axis(cutoff: float | None, voltages: Sequence[float]) -> tuple[float, float, list[float]]:
    """電圧の縦軸の (下限, 上限, 目盛り)。目盛りは両端を含めて等間隔に 6 本。

    voltage_ylim の範囲を 0.1 V 単位で外側に広げ、間隔が 0.1 V の倍数になるようにする
    （既定の 終止 3.000 V なら 2.8〜4.3、目盛り 0.3 V ごと）。
    """
    lo, hi = voltage_ylim(cutoff, voltages)
    lo = math.floor(round(lo * 10, 6)) / 10
    step = max(math.ceil(round((hi - lo) / 5 * 10, 6)) / 10, 0.1)
    return lo, lo + step * 5, [round(lo + step * k, 3) for k in range(6)]


def current_ylim(set_current: float | None, currents: Sequence[float] = ()) -> tuple[float, float]:
    """0 〜 放電電流設定値 × 1.5（設定が無いときはデータの最大から決める）"""
    if set_current:
        return 0.0, set_current * 1.5
    top = max(currents) if len(currents) else 1.0
    return 0.0, max(top, 0.001) * 1.5


def _apply_common(ax_v, ax_i, elapsed, voltage, current, cutoff, set_current, *, suffix_h: bool) -> None:
    max_t = elapsed[-1] if len(elapsed) else 0.0
    xmax, step = time_axis(max_t)
    xs_v, ys_v = decimate(elapsed, voltage)
    xs_i, ys_i = decimate(elapsed, current)
    ax_v._sdl_line.set_data([x / 3600 for x in xs_v], ys_v)
    ax_i._sdl_line.set_data([x / 3600 for x in xs_i], ys_i)

    ticks = [k * step for k in range(int(round(xmax / step)) + 1)]
    ax_i.set_xlim(0, xmax)
    for ax in (ax_v, ax_i):
        ax.xaxis.set_major_locator(FixedLocator(ticks))
    last = ticks[-1]
    ax_i.xaxis.set_major_formatter(FuncFormatter(
        lambda x, _pos: format_hmm(x) + (" h" if suffix_h and abs(x - last) < 1e-9 else "")))

    v_lo, v_hi, v_ticks = voltage_axis(cutoff, voltage)
    ax_v.set_ylim(v_lo, v_hi)
    ax_v.yaxis.set_major_locator(FixedLocator(v_ticks))
    lo, hi = current_ylim(set_current, current)
    ax_i.set_ylim(lo, hi)
    ax_i.yaxis.set_major_locator(FixedLocator([lo + (hi - lo) * k / 3 for k in range(4)]))
    ax_v._sdl_cutoff.set_ydata([cutoff, cutoff] if cutoff is not None else [float("nan")] * 2)


# ---- 画面（液晶スタイル） ----
class LcdPlot:
    """画面の 2 段グラフ。FigureCanvasTkAgg に載せて使う（電流グラフは高さ 92px 固定）"""

    def __init__(self, figure: Figure):
        setup_fonts()
        self.figure = figure
        figure.set_facecolor(C["lcd-bg"])
        self.ax_v = figure.add_axes((0.1, 0.4, 0.85, 0.5))
        self.ax_i = figure.add_axes((0.1, 0.1, 0.85, 0.2), sharex=self.ax_v)
        dpi = figure.dpi
        self._tick_font = {"family": _fonts["num"], "size": px_to_pt(11, dpi)}
        head = px_to_pt(12, dpi)
        for ax in (self.ax_v, self.ax_i):
            ax.set_facecolor(C["lcd-bg"])
            for spine in ax.spines.values():
                spine.set_color(C["lcd-frame"])
                spine.set_linewidth(1.0)
            ax.grid(True, color=C["lcd-grid"], linewidth=0.8)
            ax.set_axisbelow(True)
            ax.tick_params(colors=C["lcd-tick"], length=0, pad=4)
        self.ax_v.tick_params(labelbottom=False)
        self.ax_v.yaxis.set_major_formatter(FuncFormatter(lambda y, _p: f"{y:.1f}"))
        self.ax_i.yaxis.set_major_formatter(FuncFormatter(lambda y, _p: f"{y:.1f}"))
        (self.ax_v._sdl_line,) = self.ax_v.plot([], [], color=C["lcd-value"], linewidth=1.8)
        (self.ax_i._sdl_line,) = self.ax_i.plot([], [], color=C["lcd-accent"], linewidth=1.8)
        self.ax_v._sdl_cutoff = self.ax_v.axhline(float("nan"), color=C["lcd-cutoff"], linewidth=1.2,
                                                  linestyle=CUTOFF_DASH)
        self.ax_v.set_title("電圧 [V]", loc="left", pad=6, color=C["lcd-label"], fontsize=head)
        self.legend = self.ax_v.set_title("", loc="right", pad=6, color=C["lcd-cutoff"], fontsize=head)
        self.ax_i.set_title("電流 [A]", loc="left", pad=6, color=C["lcd-label"], fontsize=head)
        self.layout()
        self.update([], [], [], None, None)

    def layout(self) -> None:
        """余白・電流グラフの高さを px で固定し、電圧グラフを残りに伸ばす"""
        w, h = self.figure.get_size_inches() * self.figure.dpi
        w, h = max(w, 200), max(h, 200)
        left, right = LCD_LEFT / w, 1 - LCD_RIGHT / w
        v_bottom = (LCD_BOTTOM + LCD_CURRENT_H + LCD_GAP) / h
        self.ax_i.set_position((left, LCD_BOTTOM / h, right - left, LCD_CURRENT_H / h))
        self.ax_v.set_position((left, v_bottom, right - left, max(1 - LCD_TOP / h - v_bottom, 0.05)))

    def update(self, elapsed: Sequence[float], voltage: Sequence[float], current: Sequence[float],
               cutoff: float | None, set_current: float | None) -> None:
        _apply_common(self.ax_v, self.ax_i, elapsed, voltage, current, cutoff, set_current, suffix_h=True)
        self.legend.set_text(f"- - 終止電圧 {cutoff:.3f} V" if cutoff is not None else "")
        # 目盛り数字は Consolas。横軸の最初は左揃え・最後は右揃え（液晶の枠からはみ出さないように）
        for ax in (self.ax_v, self.ax_i):
            for tick in ax.xaxis.get_major_ticks() + ax.yaxis.get_major_ticks():
                tick.label1.set_fontproperties(self._tick_font)
        ticks = self.ax_i.xaxis.get_major_ticks()
        for k, tick in enumerate(ticks):
            tick.label1.set_horizontalalignment("left" if k == 0 else "right" if k == len(ticks) - 1 else "center")


# ---- PNG（白背景スタイル） ----
def png_title_lines(base: str | None, model: str, current: float | None, cutoff: float | None,
                    mah: float | None = None, wh: float | None = None, reason: str | None = None) -> list[str]:
    """1 行目: ベース名、2 行目: 型番・放電電流・終止電圧（未入力は省く）、3 行目: 完了後の結果"""
    lines = [base or "（未開始）"]
    second = []
    if model:
        second.append(f"型番: {model}")
    if current is not None:
        second.append(f"放電電流: {current:.3f} A")
    if cutoff is not None:
        second.append(f"終止電圧: {cutoff:.3f} V")
    if second:
        lines.append(" / ".join(second))
    if reason is not None and mah is not None and wh is not None:
        lines.append(f"放電容量: {mah:.1f} mAh / 電力量: {wh:.3f} Wh / 終了理由: {reason}")
    return lines


def render_png(path: Path, elapsed: Sequence[float], voltage: Sequence[float], current: Sequence[float],
               cutoff: float | None, set_current: float | None, title_lines: list[str]) -> None:
    """1600×1000 px の白背景 PNG を保存する（画面のグラフとは別の Figure で描く）"""
    setup_fonts()
    fig = Figure(figsize=PNG_SIZE_INCH, dpi=PNG_DPI, facecolor=C["png-bg"])
    FigureCanvasAgg(fig)
    gs = fig.add_gridspec(2, 1, height_ratios=[2, 1], hspace=0.08)
    ax_v = fig.add_subplot(gs[0])
    ax_i = fig.add_subplot(gs[1], sharex=ax_v)
    for ax in (ax_v, ax_i):
        ax.set_facecolor(C["png-bg"])
        ax.grid(True, color=C["png-grid"], linewidth=1.0)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(C["png-text"])
        ax.tick_params(colors=C["png-text"], labelsize=11)
    ax_v.tick_params(labelbottom=False)
    (ax_v._sdl_line,) = ax_v.plot([], [], color=C["png-voltage"], linewidth=2.0)
    (ax_i._sdl_line,) = ax_i.plot([], [], color=C["png-current"], linewidth=2.0)
    ax_v._sdl_cutoff = ax_v.axhline(float("nan"), color=C["png-cutoff"], linewidth=1.5, linestyle=CUTOFF_DASH)
    ax_i.yaxis.set_major_formatter(FuncFormatter(lambda y, _p: f"{y:.2f}"))
    _apply_common(ax_v, ax_i, elapsed, voltage, current, cutoff, set_current, suffix_h=False)
    if cutoff is not None:
        ax_v.text(1.0, cutoff, f"終止電圧 {cutoff:.3f} V", transform=ax_v.get_yaxis_transform(),
                  ha="right", va="bottom", color=C["png-cutoff"], fontsize=11,
                  bbox={"facecolor": C["png-bg"], "edgecolor": "none", "pad": 2})
    ax_v.set_ylabel("電圧 [V]", color=C["png-text"], fontsize=13)
    ax_i.set_ylabel("電流 [A]", color=C["png-text"], fontsize=13)
    ax_i.set_xlabel("経過時間 [h:mm]", color=C["png-text"], fontsize=13)
    n = len(title_lines)
    fig.suptitle("\n".join(title_lines), color=C["png-text"], fontsize=15, linespacing=1.5, y=0.985, va="top")
    fig.subplots_adjust(left=0.07, right=0.97, bottom=0.08, top=0.92 - 0.035 * (n - 1))
    fig.savefig(str(path), dpi=PNG_DPI, format="png", facecolor=C["png-bg"])

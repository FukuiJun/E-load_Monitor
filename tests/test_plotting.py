"""グラフ（F-07、F-08、AC-11）"""

import struct
import time

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

import plotting


def test_decimate_keeps_last_point_and_limit():
    xs = list(range(86400))
    dx, dy = plotting.decimate(xs, xs)
    assert len(dx) <= plotting.MAX_PLOT_POINTS
    assert dx[0] == 0 and dx[-1] == 86399
    small = list(range(100))
    assert plotting.decimate(small, small) == (small, small)


def test_time_axis_units():
    assert plotting.time_axis(3599) == (60.0, "経過時間 [分]")
    assert plotting.time_axis(3600) == (3600.0, "経過時間 [時間]")


def test_graph_update_86400_points_within_half_second():
    """AC-11：86,400 点でもグラフ更新（描画込み）が 0.5 秒以内"""
    fig = Figure(figsize=(9, 6), dpi=96)
    canvas = FigureCanvasAgg(fig)
    plot = plotting.DischargePlot(fig)
    n = 86400
    t = [float(k) for k in range(n)]
    v = [4.2 - 1.2 * k / n for k in range(n)]
    i = [1.0] * n
    plot.update(t[:10], v[:10], i[:10], 3.0)
    canvas.draw()  # 初回の描画（フォント読み込み等）は除く
    worst = 0.0
    for _ in range(3):
        start = time.perf_counter()
        plot.update(t, v, i, 3.0)
        canvas.draw()
        worst = max(worst, time.perf_counter() - start)
    assert worst < 0.5, f"{worst:.3f} 秒"
    assert len(plot.line_v.get_xdata()) <= plotting.MAX_PLOT_POINTS
    assert plot.ax_i.get_xlabel() == "経過時間 [時間]"


def test_cutoff_line_drawn():
    fig = Figure()
    plot = plotting.DischargePlot(fig)
    plot.update([0, 1], [4.0, 3.9], [1, 1], 3.0)
    assert list(plot.cutoff_line.get_ydata()) == [3.0, 3.0]
    assert plot.cutoff_line.get_linestyle() == "--"
    lo, hi = plot.ax_v.get_ylim()
    assert lo < 3.0 < hi


def test_render_png_size_and_title(tmp_path):
    """5.2：PNG は 1600×1000 px。F-08：タイトルにベース名・型番"""
    path = tmp_path / "g.png"
    title = plotting.make_title("20261001_143005_4.1V_pana", "NCR18650B", 1.0, 3.0)
    assert "20261001_143005_4.1V_pana" in title and "NCR18650B" in title
    assert "1.000 A" in title and "3.000 V" in title
    plotting.render_png(path, [0, 60, 120], [4.1, 4.0, 3.9], [1, 1, 1], 3.0, title)
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = struct.unpack(">II", head[16:24])
    assert (w, h) == (1600, 1000)

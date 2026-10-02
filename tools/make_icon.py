"""アプリのアイコンを作る（デザイン案B「液晶カーブ」）

    python tools/make_icon.py

assets/icon.svg と同じ形（512×512 の座標）を Pillow で描き、次を作り直す:
    assets/app.ico         exe とウィンドウのアイコン（16〜256 px を 1 ファイルに）
    assets/icon_<n>.png    ウィンドウのアイコン用（16 / 32 / 48 / 256 px）

形や色を変えるときは assets/icon.svg とこのファイルの両方を直す。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
BASE = 512            # デザインの座標の大きさ
SUPER = 2048          # この大きさで描いてから縮小する（線をなめらかにするため）
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
PNG_SIZES = [16, 32, 48, 256]

COLORS = {
    "frame": "#9aa1a8",      # 外周の細い枠
    "chassis": "#e3e6e9",    # 筐体
    "bezel": "#2a2d30",      # 液晶の枠
    "lcd": "#050505",        # 液晶
    "cutoff": "#e8892b",     # 終止電圧の破線
    "voltage": "#ffe14a",    # 電圧カーブ
    "current": "#5fb4ff",    # 電流の直線
    "key": "#b9bec3",        # ボタン
    "key_edge": "#9aa1a8",
    "plus": "#d23a2f",       # 赤の端子
    "minus": "#1d1f21",      # 黒の端子
    "ring": "#f4f5f6",       # 端子の白い縁
}


def cubic(p0, p1, p2, p3, n=48):
    pts = []
    for k in range(n + 1):
        t = k / n
        u = 1 - t
        pts.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                    u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return pts


def draw_master(size: int = SUPER) -> Image.Image:
    s = size / BASE
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def box(x0, y0, x1, y1):
        return (x0 * s, y0 * s, x1 * s - 1, y1 * s - 1)

    def rrect(x0, y0, x1, y1, r, fill, outline=None, width=0):
        d.rounded_rectangle(box(x0, y0, x1, y1), radius=r * s, fill=fill, outline=outline,
                            width=round(width * s))

    def round_line(points, color, width):
        pts = [(x * s, y * s) for x, y in points]
        w = width * s
        d.line(pts, fill=color, width=round(w), joint="curve")
        for x, y in (pts[0], pts[-1]):  # 線の端を丸く
            d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=color)

    def circle(cx, cy, r, fill, ring, ring_w):
        # SVG の stroke は輪郭の中心に描かれるので、外側に stroke の半分だけ広げる
        R = r + ring_w / 2
        d.ellipse(((cx - R) * s, (cy - R) * s, (cx + R) * s, (cy + R) * s), fill=fill, outline=ring,
                  width=round(ring_w * s))

    c = COLORS
    rrect(24, 24, 488, 488, 40, c["frame"])
    rrect(40, 40, 472, 472, 26, c["chassis"])
    rrect(84, 96, 428, 360, 10, c["bezel"])
    rrect(104, 116, 408, 340, 4, c["lcd"])
    # 終止電圧の破線（線 26・間隔 16）
    x = 120
    while x < 392:
        d.line([(x * s, 266 * s), (min(x + 26, 392) * s, 266 * s)], fill=c["cutoff"], width=round(10 * s))
        x += 26 + 16
    # 電圧カーブ M124 146 C190 160, 262 180, 312 196 S 372 224, 392 282
    curve = cubic((124, 146), (190, 160), (262, 180), (312, 196)) + \
        cubic((312, 196), (362, 212), (372, 224), (392, 282))[1:]
    round_line(curve, c["voltage"], 18)
    round_line([(124, 314), (392, 314)], c["current"], 14)
    for x0 in (106, 150, 194):
        rrect(x0, 398, x0 + 34, 424, 6, c["key"], c["key_edge"], 3)
    circle(325, 411, 28, c["plus"], c["ring"], 6)
    circle(397, 411, 28, c["minus"], c["ring"], 6)
    return img


def render(size: int, master: Image.Image | None = None) -> Image.Image:
    master = master or draw_master()
    return master.resize((size, size), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(exist_ok=True)
    master = draw_master()
    images = {n: render(n, master) for n in ICO_SIZES}
    largest = images[ICO_SIZES[-1]]
    largest.save(ASSETS / "app.ico", format="ICO", sizes=[(n, n) for n in ICO_SIZES],
                 append_images=[images[n] for n in ICO_SIZES[:-1]])
    for n in PNG_SIZES:
        images[n].save(ASSETS / f"icon_{n}.png")
    print(f"作成しました: {ASSETS / 'app.ico'}（{', '.join(map(str, ICO_SIZES))} px）")


if __name__ == "__main__":
    main()

"""積算（放電容量・電力量）、ファイル名、一時ファイル・最終 CSV の作成"""

from __future__ import annotations

import csv
import io
import os
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# 画面の選択肢 → ファイル名に使う略称
MAKERS = ["Panasonic", "マクセル"]
MAKER_ABBR = {"Panasonic": "pana", "マクセル": "maxell"}
FULL_VOLTAGES = ["4.1V", "4.2V"]

CSV_ENCODING = "utf-8-sig"  # UTF-8 BOM 付き（Excel で文字化けしない）
CSV_NEWLINE = "\r\n"
COLUMNS = ["日時", "経過時間[s]", "電圧[V]", "電流[A]", "電力[W]", "放電容量[mAh]", "電力量[Wh]"]
PARTIAL_SUFFIX = ".partial.csv"
# 放電開始前に確保されている必要がある空き容量（24 時間分の CSV が約 7MB）
MIN_FREE_BYTES = 20 * 1024 * 1024

END_REASON_CUTOFF = "終止電圧到達"
END_REASON_MANUAL = "手動停止"
END_REASON_COMM_LOST = "通信断"
END_REASON_WRITE_ERROR = "保存先書き込みエラー"
END_REASON_ERROR = "異常終了"


# ---- ファイル名 ----
def make_base_name(start: datetime, full_voltage: str | None = None, maker: str | None = None) -> str:
    """<YYYYMMDD_HHMMSS>[_<満充電電圧>][_<メーカー略称>]（未選択の部分は _ ごと省く）"""
    parts = [start.strftime("%Y%m%d_%H%M%S")]
    if full_voltage:
        parts.append(full_voltage)
    if maker:
        parts.append(MAKER_ABBR[maker])
    return "_".join(parts)


def output_paths(folder: Path, base: str) -> dict[str, Path]:
    return {"csv": folder / f"{base}.csv", "png": folder / f"{base}.png",
            "partial": folder / f"{base}{PARTIAL_SUFFIX}"}


def unique_base_name(folder: Path, base: str) -> str:
    """CSV・PNG・一時ファイルのどれかが既にあれば末尾に _2, _3 … を付ける"""
    candidate, n = base, 1
    while any(p.exists() for p in output_paths(folder, candidate).values()):
        n += 1
        candidate = f"{base}_{n}"
    return candidate


def find_partial_files(folder: Path) -> list[Path]:
    try:
        return sorted(Path(folder).glob(f"*{PARTIAL_SUFFIX}"))
    except OSError:
        return []


def check_writable(folder: Path) -> None:
    """保存先に書き込めるか・空き容量があるかを確かめる。だめなら OSError（メッセージ付き）"""
    folder = Path(folder)
    if not folder.is_dir():
        raise OSError(f"保存先フォルダがありません: {folder}")
    test = folder / f".sdl_logger_write_test_{os.getpid()}.tmp"
    try:
        with open(test, "wb") as fp:
            fp.write(b"test")
    except OSError as e:
        raise OSError(f"保存先に書き込めません: {folder}（{e.strerror or e}）") from e
    finally:
        try:
            test.unlink()
        except OSError:
            pass
    if shutil.disk_usage(folder).free < MIN_FREE_BYTES:
        raise OSError(f"保存先の空き容量が不足しています: {folder}")


# ---- 積算 ----
class Integrator:
    """電流・電力の台形積分（mAh・Wh）"""

    def __init__(self) -> None:
        self.mah = 0.0
        self.wh = 0.0
        self._last: tuple[float, float, float] | None = None

    def add(self, elapsed: float, current: float, power: float) -> tuple[float, float]:
        if self._last is not None:
            t0, i0, p0 = self._last
            dt = elapsed - t0
            if dt > 0:
                self.mah += (i0 + current) / 2 * dt / 3.6
                self.wh += (p0 + power) / 2 * dt / 3600
        self._last = (elapsed, current, power)
        return self.mah, self.wh


# ---- 測定行 ----
@dataclass(frozen=True)
class Sample:
    timestamp: datetime
    elapsed: float
    voltage: float
    current: float
    power: float
    mah: float
    wh: float
    voltage_text: str = ""
    current_text: str = ""
    power_text: str = ""

    def row(self) -> list[str]:
        return [
            format_datetime_ms(self.timestamp),
            f"{self.elapsed:.3f}",
            self.voltage_text or f"{self.voltage:.5f}",
            self.current_text or f"{self.current:.4f}",
            self.power_text or f"{self.power:.4f}",
            f"{self.mah:.3f}",
            f"{self.wh:.4f}",
        ]


def format_datetime(dt: datetime) -> str:
    return dt.strftime("%Y/%m/%d %H:%M:%S")


def format_datetime_ms(dt: datetime) -> str:
    return dt.strftime("%Y/%m/%d %H:%M:%S.") + f"{dt.microsecond // 1000:03d}"


def _csv_line(values: list[str]) -> str:
    buf = io.StringIO()
    csv.writer(buf, lineterminator=CSV_NEWLINE).writerow(values)
    return buf.getvalue()


class PartialWriter:
    """一時ファイル（<ベース名>.partial.csv）に測定行を 1 行ずつ追記する（毎行 flush）"""

    def __init__(self, path: Path):
        self.path = Path(path)
        # 新規作成のみ（既存ファイルは上書きしない）
        self._fp = open(self.path, "x", encoding=CSV_ENCODING, newline="")
        self._write(_csv_line(COLUMNS))

    def _write(self, text: str) -> None:
        self._fp.write(text)
        self._fp.flush()
        try:
            os.fsync(self._fp.fileno())
        except OSError:
            pass

    def append(self, sample: Sample) -> None:
        self._write(_csv_line(sample.row()))

    def close(self) -> None:
        if not self._fp.closed:
            try:
                self._fp.close()
            except OSError:
                pass

    @property
    def closed(self) -> bool:
        return self._fp.closed


# ---- 最終 CSV ----
@dataclass
class TestInfo:
    __test__ = False  # pytest にテストクラスと見なされないように

    start: datetime
    end: datetime
    end_reason: str
    maker: str | None
    full_voltage: str | None  # "4.1V" など
    model: str
    current: float
    cutoff: float
    mah: float
    wh: float
    interval: float
    idn: str
    note: str


def format_interval(value: float) -> str:
    """1.0 → '1.0'、0.25 → '0.25'（小数 1 桁以上・余分な 0 なし）"""
    text = f"{value:.3f}".rstrip("0")
    return text + "0" if text.endswith(".") else text


def info_lines(info: TestInfo) -> str:
    full = info.full_voltage[:-1] if info.full_voltage and info.full_voltage.endswith("V") else (info.full_voltage or "")
    rows = [
        ["試験情報"],
        ["開始日時", format_datetime(info.start)],
        ["終了日時", format_datetime(info.end)],
        ["終了理由", info.end_reason],
        ["メーカー", info.maker or ""],
        ["満充電電圧[V]", full],
        ["型番", info.model or ""],
        ["放電電流[A]", f"{info.current:.3f}"],
        ["終止電圧[V]", f"{info.cutoff:.3f}"],
        ["放電容量[mAh]", f"{info.mah:.1f}"],
        ["電力量[Wh]", f"{info.wh:.3f}"],
        ["取得周期[s]", format_interval(info.interval)],
        ["機器", info.idn],
    ]
    text = "".join(_csv_line(r) for r in rows)
    # 備考は改行・カンマを含んでよい。常にダブルクォートで囲む（中の " は "" にする）
    text += '備考,"' + (info.note or "").replace('"', '""') + '"' + CSV_NEWLINE
    return text


def write_final_csv(path: Path, info: TestInfo, partial_path: Path) -> None:
    """試験情報ブロック＋空行＋一時ファイルの内容（列見出し＋測定行）で最終 CSV を作る。

    同名のファイルがあれば上書きせずに FileExistsError。途中で失敗したら作りかけの CSV は消す。
    """
    with open(partial_path, "r", encoding=CSV_ENCODING, newline="") as fp:
        measured = fp.read()
    path = Path(path)
    try:
        with open(path, "x", encoding=CSV_ENCODING, newline="") as fp:
            fp.write(info_lines(info))
            fp.write(CSV_NEWLINE)
            fp.write(measured)
            fp.flush()
            os.fsync(fp.fileno())
    except FileExistsError:
        raise
    except OSError:
        try:
            path.unlink()
        except OSError:
            pass
        raise

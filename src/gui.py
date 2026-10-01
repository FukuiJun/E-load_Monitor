"""画面（tkinter + matplotlib）

通信はすべて別スレッドで行い、結果は ui_queue / session.events 経由で画面スレッドが受け取る
（応答待ちで画面が固まらないようにするため）。
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

import plotting
import recorder
import settings as settings_mod
from sdl_client import CONNECT_ERROR_MESSAGE, SDLClient, SDLError
from session import Conditions, DischargeSession, StartError

log = logging.getLogger("sdl.gui")

APP_TITLE = "SDL放電ロガー"
MODEL_MAX_LEN = 40
POLL_MS = 100
GRAPH_MS = 500
IDLE_VOLTAGE_INTERVAL = 1.0
DISCARD_BG = "#c62828"
DISCARD_BG_ACTIVE = "#b71c1c"
DISCARD_BG_DISABLED = "#e6a9a6"

# 画面の状態
DISCONNECTED = "disconnected"
CONNECTING = "connecting"
IDLE = "idle"            # 接続中・放電していない
STARTING = "starting"
DISCHARGING = "discharging"
STOPPING = "stopping"

DISCARD_CONFIRM = "データを保存せずに停止します。よろしいですか？"
CLOSE_QUESTION = "放電中です。停止・保存して終了しますか？"


def format_elapsed(seconds: float) -> str:
    s = int(max(seconds, 0))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class InputError(Exception):
    pass


def parse_number(text: str, name: str, lo: float, hi: float, unit: str, digits: int) -> float:
    try:
        value = float(text.strip())
    except ValueError:
        value = None
    if value is None or not (lo <= value <= hi):
        raise InputError(f"{name}は {lo:.{digits}f}〜{hi:.{digits}f} {unit} の範囲で入力してください")
    return value


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.settings = settings_mod.load()
        self.state = DISCONNECTED
        self.client: SDLClient | None = None
        self.session: DischargeSession | None = None
        self.ui_queue: queue.Queue = queue.Queue()
        self._monitor_stop: threading.Event | None = None
        self._closing_after_stop = False
        self._graph_key = None

        root.title(APP_TITLE)
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.minsize(min(1280, sw), min(800, max(sh - 80, 400)))
        root.geometry(f"{min(1280, sw)}x{min(800, max(sh - 80, 400))}")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.report_callback_exception = self._on_tk_error

        self._build()
        self._apply_state()
        root.after(POLL_MS, self._poll)
        root.after(GRAPH_MS, self._graph_tick)
        root.after_idle(self._after_shown)

    # ------------------------------------------------------------------ 画面の組み立て
    def _build(self) -> None:
        root = self.root
        style = ttk.Style(root)
        style.configure("Value.TLabel", font=("Yu Gothic UI", 16, "bold"))
        style.configure("Unit.TLabel", font=("Yu Gothic UI", 10))
        root.columnconfigure(0, weight=1)
        root.rowconfigure(1, weight=1)

        # 上段：接続
        top = ttk.Frame(root, padding=(8, 6))
        top.grid(row=0, column=0, sticky="ew")
        self.connect_btn = ttk.Button(top, text="接続", width=8, command=self.on_connect)
        self.connect_btn.pack(side="left")
        ttk.Label(top, text="IP:").pack(side="left", padx=(12, 2))
        self.host_var = tk.StringVar(value=self.settings.host)
        self.host_entry = ttk.Entry(top, textvariable=self.host_var, width=16)
        self.host_entry.pack(side="left")
        ttk.Label(top, text="Port:").pack(side="left", padx=(10, 2))
        self.port_var = tk.StringVar(value=str(self.settings.port))
        self.port_entry = ttk.Entry(top, textvariable=self.port_var, width=7)
        self.port_entry.pack(side="left")
        ttk.Label(top, text="状態:").pack(side="left", padx=(16, 2))
        self.status_var = tk.StringVar(value="未接続")
        ttk.Label(top, textvariable=self.status_var).pack(side="left", fill="x", expand=True)

        middle = ttk.Frame(root, padding=(8, 0))
        middle.grid(row=1, column=0, sticky="nsew")
        middle.columnconfigure(1, weight=1)
        middle.rowconfigure(0, weight=1)
        self._build_conditions(middle)
        self._build_graph(middle)

        # 下段：ボタン・メッセージ
        bottom = ttk.Frame(root, padding=(8, 6))
        bottom.grid(row=2, column=0, sticky="ew")
        bottom.columnconfigure(4, weight=1)
        self.start_btn = ttk.Button(bottom, text="放電開始", width=12, command=self.on_start)
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.stop_save_btn = ttk.Button(bottom, text="停止・保存", width=12, command=self.on_stop_save)
        self.stop_save_btn.grid(row=0, column=1, padx=6)
        # 誤操作防止のため停止・破棄だけ赤系にする
        self.stop_discard_btn = tk.Button(bottom, text="停止・破棄", width=12, command=self.on_stop_discard,
                                          bg=DISCARD_BG, fg="white", activebackground=DISCARD_BG_ACTIVE,
                                          activeforeground="white", disabledforeground="#fdf3f2",
                                          relief="raised")
        self.stop_discard_btn.grid(row=0, column=2, padx=6)
        self.graph_btn = ttk.Button(bottom, text="グラフ保存", width=12, command=self.on_save_graph)
        self.graph_btn.grid(row=0, column=3, padx=6)
        # メッセージ欄（高さ固定・読み取り専用。保存したファイルのパスをコピーできるよう Text にする）
        self.message_var = tk.StringVar(value="")
        self.message_text = tk.Text(bottom, height=3, wrap="char", relief="flat", borderwidth=0,
                                    background=style.lookup("TFrame", "background") or "SystemButtonFace",
                                    highlightthickness=0, state="disabled", cursor="arrow")
        self.message_text.grid(row=0, column=4, sticky="ew", padx=(12, 0))

    def _build_conditions(self, parent) -> None:
        box = ttk.LabelFrame(parent, text="試験条件", padding=8)
        box.grid(row=0, column=0, sticky="nsw", padx=(0, 8), pady=(0, 4))
        box.columnconfigure(1, weight=1)
        r = 0

        self.maker_var = tk.StringVar(value="")
        self.full_var = tk.StringVar(value="")
        self.radios: list[ttk.Radiobutton] = []
        for label, var, options in (("メーカー", self.maker_var, recorder.MAKERS),
                                    ("満充電電圧", self.full_var, recorder.FULL_VOLTAGES)):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="nw", pady=(2, 6))
            f = ttk.Frame(box)
            f.grid(row=r, column=1, sticky="w", pady=(0, 6))
            for k, (text, value) in enumerate([("未選択", "")] + [(o, o) for o in options]):
                rb = ttk.Radiobutton(f, text=text, value=value, variable=var)
                rb.grid(row=0, column=k, sticky="w", padx=(0, 10))
                self.radios.append(rb)
            r += 1

        ttk.Label(box, text="型番").grid(row=r, column=0, sticky="w", pady=3)
        self.model_var = tk.StringVar(value="")
        # 最大 40 文字（貼り付けで超えたときは 40 文字で切る）
        self.model_var.trace_add("write", lambda *_: len(self.model_var.get()) > MODEL_MAX_LEN
                                 and self.model_var.set(self.model_var.get()[:MODEL_MAX_LEN]))
        self.model_entry = ttk.Entry(box, textvariable=self.model_var, width=28)
        self.model_entry.grid(row=r, column=1, sticky="ew", pady=3)
        r += 1

        self.current_var = tk.StringVar(value=f"{self.settings.current:.3f}")
        self.cutoff_var = tk.StringVar(value=f"{self.settings.cutoff:.3f}")
        self.interval_var = tk.StringVar(value=recorder.format_interval(self.settings.interval))
        self.number_entries = []
        for label, var in (("放電電流[A]", self.current_var), ("終止電圧[V]", self.cutoff_var),
                           ("取得周期[s]", self.interval_var)):
            ttk.Label(box, text=label).grid(row=r, column=0, sticky="w", pady=3)
            e = ttk.Entry(box, textvariable=var, width=10, justify="right")
            e.grid(row=r, column=1, sticky="w", pady=3)
            self.number_entries.append(e)
            r += 1

        ttk.Label(box, text="保存先").grid(row=r, column=0, sticky="w", pady=3)
        ff = ttk.Frame(box)
        ff.grid(row=r, column=1, sticky="ew", pady=3)
        ff.columnconfigure(0, weight=1)
        self.folder_var = tk.StringVar(value=self.settings.folder)
        ttk.Entry(ff, textvariable=self.folder_var, state="readonly", width=24).grid(row=0, column=0, sticky="ew")
        self.folder_btn = ttk.Button(ff, text="参照", width=6, command=self.on_browse)
        self.folder_btn.grid(row=0, column=1, padx=(4, 0))
        r += 1

        ttk.Label(box, text="備考（放電中も編集可）").grid(row=r, column=0, columnspan=2, sticky="w", pady=(8, 2))
        r += 1
        nf = ttk.Frame(box)
        nf.grid(row=r, column=0, columnspan=2, sticky="nsew")
        box.rowconfigure(r, weight=1)
        nf.columnconfigure(0, weight=1)
        nf.rowconfigure(0, weight=1)
        self.note_text = tk.Text(nf, width=36, height=8, wrap="char", undo=True)
        self.note_text.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(nf, orient="vertical", command=self.note_text.yview)
        sb.grid(row=0, column=1, sticky="ns")
        self.note_text.configure(yscrollcommand=sb.set)
        self.note_text.bind("<<Modified>>", self._on_note_modified)

    def _build_graph(self, parent) -> None:
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew", pady=(0, 4))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        self.figure = Figure(figsize=(9, 6), dpi=96, facecolor="white")
        self.canvas = FigureCanvasTkAgg(self.figure, master=right)
        self.plot = plotting.DischargePlot(self.figure)
        self.figure.subplots_adjust(left=0.09, right=0.98, top=0.93, bottom=0.10, hspace=0.12)
        self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

        values = ttk.Frame(right, padding=(4, 6))
        values.grid(row=1, column=0, sticky="ew")
        self.value_vars = {}
        for k, (key, label) in enumerate((("v", "電圧"), ("i", "電流"), ("p", "電力"), ("mah", "放電容量"),
                                          ("wh", "電力量"), ("elapsed", "経過"))):
            cell = ttk.Frame(values)
            cell.grid(row=0, column=k, sticky="w", padx=(0, 22))
            ttk.Label(cell, text=label, style="Unit.TLabel").pack(anchor="w")
            var = tk.StringVar(value="—")
            ttk.Label(cell, textvariable=var, style="Value.TLabel").pack(anchor="w")
            self.value_vars[key] = var

    # ------------------------------------------------------------------ 状態とボタン
    def _set_state(self, state: str) -> None:
        self.state = state
        self._apply_state()

    def _apply_state(self) -> None:
        s = self.state
        busy = s in (STARTING, DISCHARGING, STOPPING)
        edit = "disabled" if busy else "normal"
        for rb in self.radios:
            rb.configure(state=edit)
        self.model_entry.configure(state=edit)
        for e in self.number_entries:
            e.configure(state=edit)
        self.folder_btn.configure(state=edit)
        conn_edit = "normal" if s == DISCONNECTED else "disabled"
        self.host_entry.configure(state=conn_edit)
        self.port_entry.configure(state=conn_edit)
        self.connect_btn.configure(text="切断" if s in (IDLE, STARTING, DISCHARGING, STOPPING) else "接続",
                                   state="normal" if s in (DISCONNECTED, IDLE) else "disabled")
        self.start_btn.configure(state="normal" if s == IDLE else "disabled")
        stop = "normal" if s == DISCHARGING else "disabled"
        self.stop_save_btn.configure(state=stop)
        # 無効のときは淡い色にして、押せないことが分かるようにする
        self.stop_discard_btn.configure(state=stop, bg=DISCARD_BG if stop == "normal" else DISCARD_BG_DISABLED)

    def message(self, text: str) -> None:
        self.message_var.set(text)
        self.message_text.configure(state="normal")
        self.message_text.delete("1.0", "end")
        self.message_text.insert("1.0", text)
        self.message_text.configure(state="disabled")

    # ------------------------------------------------------------------ 接続
    def on_connect(self) -> None:
        if self.state == IDLE:
            self.disconnect()
            return
        if self.state != DISCONNECTED:
            return
        host = self.host_var.get().strip()
        try:
            port = int(self.port_var.get().strip())
            if not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror(APP_TITLE, "ポートは 1〜65535 の整数で入力してください")
            return
        if not host:
            messagebox.showerror(APP_TITLE, "IP アドレスを入力してください")
            return
        client = SDLClient(host, port)
        self._set_state(CONNECTING)
        self.status_var.set("接続しています…")
        self.message("")
        self._run_bg(client.connect, lambda idn: self._on_connected(client, idn), self._on_connect_failed)

    def _on_connected(self, client: SDLClient, idn: str) -> None:
        self.client = client
        self.settings.host, self.settings.port = client.host, client.port
        self.status_var.set(f"接続中  {idn}")
        self.message("接続しました")
        self._set_state(IDLE)
        self._start_monitor()

    def _on_connect_failed(self, exc: BaseException) -> None:
        self._set_state(DISCONNECTED)
        self.status_var.set("未接続")
        text = str(exc) if isinstance(exc, SDLError) else CONNECT_ERROR_MESSAGE
        self.message(text)
        messagebox.showerror(APP_TITLE, text)

    def disconnect(self) -> None:
        self._stop_monitor()
        client, self.client = self.client, None
        if client is not None:
            threading.Thread(target=client.close, daemon=True).start()
        self._set_state(DISCONNECTED)
        self.status_var.set("未接続")
        self.value_vars["v"].set("—")
        self.message("切断しました")

    # 放電前の電圧表示（1 秒周期）
    def _start_monitor(self) -> None:
        self._stop_monitor()
        stop = threading.Event()
        self._monitor_stop = stop
        threading.Thread(target=self._monitor_loop, args=(self.client, stop), name="idle-monitor",
                         daemon=True).start()

    def _stop_monitor(self) -> None:
        if self._monitor_stop is not None:
            self._monitor_stop.set()
            self._monitor_stop = None

    def _monitor_loop(self, client: SDLClient, stop: threading.Event) -> None:
        while not stop.is_set():
            with client._lock:  # 停止の判定と通信を一体にする（放電開始と入れ違いにならないように）
                if stop.is_set():
                    break
                try:
                    if not client.connected:
                        client.reconnect()
                    v = client.measure_voltage()
                    self.ui_queue.put((self._on_idle_voltage, (stop, v)))
                except SDLError as e:
                    self.ui_queue.put((self._on_idle_error, (stop, str(e))))
            stop.wait(IDLE_VOLTAGE_INTERVAL)

    def _on_idle_voltage(self, stop, v: float) -> None:
        if stop is not self._monitor_stop or self.state != IDLE:
            return
        self.value_vars["v"].set(f"{v:.3f} V")
        if self.client is not None:
            self.status_var.set(f"接続中  {self.client.idn}")

    def _on_idle_error(self, stop, text: str) -> None:
        if stop is not self._monitor_stop or self.state != IDLE:
            return
        self.value_vars["v"].set("—")
        self.status_var.set("応答がありません（再接続を試みています）")

    # ------------------------------------------------------------------ 放電
    def read_conditions(self) -> Conditions:
        current = parse_number(self.current_var.get(), "放電電流", *settings_mod.CURRENT_RANGE, "A", 3)
        cutoff = parse_number(self.cutoff_var.get(), "終止電圧", *settings_mod.CUTOFF_RANGE, "V", 3)
        interval = parse_number(self.interval_var.get(), "取得周期", *settings_mod.INTERVAL_RANGE, "秒", 1)
        return Conditions(maker=self.maker_var.get() or None, full_voltage=self.full_var.get() or None,
                          model=self.model_var.get().strip(), current=current, cutoff=cutoff, interval=interval)

    def note(self) -> str:
        return self.note_text.get("1.0", "end-1c")

    def on_start(self) -> None:
        if self.state != IDLE or self.client is None:
            return
        try:
            cond = self.read_conditions()
        except InputError as e:
            messagebox.showerror(APP_TITLE, str(e))
            return
        folder = Path(self.folder_var.get())
        self.current_var.set(f"{cond.current:.3f}")
        self.cutoff_var.set(f"{cond.cutoff:.3f}")
        self.interval_var.set(recorder.format_interval(cond.interval))
        self._remember_settings()
        settings_mod.save(self.settings)

        self._stop_monitor()
        session = DischargeSession(self.client, folder, cond, note=self.note())
        self._set_state(STARTING)
        self.message("放電を開始しています…")
        self._run_bg(session.start, lambda _r: self._on_started(session), self._on_start_failed)

    def _on_started(self, session: DischargeSession) -> None:
        self.session = session
        session.note = self.note()
        self._graph_key = None
        self._set_state(DISCHARGING)
        self.message(f"放電中: {session.base_name}")

    def _on_start_failed(self, exc: BaseException) -> None:
        self._set_state(IDLE)
        self._start_monitor()
        text = str(exc) if isinstance(exc, (StartError, SDLError)) else f"放電を開始できません: {exc}"
        if not isinstance(exc, (StartError, SDLError)):
            log.error("放電開始で想定外のエラー", exc_info=exc)
        self.message(text)
        messagebox.showwarning(APP_TITLE, text)

    def _on_note_modified(self, _event=None) -> None:
        if self.session is not None and self.session.running:
            self.session.note = self.note()
        self.note_text.edit_modified(False)

    def on_stop_save(self) -> None:
        self._request_stop(save=True)

    def on_stop_discard(self) -> None:
        if self.state != DISCHARGING:
            return
        if not messagebox.askyesno(APP_TITLE, DISCARD_CONFIRM, icon="warning", default="no"):
            return
        self._request_stop(save=False)

    def _request_stop(self, save: bool) -> None:
        if self.state != DISCHARGING or self.session is None:
            return
        self.session.note = self.note()
        self.session.request_stop(save=save)
        self._set_state(STOPPING)
        self.message("停止しています…")

    def _on_sample(self, s: recorder.Sample) -> None:
        self.value_vars["v"].set(f"{s.voltage:.3f} V")
        self.value_vars["i"].set(f"{s.current:.3f} A")
        self.value_vars["p"].set(f"{s.power:.2f} W")
        self.value_vars["mah"].set(f"{s.mah:.1f} mAh")
        self.value_vars["wh"].set(f"{s.wh:.3f} Wh")

    def _on_finished(self, result) -> None:
        session = self.session
        self._draw_graph(force=True)
        if session is not None and session.start_monotonic is not None and session.latest is not None:
            self.value_vars["elapsed"].set(format_elapsed(session.latest.elapsed))
        lines = []
        if result.discarded:
            lines.append("停止しました（データは破棄しました）")
        else:
            lines.append(f"停止しました（{result.end_reason}）")
            if result.csv_path:
                lines.append(f"CSV: {result.csv_path}")
            if result.png_path:
                lines.append(f"PNG: {result.png_path}")
            if result.error:
                lines.append(result.error)
        lines.extend(result.messages)
        text = "\n".join(lines)
        self.message(text)

        # 通信断で終わったときも接続中の扱いのまま、電圧表示の監視で再接続を試みる
        if self.client is not None:
            self._set_state(IDLE)
            self._start_monitor()
        else:
            self._set_state(DISCONNECTED)

        if self._closing_after_stop:
            self._quit()
            return
        problem = result.error or result.messages
        if problem:
            messagebox.showerror(APP_TITLE, text)
        elif result.end_reason == recorder.END_REASON_CUTOFF:
            messagebox.showinfo(APP_TITLE, "終止電圧に到達しました\n\n" + text)

    # ------------------------------------------------------------------ グラフ
    def _graph_tick(self) -> None:
        try:
            self._draw_graph()
            if self.session is not None and self.session.running and self.session.start_monotonic is not None:
                self.value_vars["elapsed"].set(format_elapsed(time.monotonic() - self.session.start_monotonic))
        finally:
            try:
                self.root.after(GRAPH_MS, self._graph_tick)
            except tk.TclError:
                pass  # ウィンドウを閉じた後

    def _graph_source(self):
        """(経過時間, 電圧, 電流, 終止電圧, タイトル)。放電前は入力中の終止電圧の線だけ"""
        s = self.session
        if s is not None:
            t, v, i = s.snapshot()
            return t, v, i, s.cond.cutoff, s.title()
        try:
            cutoff = parse_number(self.cutoff_var.get(), "", *settings_mod.CUTOFF_RANGE, "", 3)
        except InputError:
            cutoff = None
        try:
            current = parse_number(self.current_var.get(), "", *settings_mod.CURRENT_RANGE, "", 3)
        except InputError:
            current = None
        title = plotting.make_title(None, self.model_var.get().strip(), current, cutoff)
        return [], [], [], cutoff, title

    def _draw_graph(self, force: bool = False) -> None:
        t, v, i, cutoff, title = self._graph_source()
        key = (id(self.session), len(t), cutoff, title)
        if not force and key == self._graph_key:
            return
        self._graph_key = key
        self.plot.set_title(title)
        self.plot.update(t, v, i, cutoff)
        self.canvas.draw_idle()

    def on_save_graph(self) -> None:
        t, v, i, cutoff, title = self._graph_source()
        folder = Path(self.folder_var.get())
        now = datetime.now()
        if self.session is not None and self.session.base_name:
            name = f"{self.session.base_name}_{now:%H%M%S}.png"
        else:
            name = f"graph_{now:%Y%m%d_%H%M%S}.png"
        path = folder / name
        try:
            plotting.render_png(path, t, v, i, cutoff, title)
        except Exception as e:  # noqa: BLE001
            log.exception("グラフを保存できません")
            messagebox.showerror(APP_TITLE, f"グラフを保存できませんでした: {path}\n{e}")
            return
        self.message(f"グラフを保存しました: {path}")
        log.info("グラフ保存 %s", path)

    # ------------------------------------------------------------------ 保存先
    def on_browse(self) -> None:
        folder = filedialog.askdirectory(parent=self.root, title="保存先フォルダ",
                                         initialdir=self.folder_var.get() or None, mustexist=True)
        if folder:
            self.folder_var.set(os.path.normpath(folder))
            self.settings.folder = self.folder_var.get()
            self._check_partials()

    def _check_partials(self) -> None:
        """保存先に前回の一時ファイルが残っていれば知らせる（自動処理はしない）"""
        found = recorder.find_partial_files(Path(self.folder_var.get()))
        if not found:
            return
        names = "\n".join(str(p) for p in found)
        log.warning("前回の一時ファイルが残っています: %s", ", ".join(str(p) for p in found))
        self.message(f"前回の記録が途中で終了しています: {found[0]}" + (f" ほか {len(found) - 1} 件" if len(found) > 1 else ""))
        messagebox.showwarning(APP_TITLE, f"前回の記録が途中で終了しています:\n{names}")

    # ------------------------------------------------------------------ 終了・その他
    def _remember_settings(self) -> None:
        s = self.settings
        host = self.host_var.get().strip()
        if host:
            s.host = host
        try:
            port = int(self.port_var.get())
            if 1 <= port <= 65535:
                s.port = port
        except ValueError:
            pass
        if self.folder_var.get():
            s.folder = self.folder_var.get()
        for name, var, rng in (("current", self.current_var, settings_mod.CURRENT_RANGE),
                               ("cutoff", self.cutoff_var, settings_mod.CUTOFF_RANGE),
                               ("interval", self.interval_var, settings_mod.INTERVAL_RANGE)):
            try:
                setattr(s, name, parse_number(var.get(), "", *rng, "", 3))
            except InputError:
                pass

    def ask_close_choice(self) -> str | None:
        """放電中に閉じようとしたときのダイアログ。'save' / 'discard' / None（キャンセル）"""
        return CloseDialog(self.root).result

    def on_close(self) -> None:
        if self.state == DISCHARGING:
            choice = self.ask_close_choice()
            if choice is None or self.state != DISCHARGING:
                return
            self._closing_after_stop = True
            self._request_stop(save=(choice == "save"))
            return
        if self.state in (STARTING, STOPPING):
            if self.state == STOPPING:
                self._closing_after_stop = True
            self.message("処理中です。終わるまでお待ちください")
            return
        self._quit()

    def _quit(self) -> None:
        self._remember_settings()
        settings_mod.save(self.settings)
        self._stop_monitor()
        if self.client is not None:
            self.client.close()
        log.info("終了")
        self.root.destroy()

    def _run_bg(self, func, on_ok, on_err) -> None:
        def worker():
            try:
                result = func()
            except BaseException as e:  # noqa: BLE001
                self.ui_queue.put((on_err, (e,)))
            else:
                self.ui_queue.put((on_ok, (result,)))

        threading.Thread(target=worker, daemon=True).start()

    def _poll(self) -> None:
        try:
            while True:
                try:
                    func, args = self.ui_queue.get_nowait()
                except queue.Empty:
                    break
                func(*args)
            s = self.session
            if s is not None:
                while True:
                    try:
                        kind, payload = s.events.get_nowait()
                    except queue.Empty:
                        break
                    if kind == "sample":
                        self._on_sample(payload)
                    elif kind == "status":
                        self.message(payload)
                    elif kind == "finished":
                        self._on_finished(payload)
        finally:
            try:
                self.root.after(POLL_MS, self._poll)
            except tk.TclError:
                pass  # ウィンドウを閉じた後

    def _after_shown(self) -> None:
        ready = os.environ.get("SDL_LOGGER_READY_FILE")
        if ready:
            # ビルドの確認（起動時間の測定）用：ウィンドウが表示されたことを知らせる
            self.root.update_idletasks()
            try:
                Path(ready).write_text("ready", encoding="utf-8")
            except OSError:
                pass
        self._check_partials()

    def _on_tk_error(self, exc_type, exc, tb) -> None:
        log.error("画面の処理で想定外のエラー", exc_info=(exc_type, exc, tb))
        try:
            messagebox.showerror(APP_TITLE, f"想定外のエラーが発生しました:\n{exc}\n\n詳細は sdl_logger.log を参照してください")
        except tk.TclError:
            pass


class CloseDialog:
    """「保存して終了 / 破棄して終了 / キャンセル」の 3 択"""

    def __init__(self, parent: tk.Tk):
        self.result: str | None = None
        top = self.top = tk.Toplevel(parent)
        top.title(APP_TITLE)
        top.transient(parent)
        top.resizable(False, False)
        frm = ttk.Frame(top, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=CLOSE_QUESTION).pack(anchor="w", pady=(0, 14))
        btns = ttk.Frame(frm)
        btns.pack(anchor="e")
        save = ttk.Button(btns, text="保存して終了", command=lambda: self._done("save"))
        save.pack(side="left", padx=4)
        tk.Button(btns, text="破棄して終了", command=lambda: self._done("discard"), bg=DISCARD_BG, fg="white",
                  activebackground=DISCARD_BG_ACTIVE, activeforeground="white").pack(side="left", padx=4)
        ttk.Button(btns, text="キャンセル", command=lambda: self._done(None)).pack(side="left", padx=4)
        top.protocol("WM_DELETE_WINDOW", lambda: self._done(None))
        top.bind("<Escape>", lambda e: self._done(None))
        save.focus_set()
        top.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - top.winfo_width()) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - top.winfo_height()) // 3
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        top.grab_set()
        parent.wait_window(top)

    def _done(self, result: str | None) -> None:
        self.result = result
        self.top.grab_release()
        self.top.destroy()

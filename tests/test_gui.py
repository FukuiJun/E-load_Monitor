"""画面の自動テスト（AC-01, AC-05, AC-09, AC-10 の自動化できる部分）。ディスプレイが無ければスキップ"""

import time
from pathlib import Path

import pytest

try:
    import tkinter as tk

    _r = tk.Tk()
    _r.destroy()
    HAS_DISPLAY = True
except Exception:  # noqa: BLE001
    HAS_DISPLAY = False

pytestmark = pytest.mark.skipif(not HAS_DISPLAY, reason="ディスプレイが無いためスキップ")


class Dialogs:
    def __init__(self):
        self.calls = []
        self.answer = True

    def recorder(self, name):
        def f(*args, **kwargs):
            self.calls.append((name, args[1] if len(args) > 1 else kwargs.get("message", "")))
            return self.answer if name.startswith("ask") else "ok"
        return f

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def dialogs(monkeypatch):
    import gui

    d = Dialogs()
    for name in ("showinfo", "showwarning", "showerror", "askyesno"):
        monkeypatch.setattr(gui.messagebox, name, d.recorder(name))
    return d


def pump(root, cond, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        root.update()
        if cond():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def make_app(dialogs, tmp_path):
    import gui

    apps = []

    def make():
        root = tk.Tk()
        app = gui.App(root)
        apps.append(app)
        return app

    yield make
    for app in apps:
        try:
            app.root.destroy()
        except tk.TclError:
            pass


def connect(app, fake, folder):
    app.host_var.set("127.0.0.1")
    app.port_var.set(str(fake.port))
    app.folder_var.set(str(folder))
    app.on_connect()
    assert pump(app.root, lambda: app.state == "idle")


def test_connect_shows_idn_and_voltage(make_app, fake, tmp_path):
    """AC-01／F-01：接続すると IDN と「接続中」、放電前でも電圧を表示"""
    app = make_app()
    connect(app, fake, tmp_path)
    assert "接続中" in app.status_var.get()
    assert "SDL1020X-E" in app.status_var.get()
    assert pump(app.root, lambda: app.value_vars["v"].get().endswith(" V"))
    assert str(app.start_btn["state"]) == "normal"


def test_connect_failure_message(make_app, dialogs, tmp_path):
    """AC-01：つながらないとき F-01 のメッセージ。放電開始不可"""
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    app = make_app()
    app.host_var.set("127.0.0.1")
    app.port_var.set(str(port))
    app.on_connect()
    assert pump(app.root, lambda: "showerror" in dialogs.names())
    assert "接続できません。IP アドレスと LAN ケーブルを確認してください" in dialogs.calls[-1][1]
    assert app.state == "disconnected"
    assert str(app.start_btn["state"]) == "disabled"


def test_unselected_can_be_chosen_again(make_app):
    """F-02：起動時は未選択。一度選んだ後でも未選択に戻せる"""
    app = make_app()
    assert app.maker_var.get() == "" and app.full_var.get() == ""
    labels = [str(rb["text"]) for rb in app.radios]
    assert labels == ["未選択", "Panasonic", "マクセル", "未選択", "4.1V", "4.2V"]
    app.radios[1].invoke()
    assert app.maker_var.get() == "Panasonic"
    app.radios[0].invoke()
    assert app.maker_var.get() == ""


def test_model_max_40(make_app):
    app = make_app()
    app.model_entry.insert(0, "x" * 50)
    assert len(app.model_var.get()) == 40


def test_discharge_auto_stop_saves(make_app, fake, dialogs, tmp_path):
    """F-03〜F-05：放電中は条件を編集不可（備考は可）。終止電圧で自動停止・保存"""
    app = make_app()
    connect(app, fake, tmp_path)
    app.radios[2].invoke()  # マクセル
    app.model_var.set("NCR18650B")
    app.interval_var.set("0.2")
    app.note_text.insert("1.0", "最初")
    app.on_start()
    assert pump(app.root, lambda: app.state == "discharging")
    assert str(app.model_entry["state"]) == "disabled"
    assert all(str(rb["state"]) == "disabled" for rb in app.radios)
    assert str(app.note_text["state"]) == "normal"
    assert str(app.stop_save_btn["state"]) == "normal"
    assert str(app.stop_discard_btn["state"]) == "normal"
    assert str(app.start_btn["state"]) == "disabled"
    app.note_text.insert("end", "→変更")
    assert pump(app.root, lambda: app.value_vars["mah"].get().endswith("mAh"))
    fake.voltage_override = 2.5
    assert pump(app.root, lambda: app.state == "idle")
    assert "showinfo" in dialogs.names()
    base = app.session.base_name
    assert base.endswith("_maxell")
    csv_path = tmp_path / f"{base}.csv"
    assert csv_path.exists() and (tmp_path / f"{base}.png").exists()
    assert str(csv_path) in app.message_var.get()
    text = csv_path.read_text(encoding="utf-8-sig")
    assert '備考,"最初→変更"' in text
    assert "メーカー,マクセル" in text
    assert "満充電電圧[V],\r\n" in text.replace("\n", "\r\n").replace("\r\r", "\r")
    assert str(app.model_entry["state"]) == "normal"


def test_start_refused_below_cutoff(make_app, fake, dialogs, tmp_path):
    app = make_app()
    connect(app, fake, tmp_path)
    fake.voltage_override = 2.9
    app.on_start()
    assert pump(app.root, lambda: "showwarning" in dialogs.names())
    assert "電圧が終止電圧以下です" in dialogs.calls[-1][1]
    assert app.state == "idle"


def test_invalid_input_refused(make_app, fake, dialogs, tmp_path):
    app = make_app()
    connect(app, fake, tmp_path)
    app.current_var.set("5.5")
    app.on_start()
    assert dialogs.calls[-1][0] == "showerror"
    assert "0.001〜5.000" in dialogs.calls[-1][1]
    assert app.state == "idle"


def test_stop_discard_confirm(make_app, fake, dialogs, tmp_path):
    """F-06：いいえなら放電継続、はいなら破棄（ファイルは残らない）"""
    app = make_app()
    connect(app, fake, tmp_path)
    app.interval_var.set("0.2")
    app.on_start()
    assert pump(app.root, lambda: app.state == "discharging")
    dialogs.answer = False
    app.on_stop_discard()
    assert dialogs.calls[-1] == ("askyesno", "データを保存せずに停止します。よろしいですか？")
    assert app.state == "discharging"
    dialogs.answer = True
    app.on_stop_discard()
    assert pump(app.root, lambda: app.state == "idle")
    assert not fake.load_on
    assert list(tmp_path.iterdir()) == []


def test_save_graph_names(make_app, fake, tmp_path):
    """F-08：未開始時は graph_<日時>.png、開始後は <ベース名>_<時刻>.png"""
    app = make_app()
    app.folder_var.set(str(tmp_path))
    app.on_save_graph()
    pngs = list(tmp_path.glob("graph_*.png"))
    assert len(pngs) == 1 and len(pngs[0].stem) == len("graph_20261001_143005")
    connect(app, fake, tmp_path)
    app.interval_var.set("0.2")
    app.on_start()
    assert pump(app.root, lambda: app.state == "discharging")
    app.on_save_graph()
    base = app.session.base_name
    named = [p for p in tmp_path.glob(f"{base}_*.png")]
    assert len(named) == 1 and len(named[0].stem) == len(base) + 7
    app.on_stop_save()
    assert pump(app.root, lambda: app.state == "idle")


def test_settings_restored(make_app, fake, tmp_path, app_dir):
    """AC-10：設定は再起動後に復元。メーカー・満充電電圧は未選択、型番・備考は空"""
    app = make_app()
    app.host_var.set("192.168.10.9")
    app.port_var.set("5026")
    app.folder_var.set(str(tmp_path))
    app.current_var.set("2.5")
    app.cutoff_var.set("2.8")
    app.interval_var.set("5")
    app.maker_var.set("Panasonic")
    app.full_var.set("4.1V")
    app.model_var.set("ABC")
    app.note_text.insert("1.0", "メモ")
    app.on_close()
    assert (app_dir / "sdl_logger_settings.json").exists()
    app2 = make_app()
    assert app2.host_var.get() == "192.168.10.9"
    assert app2.port_var.get() == "5026"
    assert app2.folder_var.get() == str(tmp_path)
    assert app2.current_var.get() == "2.500"
    assert app2.cutoff_var.get() == "2.800"
    assert app2.interval_var.get() == "5.0"
    assert app2.maker_var.get() == "" and app2.full_var.get() == ""
    assert app2.model_var.get() == "" and app2.note() == ""


def test_close_during_discharge_saves(make_app, fake, tmp_path, monkeypatch):
    """F-10：放電中に閉じる →「保存して終了」で停止・保存してから終了"""
    app = make_app()
    connect(app, fake, tmp_path)
    app.interval_var.set("0.2")
    app.on_start()
    assert pump(app.root, lambda: app.state == "discharging")
    monkeypatch.setattr(app, "ask_close_choice", lambda: None)
    app.on_close()
    assert app.state == "discharging"  # キャンセル
    monkeypatch.setattr(app, "ask_close_choice", lambda: "save")
    base = app.session.base_name
    app.on_close()
    closed = []
    app.root.bind("<Destroy>", lambda e: closed.append(1) if e.widget is app.root else None)
    pump(app.root, lambda: bool(closed), timeout=10)
    assert (tmp_path / f"{base}.csv").exists()
    assert not fake.load_on


def test_close_during_discharge_discards(make_app, fake, tmp_path, monkeypatch):
    app = make_app()
    connect(app, fake, tmp_path)
    app.interval_var.set("0.2")
    app.on_start()
    assert pump(app.root, lambda: app.state == "discharging")
    monkeypatch.setattr(app, "ask_close_choice", lambda: "discard")
    session = app.session
    app.on_close()
    closed = []
    app.root.bind("<Destroy>", lambda e: closed.append(1) if e.widget is app.root else None)
    pump(app.root, lambda: bool(closed), timeout=10)
    assert session.finished
    assert list(tmp_path.iterdir()) == []
    assert not fake.load_on


def test_partial_file_notice_at_startup(dialogs, tmp_path, app_dir):
    """9 章：起動時に保存先の *.partial.csv を検出したら知らせる（自動処理はしない）"""
    import json

    import gui

    (app_dir / "sdl_logger_settings.json").write_text(json.dumps({"folder": str(tmp_path)}), encoding="utf-8")
    p = tmp_path / "20261001_143005_4.1V_pana.partial.csv"
    p.write_text("x")
    root = tk.Tk()
    try:
        gui.App(root)
        pump(root, lambda: bool(dialogs.calls), timeout=3)
        assert dialogs.calls[0][0] == "showwarning"
        assert f"前回の記録が途中で終了しています:\n{p}" == dialogs.calls[0][1]
        assert p.exists()
    finally:
        root.destroy()


def test_format_elapsed():
    import gui

    assert gui.format_elapsed(9755) == "02:42:35"
    assert gui.format_elapsed(0) == "00:00:00"

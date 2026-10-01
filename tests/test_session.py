"""放電の進行（F-03〜F-06、9 章、AC-04, AC-06, AC-07）"""

import csv
import time

import pytest

from sdl_client import SDLClient
from session import Conditions, DischargeSession, StartError

COND = Conditions(maker="Panasonic", full_voltage="4.1V", model="NCR18650B", current=1.0, cutoff=3.0,
                  interval=0.2)


def make_session(fake, folder, cond=COND, **kw):
    client = SDLClient("127.0.0.1", fake.port)
    client.connect()
    kw.setdefault("reconnect_attempts", 3)
    kw.setdefault("reconnect_interval", 0.1)
    return DischargeSession(client, folder, cond, **kw)


def samples(session):
    out = []
    while not session.events.empty():
        kind, payload = session.events.get()
        if kind == "sample":
            out.append(payload)
    return out


def test_start_sets_cc_and_load_on(fake, tmp_path):
    s = make_session(fake, tmp_path)
    s.start()
    try:
        assert ":SOUR:FUNC CURR" in fake.commands
        assert ":SOUR:CURR:IRANG 5" in fake.commands
        assert ":SOUR:CURR:LEV:IMM 1.000" in fake.commands
        assert fake.load_on
        assert s.paths["partial"].exists()
        assert s.base_name.endswith("_4.1V_pana")
    finally:
        s.request_stop(save=False)
        s.wait(5)


def test_start_refused_when_voltage_at_or_below_cutoff(fake, tmp_path):
    fake.voltage_override = 3.0
    s = make_session(fake, tmp_path)
    with pytest.raises(StartError, match="電圧が終止電圧以下です"):
        s.start()
    assert not fake.load_on
    assert list(tmp_path.iterdir()) == []


def test_start_refused_when_folder_missing(fake, tmp_path):
    s = make_session(fake, tmp_path / "なし")
    with pytest.raises(StartError):
        s.start()
    assert not fake.load_on


def test_auto_stop_at_cutoff(fake, tmp_path):
    """AC-04：終止電圧を下回ると 3 サンプル以内に負荷 OFF が送られ、CSV・PNG が保存される"""
    s = make_session(fake, tmp_path)
    s.start()
    time.sleep(0.5)
    fake.voltage_override = 2.9
    n_before = len(s.snapshot()[0])
    result = s.wait(10)
    assert result is not None
    assert result.end_reason == "終止電圧到達"
    assert not fake.load_on
    assert ":SOUR:INP:STAT OFF" in fake.commands[-2:]
    t, v, _ = s.snapshot()
    below = [x for x in v if x <= 3.0]
    assert len(below) == 3  # 3 サンプル目で停止（それ以上は測らない）
    assert len(t) <= n_before + 4
    assert result.csv_path.exists() and result.png_path.exists()
    assert not s.paths["partial"].exists()
    text = result.csv_path.read_text(encoding="utf-8-sig")
    assert "終了理由,終止電圧到達" in text


def test_noise_does_not_stop(fake, tmp_path):
    """終止電圧以下が 2 回続いただけでは止まらない（連続 3 回で停止）"""
    s = make_session(fake, tmp_path, cond=Conditions(None, None, "", 1.0, 3.0, 0.1))
    s.start()
    try:
        for _ in range(3):
            fake.voltage_override = 2.9
            time.sleep(0.15)
            fake.voltage_override = 3.5
            time.sleep(0.25)
        assert s.running
    finally:
        s.request_stop(save=False)
        s.wait(5)


def test_manual_stop_and_save_with_note(fake, tmp_path):
    """F-05：停止・保存。備考は放電中に変えた内容（保存時点）が CSV に入る"""
    s = make_session(fake, tmp_path, note="最初")
    s.start()
    time.sleep(0.5)
    s.note = "25℃恒温槽内。\n2回目"
    s.request_stop(save=True)
    result = s.wait(10)
    assert result.end_reason == "手動停止"
    assert not fake.load_on
    assert result.csv_path.name == f"{s.base_name}.csv"
    assert result.png_path.name == f"{s.base_name}.png"
    assert not s.paths["partial"].exists()
    with open(result.csv_path, encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.reader(fp))
    info = {r[0]: r[1:] for r in rows[:14] if r}
    assert info["備考"] == ["25℃恒温槽内。\n2回目"]
    assert info["型番"] == ["NCR18650B"]
    header = rows.index(["日時", "経過時間[s]", "電圧[V]", "電流[A]", "電力[W]", "放電容量[mAh]", "電力量[Wh]"])
    data = rows[header + 1:]
    assert len(data) == len(s.snapshot()[0]) >= 3
    assert data[0][1] == "0.000"
    assert float(data[-1][5]) == pytest.approx(result.mah, abs=0.001)


def test_discard(fake, tmp_path):
    """AC-06：停止・破棄で CSV・PNG・一時ファイルが残らず、負荷 OFF が送られる"""
    s = make_session(fake, tmp_path)
    s.start()
    time.sleep(0.5)
    s.request_stop(save=False)
    result = s.wait(10)
    assert result.discarded
    assert ":SOUR:INP:STAT OFF" in fake.commands[-2:]
    assert not fake.load_on
    assert list(tmp_path.iterdir()) == []


def test_comm_lost_saves(fake, tmp_path):
    """AC-07：放電中にシミュレータを止めると、再接続を試みた後「通信断」で保存される"""
    s = make_session(fake, tmp_path)
    s.start()
    time.sleep(0.5)
    fake.stop()
    result = s.wait(15)
    assert result is not None
    assert result.end_reason == "通信断"
    assert not result.load_off_ok
    assert any("負荷を OFF" in m for m in result.messages)
    statuses = []
    while not s.events.empty():
        kind, payload = s.events.get()
        if kind == "status":
            statuses.append(payload)
    assert any("再接続しています（3/3）" in st for st in statuses)
    assert result.csv_path.exists() and result.png_path.exists()
    assert "終了理由,通信断" in result.csv_path.read_text(encoding="utf-8-sig")


def test_reconnect_and_continue(fake, tmp_path):
    """9 章：一時的な切断なら再接続して記録を続ける"""
    s = make_session(fake, tmp_path, reconnect_attempts=10, reconnect_interval=0.2)
    s.start()
    time.sleep(0.5)
    fake.stop()
    time.sleep(0.5)
    fake.restart()
    n = len(s.snapshot()[0])
    time.sleep(1.5)
    assert s.running
    assert len(s.snapshot()[0]) > n
    s.request_stop(save=True)
    result = s.wait(10)
    assert result.end_reason == "手動停止"
    assert result.load_off_ok
    assert not fake.load_on


def test_reconnect_finds_load_off_stops(fake, tmp_path):
    """再接続後に負荷が OFF（SDL の再起動など）なら止めて保存する"""
    s = make_session(fake, tmp_path, reconnect_interval=0.2)
    s.start()
    time.sleep(0.3)
    fake.stop()
    fake.load_on = False
    fake.restart()
    result = s.wait(10)
    assert result.end_reason == "通信断"
    assert result.csv_path.exists()


def test_invalid_responses_ten_times_is_comm_lost(fake, tmp_path):
    """9 章：数値でない応答はスキップし、連続 10 回で通信断扱い"""
    s = make_session(fake, tmp_path, cond=Conditions(None, None, "", 1.0, 3.0, 0.05))
    s.start()
    time.sleep(0.2)
    n = len(s.snapshot()[0])
    fake.garbage = True
    result = s.wait(10)
    assert result.end_reason == "通信断"
    assert len(s.snapshot()[0]) <= n + 1  # 切り替えた瞬間に測定中だった 1 回分は記録されうる
    assert not fake.load_on


def test_invalid_response_is_skipped(fake, tmp_path):
    s = make_session(fake, tmp_path, cond=Conditions(None, None, "", 1.0, 3.0, 0.1))
    s.start()
    time.sleep(0.25)
    fake.garbage = True
    time.sleep(0.35)
    fake.garbage = False
    time.sleep(0.3)
    assert s.running
    s.request_stop(save=False)
    s.wait(5)


def test_final_csv_failure_keeps_partial(fake, tmp_path):
    """9 章：最終 CSV が作れないとき一時ファイルを残し、パスを知らせる"""
    s = make_session(fake, tmp_path)
    s.start()
    time.sleep(0.3)
    s.paths["csv"].write_text("Excel で開いている同名ファイル")
    s.request_stop(save=True)
    result = s.wait(10)
    assert result.csv_path is None
    assert result.partial_path == s.paths["partial"]
    assert result.error == f"保存できませんでした。一時ファイル: {s.paths['partial']}"
    assert s.paths["partial"].exists()


def test_partial_has_rows_while_running(fake, tmp_path):
    """8 章：放電中も一時ファイルに直前の行まで書かれている"""
    s = make_session(fake, tmp_path)
    s.start()
    time.sleep(0.7)
    n = len(s.snapshot()[0])
    lines = s.paths["partial"].read_text(encoding="utf-8-sig").splitlines()
    assert len(lines) - 1 >= n - 1
    s.request_stop(save=False)
    s.wait(5)


def test_unique_name_when_started_twice_in_same_second(fake, tmp_path):
    names = []
    for _ in range(2):
        s = make_session(fake, tmp_path)
        s.start()
        names.append(s.base_name)
        s.request_stop(save=True)
        s.wait(10)
    if names[0][:15] == names[1][:15]:
        assert names[1] == names[0] + "_2"

"""SDL 通信（F-01、AC-01）"""

import socket
import threading
import time

import pytest

from fake_sdl import FakeSDL
from sdl_client import (CONNECT_ERROR_MESSAGE, SDLClient, SDLConnectionError, SDLResponseError,
                        current_range_for)


def test_connect_returns_idn(fake):
    """AC-01：シミュレータに接続して IDN 文字列を得る"""
    client = SDLClient("127.0.0.1", fake.port)
    idn = client.connect()
    assert "SDL1020X-E" in idn
    assert client.connected
    client.close()


def test_connect_refused_is_quick():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    client = SDLClient("127.0.0.1", port)
    with pytest.raises(SDLConnectionError, match=CONNECT_ERROR_MESSAGE):
        client.connect()


def test_connect_unreachable_ip_within_5s():
    """AC-01：存在しない IP では 5 秒以内にエラー（ルーティングされないアドレス）"""
    client = SDLClient("10.255.255.1", 5025)
    t = time.monotonic()
    with pytest.raises(SDLConnectionError, match=CONNECT_ERROR_MESSAGE):
        client.connect()
    assert time.monotonic() - t < 5.0


def test_connect_no_response_times_out_in_3s():
    """接続はできるが応答しない機器：3 秒でタイムアウト"""
    fake = FakeSDL(port=0).start()
    fake.silent = True
    try:
        client = SDLClient("127.0.0.1", fake.port)
        t = time.monotonic()
        with pytest.raises(SDLConnectionError, match=CONNECT_ERROR_MESSAGE):
            client.connect()
        assert 2.5 < time.monotonic() - t < 5.0
        assert not client.connected
    finally:
        fake.stop()


def test_connect_rejects_non_sdl():
    fake = FakeSDL(port=0, idn="KEYSIGHT,34461A,0,1").start()
    try:
        with pytest.raises(SDLResponseError):
            SDLClient("127.0.0.1", fake.port).connect()
    finally:
        fake.stop()


def test_measure_keeps_raw_text(fake):
    client = SDLClient("127.0.0.1", fake.port)
    client.connect()
    fake.voltage_override = 4.18512
    m = client.measure()
    assert m.voltage == pytest.approx(4.18512)
    assert m.voltage_text == "4.18512"
    assert m.current == 0.0


def test_garbage_response_raises_response_error(fake):
    client = SDLClient("127.0.0.1", fake.port)
    client.connect()
    fake.garbage = True
    with pytest.raises(SDLResponseError):
        client.measure()
    fake.garbage = False
    assert client.measure_voltage() > 0  # 接続はそのまま使える


def test_setup_cc_and_load(fake):
    client = SDLClient("127.0.0.1", fake.port)
    client.connect()
    client.setup_cc(1.0)
    client.query("*IDN?")  # 書き込みのみのコマンドがシミュレータで処理されるのを待つ
    assert fake.commands[-4:-1] == [":SOUR:FUNC CURR", ":SOUR:CURR:IRANG 5", ":SOUR:CURR:LEV:IMM 1.000"]
    client.set_load(True)
    assert client.load_state() is True
    assert client.load_requested
    m = client.measure()
    assert m.current == pytest.approx(1.0)
    client.set_load(False)
    assert client.load_state() is False
    assert not client.load_requested


def test_current_range():
    assert current_range_for(5.0) == 5
    assert current_range_for(0.001) == 5
    assert current_range_for(5.001) == 30


def test_disconnect_raises_connection_error_and_reconnect(fake):
    client = SDLClient("127.0.0.1", fake.port)
    client.connect()
    fake.disconnect_clients()
    time.sleep(0.05)
    with pytest.raises(SDLConnectionError):
        client.measure()
    assert not client.connected
    client.reconnect()
    assert client.measure_voltage() > 0


def test_load_off_safely_reconnects(fake):
    client = SDLClient("127.0.0.1", fake.port)
    client.connect()
    client.set_load(True)
    fake.disconnect_clients()
    time.sleep(0.05)
    client.close()
    assert client.load_off_safely()
    assert fake.load_on is False


def test_emergency_load_off_when_lock_is_held(fake):
    client = SDLClient("127.0.0.1", fake.port)
    client.connect()
    client.set_load(True)
    held = threading.Event()
    release = threading.Event()

    def hold():
        with client._lock:
            held.set()
            release.wait(5)

    th = threading.Thread(target=hold)
    th.start()
    held.wait()
    try:
        assert client.emergency_load_off()
        time.sleep(0.1)
        assert fake.load_on is False
    finally:
        release.set()
        th.join()

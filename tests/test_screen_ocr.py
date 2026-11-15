"""Windows 標準の文字認識（screen_ocr）と、野狐パネルの実 OCR 読み取りのテスト"""

import os
import subprocess
import sys

import pytest
from PIL import Image

from katrain.core import screen_ocr
from katrain.core.board_spectate import read_spectate_info
from tests.test_board_watch_fox import _open, _reader_on

_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
SPECTATE1 = os.path.join(_DATA_DIR, "board_watch_fox_spectate1.png")
SPECTATE2 = os.path.join(_DATA_DIR, "board_watch_fox_spectate2.png")


@pytest.mark.parametrize("failure", ["missing", "timeout", "nonzero"])
def test_ocr_lines_returns_none_when_powershell_fails(monkeypatch, failure):
    def runner(cmd, **kwargs):
        if failure == "missing":
            raise FileNotFoundError("powershell")
        if failure == "timeout":
            raise subprocess.TimeoutExpired(cmd, 1)
        return subprocess.CompletedProcess(cmd, 1, b"", b"")

    monkeypatch.setattr(screen_ocr.sys, "platform", "win32")
    monkeypatch.setattr(screen_ocr.subprocess, "run", runner)
    assert screen_ocr.ocr_lines(Image.new("RGB", (50, 20))) is None


def test_ocr_lines_parses_utf8_lines_and_removes_temp_file(monkeypatch):
    seen = {}

    def runner(cmd, **kwargs):
        seen["path"] = cmd[cmd.index("-Path") + 1]
        assert os.path.exists(seen["path"])
        return subprocess.CompletedProcess(cmd, 0, "コミ\r\n\r\n 0子 アゲハマ 3子 \r\n".encode("utf-8"), b"")

    monkeypatch.setattr(screen_ocr.sys, "platform", "win32")
    monkeypatch.setattr(screen_ocr.subprocess, "run", runner)
    assert screen_ocr.ocr_lines(Image.new("RGB", (50, 20))) == ["コミ", "0子 アゲハマ 3子"]
    assert not os.path.exists(seen["path"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows OCR")
@pytest.mark.parametrize("path,agehama", [(SPECTATE1, (0, 0)), (SPECTATE2, (3, 0))])
def test_real_ocr_through_production_crop(monkeypatch, path, agehama):
    # 手で決めた矩形ではなく read_spectate_info の切り出しそのものを通す
    reader = _reader_on(monkeypatch, _open(path))
    reader.read()
    monkeypatch.setattr(reader, "window_title_text", lambda: "x")
    if screen_ocr.ocr_lines(Image.new("RGB", (60, 30), "white")) is None:
        pytest.skip("日本語 OCR が無い環境")
    got = read_spectate_info(reader)
    assert (got.komi, got.agehama_b, got.agehama_w) == (7.5, *agehama)

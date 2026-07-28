import os

import pytest
from PIL import Image

from katrain.core.tsumego_capture import CaptureError, detect_board

SAMPLE = os.path.join(os.path.dirname(__file__), "data", "tsumego_app_sample.png")


def test_detect_board_returns_square_bbox():
    img = Image.open(SAMPLE)
    x0, y0, x1, y1 = detect_board(img)
    w, h = x1 - x0 + 1, y1 - y0 + 1
    assert min(w, h) >= 300
    assert 0.9 < w / h < 1.1
    # 盤は画像の中央下寄り: bbox が画像内に収まっている
    assert 0 <= x0 < x1 < img.width
    assert 0 <= y0 < y1 < img.height


def test_detect_board_fails_without_board():
    img = Image.new("RGB", (800, 600), (20, 40, 120))  # 青一色
    with pytest.raises(CaptureError):
        detect_board(img)

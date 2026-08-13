# Web 盤面認識（PlayGo.gg）の実スクリーンショット検証。
#
#   python docs/superpowers/specs/calibration-data/tsumego-web/validate_web_capture.py
#
# 合成盤のユニットテスト（tests/test_tsumego_capture.py の test_web_*）は幾何と経路を固定するが、
# 実サイトの木目・アンチエイリアス・フォント描画に対する閾値の妥当性はここでしか回帰できない。
# 認識まわりの閾値（WEB_LINE_DARK / WEB_GLYPH_* 等）を触ったら必ず回すこと。
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
from katrain.core.tsumego_capture import recognize_board  # noqa: E402

HERE = os.path.dirname(__file__)

# 期待値は 2026-08-13 のスクリーンショットを目視読みして確定したもの
EXPECTED = {
    "playgo-9x9-partial-20260813.png": {
        "kind": "web_partial",
        "size": 9,
        "cropped": {"right", "bottom"},
        "black": {"F9", "D8", "F8", "D7", "F7", "E6"},
        "white": {"C9", "E9", "C8", "E8", "C7", "E7", "C6"},
    },
    "playgo-19x19-full-20260813.png": {
        "kind": "web_full",
        "size": 19,
        "cropped": set(),
        "black": set("B17 C15 R9 R8 O7 P7 S7 P6 Q6 S6 R5 S5 D4 P4 Q4 O3 P3 P2".split()),
        "white": set("D17 O17 E16 R16 S9 P8 Q8 S8 Q7 R7 R6 O5 P5 Q5 R4 S4 Q3 S3 Q2 S2 R1".split()),
    },
    # 以下3枚はモバイル風の縦長レイアウトで初版が失敗したケース（2026-08-13 追記1）:
    # 縦に並んだ数字ラベル列が幻の格子線になる／行番号が1つも見えない下寄せクロップ／
    # 半透明のホバー石（茶色のゴースト）。回帰の要はそれぞれ 幻線トリム・辺アンカー・ゴースト空点化
    "playgo-19x19-partial-topright-mobile-20260813.png": {
        "kind": "web_partial",
        "size": 19,
        "cropped": {"left", "bottom"},
        "black": set("M17 N17 O18 Q17 Q18 R12 R14 R16 R18 R19 S16".split()),  # M18 のゴーストは含まない
        "white": set("N16 O15 O17 P16 P17 Q16 R17 S17 S18 S19".split()),
    },
    "playgo-19x19-partial-bottom-mobile-20260813.png": {
        "kind": "web_partial",
        "size": 19,  # フォールバック推定（上端・右端とも切れているため）
        "cropped": {"left", "right", "top"},
        "black": set("G2 G3 H3 H4 H5 K5 L3 L5 M1 M3 M5 N1 N5 O2 O3 O4".split()),
        "white": set("J2 J3 K1 K3 K4 L4 M2 M4 N2 N3 N4".split()),
    },
    "playgo-9x9-full-mobile-20260813.png": {
        "kind": "web_full",
        "size": 9,
        "cropped": set(),
        "black": set("B5 C5 C6 C8 D4 D7 E2 E3 E4 F4 H7".split()),
        "white": set("B2 B4 C4 D2 D3 D5 D6 E5 E8 G3 G6 G7 G8 H4 H6".split()),
    },
}

COLS = "ABCDEFGHJKLMNOPQRST"


def stones_of(grid, color):
    size = len(grid)
    return {f"{COLS[j]}{size - i}" for i in range(size) for j in range(size) if grid[i][j] == color}


def main():
    failures = 0
    for name, exp in EXPECTED.items():
        view = recognize_board(Image.open(os.path.join(HERE, name)))
        checks = [
            ("kind", view.kind, exp["kind"]),
            ("size", len(view.grid), exp["size"]),
            ("cropped", set(view.cropped_sides), exp["cropped"]),
            ("black", stones_of(view.grid, "B"), exp["black"]),
            ("white", stones_of(view.grid, "W"), exp["white"]),
        ]
        bad = [(k, got, want) for k, got, want in checks if got != want]
        if bad:
            failures += 1
            print(f"FAIL {name}")
            for k, got, want in bad:
                print(f"  {k}: got {got} / want {want}")
        else:
            print(f"OK   {name} ({exp['kind']} {exp['size']}x{exp['size']})")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

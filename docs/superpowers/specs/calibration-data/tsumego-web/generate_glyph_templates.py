# 座標ラベルのグリフテンプレート（katrain/core/tsumego_capture_glyphs.py）の再生成スクリプト。
#
#   python docs/superpowers/specs/calibration-data/tsumego-web/generate_glyph_templates.py > \
#       katrain/core/tsumego_capture_glyphs.py
#
# 19路全体表示のスクリーンショット（4辺のラベルに 1-19・A-T が全部そろっている）から、
# 既知の並び（行は上から 19..1、列は左から A..T）を教師にして全グリフを抽出し、
# ハミング距離2以下の重複を間引いて埋め込みモジュールのソースを出力する。
# 別サイト・フォント変更に対応するときはスクリーンショットを追加してここから作り直す
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", ".."))
from katrain.core.tsumego_capture import (  # noqa: E402
    COL_LETTERS,
    _web_band_boxes,
    _web_bitmap_distance,
    _web_detect_lines,
    _web_glyph_bitmap,
    _web_read_band,
    detect_board,
)

SOURCE = os.path.join(os.path.dirname(__file__), "playgo-19x19-full-20260813.png")


def main():
    rgb = Image.open(SOURCE).convert("RGB")
    board_rect = detect_board(rgb)
    vpos, hpos, vsp, hsp = _web_detect_lines(rgb, board_rect)
    assert len(vpos) == len(hpos) == 19, f"19路の全体表示が前提です（検出 {len(vpos)}x{len(hpos)}）"
    bands = _web_band_boxes(board_rect, vpos, hpos, vsp, hsp, rgb.size)
    samples = {}  # char -> [bitmap, ...]
    for side in ("left", "right"):
        for i, comps in _web_read_band(rgb, side, bands[side], vpos, hpos, vsp, hsp).items():
            num = str(19 - i)
            if len(comps) == len(num):
                for ch, c in zip(num, comps):
                    samples.setdefault(ch, []).append(_web_glyph_bitmap(rgb, c))
    for side in ("top", "bottom"):
        for i, comps in _web_read_band(rgb, side, bands[side], vpos, hpos, vsp, hsp).items():
            if len(comps) == 1:
                samples.setdefault(COL_LETTERS[i], []).append(_web_glyph_bitmap(rgb, comps[0]))
    missing = set("0123456789") | set(COL_LETTERS)
    missing -= set(samples)
    assert not missing, f"抽出できなかった文字があります: {sorted(missing)}"
    kept = {}
    for ch, bmps in sorted(samples.items()):
        uniq = []
        for b in bmps:
            if all(_web_bitmap_distance(b, u) > 2 for u in uniq):
                uniq.append(b)
        kept[ch] = uniq
    out = []
    out.append('"""Web 盤面（PlayGo.gg 等）の座標ラベル用グリフテンプレート。')
    out.append("")
    out.append("10x14 の二値ビットマップ（'#'=暗画素）を行ごとに '/' で連結した文字列。実スクリーンショット")
    out.append("2枚（9路部分表示・19路全体表示、2026-08-13）の全ラベルから抽出し、ハミング距離2以下の")
    out.append("重複を間引いたもの。ラベルはズーム非依存の固定UIフォント（実測高さ13-14px）なので、")
    out.append("正規化後のテンプレートはズーム率が変わっても一致する。生成スクリプトは")
    out.append('docs/superpowers/specs/calibration-data/tsumego-web/ を参照"""')
    out.append("")
    out.append("GLYPH_TEMPLATES = {")
    for ch, bmps in kept.items():
        out.append(f'    "{ch}": [')
        for bmp in bmps:
            row_strs = ["".join("#" if v else "." for v in row) for row in bmp]
            out.append(f'        "{"/".join(row_strs)}",')
        out.append("    ],")
    out.append("}")
    print("\n".join(out))


if __name__ == "__main__":
    main()

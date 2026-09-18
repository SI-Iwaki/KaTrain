"""攻城（ai:siege）・狩猟（ai:hunt / ai:hunt_diverge）の既定値が文書と実際の挙動で一致すること。

戦略は `self.settings.get(key, コードの既定)` で値を読み、`self.settings` は config.json の
`ai/<戦略>` セクションそのもの。同梱 config.json（とそれを写したユーザー設定）は全キーを
19路の値で持つので、コード側に盤サイズ別の既定を書いても**キーのある項目では使われない**。
2026-04-09 の実装から 13路の既定（攻城 25/4/3.0/4.0/2.5・狩猟 4.0/4/2.5/6.0/5.0）は一度も
効いておらず、マニュアルと rules の「既定（19路 / 13路）」表だけがそれを謳っていた
（2026-09-18 に文書を実際の挙動へ合わせ、効いていない既定をコードから削除した）。
"""

import json
import os
import re

import pytest

from katrain.core.ai import hunt_default_focus_stddev
from katrain.core.utils import find_package_resource

MANUAL_PAGE = os.path.join(os.path.dirname(__file__), "..", "docs", "manual", "src", "06c_ai_attack.html")


def _package_ai_config():
    with open(find_package_resource("katrain/config.json"), encoding="utf-8") as f:
        return json.load(f)["ai"]


def _manual_defaults(card_id):
    """マニュアルの戦略カード（<div class="card" id=...>）の設定表から {キー: 既定欄の文字列} を返す"""
    with open(MANUAL_PAGE, encoding="utf-8") as f:
        html = f.read()
    start = html.index(f'<div class="card" id="{card_id}">')
    end = html.find('<div class="card"', start + 1)
    card = html[start : end if end >= 0 else len(html)]
    return dict(re.findall(r"<tr><td>([a-z0-9_]+)</td><td>([^<]*)</td>", card))


def _matches(cell, value):
    if isinstance(value, bool):
        return cell == ("ON" if value else "OFF")
    try:
        return float(cell) == float(value)
    except ValueError:  # 「40 / 25」のような盤別併記は数値として読めない
        return False


@pytest.mark.parametrize(
    "card_id, section, lists_every_key",
    [
        ("ai-siege", "ai:siege", True),
        ("ai-hunt", "ai:hunt", True),
        ("ai-hunt-diverge", "ai:hunt_diverge", False),  # 共通項目は「（その他）狩猟戦略と同じ」の1行
    ],
)
def test_manual_defaults_are_the_values_actually_used(card_id, section, lists_every_key):
    """マニュアルの既定欄は同梱 config.json の値（＝どの盤でも実際に使われる値）と一致する"""
    config = _package_ai_config()[section]
    documented = _manual_defaults(card_id)
    assert documented, f"{card_id} の設定表が読めない"
    if lists_every_key:
        assert set(documented) == set(config)
    mismatches = {k: (cell, config[k]) for k, cell in documented.items() if k in config and not _matches(cell, config[k])}
    assert not mismatches, f"マニュアルの既定欄が config.json と違う（キー: (マニュアル, config)）: {mismatches}"


def test_hunt_focus_default_depends_on_board_size():
    assert hunt_default_focus_stddev(13) == 5.0
    assert hunt_default_focus_stddev(19) == 7.0


def test_hunt_diverge_runs_attention_focus_with_the_code_default():
    """ai:hunt_diverge のセクションには hunt_focus_stddev が無い＝注意フォーカスは盤別のコード既定
    （13路 5.0 / 19路 7.0）で動く。これがコード側の盤別既定で唯一効いているもの。

    キーを足すと 13路の値がその値に変わる（ai:hunt の 13路既定が死んでいたのと同じ仕組み）。
    GUI に出したくなったら、盤別の値を保つために盤別キー（`_13` 接尾辞）で足すこと。
    """
    assert "hunt_focus_stddev" not in _package_ai_config()["ai:hunt_diverge"]

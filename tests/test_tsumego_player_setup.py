"""詰碁キャプチャが黒番に設定する ai:tsumego が GUI 往復で消えないことを守る回帰テスト。

実測 2026-07-30: GUI の対局者ウィジェットは選択肢（AI_STRATEGIES_RECOMMENDED_ORDER）に無い
player_subtype を保持できず、種別を人間→AIに変えた瞬間にドロップダウンの現在値（ai:default）を
KaTrain 側へ書き戻す。そのため起動後1回目のキャプチャだけ黒番が ai:default になり、
詰碁戦略（ownership 選択・コウ勝ち前提評価）が丸ごと無効化されて誤答していた。
"""

from katrain.core.constants import (
    AI_OPTION_VALUES,
    AI_STRATEGIES,
    AI_STRATEGIES_RECOMMENDED_ORDER,
    AI_STRENGTH,
    AI_TSUMEGO,
)


def test_tsumego_strategy_is_selectable_in_the_player_widget():
    # ここに入っていないと GUI 往復で ai:default に戻され、詰碁戦略が動かない
    assert AI_TSUMEGO in AI_STRATEGIES_RECOMMENDED_ORDER
    assert AI_TSUMEGO in AI_STRATEGIES
    assert AI_TSUMEGO in AI_STRENGTH  # update_calculated_ranks が引く


def test_tsumego_default_settings_fit_the_gui_widgets():
    # 設定画面を開いたときに既定値がスライダーの範囲外だと、開いただけで値が変わりうる
    import json
    import os

    with open(os.path.join(os.path.dirname(__file__), "..", "katrain", "config.json"), encoding="utf-8") as f:
        defaults = json.load(f)["ai"][AI_TSUMEGO]
    for key, value in defaults.items():
        values = AI_OPTION_VALUES.get(key)
        if values is None or values == "bool":
            continue
        allowed = [v[0] if isinstance(v, tuple) else v for v in values]
        assert value in allowed, f"{key}={value} が AI_OPTION_VALUES の範囲外"

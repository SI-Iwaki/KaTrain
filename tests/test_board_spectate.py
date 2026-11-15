import ast
import os
from types import SimpleNamespace

import pytest

from katrain.core.board_spectate import (
    BEHIND_TEXT,
    ESTIMATED_NOTE,
    SpectateInfo,
    agehama_base,
    agehama_totals,
    append_plan,
    assumed_next_player,
    capture_base_for,
    engine_komi_offset,
    fallback_next_player,
    node_in_tree,
    popup_players_after_spectate,
    promote_to_main_line,
    read_spectate_info,
    replay_counting,
    spectate_status_text,
    next_player_from,
    parse_fox_panel,
    parse_fox_title,
    spectate_sync,
)
from katrain.core.board_spectate import SpectateState, SpectateWatcher, spectate_watch_settings
from katrain.core.board_watch import STATUS_IDLE, STATUS_WARN, STATUS_WATCHING, PermanentCaptureError, apply_move_to_grid, watch_settings_from_config


def g(s):
    return [list(r) for r in s.split("/")]


def replay(grid, moves):
    for i, j, c in moves:
        grid = apply_move_to_grid(grid, i, j, c)
        assert grid is not None
    return grid


G0 = g("...../.B.../...../...W./.....")
G0_PLUS_B = g("B..../.B.../...../...W./.....")
G0_PLUS_BW = g("B..../.B.../...../...W./W....")
G0_PLUS_BWB = g("B...B/.B.../...../...W./W....")
G0_PLUS_BB = g("B...B/.B.../...../...W./.....")
G0_MINUS_STONE = g("...../...../...../...W./.....")
G7 = [["."] * 7 for _ in range(7)]

# 白 1 子 (0,0) がアタリ。黒が (1,0) で取る
ATARI = g("WB.../...../...../...../.....")
AFTER_CAPTURE = g(".B.../B..../...../...../.....")

# 黒 (0,0) は、先に黒 (0,2) を置いて白 (0,1) の呼吸点を (0,0) だけにしないと自殺手になる
NEEDS_ORDER = g(".W.../WB.../...../...../.....")
NEEDS_ORDER_AFTER = g("B.B../WB.../...../...../....W")

# コウ形: 白 (1,1) が黒 3 子に囲まれてアタリ。黒 (1,2) で取れる
KO_BEFORE = g(".BW../BW.W./.BW../...../.....")
# 黒が新しく置いた (1,2) の石があるのに、取られるはずの白 (1,1) が盤に残っている（取りが盤に反映されていない）
CAPTURE_NOT_REFLECTED = g(".BW../BWBW./.BW../...../.....")

# tip の黒 (1,1) が白に変わり、黒 (4,0) が増えた盤
GAP_RECOLOURED = g("...../.W.../...../...W./B....")


def test_in_sync():
    assert spectate_sync(G0, G0, "B").kind == "in_sync"


def test_single_move_and_capture():
    v = spectate_sync(ATARI, AFTER_CAPTURE, "B", last_mover="B")
    assert (v.kind, v.moves, v.estimated) == ("moves", ((1, 0, "B"),), False)


def test_three_moves_are_alternated_and_marked_estimated():
    v = spectate_sync(G0, G0_PLUS_BWB, "B", last_mover="B")
    assert v.kind == "moves" and [m[2] for m in v.moves] == ["B", "W", "B"] and v.estimated
    assert replay(G0, v.moves) == G0_PLUS_BWB


def test_two_moves_one_per_colour_have_a_determined_order():
    # 早碁では確定待ちの間に 2 手進む。黒白 1 手ずつなら順序は 1 通り＝推定ではない
    v = spectate_sync(G0, G0_PLUS_BW, "B", last_mover="W")
    assert v.kind == "moves" and [m[2] for m in v.moves] == ["B", "W"] and not v.estimated


def test_order_that_needs_capture_first_is_found():
    v = spectate_sync(NEEDS_ORDER, NEEDS_ORDER_AFTER, "B")
    assert v.kind == "moves" and replay(NEEDS_ORDER, v.moves) == NEEDS_ORDER_AFTER


@pytest.mark.parametrize(
    "tip,obs,kw",
    [
        (G0, G0_PLUS_BB, {}),  # 黒 2 手＝交互にならない
        (KO_BEFORE, CAPTURE_NOT_REFLECTED, {}),  # 取りが盤に反映されていない盤
        (G0, G0_PLUS_B, {"last_mover": "W"}),  # 直前手の印と色が合わない
        (G0, G0_PLUS_B, {"app_move_number": 12, "tip_move_number": 10}),  # 手数が合わない
        (G0, GAP_RECOLOURED, {}),  # tip の石の色が変わっている（黒 (1,1) が白）＋黒 1 子
        (G0, G7, {}),  # 盤サイズ違い
    ],
)
def test_unexplained_diff_reimports(tip, obs, kw):
    assert spectate_sync(tip, obs, "B", **kw).kind == "reimport"


def test_app_showing_earlier_mainline_position_is_behind_not_reimport():  # Review Focus 6
    v = spectate_sync(G0_PLUS_BWB, G0_PLUS_B, "W", ancestor_grids=(G0, G0_PLUS_B, G0_PLUS_BW))
    assert v.kind == "behind"


def test_move_number_check_passes_when_consistent():
    assert spectate_sync(G0, G0_PLUS_B, "B", app_move_number=11, tip_move_number=10).kind == "moves"


def test_real_ko_take_and_retake_is_in_sync():
    # 黒が取り、白が取り返すと tip に戻る。この 2 手は記録されない（既知の限界）
    taken = apply_move_to_grid(KO_BEFORE, 1, 2, "B")
    retaken = apply_move_to_grid(taken, 1, 1, "W")
    assert retaken == KO_BEFORE
    assert spectate_sync(KO_BEFORE, retaken, "B").kind == "in_sync"


def test_stone_played_and_captured_during_gap_is_reimport_not_moves():
    tip = g("...../...../...../....W/.....")
    after_b = apply_move_to_grid(tip, 4, 4, "B")
    observed = apply_move_to_grid(after_b, 4, 3, "W")
    assert observed[4][4] == "." and observed[4][3] == "W"  # 黒は取られて消え、白 1 子だけ増えた
    assert spectate_sync(tip, observed, "B").kind == "reimport"


def test_parse_fox_title():
    assert parse_fox_title("> [高級対局室1] > 46372号対局室　観戦中 [98手目] - レーティング - 中国ルール") == (98, "chinese")
    assert parse_fox_title("> [高級対局室1] > 46453号大会対局室　観戦中 [85手目] - 大会") == (85, None)
    assert parse_fox_title("BlueStacks App Player") == (None, None)


def test_parse_fox_panel_real_ocr_lines():
    # 実測 2026-11-15 の OCR 出力（文字間に空白が入る・誤読行が混ざる）
    lines = ["噌 起", "黒 コ ミ 3 又 3 / 4 子", "1 分", "10 秒 1 回", "1 回 。 矜 読 み 1 回", "0 子 ア ゲ ハ マ 3 子"]
    assert parse_fox_panel(lines) == (7.5, "chinese", 3, 0)  # 左＝白が取った数、右＝黒が取った数


@pytest.mark.parametrize(
    "text,komi,rules", [("黒コミ6目半", 6.5, "japanese"), ("黒コミ7目半", 7.5, None), ("黒コミ3又3/4子", 7.5, "chinese")]
)
def test_komi_table(text, komi, rules):
    assert parse_fox_panel([text])[:2] == (komi, rules)


def test_japanese_room_komi_notation():
    # 実機 2026-11-15: 日本ルールの部屋は「黒6.5目コミ出し」。見出しを読み違えても数字で拾う
    assert parse_fox_panel(["黒 6 . 5 目 コ ミ 出 し"])[:2] == (6.5, "japanese")
    assert parse_fox_panel(["黒6.5目。ミ出し", "0子アゲハマ2子"]) == (6.5, "japanese", 2, 0)
    assert parse_fox_panel(["黒7目コミ出し"])[:2] == (7.0, "japanese")


def test_full_width_digits_are_accepted_in_the_info_inputs():
    from katrain.core.board_spectate import (
        numeric_input_filter,
        parse_spectate_captures,
        parse_spectate_komi,
    )

    assert parse_spectate_komi("６．５") == 6.5 and parse_spectate_captures("１２") == 12
    assert numeric_input_filter(True)("７．５", False) == "7.5"
    assert numeric_input_filter(True)("あ6.5目", False) == "6.5"
    assert numeric_input_filter(False)("３.2", False) == "32"


def test_komi_is_found_even_when_the_label_is_misread():
    # 実測: 1 枚目の本番の切り出しでは「黒 。 ミ 3 又 3 / 4 子」と「コ」を読み違えた
    assert parse_fox_panel(["黒 。 ミ 3 又 3 / 4 子", "0 子 ア ゲ ハ マ 0 子"]) == (7.5, "chinese", 0, 0)


def test_unknown_komi_text_is_none_not_a_guess():
    assert parse_fox_panel(["黒コミ2又1/4子", "アゲハマ"]) == (None, None, None, None)


def test_engine_komi_offset_only_for_territory_rules():
    assert engine_komi_offset("japanese", 3, 0) == -3.0
    assert engine_komi_offset("korean", 0, 2) == 2.0
    assert engine_komi_offset("chinese", 3, 0) == 0.0


def test_agehama_base_does_not_double_count():
    assert agehama_base(5, 2) == 3 and agehama_base(1, 4) == 0


def test_next_player_from():
    assert next_player_from("B", None) == "W"
    assert next_player_from(None, 85) == "W"  # 奇数手目＝黒が打った直後
    assert next_player_from(None, 98) == "B"
    assert next_player_from(None, None) is None


def test_find_window_title_uses_same_candidate_order_as_rect(monkeypatch):
    from katrain.core import tsumego_capture as tc

    seen = []

    def fake_enum(titles):
        seen.append(titles)
        return {"bluestacks": ((0, 0, 300, 300), "BlueStacks App Player"), "fox": ((1, 1, 500, 500), "Fox Go")}

    monkeypatch.setattr(tc, "_enum_window_matches", fake_enum)
    assert tc.find_window_title("Fox, BlueStacks") == "Fox Go"
    assert tc.find_window_rect("Fox, BlueStacks") == (1, 1, 500, 500)
    assert tc.find_window_title("BlueStacks,Fox") == "BlueStacks App Player"
    assert seen[0] == ["fox", "bluestacks"]
    with pytest.raises(tc.CaptureError):
        tc.find_window_title("nonexistent")


ANCESTOR = g("...../.B.../...../...../.....")


class Calls:
    def __init__(self):
        self.moves = []
        self.reimports = []
        self.status = []


def make_watcher(frames, ancestors=(), clock_step=0.0, hints=None):
    calls = Calls()
    seq = list(frames)
    t = [0.0]

    def clock():
        t[0] += clock_step
        return t[0]

    def capture():
        f = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(f, Exception):
            raise f
        return f

    w = SpectateWatcher(
        capture,
        lambda: w.state,
        lambda moves, depth, est: calls.moves.append((moves, depth, est)),
        lambda observed, reason: calls.reimports.append((observed, reason)),
        lambda kind, text: calls.status.append((kind, text)),
        spectate_watch_settings({}),
        hints_fn=hints,
        clock=clock,
    )
    w.calls = calls
    w.state = SpectateState(G0, "B", 10, 0, 5, tuple(ancestors))
    return w, calls


def test_settings():
    s = spectate_watch_settings({"spectate_poll_ms": 700, "auto_stop_sec": 60})
    assert s.poll_interval_ms == 700 and s.auto_stop_sec == 0
    assert spectate_watch_settings(None).poll_interval_ms == 1000
    assert s.stable_frames == watch_settings_from_config({}).stable_frames


def test_move_needs_two_identical_frames():
    w, calls = make_watcher(frames=[G0_PLUS_B, G0_PLUS_B])
    w.step()
    assert calls.moves == []
    w.step()
    assert calls.moves == [(((0, 0, "B"),), 0, False)]


def test_flicker_frame_is_ignored():
    w, calls = make_watcher(frames=[G0_PLUS_B, G0, G0])
    for _ in range(3):
        w.step()
    assert calls.moves == [] and calls.reimports == []


def test_reimport_needs_two_identical_frames_and_fires_once():
    w, calls = make_watcher(frames=[G0_PLUS_BB] * 4)
    for _ in range(4):
        w.step()
    assert len(calls.reimports) == 1


def test_reimport_is_confirmed_at_idle_interval_not_fast():
    w, calls = make_watcher(frames=[G0_PLUS_BB] * 2)
    w.step()
    assert w.interval_ms == w.settings.poll_interval_ms and calls.reimports == []


def test_moves_confirmation_is_fast():
    w, calls = make_watcher(frames=[G0_PLUS_B] * 2)
    w.step()
    assert w.interval_ms == w.settings.poll_interval_active_ms


def test_behind_does_nothing_and_shows_hint():
    w, calls = make_watcher(frames=[ANCESTOR] * 3, ancestors=(ANCESTOR,))
    for _ in range(3):
        w.step()
    assert calls.moves == [] and calls.reimports == [] and "過去の局面" in calls.status[-1][1]


def test_no_second_append_until_state_advances():
    w, calls = make_watcher(frames=[G0_PLUS_B] * 5)
    for _ in range(5):
        w.step()
    assert len(calls.moves) == 1


def test_never_auto_stops_and_never_warns_stall():
    w, calls = make_watcher(frames=[G0] * 3, clock_step=3600.0)
    for _ in range(3):
        w.step()
    assert not any(k in (STATUS_WARN, STATUS_IDLE) for k, _ in calls.status)
    assert not w._stopped.is_set()


def test_in_sync_status_only_on_transition():
    w, calls = make_watcher(frames=[G0] * 3)
    for _ in range(3):
        w.step()
    assert len(calls.status) == 1


def test_capture_failure_warns_but_keeps_running():
    w, calls = make_watcher(frames=[PermanentCaptureError("窓が無い"), G0])
    w.step()
    assert calls.status[-1][0] == STATUS_WARN
    w.step()
    assert calls.moves == [] and calls.reimports == []


def test_step_once_applies_without_waiting():
    w, calls = make_watcher(frames=[G0_PLUS_BWB])
    assert w.step_once().kind == "moves" and len(calls.moves) == 1
    assert calls.moves[0][2] is True


def test_step_once_reimport_and_failure():
    w, calls = make_watcher(frames=[G0_PLUS_BB])
    assert w.step_once().kind == "reimport" and len(calls.reimports) == 1
    w, calls = make_watcher(frames=[PermanentCaptureError("x")])
    assert w.step_once() is None and calls.status[-1][0] == STATUS_WARN


def test_hints_exception_is_swallowed():
    def bad():
        raise RuntimeError("x")

    w, calls = make_watcher(frames=[G0_PLUS_B] * 2, hints=bad)
    w.step()
    w.step()
    assert len(calls.moves) == 1


def test_watching_status_restored_after_warning():
    w, calls = make_watcher(frames=[G0, PermanentCaptureError("x"), G0])
    for _ in range(3):
        w.step()
    assert [k for k, _ in calls.status] == [STATUS_WATCHING, STATUS_WARN, STATUS_WATCHING]


def test_confirmation_must_be_consecutive_across_fired_key():
    w, calls = make_watcher(frames=[G0_PLUS_B, G0_PLUS_B, G0_PLUS_BB, G0_PLUS_B, G0_PLUS_BB])
    for _ in range(5):
        w.step()
    assert len(calls.moves) == 1 and calls.reimports == []


def test_no_fast_polling_after_fired_move_without_advance():
    w, calls = make_watcher(frames=[G0_PLUS_B] * 3)
    for _ in range(3):
        w.step()
    assert len(calls.moves) == 1 and w.interval_ms == w.settings.poll_interval_ms


def test_step_once_state_exception_warns_and_returns_none():
    w, calls = make_watcher(frames=[G0])

    def boom():
        raise RuntimeError("x")

    w.get_state_fn = boom
    assert w.step_once() is None and calls.status[-1][0] == STATUS_WARN


def test_state_advance_clears_dedupe():
    w, calls = make_watcher(frames=[G0_PLUS_B, G0_PLUS_B, G0_PLUS_BW, G0_PLUS_BW])
    w.step()
    w.step()
    w.state = SpectateState(G0_PLUS_B, "W", 11, 1, 5)
    w.step()
    w.step()
    assert [m[0] for m in calls.moves] == [((0, 0, "B"),), ((4, 0, "W"),)]
    assert calls.moves[1][1] == 1


# --- 観戦セッションの判断（__main__ の観戦ハンドラが使う純関数） ---


def test_append_plan_keeps_cursor_when_user_is_browsing():
    assert append_plan(cursor_is_tip=False, tip_in_tree=True, insert_mode=False) == "append_keep_cursor"
    assert append_plan(cursor_is_tip=True, tip_in_tree=True, insert_mode=False) == "append_follow"
    assert append_plan(cursor_is_tip=False, tip_in_tree=False, insert_mode=False) == "reimport"  # 末尾ノードが削除された
    assert append_plan(cursor_is_tip=True, tip_in_tree=True, insert_mode=True) == "skip"


def test_append_plan_skips_in_insert_mode_even_when_the_tip_is_gone():
    # 挿入モード中は表示位置を動かせない（Game.set_current_node が拒否する）＝取り込み直しも見送る
    assert append_plan(cursor_is_tip=False, tip_in_tree=False, insert_mode=True) == "skip"


class _Node:
    def __init__(self, parent=None):
        self.parent = parent
        self.children = []
        if parent is not None:
            parent.children.append(self)


def test_node_in_tree_follows_the_children_lists_not_only_the_parent_pointers():
    root = _Node()
    a = _Node(root)
    b = _Node(a)
    assert node_in_tree(b, root) and node_in_tree(root, root)
    # KaTrain の「ノードを削除」は親の children から外すだけで parent は残る（movetree.delete_selected_node）
    root.children.remove(a)
    assert not node_in_tree(b, root) and not node_in_tree(a, root)


def test_node_in_tree_rejects_a_node_of_another_tree():
    assert not node_in_tree(_Node(_Node()), _Node())


@pytest.mark.parametrize(
    "rows, expected",
    [
        ("...../...../...../...../.....", "B"),
        ("B..../...../...../...../.....", "W"),
        ("B..../.W.../...../...../.....", "B"),
        ("BB.../...../...../...../.....", "B"),  # 取りが起きた形＝決まらないので黒番に仮置き
        ("WW.../...../...../...../.....", "B"),
    ],
)
def test_fallback_next_player_from_stone_counts(rows, expected):
    assert fallback_next_player(g(rows)) == expected


def test_assumed_next_player_continues_alternation_from_the_tip():
    # 末尾は黒番。黒 1・白 1 が増えた＝黒番に戻る／黒だけ 1 増えた＝白番
    assert assumed_next_player("B", G0, G0_PLUS_BW) == "B"
    assert assumed_next_player("B", G0, G0_PLUS_B) == "W"
    assert assumed_next_player("W", G0, G0_PLUS_BWB) == "W"  # 交互から外れていても、多く増えた色（黒）の逆
    assert assumed_next_player("W", G0, G0) == "W"


def test_replay_counting_counts_captured_stones_by_their_colour():
    grid, captured = replay_counting(ATARI, ((1, 0, "B"),))
    assert grid == AFTER_CAPTURE and captured == {"B": 0, "W": 1}


def test_replay_counting_gives_none_for_an_unplayable_move():
    assert replay_counting(G0, ((1, 1, "W"),)) is None  # 石がある点


def test_agehama_totals_and_capture_base_cross_the_keys_like_prisoner_count():
    # 黒のアゲハマ＝取られた白石。prisoner_count / capture_base のキーは取られた石の色
    assert agehama_totals(3, 1, {"B": 2, "W": 5}) == (8, 3)
    assert capture_base_for(3, 1) == {"W": 3, "B": 1}


def test_status_text_with_the_app_move_number():
    text = spectate_status_text(2, 85, "chinese", 7.5, 3, 0)
    assert text == "観戦中 87手目  中国ルール コミ7.5  アゲハマ 黒3 白0"


def test_status_text_without_the_app_move_number():
    text = spectate_status_text(4, None, "japanese", 6.5, 0, 2)
    assert text == "観戦中（取り込みから 4 手）  日本ルール コミ6.5  アゲハマ 黒0 白2"


def test_status_text_rules_label_falls_back_to_the_name():
    assert "aga ルール" not in spectate_status_text(0, None, "aga", 7, 0, 0)
    assert "AGAルール コミ7 " in spectate_status_text(0, None, "aga", 7, 0, 0)
    assert "独自ルール" in spectate_status_text(0, None, {"scoring": "AREA"}, 7.5, 0, 0)


# --- __main__ の配線（静的検査。__main__ は Kivy 依存で import できない） ---

_MAIN = os.path.join(os.path.dirname(__file__), "..", "katrain", "__main__.py")


def _main_source():
    with open(_MAIN, encoding="utf-8") as f:
        return f.read()


def _main_functions():
    tree = ast.parse(_main_source())
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}


def _calls(func):
    return [
        (n.lineno, n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", None))
        for n in ast.walk(func)
        if isinstance(n, ast.Call)
    ]


def test_spectate_hotkey_is_in_the_board_watch_hotkey_table():
    assert '"spectate_hotkey", "ctrl+alt+w", "_spectate_trigger"' in _main_source()
    assert "_spectate_trigger" in _main_functions()


def test_spectate_import_puts_the_offset_on_the_root_before_the_new_game():
    calls = _calls(_main_functions()["_spectate_import"])
    root_line = min(line for line, name in calls if name == "spectate_root")
    new_game_line = min(line for line, name in calls if name == "_do_new_game")
    assert root_line < new_game_line


def test_rebuilding_the_game_and_stopping_the_watcher_end_the_spectate_session():
    funcs = _main_functions()
    for name in ("_do_new_game", "_stop_board_watcher", "_do_spectate_stop"):
        assert "_spectate_end" in [callee for _line, callee in _calls(funcs[name])], name


def test_game_watch_hotkey_ends_spectating_before_starting():
    trigger = ast.get_source_segment(_main_source(), _main_functions()["_board_watch_trigger"])
    assert "_spectate_session" in trigger and '"spectate-stop"' in trigger


def test_info_change_discards_old_komi_queries_before_reanalysing():
    # GameNode.set_analysis は世代を見ない＝古いコミのクエリの遅れた結果が、消したばかりの解析に混ざる
    calls = _calls(_main_functions()["_do_spectate_info"])
    discard = min(line for line, name in calls if name == "on_new_game")
    reanalyse = min(line for line, name in calls if name == "analyze_all_nodes")
    assert discard < reanalyse


def test_forget_fired_lets_the_same_verdict_fire_again():
    # 反映側が取り込めなかった（挿入モード・クリックとのすれ違い）とき、同じ盤でもう一度確定・発火させる
    w, calls = make_watcher(frames=[G0_PLUS_B] * 8)
    for _ in range(4):
        w.step()
    assert len(calls.moves) == 1  # 発火済みの判定は投げ直さない
    w.forget_fired()
    w.step()
    assert len(calls.moves) == 1  # 確定は改めて stable_frames 周
    w.step()
    assert len(calls.moves) == 2


def test_estimated_note_does_not_claim_auto_was_off():
    # 自動反映 ON でも確定待ちの間に 2 手来れば推定になる
    assert ESTIMATED_NOTE.format(n=2) == "順序は推定（まとめて反映した 2 手）"


def test_popup_players_after_spectate_restores_the_colours_the_user_did_not_touch():
    human, ai = ("player:human", "game:normal"), ("player:ai", "ai:default")
    saved = {"B": ai, "W": human}
    current = {"B": human, "W": human}  # 観戦中は両者とも人間
    assert popup_players_after_spectate(dict(current), current, saved) == saved
    jigo = ("player:ai", "ai:jigo")
    assert popup_players_after_spectate({"B": human, "W": jigo}, current, saved) == {"B": ai, "W": jigo}


def test_new_game_popup_ends_spectating_before_reading_the_player_widgets():
    # NewGamePopup.update_config は欄を読む（update_playerinfo）→ 新規対局 → 欄をもう一度読む。欄の同期は Clock で
    # 遅れるので、1 回目に読む前に観戦を終えて欄を直す。対局の編集（editgame）では観戦を終えない
    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "gui", "popups.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    cls = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef) and n.name == "NewGamePopup")
    func = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "update_config")
    names = [
        n.lineno for n in ast.walk(func) if isinstance(n, ast.Constant) and n.value == "spectate_end_for_new_game"
    ]
    calls = _calls(func)
    end_line = min(line for line, name in calls if name == "end_spectate")  # getattr(katrain, ...) で引いた口
    assert names and max(names) < end_line < min(line for line, name in calls if name == "update_playerinfo")
    guards = [n for n in ast.walk(func) if isinstance(n, ast.If) and n.lineno < end_line <= n.end_lineno]
    assert any("editgame" in ast.get_source_segment(src, g.test) for g in guards)


# --- 最終レビュー指摘 1: アプリが過去の局面・変化図を表示しても棋譜を消さない（behind） ---


def test_app_stepped_back_before_the_import_point_is_behind():
    # 野狐の ◀ で取り込み時点より前に戻った盤＝石が消えただけ（本譜の過去の局面には無い）
    v = spectate_sync(G0, G0_MINUS_STONE, "B")
    assert v.kind == "behind" and v.reason
    v = spectate_sync(G0, G0_MINUS_STONE, "B", app_move_number=7, tip_move_number=10)
    assert v.kind == "behind" and v.reason


def test_only_recoloured_cells_is_behind():
    recoloured = g("...../.W.../...../...W./.....")  # tip の黒 (1,1) が白に変わっただけ
    assert spectate_sync(G0, recoloured, "B").kind == "behind"


def test_recoloured_cell_plus_an_added_stone_still_follows_the_old_logic():
    assert spectate_sync(G0, GAP_RECOLOURED, "B").kind == "reimport"


def test_earlier_position_with_a_reappearing_stone_is_behind_by_the_move_number():
    # 黒が (1,0) で白 (0,0) を取る前の局面＝取られた白が盤に戻る（増えた石がある）。アプリの手数が本譜の末尾より前
    v = spectate_sync(AFTER_CAPTURE, ATARI, "W", app_move_number=9, tip_move_number=10)
    assert v.kind == "behind" and v.reason
    assert spectate_sync(AFTER_CAPTURE, ATARI, "W").kind == "reimport"  # 手数が読めない盤では従来どおり


def test_variation_diagram_is_behind_when_the_move_number_does_not_advance():
    # 変化図: 石が増えたのに窓タイトルの [N手目] が進まない（本物の着手は必ず手数を進める）
    v = spectate_sync(G0, G0_PLUS_B, "B", last_mover="B", app_move_number=10, tip_move_number=10)
    assert v.kind == "behind" and v.reason
    v = spectate_sync(G0, G0_PLUS_BWB, "B", last_mover="B", app_move_number=10, tip_move_number=10)
    assert v.kind == "behind"


def test_variation_like_added_stone_without_move_numbers_follows_the_old_logic():
    # 手数が読めない盤（野狐以外）では変化図と本物の着手を区別できない（既知の限界）
    assert spectate_sync(G0, G0_PLUS_B, "B", last_mover="B").kind == "moves"
    assert spectate_sync(G0, G0_PLUS_B, "B", app_move_number=10).kind == "moves"  # 片方だけでは比べない
    assert spectate_sync(G0, G0_PLUS_B, "B", tip_move_number=10).kind == "moves"
    assert spectate_sync(G0, G0_PLUS_BB, "B").kind == "reimport"


def test_move_number_ahead_but_inconsistent_still_reimports():
    assert spectate_sync(G0, G0_PLUS_B, "B", app_move_number=12, tip_move_number=10).kind == "reimport"


def test_ancestor_behind_carries_a_reason():
    v = spectate_sync(G0_PLUS_BWB, G0_PLUS_B, "W", ancestor_grids=(G0, G0_PLUS_B, G0_PLUS_BW))
    assert v.kind == "behind" and v.reason


def test_watcher_waits_while_the_app_shows_an_earlier_position():
    w, calls = make_watcher(frames=[G0_MINUS_STONE] * 3)
    for _ in range(3):
        w.step()
    assert calls.moves == [] and calls.reimports == []
    assert calls.status == [(STATUS_WATCHING, BEHIND_TEXT)]
    assert w.interval_ms == w.settings.poll_interval_ms


def test_watcher_waits_while_the_app_shows_a_variation_diagram():
    # 窓タイトルの手数（ヒント）が本譜の末尾（10 手目）のまま石が増えた
    w, calls = make_watcher(frames=[G0_PLUS_B] * 3, hints=lambda: ("B", 10))
    for _ in range(3):
        w.step()
    assert calls.moves == [] and calls.reimports == [] and calls.status == [(STATUS_WATCHING, BEHIND_TEXT)]
    assert w.interval_ms == w.settings.poll_interval_ms
    assert w.step_once().kind == "behind" and calls.moves == [] and calls.reimports == []


# --- 最終レビュー指摘 3: 本物の手を本筋（children[0]）にする ---


def test_promote_to_main_line_moves_each_node_to_the_front_and_keeps_the_others():
    root = _Node()
    user = _Node(root)  # 末尾でユーザーが検討した変化
    real = _Node(root)  # アプリの本物の手（game.play は children の末尾に足す）
    after = _Node(real)
    assert promote_to_main_line([real, after])
    assert root.children == [real, user] and real.children == [after]
    assert not promote_to_main_line([real, after])  # 既に本筋なら何もしない


# --- 最終レビュー指摘 M4: read_spectate_info は例外を外へ出さない ---


class _FoxInfoReader:
    """read_spectate_info 用の野狐の偽リーダー。fail に挙げた口が例外を投げる"""

    _board_rect = (0, 0, 100, 100)

    def __init__(self, fail=()):
        self.fail = set(fail)

    def _maybe_fail(self, name):
        if name in self.fail:
            raise RuntimeError(name)

    def last_mover_color(self):
        self._maybe_fail("last_mover")
        return "W"

    def profile_name(self):
        return "fox"

    def window_title_text(self):
        self._maybe_fail("title")
        return "> [高級対局室1] > 46372号対局室 観戦中 [98手目] - レーティング - 中国ルール"

    def last_image(self):
        self._maybe_fail("image")
        return SimpleNamespace(size=(300, 100), crop=lambda box: ("panel", box))


def _ocr_ok(_img):
    return ["黒コミ3又3/4子", "0子アゲハマ3子"]


def _ocr_boom(_img):
    raise RuntimeError("OCR が落ちた")


def test_read_spectate_info_reads_the_fake_fox_window():
    assert read_spectate_info(_FoxInfoReader(), ocr=_ocr_ok) == SpectateInfo("chinese", 7.5, 3, 0, "B", 98)


def test_read_spectate_info_keeps_the_title_when_the_screenshot_fails():
    got = read_spectate_info(_FoxInfoReader(fail={"image"}), ocr=_ocr_ok)
    assert got == SpectateInfo(rules="chinese", next_player="B", app_move_number=98)


def test_read_spectate_info_keeps_the_title_when_ocr_fails():
    got = read_spectate_info(_FoxInfoReader(), ocr=_ocr_boom)
    assert got == SpectateInfo(rules="chinese", next_player="B", app_move_number=98)


def test_read_spectate_info_never_raises():
    assert read_spectate_info(_FoxInfoReader(fail={"last_mover", "title", "image"}), ocr=_ocr_ok) == SpectateInfo()
    got = read_spectate_info(_FoxInfoReader(fail={"last_mover"}), ocr=_ocr_ok)
    assert got.app_move_number == 98 and got.next_player == "B" and got.komi == 7.5  # 手番は手数の偶奇から
    got = read_spectate_info(_FoxInfoReader(fail={"title"}), ocr=_ocr_ok)
    assert got == SpectateInfo("chinese", 7.5, 3, 0, "B", None)  # パネルは読む・ルールはコミの表記から


# --- 最終レビュー指摘 M3: 対局の編集でルールを変えたらエンジンへのコミ補正を計算し直す ---


def test_edit_game_recomputes_the_komi_offset_before_reanalysing():
    path = os.path.join(os.path.dirname(__file__), "..", "katrain", "gui", "popups.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()
    cls = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ClassDef) and n.name == "NewGamePopup")
    func = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "update_config")
    calls = _calls(func)
    recompute = [line for line, name in calls if name == "komi_offset_after_rules_change"]
    discard = min(line for line, name in calls if name == "on_new_game")
    assert recompute and max(recompute) < discard

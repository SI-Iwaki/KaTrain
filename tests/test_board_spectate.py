import pytest

from katrain.core.board_spectate import (
    agehama_base,
    engine_komi_offset,
    next_player_from,
    parse_fox_panel,
    parse_fox_title,
    spectate_sync,
)
from katrain.core.board_spectate import SpectateState, SpectateWatcher, spectate_watch_settings
from katrain.core.board_watch import STATUS_WARN, PermanentCaptureError, apply_move_to_grid, watch_settings_from_config


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


def test_order_that_needs_capture_first_is_found():
    v = spectate_sync(NEEDS_ORDER, NEEDS_ORDER_AFTER, "B")
    assert v.kind == "moves" and replay(NEEDS_ORDER, v.moves) == NEEDS_ORDER_AFTER


@pytest.mark.parametrize(
    "tip,obs,kw",
    [
        (G0, G0_PLUS_BB, {}),  # 黒 2 手＝交互にならない
        (KO_BEFORE, CAPTURE_NOT_REFLECTED, {}),  # 取りが盤に反映されていない盤
        (G0, G0_MINUS_STONE, {}),  # 石が消えただけ
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
        self.idle_stops = 0


def make_watcher(frames, ancestors=(), clock_step=0.0, hints=None):
    calls = Calls()
    seq = list(frames)
    state = SpectateState(G0, "B", 10, 0, 5, tuple(ancestors))
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
        lambda: state,
        lambda moves, depth, est: calls.moves.append((moves, depth, est)),
        lambda observed, reason: calls.reimports.append((observed, reason)),
        lambda kind, text: calls.status.append((kind, text)),
        spectate_watch_settings({}),
        hints_fn=hints,
        clock=clock,
    )
    w.calls = calls
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
    w, calls = make_watcher(frames=[G0_MINUS_STONE] * 4)
    for _ in range(4):
        w.step()
    assert len(calls.reimports) == 1


def test_reimport_is_confirmed_at_idle_interval_not_fast():
    w, calls = make_watcher(frames=[G0_MINUS_STONE] * 2)
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
    assert calls.idle_stops == 0 and not any(k == STATUS_WARN for k, _ in calls.status)
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
    w, calls = make_watcher(frames=[G0_MINUS_STONE])
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

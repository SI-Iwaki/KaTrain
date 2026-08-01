"""isort:skip_file"""

# first, logging level lower
import os
import sys

os.environ["KCFG_KIVY_LOG_LEVEL"] = os.environ.get("KCFG_KIVY_LOG_LEVEL", "warning")

from kivy.utils import platform as kivy_platform

if kivy_platform == "win":
    from ctypes import windll, c_int64

    if hasattr(windll.user32, "SetProcessDpiAwarenessContext"):
        windll.user32.SetProcessDpiAwarenessContext(c_int64(-4))

import kivy

kivy.require("2.0.0")

# next, icon
from katrain.core.utils import find_package_resource, PATHS
from kivy.config import Config

if kivy_platform == "macosx":
    ICON = find_package_resource("katrain/img/icon.icns")
else:
    ICON = find_package_resource("katrain/img/icon.ico")
Config.set("kivy", "window_icon", ICON)
Config.set("input", "mouse", "mouse,multitouch_on_demand")

# next, certificates on package builds https://github.com/sanderland/katrain/issues/414
if getattr(sys, "frozen", False):
    import ssl

    if ssl.get_default_verify_paths().cafile is None and hasattr(sys, "_MEIPASS"):
        os.environ["SSL_CERT_FILE"] = os.path.join(sys._MEIPASS, "certifi", "cacert.pem")


import ctypes
import re
import signal
import json
import threading
import traceback
from queue import Queue
import urllib3
import webbrowser
import time
import random
import glob

from kivy.base import ExceptionHandler, ExceptionManager
from kivy.app import App
from kivy.core.clipboard import Clipboard
from kivy.lang import Builder
from kivy.resources import resource_add_path
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen
from kivy.core.window import Window
from kivy.uix.widget import Widget
from kivy.resources import resource_find
from kivy.properties import BooleanProperty, NumericProperty, ObjectProperty, StringProperty
from kivy.clock import Clock
from kivy.metrics import dp
from katrain.core.ai import generate_ai_move

from katrain.core.lang import DEFAULT_LANGUAGE, i18n
from katrain.core.constants import (
    OUTPUT_ERROR,
    OUTPUT_KATAGO_STDERR,
    OUTPUT_INFO,
    OUTPUT_DEBUG,
    OUTPUT_EXTRA_DEBUG,
    MODE_ANALYZE,
    HOMEPAGE,
    VERSION,
    STATUS_ERROR,
    STATUS_INFO,
    PLAYING_NORMAL,
    PLAYER_HUMAN,
    SGF_INTERNAL_COMMENTS_MARKER,
    MODE_PLAY,
    DATA_FOLDER,
    AI_DEFAULT,
    AI_TSUMEGO,
    AI_TSUMEGO_SOLVER,
)
from katrain.gui.popups import (
    ConfigTeacherPopup,
    ConfigTimerPopup,
    I18NPopup,
    SaveSGFPopup,
    ContributePopup,
    EngineRecoveryPopup,
)
from katrain.gui.sound import play_sound
from katrain.core.base_katrain import KaTrainBase
from katrain.core.engine import KataGoEngine
from katrain.core.contribute_engine import KataGoContributeEngine
from katrain.core.game import (
    Game,
    IllegalMoveException,
    KaTrainSGF,
    BaseGame,
    REGION_ANALYSIS_WIDE_ROOT_NOISE,
    region_analysis_extra_settings,
)
from katrain.core.sgf_parser import Move, ParseError
from katrain.gui.popups import ConfigPopup, LoadSGFPopup, NewGamePopup, ConfigAIPopup
from katrain.gui.theme import Theme
from kivymd.app import MDApp

# used in kv
from katrain.gui.kivyutils import *
from katrain.gui.widgets import MoveTree, I18NFileBrowser, SelectionSlider, ScoreGraph  # noqa F401
from katrain.gui.badukpan import AnalysisControls, BadukPanControls, BadukPanWidget  # noqa F401
from katrain.gui.controlspanel import ControlsPanel  # noqa F401


class KaTrainGui(Screen, KaTrainBase):
    """Top level class responsible for tying everything together"""

    zen = NumericProperty(0)
    tsumego_view = BooleanProperty(False)  # 詰碁専用表示: 右パネル+上部トグル非表示、下部ナビは残す
    controls = ObjectProperty(None)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.engine = None
        self.contributing = False

        self.new_game_popup = None
        self.fileselect_popup = None
        self.config_popup = None
        self.ai_settings_popup = None
        self.teacher_settings_popup = None
        self.timer_settings_popup = None
        self.contribute_popup = None

        self.pondering = False
        self.show_move_num = False

        self.animate_contributing = False
        self.message_queue = Queue()

        self.last_key_down = None
        self.last_focus_event = 0

    def log(self, message, level=OUTPUT_INFO):
        super().log(message, level)
        if level == OUTPUT_KATAGO_STDERR and "ERROR" not in self.controls.status.text:
            if self.contributing:
                self.controls.set_status(message, STATUS_INFO)
            elif "starting" in message.lower():
                self.controls.set_status("KataGo engine starting...", STATUS_INFO)
            elif message.startswith("Tuning"):
                self.controls.set_status(
                    "KataGo is tuning settings for first startup, please wait." + message, STATUS_INFO
                )
                return
            elif "ready" in message.lower():
                self.controls.set_status("KataGo engine ready.", STATUS_INFO)
        if (
            level == OUTPUT_ERROR
            or (level == OUTPUT_KATAGO_STDERR and "error" in message.lower() and "tuning" not in message.lower())
        ) and getattr(self, "controls", None):
            self.controls.set_status(f"ERROR: {message}", STATUS_ERROR)

    def handle_animations(self, *_args):
        if self.contributing and self.animate_contributing:
            self.engine.advance_showing_game()
        if (self.contributing and self.animate_contributing) or self.pondering:
            self.board_controls.engine_status_pondering += 5
        else:
            self.board_controls.engine_status_pondering = -1

    @property
    def play_analyze_mode(self):
        return self.play_mode.mode

    def toggle_continuous_analysis(self, quiet=False):
        if self.contributing:
            self.animate_contributing = not self.animate_contributing
        else:
            if self.pondering:
                self.controls.set_status("", STATUS_INFO)
            elif not quiet:  # See #549
                Clock.schedule_once(self.analysis_controls.hints.activate, 0)
            self.pondering = not self.pondering
            self.update_state()

    def toggle_move_num(self):
        self.show_move_num = not self.show_move_num
        self.update_state()

    def start(self):
        if self.engine:
            return
        self.board_gui.trainer_config = self.config("trainer")
        self.engine = KataGoEngine(self, self.config("engine"))
        threading.Thread(target=self._message_loop_thread, daemon=True).start()
        sgf_args = [
            f
            for f in sys.argv[1:]
            if os.path.isfile(f) and any(f.lower().endswith(ext) for ext in ["sgf", "ngf", "gib"])
        ]
        if sgf_args:
            self.load_sgf_file(sgf_args[0], fast=True, rewind=True)
        else:
            self._do_new_game(_log=False)

        Clock.schedule_interval(self.handle_animations, 0.1)
        Window.request_keyboard(None, self, "").bind(on_key_down=self._on_keyboard_down, on_key_up=self._on_keyboard_up)

        def set_focus_event(*args):
            self.last_focus_event = time.time()

        MDApp.get_running_app().root_window.bind(focus=set_focus_event)
        self._setup_tsumego_capture()

    def update_gui(self, cn, redraw_board=False):
        # Handle prisoners and next player display
        prisoners = self.game.prisoner_count
        top, bot = [w.__self__ for w in self.board_controls.circles]  # no weakref
        if self.next_player_info.player == "W":
            top, bot = bot, top
            self.controls.players["W"].active = True
            self.controls.players["B"].active = False
        else:
            self.controls.players["W"].active = False
            self.controls.players["B"].active = True
        self.board_controls.mid_circles_container.clear_widgets()
        self.board_controls.mid_circles_container.add_widget(bot)
        self.board_controls.mid_circles_container.add_widget(top)

        self.controls.players["W"].captures = prisoners["W"]
        self.controls.players["B"].captures = prisoners["B"]

        # update engine status dot
        if not self.engine or not self.engine.katago_process or self.engine.katago_process.poll() is not None:
            self.board_controls.engine_status_col = Theme.ENGINE_DOWN_COLOR
        elif self.engine.is_idle():
            self.board_controls.engine_status_col = Theme.ENGINE_READY_COLOR
        else:
            self.board_controls.engine_status_col = Theme.ENGINE_BUSY_COLOR
        self.board_controls.queries_remaining = self.engine.queries_remaining()

        # redraw board/stones
        if redraw_board:
            self.board_gui.draw_board()
        self.board_gui.redraw_board_contents_trigger()
        self.controls.update_evaluation()
        self.controls.update_timer(1)
        # update move tree
        self.controls.move_tree.current_node = self.game.current_node

    def update_state(self, redraw_board=False):  # redirect to message queue thread
        self("update_state", redraw_board=redraw_board)

    def _do_update_state(
        self, redraw_board=False
    ):  # is called after every message and on receiving analyses and config changes
        # AI and Trainer/auto-undo handlers
        if not self.game or not self.game.current_node:
            return
        cn = self.game.current_node
        if not self.contributing:
            last_player, next_player = self.players_info[cn.player], self.players_info[cn.next_player]
            if self.play_analyze_mode == MODE_PLAY and self.nav_drawer.state != "open" and self.popup_open is None:
                points_lost = cn.points_lost
                if (
                    last_player.human
                    and cn.analysis_complete
                    and points_lost is not None
                    and points_lost > self.config("trainer/eval_thresholds")[-4]
                ):
                    self.play_mistake_sound(cn)
                teaching_undo = cn.player and last_player.being_taught and cn.parent
                if (
                    teaching_undo
                    and cn.analysis_complete
                    and cn.parent.analysis_complete
                    and not cn.children
                    and not self.game.end_result
                ):
                    self.game.analyze_undo(cn)  # not via message loop
                if (
                    cn.analysis_complete
                    and next_player.ai
                    and not cn.children
                    and not self.game.end_result
                    and not (teaching_undo and cn.auto_undo is None)
                ):  # cn mismatch stops this if undo fired. avoid message loop here or fires repeatedly.
                    region = self.game.region_of_interest
                    if not region or cn.analysis.get("region_completed"):
                        self._do_ai_move(cn)
                        Clock.schedule_once(self._play_stone_sound, 0.25)
                    elif not cn.analysis.get("region_requested"):
                        # リージョン設定時、全盤fast解析だけでAIを発火させると刈り取り前の枠外・浅読み
                        # 候補を打ってしまう。リージョン解析が未発行の局面（手動リージョン選択直後等）
                        # では一度だけ発行して完了を待つ（Game.play/_do_tsumego_frame 経由は発行済み）
                        cn.analyze(self.game.engines[cn.next_player], region_of_interest=region)
            if self.engine:
                if self.pondering:
                    self.game.analyze_extra("ponder")
                else:
                    self.engine.stop_pondering()
        Clock.schedule_once(lambda _dt: self.update_gui(cn, redraw_board=redraw_board), -1)  # trigger?

    def update_player(self, bw, **kwargs):
        super().update_player(bw, **kwargs)
        if self.game:
            sgf_name = self.game.root.get_property("P" + bw)
            self.players_info[bw].name = None if not sgf_name or SGF_INTERNAL_COMMENTS_MARKER in sgf_name else sgf_name
        if self.controls:
            self.controls.update_players()
            self.update_state()
        for player_setup_block in PlayerSetupBlock.INSTANCES:
            player_setup_block.update_player_info(bw, self.players_info[bw])

    def set_note(self, note):
        self.game.current_node.note = note

    # The message loop is here to make sure moves happen in the right order, and slow operations don't hang the GUI
    def _message_loop_thread(self):
        while True:
            game, msg, args, kwargs = self.message_queue.get()
            try:
                self.log(f"Message Loop Received {msg}: {args} for Game {game}", OUTPUT_EXTRA_DEBUG)
                if game != self.game.game_id:
                    self.log(
                        f"Message skipped as it is outdated (current game is {self.game.game_id}", OUTPUT_EXTRA_DEBUG
                    )
                    continue
                msg = msg.replace("-", "_")
                if self.contributing:
                    if msg not in [
                        "katago_contribute",
                        "redo",
                        "undo",
                        "update_state",
                        "save_game",
                        "find_mistake",
                    ]:
                        self.controls.set_status(
                            i18n._("gui-locked").format(action=msg), STATUS_INFO, check_level=False
                        )
                        continue
                fn = getattr(self, f"_do_{msg}")
                fn(*args, **kwargs)
                if msg != "update_state":
                    self._do_update_state()
            except Exception as exc:
                self.log(f"Exception in processing message {msg} {args}: {exc}", OUTPUT_ERROR)
                traceback.print_exc()

    def __call__(self, message, *args, **kwargs):
        if self.game:
            if message.endswith("popup"):  # gui code needs to run in main kivy thread.
                if self.contributing and "save" not in message and message != "contribute-popup":
                    self.controls.set_status(
                        i18n._("gui-locked").format(action=message), STATUS_INFO, check_level=False
                    )
                    return
                fn = getattr(self, f"_do_{message.replace('-', '_')}")
                Clock.schedule_once(lambda _dt: fn(*args, **kwargs), -1)
            else:  # game related actions
                self.message_queue.put([self.game.game_id, message, args, kwargs])

    def _do_new_game(self, move_tree=None, analyze_fast=False, sgf_filename=None, _log=True):
        if _log:
            self.start_game_log()
        self.pondering = False
        mode = self.play_analyze_mode
        if (move_tree is not None and mode == MODE_PLAY) or (move_tree is None and mode == MODE_ANALYZE):
            self.play_mode.switch_ui_mode()  # for new game, go to play, for loaded, analyze
        self.board_gui.animating_pv = None
        self.board_gui.reset_rotation()
        self.engine.on_new_game()  # clear queries
        self.game = Game(
            self,
            self.engine,
            move_tree=move_tree,
            analyze_fast=analyze_fast or not move_tree,
            sgf_filename=sgf_filename,
        )
        for bw, player_info in self.players_info.items():
            player_info.sgf_rank = self.game.root.get_property(bw + "R")
            player_info.calculated_rank = None
            if sgf_filename is not None:  # load game->no ai player
                player_info.player_type = PLAYER_HUMAN
                player_info.player_subtype = PLAYING_NORMAL
            self.update_player(bw, player_type=player_info.player_type, player_subtype=player_info.player_subtype)
        self.controls.graph.initialize_from_game(self.game.root)
        self.update_state(redraw_board=True)

    def _do_katago_contribute(self):
        if self.contributing and not self.engine.server_error and self.engine.katago_process is not None:
            return
        self.contributing = self.animate_contributing = True  # special mode
        if self.play_analyze_mode == MODE_PLAY:  # switch to analysis view
            self.play_mode.switch_ui_mode()
        self.pondering = False
        self.board_gui.animating_pv = None
        for bw, player_info in self.players_info.items():
            self.update_player(bw, player_type=PLAYER_AI, player_subtype=AI_DEFAULT)
        self.engine.shutdown(finish=False)
        self.engine = KataGoContributeEngine(self)
        self.game = BaseGame(self)

    def _do_insert_mode(self, mode="toggle"):
        self.game.set_insert_mode(mode)
        if self.play_analyze_mode != MODE_ANALYZE:
            self.play_mode.switch_ui_mode()

    def _do_ai_move(self, node=None):
        if node is None or self.game.current_node == node:
            mode = self.next_player_info.strategy
            settings = self.config(f"ai/{mode}")
            if settings is not None:
                generate_ai_move(self.game, mode, settings)
            else:
                self.log(f"AI Mode {mode} not found!", OUTPUT_ERROR)

    def _do_undo(self, n_times=1):
        if n_times == "smart":
            n_times = 1
            if self.play_analyze_mode == MODE_PLAY and self.last_player_info.ai and self.next_player_info.human:
                n_times = 2
        self.board_gui.animating_pv = None
        self.game.undo(n_times)

    def _do_reset_analysis(self):
        self.game.reset_current_analysis()

    def _do_resign(self):
        self.game.current_node.end_state = f"{self.game.current_node.player}+R"

    def _do_redo(self, n_times=1):
        self.board_gui.animating_pv = None
        self.game.redo(n_times)

    def _do_rotate(self):
        self.board_gui.rotate_gridpos()

    def _do_find_mistake(self, fn="redo"):
        self.board_gui.animating_pv = None
        getattr(self.game, fn)(9999, stop_on_mistake=self.config("trainer/eval_thresholds")[-4])

    def _do_switch_branch(self, *args):
        self.board_gui.animating_pv = None
        self.controls.move_tree.switch_branch(*args)

    def _play_stone_sound(self, _dt=None):
        play_sound(random.choice(Theme.STONE_SOUNDS))

    def _do_play(self, coords):
        self.board_gui.animating_pv = None
        try:
            old_prisoner_count = self.game.prisoner_count["W"] + self.game.prisoner_count["B"]
            self.game.play(Move(coords, player=self.next_player_info.player))
            if old_prisoner_count < self.game.prisoner_count["W"] + self.game.prisoner_count["B"]:
                play_sound(Theme.CAPTURING_SOUND)
            elif not self.game.current_node.is_pass:
                self._play_stone_sound()

        except IllegalMoveException as e:
            self.controls.set_status(f"Illegal Move: {str(e)}", STATUS_ERROR)

    def _do_analyze_extra(self, mode, **kwargs):
        self.game.analyze_extra(mode, **kwargs)

    def _do_selfplay_setup(self, until_move, target_b_advantage=None):
        self.game.selfplay(int(until_move) if isinstance(until_move, float) else until_move, target_b_advantage)

    def _do_select_box(self):
        self.controls.set_status(i18n._("analysis:region:start"), STATUS_INFO)
        self.board_gui.selecting_region_of_interest = True

    def _do_new_game_popup(self):
        self.controls.timer.paused = True
        if not self.new_game_popup:
            self.new_game_popup = I18NPopup(
                title_key="New Game title", size=[dp(800), dp(900)], content=NewGamePopup(self)
            ).__self__
            self.new_game_popup.content.popup = self.new_game_popup
        self.new_game_popup.open()
        self.new_game_popup.content.update_from_current_game()

    def _do_timer_popup(self):
        self.controls.timer.paused = True
        if not self.timer_settings_popup:
            self.timer_settings_popup = I18NPopup(
                title_key="timer settings", size=[dp(600), dp(500)], content=ConfigTimerPopup(self)
            ).__self__
            self.timer_settings_popup.content.popup = self.timer_settings_popup
        self.timer_settings_popup.open()

    def _do_teacher_popup(self):
        self.controls.timer.paused = True
        if not self.teacher_settings_popup:
            self.teacher_settings_popup = I18NPopup(
                title_key="teacher settings", size=[dp(800), dp(825)], content=ConfigTeacherPopup(self)
            ).__self__
            self.teacher_settings_popup.content.popup = self.teacher_settings_popup
        self.teacher_settings_popup.open()

    def _do_config_popup(self):
        self.controls.timer.paused = True
        if not self.config_popup:
            self.config_popup = I18NPopup(
                title_key="general settings title", size=[dp(1200), dp(950)], content=ConfigPopup(self)
            ).__self__
            self.config_popup.content.popup = self.config_popup
            self.config_popup.title += ": " + self.config_file
        self.config_popup.open()

    def _do_contribute_popup(self):
        if not self.contribute_popup:
            self.contribute_popup = I18NPopup(
                title_key="contribute settings title", size=[dp(1100), dp(800)], content=ContributePopup(self)
            ).__self__
            self.contribute_popup.content.popup = self.contribute_popup
        self.contribute_popup.open()

    def _do_ai_popup(self):
        self.controls.timer.paused = True
        if not self.ai_settings_popup:
            self.ai_settings_popup = I18NPopup(
                title_key="ai settings", size=[dp(750), dp(830)], content=ConfigAIPopup(self)
            ).__self__
            self.ai_settings_popup.content.popup = self.ai_settings_popup
        self.ai_settings_popup.open()

    def _do_engine_recovery_popup(self, error_message, code):
        current_open = self.popup_open
        if current_open and isinstance(current_open.content, EngineRecoveryPopup):
            self.log(f"Not opening engine recovery popup with {error_message} as one is already open", OUTPUT_DEBUG)
            return
        popup = I18NPopup(
            title_key="engine recovery",
            size=[dp(600), dp(700)],
            content=EngineRecoveryPopup(self, error_message=error_message, code=code),
        ).__self__
        popup.content.popup = popup
        popup.open()

    def _do_tsumego_frame(self, ko, margin):
        from katrain.core.tsumego_frame import tsumego_frame_from_katrain_game

        if not self.game.stones:
            return

        black_to_play_p = self.next_player_info.player == "B"
        node, analysis_region = tsumego_frame_from_katrain_game(
            self.game, self.game.komi, black_to_play_p, ko_p=ko, margin=margin
        )
        self.game.set_current_node(node)
        if self.play_mode.mode == MODE_PLAY:
            self.play_mode.switch_ui_mode()  # go to analysis mode
        if analysis_region:
            flattened_region = [
                analysis_region[0][1],
                analysis_region[0][0],
                analysis_region[1][1],
                analysis_region[1][0],
            ]
            self.game.set_region_of_interest(flattened_region)
        engine = self.game.engines[node.next_player]
        if self.game.region_of_interest:
            # Game.play() と同じ2段構え: 全盤の高速解析で root 勝率を得てから、リージョン限定で本解析
            # （これがないと初期解析が全盤対象になり、枠外の詰め物エリアの手が最善手として表示される）
            deep_visits = self.game.region_analysis_visits
            node.analyze(engine, analyze_fast=True)
            node.analyze(
                engine,
                region_of_interest=self.game.region_of_interest,
                visits=deep_visits,
                time_limit=deep_visits is None,
                extra_settings=region_analysis_extra_settings(
                    deep_visits, self.game.region_analysis_wide_root_noise
                ),
                # ai:tsumego が候補手ごとの ownership を使う。詰碁キャプチャ経由
                # （deep_visits あり）のときだけ要求する
                ownership=True if deep_visits else None,
            )
        else:
            node.analyze(engine)
        self.update_state(redraw_board=True)

    def _apply_tsumego_region(self, analysis_region, board_size):
        """リージョンを設定し、全盤fast → リージョン限定の2段解析を発行する。

        analysis_region は tsumego_frame_board が返す ((imin, imax), (jmin, jmax))。
        この i は認識グリッド（tsumego_capture.classify_intersections）準拠の上origin
        （画面上でcyが下に増えるのに合わせて上から数えた行）。一方 KaTrain の
        Move.coords / set_region_of_interest が使う y は下origin
        （sgf_parser.Move.from_sgf の y = board_size - sgf_row_index - 1 と同じ変換）。
        ここで y = board_size - 1 - i に変換しないと縦方向が反転したリージョンになり、
        詰碁本体の一部がリージョン外に落ちて誤答の原因になる（実測で確認済みのバグ）。
        手動枠付け経路（_do_tsumego_frame）は game.board から作るため既に下origin i=y
        になっており、この変換は不要（対象が異なるので流用しない）。
        """
        node = self.game.current_node
        if self.play_mode.mode == MODE_PLAY:
            self.play_mode.switch_ui_mode()  # go to analysis mode
        if analysis_region:
            (imin, imax), (jmin, jmax) = analysis_region
            ymin, ymax = board_size - 1 - imax, board_size - 1 - imin  # 上origin i → 下origin y
            self.game.set_region_of_interest([jmin, jmax, ymin, ymax])
        engine = self.game.engines[node.next_player]
        if self.game.region_of_interest:
            # Game.play() と同じ2段構え: 全盤の高速解析で root 勝率を得てから、リージョン限定で本解析
            # （これがないと初期解析が全盤対象になり、枠外の詰め物エリアの手が最善手として表示される）
            deep_visits = self.game.region_analysis_visits
            node.analyze(engine, analyze_fast=True)
            node.analyze(
                engine,
                region_of_interest=self.game.region_of_interest,
                visits=deep_visits,
                time_limit=deep_visits is None,
                extra_settings=region_analysis_extra_settings(
                    deep_visits, self.game.region_analysis_wide_root_noise
                ),
                # ai:tsumego が候補手ごとの ownership を使う。詰碁キャプチャ経由
                # （deep_visits あり）のときだけ要求する
                ownership=True if deep_visits else None,
            )
        else:
            node.analyze(engine)
        self.update_state(redraw_board=True)

    # Win32 グローバルホットキー用の定数
    _HOTKEY_MODS = {"alt": 0x0001, "ctrl": 0x0002, "control": 0x0002, "shift": 0x0004, "win": 0x0008, "super": 0x0008}
    _HOTKEY_NAMED_KEYS = {
        "space": 0x20,
        "esc": 0x1B,
        "escape": 0x1B,
        "tab": 0x09,
        "enter": 0x0D,
        "return": 0x0D,
        "backspace": 0x08,
        "insert": 0x2D,
        "delete": 0x2E,
        "home": 0x24,
        "end": 0x23,
        "pageup": 0x21,
        "pagedown": 0x22,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
    }
    _MOD_NOREPEAT = 0x4000  # 押しっぱなしの自動リピートで多重発火させない
    _WM_HOTKEY = 0x0312
    _TSUMEGO_HOTKEY_ID = 0xA71

    @classmethod
    def _parse_hotkey(cls, spec):
        """ホットキー文字列（f4 / ctrl+shift+g 等）を RegisterHotKey 用の (modifiers, 仮想キーコード) に変換する"""
        mods, key = 0, None
        for part in spec.lower().replace(" ", "").split("+"):
            if part in cls._HOTKEY_MODS:
                mods |= cls._HOTKEY_MODS[part]
            elif part:
                key = part
        if not key:
            raise ValueError(f"キー本体が指定されていません: {spec!r}")
        if re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key):
            return mods, 0x6F + int(key[1:])  # VK_F1 = 0x70
        if key in cls._HOTKEY_NAMED_KEYS:
            return mods, cls._HOTKEY_NAMED_KEYS[key]
        if len(key) == 1:
            # 引数は WCHAR 値。argtypes を指定しないと ctypes が str をポインタに変換して必ず -1 になる
            user32 = ctypes.windll.user32
            user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
            user32.VkKeyScanW.restype = ctypes.c_short
            scan = user32.VkKeyScanW(key)
            if scan != -1:
                return mods, scan & 0xFF  # 上位バイトのシフト状態は使わない（修飾キーは spec 側で指定する）
        raise ValueError(f"未対応のキー指定です: {spec!r}")

    def _setup_tsumego_capture(self):
        settings = self._config.get("tsumego_capture") or {}
        if not settings.get("enabled", False):
            return
        if sys.platform != "win32":
            self.log("tsumego_capture: Windows 専用機能のためホットキーは登録しません", OUTPUT_INFO)
            return
        from katrain.core.tsumego_capture import ensure_dpi_awareness

        ensure_dpi_awareness()
        spec = settings.get("hotkey", "f4")
        try:
            mods, vk = self._parse_hotkey(spec)
        except ValueError as e:
            self.log(f"tsumego_capture: ホットキー設定が不正です: {e}", OUTPUT_ERROR)
            return
        self._tsumego_capture_busy = False
        threading.Thread(target=self._tsumego_hotkey_loop, args=(spec, mods, vk), daemon=True).start()

    def _tsumego_hotkey_loop(self, spec, mods, vk):
        """RegisterHotKey で登録し、専用スレッドのメッセージループで WM_HOTKEY を待つ。

        以前は keyboard パッケージの WH_KEYBOARD_LL フックを使っていたが、フックのコールバックが
        LowLevelHooksTimeout（レジストリ未設定なら既定 300ms）を超えると Windows がフックを黙って
        チェーンから外す。KaTrain では Kivy 描画や KataGo 解析結果の処理で GIL が長く握られることが
        あり、それに巻き込まれてホットキーが突然無反応になっていた（listen スレッドは GetMessage
        ループのまま生き続けるので、プロセスを外から見ても異常に見えないのが厄介だった）。
        RegisterHotKey なら WM_HOTKEY がこのスレッドのメッセージキューに積まれるため取りこぼさない。
        """
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, self._TSUMEGO_HOTKEY_ID, mods | self._MOD_NOREPEAT, vk):
            self.log(
                f"tsumego_capture: ホットキー {spec} の登録に失敗しました"
                f"（他のアプリが同じキーを使用している可能性があります）",
                OUTPUT_ERROR,
            )
            return
        self.log(f"tsumego_capture: ホットキー {spec} を登録しました", OUTPUT_INFO)
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == self._WM_HOTKEY:
                    # キャプチャ中もメッセージループを止めないよう、実処理は作業スレッドに投げる
                    threading.Thread(target=self._tsumego_capture_trigger, daemon=True).start()
        finally:
            user32.UnregisterHotKey(None, self._TSUMEGO_HOTKEY_ID)

    def _tsumego_capture_trigger(self):
        # ホットキースレッドが起こした作業スレッドで実行される。
        # 認識までここで行い、盤面への反映はメッセージループに投げる
        from katrain.core.tsumego_capture import CaptureError, capture_tsumego_grid

        now = time.time()
        if now - getattr(self, "_tsumego_capture_last_trigger", 0.0) < 2.0:
            return
        self._tsumego_capture_last_trigger = now
        if getattr(self, "_tsumego_capture_busy", False):
            return
        self._tsumego_capture_busy = True
        try:
            settings = self._config.get("tsumego_capture") or {}
            try:
                grid = capture_tsumego_grid(settings)
                ko = settings.get("frame_ko", False)
                margin = int(settings.get("frame_margin", 4))
            except CaptureError as e:
                self._tsumego_capture_failed(f"詰碁キャプチャ失敗: {e}")
                return
            except Exception as e:
                self._tsumego_capture_failed(f"詰碁キャプチャで予期しないエラー: {e}")
                return
            self("tsumego-capture-apply", grid, ko, margin)
        finally:
            self._tsumego_capture_busy = False

    def _tsumego_region_wide_root_noise(self, settings):
        try:
            return float(settings.get("region_wide_root_noise", REGION_ANALYSIS_WIDE_ROOT_NOISE))
        except (TypeError, ValueError):
            return REGION_ANALYSIS_WIDE_ROOT_NOISE

    def _choose_tsumego_frame(self, grid, komi, ko, margin, settings):
        """設定の frame_ko とその反転で枠を張り、root スコアがバランスの取れた方を採用する。

        ko_p は「攻め方と守り方のどちらにコウダテ形を与えるか」の切り替えで、正解がコウ止まりの
        問題では攻め方に渡さないと守り側の無条件生きになる（＝正解手が価値を失う）。どちらが
        正しいかは問題ごとに違うため、両方を短い解析にかけて枠の設計目標（攻め方成功=5目勝ち）に
        近い方を選ぶ。解析できない場合は設定値の枠をそのまま使う。

        どの枠でも手番側（解く側）の本体石が開始時点で死と読まれる場合は None を返し、呼び出し側が
        枠なしで出題する。必ず正解手がある詰碁で開始時点から全滅はあり得ないので、それは枠が問題を
        壊しているサイン。枠バランスでは検出できない（`frame_destroys_problem` の説明を参照）。
        ただし死と出た枠はそのまま捨てず、frame_validity_visits で読み直して確かめる（生き問題は
        手番側の石そのものが戦いの対象なので、trial visits では有効な枠も死と読まれる）。
        """
        from katrain.core.tsumego_frame import (
            FRAME_BALANCE_WARN_DISTANCE,
            FRAME_VALIDITY_VISITS,
            FRAME_VALIDITY_WIDE_ROOT_NOISE,
            frame_balance_distance,
            frame_validity_verdicts,
            offence_to_win,
            pick_balanced_frame,
            solver_core_points,
            tsumego_frame_board,
        )

        candidates = []
        for ko_p in (bool(ko), not ko):
            try:
                board, region = tsumego_frame_board(grid, komi, True, ko_p=ko_p, margin=margin)
            except Exception as e:  # 枠が張れない盤（コアが大きすぎる等）は候補から外すだけ
                self.log(f"tsumego_capture: 枠(ko={ko_p})を作れませんでした: {e}", OUTPUT_INFO)
                continue
            if any(board == prev_board for _, prev_board, _ in candidates):
                continue  # コウダテ形が置けない盤では両者が同一になる
            candidates.append((ko_p, board, region))
        if not candidates:
            return tsumego_frame_board(grid, komi, True, ko_p=ko, margin=margin)  # 例外は呼び出し側へ
        if not settings.get("frame_ko_auto", True):
            candidates = candidates[:1]  # コウダテの自動選択はしないが、本体石の死活は確かめる
        try:
            trial_visits = int(settings.get("frame_ko_trial_visits", 400))
        except (TypeError, ValueError):
            trial_visits = 400
        try:
            validity_visits = int(settings.get("frame_validity_visits", FRAME_VALIDITY_VISITS))
        except (TypeError, ValueError):
            validity_visits = FRAME_VALIDITY_VISITS

        def read_start(candidate, visits):
            """枠候補の裁定クエリを発行だけして待たない（結果とログは read_finish）。

            読み直し（visits != trial_visits）は wideRootNoise=0 で撃つ。wRN は着手選択で候補を
            広げるための設定で、「手番側が生きているか」の裁定では探索が critical line に
            集中できず読みが二峰性になる（`FRAME_VALIDITY_WIDE_ROOT_NOISE`）
            """
            ko_p, board, region = candidate
            retry = visits != trial_visits
            stones = solver_core_points(grid, board, region)
            return self._tsumego_frame_solver_reading_start(
                board,
                komi,
                region,
                visits,
                settings,
                stones,
                f"ko={ko_p}",
                retry=retry,
                wide_root_noise=FRAME_VALIDITY_WIDE_ROOT_NOISE if retry else None,
            )

        def read_finish(started):
            lead, solver_own = self._tsumego_frame_solver_reading_finish(started)
            return lead, solver_own, started["stone_count"]

        def read(candidate, visits):
            return read_finish(read_start(candidate, visits))

        def read_batch(jobs):
            # 独立な裁定クエリを全部発行してから順に回収する（KataGo は numAnalysisThreads=4 で
            # 並列処理できる）。クエリ内容・採否の意味論は1本ずつと同一（frame_validity_verdicts 側で保存）
            started = [read_start(candidate, visits) for candidate, visits in jobs]
            return [read_finish(s) for s in started]

        speculative = {}

        def on_reread_start():
            # 全枠死のときだけ使う「枠なし比較読み」を、読み直しと並行して投機発行しておく
            # （使わなければ捨てる。コストは遊んでいた GPU 時間だけ）
            board_fl, region_fl = self._tsumego_frameless_board(grid, settings, quiet=True)
            if region_fl is None:
                return  # リージョン縮退盤は投機読みしない（本当に枠なし経路に落ちた時に通常経路が警告つきで読む）
            stones_fl = solver_core_points(grid, board_fl, region_fl)
            speculative["frameless"] = self._tsumego_frame_solver_reading_start(
                board_fl, komi, region_fl, trial_visits, settings, stones_fl, "枠なし"
            )

        scored, destroyed = [], []
        verdicts = frame_validity_verdicts(
            candidates,
            read,
            trial_visits,
            validity_visits,
            read_batch=read_batch,
            on_reread_start=on_reread_start,
        )
        skipped_reread = any(not v.destroys for v in verdicts)
        for verdict in verdicts:
            if len(verdict.readings) > 1:  # 浅い読みで死と出て読み直した枠だけ結論を明示する
                self.log(
                    f"tsumego_capture: 枠(ko={verdict.ko_p})の採否は{verdict.visits}visitsの読みで"
                    f"{'壊れ' if verdict.destroys else '有効（枠を使います）'}",
                    OUTPUT_INFO,
                )
            elif verdict.destroys and skipped_reread:
                self.log(
                    f"tsumego_capture: 枠(ko={verdict.ko_p})は浅い読みで死と出ましたが、"
                    f"先に有効な枠が見つかったので読み直しは省略しました"
                    f"（並列で読み直しが走っていた場合、その結果は採否に使いません）",
                    OUTPUT_INFO,
                )
            if verdict.destroys:
                destroyed.append(verdict.ko_p)
                continue
            scored.append((verdict.ko_p, verdict.board, verdict.region, verdict.lead))
        if not scored:
            # 枠なし側は深さにほぼ不感なので trial の浅い読みで比較する（`frame_over_frameless`）
            rescued = self._tsumego_frame_beats_frameless(
                grid, komi, settings, verdicts, trial_visits, started=speculative.get("frameless")
            )
            if rescued is None:
                self.log(
                    f"tsumego_capture: 枠(ko={'/'.join(str(k) for k in destroyed)})では手番側の石が開始時点で"
                    f"死と読まれます。必ず正解手がある詰碁でこれは起こり得ないので、枠が問題を壊していると"
                    f"判断して枠なしで出題します",
                    OUTPUT_INFO,
                )
                return None
            self.log(
                f"tsumego_capture: どの枠も壊れ判定ですが、枠なし盤のほうが手番側の石を死と読むため"
                f"（{rescued.ownership / max(1, rescued.stone_count):+.2f}/子 の ko={rescued.ko_p} を採用）"
                f"枠を使います",
                OUTPUT_INFO,
            )
            scored = [(rescued.ko_p, rescued.board, rescued.region, rescued.lead)]
        best = pick_balanced_frame(scored)
        if best is None:
            return scored[0][1], scored[0][2]
        if best[0] != candidates[0][0]:
            self.log(f"tsumego_capture: 枠バランスが良い ko={best[0]} の枠を採用します", OUTPUT_INFO)
        distance = frame_balance_distance(best[3])
        if distance > FRAME_BALANCE_WARN_DISTANCE:
            # 大型詰碁ではリージョン内の空き地がまるごと片側の地になり、この枠の設計
            # （攻め方成功 = offence_to_win 目勝ち）が成立しない。絶対スコアに依る判定
            # （既に成功・コウ勝ち前提）が効かなくなるので、黙って進めずに知らせる
            self.log(
                f"tsumego_capture: 警告 枠バランスが設計目標から離れています"
                f"（root={best[3]:+.2f}目 / 目標±{offence_to_win}目, 距離{distance:.1f}）。"
                f"絶対スコアに依る判定は信頼できません。frame_margin を変えて再キャプチャすると"
                f"改善する場合があります",
                OUTPUT_INFO,
            )
        return best[1], best[2]

    def _tsumego_frame_beats_frameless(self, grid, komi, settings, verdicts, visits, started=None):
        """全枠が壊れ判定のとき、枠なし盤より手番側の本体石が生きている枠があれば返す。

        枠なしは安全側のフォールバックではない（リージョン外が丸ごと相手の地になる）ので、
        捨てる先を測ってから捨てる。実測 case N: 枠なし -0.75/子 に対し有効な枠は +0.42〜+0.95/子

        `started` は読み直しフェーズと並行して投機発行しておいた枠なし読み（あれば回収するだけ）
        """
        from katrain.core.tsumego_frame import frame_over_frameless, solver_core_points

        if started is None:
            board, region = self._tsumego_frameless_board(grid, settings)
            stones = solver_core_points(grid, board, region)
            started = self._tsumego_frame_solver_reading_start(
                board, komi, region, visits, settings, stones, "枠なし"
            )
        _lead, solver_own = self._tsumego_frame_solver_reading_finish(started)
        return frame_over_frameless(verdicts, solver_own, started["stone_count"])

    def _tsumego_frame_solver_reading_start(
        self, board, komi, region, visits, settings, stones, label, retry=False, wide_root_noise=None
    ):
        """裁定クエリを発行だけして待たないコンテキストを返す（結果とログは finish 側）。

        独立なクエリを全部発行してから回収すると、KataGo（numAnalysisThreads=4）が並列に
        処理して待ちが最長1本ぶんに縮む。クエリ内容は1本ずつ撃つのと同一。
        """
        return {
            "handle": self._tsumego_frame_trial_start(board, komi, region, visits, settings, wide_root_noise),
            "board": board,
            "stones": stones,
            "stone_count": len(stones),
            "visits": visits,
            "retry": retry,
            "label": label,
        }

    def _tsumego_frame_solver_reading_finish(self, started):
        """start したクエリを回収し、root スコアと「手番側の本体石」ownership 合計をログに出す"""
        from katrain.core.utils import var_to_grid

        board, stones, visits, retry, label = (
            started["board"],
            started["stones"],
            started["visits"],
            started["retry"],
            started["label"],
        )
        lead, ownership = self._tsumego_frame_trial_wait(started["handle"])
        own_grid = var_to_grid(ownership, (len(board[0]), len(board))) if ownership else None
        solver_own = sum(own_grid[y][x] for x, y in stones) if own_grid else None
        self.log(
            f"tsumego_capture: 枠バランス試算 {label}"
            + (f"（{visits}visits で読み直し）" if retry else "")
            + f": root={'解析失敗' if lead is None else f'{lead:+.2f}目'}"
            + (
                ""
                if solver_own is None
                else f" / 手番側の本体石{len(stones)}子={solver_own:+.2f}"
                f"（{solver_own / max(1, len(stones)):+.2f}/子）"
            ),
            OUTPUT_INFO,
        )
        return lead, solver_own

    def _tsumego_frame_solver_reading(
        self, board, komi, region, visits, settings, stones, label, retry=False, wide_root_noise=None
    ):
        """盤の root スコアと「手番側の本体石」ownership 合計を測ってログに出す。取れなければ None"""
        return self._tsumego_frame_solver_reading_finish(
            self._tsumego_frame_solver_reading_start(
                board, komi, region, visits, settings, stones, label, retry=retry, wide_root_noise=wide_root_noise
            )
        )

    def _tsumego_frameless_board(self, grid, settings, quiet=False):
        """枠なしで出題する盤とリージョン。認識結果そのままで1子も書き換えない。

        `quiet` は投機的な比較読み（`on_reread_start`）用: 枠が採用されるキャプチャでは
        枠なし盤は出題されないので、リージョン縮退の ERROR 警告を出さない（実際に枠なしで
        出題する経路が改めて quiet なしで呼び、そのとき警告が出る）
        """
        from katrain.core.tsumego_frame import frameless_region

        try:
            pad = max(0, int(settings.get("region_pad", 1)))
        except (TypeError, ValueError):
            pad = 1
        analysis_region = frameless_region(grid, pad)
        if analysis_region is None and not quiet:
            # Noneのまま進めると解析リージョンが無い＝全盤解析になり、この機能が防ごうと
            # している状態そのものに陥る。A/Bテスト中はエンジンの誤判定と見分けがつかず
            # 気づけないため、ここで明示的に警告する（region_padが盤外まで広すぎる、
            # または石クラスタが検出できず全石bboxに退化した等が原因）
            self.log(
                f"tsumego_capture: 解析リージョンを絞り込めなかったため全盤を解析します。"
                f"AIの着手が詰碁の正解手と一致しないことがあります（region_pad={pad} を確認してください）",
                OUTPUT_ERROR,
            )
        return grid, analysis_region

    def _tsumego_frame_trial_start(self, board, komi, analysis_region, visits, settings, wide_root_noise=None):
        """枠の採否判定用クエリを発行だけして待たない。ハンドル（dict）を返す。取れなければ None"""
        from katrain.core.tsumego_capture import grid_to_sgf

        engine = self.engine
        if engine is None:
            return None
        try:
            node = KaTrainSGF.parse_sgf(grid_to_sgf(board, komi=komi))
        except Exception as e:
            self.log(f"tsumego_capture: 枠バランス試算のSGF化に失敗しました: {e}", OUTPUT_INFO)
            return None
        # grid_to_sgf は RU を出さない。BaseGame は未指定なら設定のルールを入れるが、ここは
        # Game を作る前なので自分で入れる（未指定だと engine 既定の japanese になり、
        # 面積計算前提の枠のスコアが 25 目規模でずれる）
        node.set_property("RU", self.config("game/rules"))
        region = None
        if analysis_region:
            (imin, imax), (jmin, jmax) = analysis_region
            region = [jmin, jmax, len(board) - 1 - imax, len(board) - 1 - imin]
        result = {}
        engine.request_analysis(
            node,
            callback=lambda analysis, partial_result: (
                None
                if partial_result
                else result.setdefault(
                    "done", (analysis["rootInfo"]["scoreLead"], analysis.get("ownership"))
                )
            ),
            error_callback=lambda error: result.setdefault("error", error),
            visits=visits,
            time_limit=False,
            ownership=True,  # 手番側の本体石が生きているかの判定に使う
            region_of_interest=region,
            extra_settings=region_analysis_extra_settings(
                visits,
                self._tsumego_region_wide_root_noise(settings) if wide_root_noise is None else wide_root_noise,
            ),
        )
        return result

    def _tsumego_frame_trial_wait(self, result, timeout=30.0):
        """start したクエリの完了を待って (scoreLead, ownership) を返す。取れなければ (None, None)"""
        if result is None:
            return None, None
        engine = self.engine
        deadline = time.time() + timeout
        while "done" not in result and "error" not in result and time.time() < deadline:
            time.sleep(0.05)
            try:
                engine.check_alive(exception_if_dead=True)
            except Exception as e:
                self.log(f"tsumego_capture: 枠バランス試算中にエンジンが停止しました: {e}", OUTPUT_INFO)
                return None, None
        return result.get("done", (None, None))

    def _tsumego_frame_trial(self, board, komi, analysis_region, visits, settings, wide_root_noise=None, timeout=30.0):
        """枠の採否判定用に root の scoreLead と ownership を取る。取れなければ (None, None)"""
        return self._tsumego_frame_trial_wait(
            self._tsumego_frame_trial_start(board, komi, analysis_region, visits, settings, wide_root_noise),
            timeout=timeout,
        )

    def _tsumego_capture_failed(self, message):
        """失敗をターミナルと GUI の両方に出す（作業スレッドから呼ばれるため GUI 更新は Clock 経由）"""
        self.log(message, OUTPUT_ERROR)
        Clock.schedule_once(lambda _dt: self.controls.set_status(message, STATUS_ERROR, check_level=False), 0)

    def _do_tsumego_capture_apply(self, grid, ko, margin):
        # メッセージループスレッドで実行。既定は枠あり（use_frame: false で枠なし運用も選択可能）。
        # 枠なしを既定にしなかった理由: 実機検証で二律背反が判明したため。空いた盤面を放置すると
        # 地合いが支配し詰碁を読む動機が消える（実測: ある局面で-53目/勝率0%、別の局面で+37目/勝率100%）。
        # コミで均衡させると今度はリージョン内の空点自体が最善手候補になり、正解手が埋もれる
        # （実測: 正解手が1800visits中わずか2visits）。枠は盤面を約80子書き換えるため死活自体を
        # 変えてしまう疑いも残り、これが枠なしモードをコードに残してある理由。
        # ただし枠が詰碁自体を壊している（手番側の石が開始時点で死）と判定されたキャプチャは、
        # 枠あり設定でもその回だけ枠なしに落ちる（_choose_tsumego_frame が None を返す）。
        # new-game と解析発行は同一メッセージ内で行う
        # （分割すると new-game で game_id が変わり後続メッセージが破棄されるため）
        from katrain.core.tsumego_capture import CaptureError, grid_to_sgf

        settings = self._config.get("tsumego_capture") or {}
        komi = self.config("game/komi", 6.5)
        board, analysis_region = None, None
        # 死活ソルバモード（スペック 2026-08-01-tsumego-solver-design.md）: KataGo を使わず問題を
        # 静的に抽出できたら、枠を張らず盤面をそのまま出題する（§3。枠の採否判定 KataGo 最大5本が消える）。
        # 抽出できない盤は従来どおり枠張り経路へ（§9.2 フォールバック）
        solver_problem = None
        if settings.get("solver_enabled", True):
            started = time.time()
            try:
                from katrain.core.tsumego_problem import extract_problem, DEFAULT_MAX_REGION_POINTS

                solver_problem = extract_problem(
                    grid=grid,
                    to_play="B",
                    max_region_points=int(settings.get("solver_max_region_points", DEFAULT_MAX_REGION_POINTS)),
                )
            except Exception as e:  # ProblemError 含む。抽出失敗は現行経路へ
                self.log(
                    f"tsumego_capture: ソルバ用の問題抽出に失敗（{e}）。現行経路で出題します", OUTPUT_INFO
                )
                solver_problem = None
            if solver_problem is not None:
                # ソルバで解ける規模のときだけソルバモードにする（P1 実測: 解けたのは
                # region<=23・空点<=12、空点23以上は1800秒でも未達）。規模超過を枠なしで
                # 出題してからフォールバックすると、従来の枠あり経路より弱くなるため、
                # ここで従来経路（枠張り）に譲る＝挙動は完全に現行のまま（G5）
                n_stones = sum(
                    1 for p in solver_problem.region if p in solver_problem.black or p in solver_problem.white
                )
                n_empties = len(solver_problem.region) - n_stones
                max_region = int(settings.get("solver_capture_max_region", 26))
                max_empties = int(settings.get("solver_capture_max_empties", 14))
                if len(solver_problem.region) > max_region or n_empties > max_empties:
                    self.log(
                        f"tsumego_capture: region {len(solver_problem.region)}点/空点{n_empties} は"
                        f"ソルバで解ける規模（{max_region}点/空点{max_empties}）を超えるため、"
                        f"現行経路（枠張り）で出題します",
                        OUTPUT_INFO,
                    )
                    solver_problem = None
            if solver_problem is not None:
                board = grid  # 盤面をそのまま出す（枠を張らない）
                size = len(grid)
                xs = [p[0] for p in solver_problem.region]
                ys = [p[1] for p in solver_problem.region]
                # analysis_region は上origin ((imin, imax), (jmin, jmax))。y（下origin）から変換
                analysis_region = ((size - 1 - max(ys), size - 1 - min(ys)), (min(xs), max(xs)))
                self.log(
                    f"tsumego_capture: ソルバモードで出題します type={solver_problem.problem_type.value}"
                    f" target={len(solver_problem.target)}子 region={len(solver_problem.region)}点"
                    f" [抽出 {time.time() - started:.2f} 秒]",
                    OUTPUT_INFO,
                )
        if board is None and settings.get("use_frame", False):
            started = time.time()
            chosen = self._choose_tsumego_frame(grid, komi, ko, margin, settings)
            # 枠の採否は解析を数本回すのでキャプチャの待ち時間に直接乗る。遅いと感じたときに
            # どこが効いているか分かるように必ず出す（読み直しは1本 3〜4 秒）
            self.log(f"tsumego_capture: 枠の採否判定に {time.time() - started:.1f} 秒", OUTPUT_INFO)
            if chosen is not None:
                board, analysis_region = chosen
        if board is None:  # 枠なし設定、または枠が詰碁を壊していると判定された場合
            board, analysis_region = self._tsumego_frameless_board(grid, settings)
        try:
            move_tree = KaTrainSGF.parse_sgf(grid_to_sgf(board, komi=komi))
        except ParseError as e:
            self.log(f"詰碁キャプチャSGF解析失敗: {e}", OUTPUT_ERROR)
            return
        except CaptureError as e:
            # 石が1つも無い等、grid_to_sgf自体が弾くケース。self.log(OUTPUT_ERROR)は
            # 本クラスのlog()内でステータスバーにも転送されるため、_tsumego_capture_failed同様
            # ユーザーに認識できる（メッセージループスレッドなのでClock経由のGUI操作は不要）
            self.log(f"詰碁キャプチャ失敗: {e}", OUTPUT_ERROR)
            return
        self._do_new_game(move_tree=move_tree)
        # ソルバモード: 抽出済みの問題コンテキストを新しいゲームに引き渡す（§9.1 照会プロトコル。
        # 戦略はこれを使ってセッションを作り、以後の手番で再抽出しない）
        self.game.tsumego_solver_problem = solver_problem
        if solver_problem is not None:
            # 投機実行（§8.3-7）: GUI 描画と並行して root を解き、証明ストアを温めておく。
            # 結果は捨ててもよい（着手時の solve がキャッシュ/温TTで速くなる）
            game_ref = self.game

            def _solver_presolve():
                from katrain.core import tsumego_solver_api as solver_api

                session = solver_api.build_session_from_game(
                    game_ref, settings, lambda msg, level=None: self.log(msg, OUTPUT_INFO)
                )
                if session is not None:
                    game_ref.tsumego_solver_session = session
                    session.presolve()

            threading.Thread(target=_solver_presolve, daemon=True).start()
        try:
            # 詰碁の正解手判定用に、初期解析＋以降の毎手のリージョン解析を深掘り専用クエリ
            # （visits指定・時間無制限）にする。0以下で既定解析にフォールバック
            deep_visits = int(settings.get("analysis_visits", 1800))
            self.game.region_analysis_visits = deep_visits if deep_visits > 0 else None
        except (TypeError, ValueError):
            self.game.region_analysis_visits = None
        try:
            # root の探索の広げ方。0 だと1手に集中して正解手が読まれないまま切り捨てられる
            self.game.region_analysis_wide_root_noise = float(
                settings.get("region_wide_root_noise", REGION_ANALYSIS_WIDE_ROOT_NOISE)
            )
        except (TypeError, ValueError):
            self.game.region_analysis_wide_root_noise = REGION_ANALYSIS_WIDE_ROOT_NOISE
        try:
            # 人間（白番）の考慮時間中に有力応手の子局面を先読みして NN キャッシュを温める本数。
            # 結果は捨てるだけ（着手判定への影響ゼロ）で、的中時は次の1800visits解析が数倍速くなる
            self.game.region_prefetch_replies = int(settings.get("ponder_replies", 3))
        except (TypeError, ValueError):
            self.game.region_prefetch_replies = 3
        self._apply_tsumego_region(analysis_region, board_size=len(grid))
        maximize = settings.get("maximize_on_capture", True)
        auto_ai = settings.get("auto_ai_black", True)
        if auto_ai:
            # 黒=AI（最善手=正解手）・白=人間。AI自動着手はプレイモードでのみ発火する。
            # モード切替は switch_ui_mode のトグルではなくプレイタブを直接トリガーする
            # （_do_new_game/_do_tsumego_frame が解析モード切替クリックをスケジュール済みで、
            #  トグルだと mode の読み値がクリック発火前になり競合する。Kivy Clock は同一timeoutの
            #  イベントをスケジュール順に発火するため、後からの直接指定で必ずプレイモードに収束）
            # 詰碁の正解判定は対象石群の死活で決まるため、盤全体の目数で選ぶ ai:default ではなく
            # ownership の変化量で選ぶ ai:tsumego を使う。ソルバモードで問題を抽出できたときは
            # 死活を厳密に解く ai:tsumego_solver（解けない盤は戦略内で ai:tsumego へフォールバック）
            tsumego_subtype = AI_TSUMEGO_SOLVER if solver_problem is not None else AI_TSUMEGO
            self.update_player("B", player_type=PLAYER_AI, player_subtype=tsumego_subtype)
            self.update_player("W", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL)
            Clock.schedule_once(lambda _dt: self.play_mode.play.trigger_action(duration=0))
            self.controls.set_status("詰碁盤面を取り込みました（黒:AIが正解手を打ちます）", STATUS_INFO)
        else:
            self.controls.set_status("詰碁盤面を取り込みました", STATUS_INFO)

        def finish_gui(_dt):
            # kvバインディングがグラフィックス命令に触るため、プロパティ変更はメインスレッドで行う
            if auto_ai:
                self.controls.timer.paused = True  # プレイモードで白番考慮中の秒読みビープを防ぐ
                # 対局者ウィジェットの更新は Clock 経由で後から走り、選択肢に無い player_subtype は
                # ドロップダウンの現在値で上書きされることがある（実測 2026-07-30: 起動後1回目の
                # キャプチャだけ ai:default に戻り、詰碁戦略が丸ごと無効化されていた）。
                # ここは round-trip の後なので、実効値を検証して必要なら入れ直す
                if self.players_info["B"].player_subtype != tsumego_subtype:
                    self.log(
                        f"tsumego_capture: 黒番が {self.players_info['B'].player_subtype} に戻されたため "
                        f"{tsumego_subtype} を再設定します",
                        OUTPUT_INFO,
                    )
                    self.update_player("B", player_type=PLAYER_AI, player_subtype=tsumego_subtype)
            if maximize:
                self.tsumego_view = True  # 盤面拡大（下部ナビは残る。F12/`で通常表示に復帰）
            try:
                user32 = ctypes.windll.user32
                hwnd = user32.FindWindowW(None, Window.title)
                if hwnd and user32.IsIconic(hwnd):
                    Window.restore()
                Window.raise_window()
            except Exception as e:
                self.log(f"tsumego_capture: ウィンドウ前面化失敗: {e}", OUTPUT_DEBUG)

        Clock.schedule_once(finish_gui, 0.1)

    def play_mistake_sound(self, node):
        if self.config("timer/sound") and node.played_mistake_sound is None and Theme.MISTAKE_SOUNDS:
            node.played_mistake_sound = True
            play_sound(random.choice(Theme.MISTAKE_SOUNDS))

    def load_sgf_file(self, file, fast=False, rewind=True):
        if self.contributing:
            return
        try:
            file = os.path.abspath(file)
            move_tree = KaTrainSGF.parse_file(file)
        except (ParseError, FileNotFoundError) as e:
            self.log(i18n._("Failed to load SGF").format(error=e), OUTPUT_ERROR)
            return
        self._do_new_game(move_tree=move_tree, analyze_fast=fast, sgf_filename=file)
        if not rewind:
            self.game.redo(999)

    def _do_analyze_sgf_popup(self):
        if not self.fileselect_popup:
            popup_contents = LoadSGFPopup(self)
            popup_contents.filesel.path = os.path.abspath(os.path.expanduser(self.config("general/sgf_load", ".")))
            self.fileselect_popup = I18NPopup(
                title_key="load sgf title", size=[dp(1200), dp(800)], content=popup_contents
            ).__self__

            def readfile(*_args):
                filename = popup_contents.filesel.filename
                self.fileselect_popup.dismiss()
                path, file = os.path.split(filename)
                if path != self.config("general/sgf_load"):
                    self.log(f"Updating sgf load path default to {path}", OUTPUT_DEBUG)
                    self._config["general"]["sgf_load"] = path
                popup_contents.update_config(False)
                self.save_config("general")
                self.load_sgf_file(filename, popup_contents.fast.active, popup_contents.rewind.active)

            popup_contents.filesel.on_success = readfile
            popup_contents.filesel.on_submit = readfile
        self.fileselect_popup.open()
        self.fileselect_popup.content.filesel.ids.list_view._trigger_update()

    def _do_save_game(self, filename=None):
        filename = filename or self.game.sgf_filename
        if not filename:
            return self("save-game-as-popup")
        try:
            msg = self.game.write_sgf(filename)
            self.log(msg, OUTPUT_INFO)
            self.controls.set_status(msg, STATUS_INFO, check_level=False)
        except Exception as e:
            self.log(f"Failed to save SGF to {filename}: {e}", OUTPUT_ERROR)

    def _do_save_game_as_popup(self):
        popup_contents = SaveSGFPopup(suggested_filename=self.game.generate_filename())
        save_game_popup = I18NPopup(
            title_key="save sgf title", size=[dp(1200), dp(800)], content=popup_contents
        ).__self__

        def readfile(*_args):
            filename = popup_contents.filesel.filename
            if not filename.lower().endswith(".sgf"):
                filename += ".sgf"
            save_game_popup.dismiss()
            path, file = os.path.split(filename.strip())
            if not path:
                path = popup_contents.filesel.path  # whatever dir is shown
            if path != self.config("general/sgf_save"):
                self.log(f"Updating sgf save path default to {path}", OUTPUT_DEBUG)
                self._config["general"]["sgf_save"] = path
                self.save_config("general")
            self._do_save_game(os.path.join(path, file))

        popup_contents.filesel.on_success = readfile
        popup_contents.filesel.on_submit = readfile
        save_game_popup.open()

    def load_sgf_from_clipboard(self):
        clipboard = Clipboard.paste()
        if not clipboard:
            self.controls.set_status("Ctrl-V pressed but clipboard is empty.", STATUS_INFO)
            return

        url_match = re.match(r"(?P<url>https?://[^\s]+)", clipboard)
        if url_match:
            self.log("Recognized url: " + url_match.group(), OUTPUT_INFO)
            http = urllib3.PoolManager()
            response = http.request("GET", url_match.group())
            clipboard = response.data.decode("utf-8")

        try:
            move_tree = KaTrainSGF.parse_sgf(clipboard)
        except Exception as exc:
            self.controls.set_status(
                i18n._("Failed to import from clipboard").format(error=exc, contents=clipboard[:50]), STATUS_INFO
            )
            return
        move_tree.nodes_in_tree[-1].analyze(
            self.engine, analyze_fast=False
        )  # speed up result for looking at end of game
        self._do_new_game(move_tree=move_tree, analyze_fast=True)
        self("redo", 9999)
        self.log("Imported game from clipboard.", OUTPUT_INFO)

    def on_touch_up(self, touch):
        if touch.is_mouse_scrolling:
            touching_board = self.board_gui.collide_point(*touch.pos) or self.board_controls.collide_point(*touch.pos)
            touching_control_nonscroll = self.controls.collide_point(
                *touch.pos
            ) and not self.controls.notes_panel.collide_point(*touch.pos)
            if self.board_gui.animating_pv is not None and touching_board:
                if touch.button == "scrollup":
                    self.board_gui.adjust_animate_pv_index(1)
                elif touch.button == "scrolldown":
                    self.board_gui.adjust_animate_pv_index(-1)
            elif touching_board or touching_control_nonscroll:  # scroll through moves
                if touch.button == "scrollup":
                    self("redo")
                elif touch.button == "scrolldown":
                    self("undo")
        return super().on_touch_up(touch)

    @property
    def shortcuts(self):
        return {
            k: v
            for ks, v in [
                (Theme.KEY_ANALYSIS_CONTROLS_SHOW_CHILDREN, self.analysis_controls.show_children),
                (Theme.KEY_ANALYSIS_CONTROLS_EVAL, self.analysis_controls.eval),
                (Theme.KEY_ANALYSIS_CONTROLS_HINTS, self.analysis_controls.hints),
                (Theme.KEY_ANALYSIS_CONTROLS_OWNERSHIP, self.analysis_controls.ownership),
                (Theme.KEY_ANALYSIS_CONTROLS_POLICY, self.analysis_controls.policy),
                (Theme.KEY_AI_MOVE, ("ai-move",)),
                (Theme.KEY_ANALYZE_EXTRA_EXTRA, ("analyze-extra", "extra")),
                (Theme.KEY_ANALYZE_EXTRA_EQUALIZE, ("analyze-extra", "equalize")),
                (Theme.KEY_ANALYZE_EXTRA_SWEEP, ("analyze-extra", "sweep")),
                (Theme.KEY_ANALYZE_EXTRA_ALTERNATIVE, ("analyze-extra", "alternative")),
                (Theme.KEY_SELECT_BOX, ("select-box",)),
                (Theme.KEY_RESET_ANALYSIS, ("reset-analysis",)),
                (Theme.KEY_INSERT_MODE, ("insert-mode",)),
                (Theme.KEY_PASS, ("play", None)),
                (Theme.KEY_SELFPLAY_TO_END, ("selfplay-setup", "end", None)),
                (Theme.KEY_NAV_PREV_BRANCH, ("undo", "branch")),
                (Theme.KEY_NAV_BRANCH_DOWN, ("switch-branch", 1)),
                (Theme.KEY_NAV_BRANCH_UP, ("switch-branch", -1)),
                (Theme.KEY_TIMER_POPUP, ("timer-popup",)),
                (Theme.KEY_TEACHER_POPUP, ("teacher-popup",)),
                (Theme.KEY_AI_POPUP, ("ai-popup",)),
                (Theme.KEY_CONFIG_POPUP, ("config-popup",)),
                (Theme.KEY_CONTRIBUTE_POPUP, ("contribute-popup",)),
                (Theme.KEY_STOP_ANALYSIS, ("analyze-extra", "stop")),
            ]
            for k in (ks if isinstance(ks, list) else [ks])
        }

    @property
    def popup_open(self) -> Popup:
        app = App.get_running_app()
        if app:
            first_child = app.root_window.children[0]
            return first_child if isinstance(first_child, Popup) else None

    def _on_keyboard_down(self, _keyboard, keycode, _text, modifiers):
        self.last_key_down = keycode
        ctrl_pressed = "ctrl" in modifiers or ("meta" in modifiers and kivy_platform == "macosx")
        shift_pressed = "shift" in modifiers
        if self.controls.note.focus:
            return  # when making notes, don't allow keyboard shortcuts
        popup = self.popup_open
        if popup:
            if keycode[1] in [
                Theme.KEY_DEEPERANALYSIS_POPUP,
                Theme.KEY_REPORT_POPUP,
                Theme.KEY_TIMER_POPUP,
                Theme.KEY_TEACHER_POPUP,
                Theme.KEY_AI_POPUP,
                Theme.KEY_CONFIG_POPUP,
                Theme.KEY_TSUMEGO_FRAME,
                Theme.KEY_CONTRIBUTE_POPUP,
            ]:  # switch between popups
                popup.dismiss()

                return
            elif keycode[1] in Theme.KEY_SUBMIT_POPUP:
                fn = getattr(popup.content, "on_submit", None)
                if fn:
                    fn()
                return
            else:
                return

        if self.contributing:
            if keycode[1] == Theme.KEY_STOP_CONTRIBUTING:
                self.engine.graceful_shutdown()
                return
            elif keycode[1] in Theme.KEY_PAUSE_CONTRIBUTE:
                self.engine.pause()
                return

        if keycode[1] == Theme.KEY_TOGGLE_CONTINUOUS_ANALYSIS:
            self.toggle_continuous_analysis(quiet=shift_pressed)
        elif keycode[1] == Theme.KEY_TOGGLE_MOVENUM:
            self.toggle_move_num()
        elif keycode[1] == Theme.KEY_TOGGLE_COORDINATES:
            self.board_gui.toggle_coordinates()
        elif keycode[1] in Theme.KEY_PAUSE_TIMER and not ctrl_pressed:
            self.controls.timer.paused = not self.controls.timer.paused
        elif keycode[1] in Theme.KEY_ZEN:
            if self.tsumego_view:
                self.tsumego_view = False  # 詰碁ビュー中はまず通常表示に戻す
            else:
                self.zen = (self.zen + 1) % 3
        elif keycode[1] in Theme.KEY_NAV_PREV:
            self("undo", 1 + shift_pressed * 9 + ctrl_pressed * 9999)
        elif keycode[1] in Theme.KEY_NAV_NEXT:
            self("redo", 1 + shift_pressed * 9 + ctrl_pressed * 9999)
        elif keycode[1] == Theme.KEY_NAV_GAME_START:
            self("undo", 9999)
        elif keycode[1] == Theme.KEY_NAV_GAME_END:
            self("redo", 9999)
        elif keycode[1] == Theme.KEY_MOVE_TREE_MAKE_SELECTED_NODE_MAIN_BRANCH:
            self.controls.move_tree.make_selected_node_main_branch()
        elif keycode[1] == Theme.KEY_NAV_MISTAKE and not ctrl_pressed:
            self("find-mistake", "undo" if shift_pressed else "redo")
        elif keycode[1] == Theme.KEY_MOVE_TREE_DELETE_SELECTED_NODE and ctrl_pressed:
            self.controls.move_tree.delete_selected_node()
        elif keycode[1] == Theme.KEY_MOVE_TREE_TOGGLE_SELECTED_NODE_COLLAPSE and not ctrl_pressed:
            self.controls.move_tree.toggle_selected_node_collapse()
        elif keycode[1] == Theme.KEY_NEW_GAME and ctrl_pressed:
            self("new-game-popup")
        elif keycode[1] == Theme.KEY_LOAD_GAME and ctrl_pressed:
            self("analyze-sgf-popup")
        elif keycode[1] == Theme.KEY_SAVE_GAME and ctrl_pressed:
            self("save-game")
        elif keycode[1] == Theme.KEY_SAVE_GAME_AS and ctrl_pressed:
            self("save-game-as-popup")
        elif keycode[1] == Theme.KEY_COPY and ctrl_pressed:
            Clipboard.copy(self.game.root.sgf())
            self.controls.set_status(i18n._("Copied SGF to clipboard."), STATUS_INFO)
        elif keycode[1] == Theme.KEY_PASTE and ctrl_pressed:
            self.load_sgf_from_clipboard()
        elif keycode[1] == Theme.KEY_NAV_PREV_BRANCH and shift_pressed:
            self("undo", "main-branch")
        elif keycode[1] == Theme.KEY_DEEPERANALYSIS_POPUP:
            self.analysis_controls.dropdown.open_game_analysis_popup()
        elif keycode[1] == Theme.KEY_TSUMEGO_FRAME:
            self.analysis_controls.dropdown.open_tsumego_frame_popup()
        elif keycode[1] == Theme.KEY_REPORT_POPUP:
            self.analysis_controls.dropdown.open_report_popup()
        elif keycode[1] == "f10" and self.debug_level >= OUTPUT_EXTRA_DEBUG:
            import yappi

            yappi.set_clock_type("cpu")
            yappi.start()
            self.log("starting profiler", OUTPUT_ERROR)
        elif keycode[1] == "f11" and self.debug_level >= OUTPUT_EXTRA_DEBUG:
            import time
            import yappi

            stats = yappi.get_func_stats()
            filename = f"callgrind.{int(time.time())}.prof"
            stats.save(filename, type="callgrind")
            self.log(f"wrote profiling results to {filename}", OUTPUT_ERROR)
        elif not ctrl_pressed:
            shortcut = self.shortcuts.get(keycode[1])
            if shortcut is not None:
                if isinstance(shortcut, Widget):
                    shortcut.trigger_action(duration=0)
                else:
                    self(*shortcut)

    def _on_keyboard_up(self, _keyboard, keycode):
        if keycode[1] in ["alt", "tab"]:
            Clock.schedule_once(lambda *_args: self._single_key_action(keycode), 0.05)

    def _single_key_action(self, keycode):
        if (
            self.controls.note.focus
            or self.popup_open
            or keycode != self.last_key_down
            or time.time() - self.last_focus_event < 0.2  # this is here to prevent alt-tab from firing alt or tab
        ):
            return
        if keycode[1] == "alt":
            self.nav_drawer.set_state("toggle")
        elif keycode[1] == "tab":
            self.play_mode.switch_ui_mode()


class KaTrainApp(MDApp):
    gui = ObjectProperty(None)
    language = StringProperty(DEFAULT_LANGUAGE)

    def __init__(self):
        super().__init__()

    def is_valid_window_position(self, left, top, width, height):
        try:
            from screeninfo import get_monitors
            monitors = get_monitors()
            for monitor in monitors:
                if (left >= monitor.x and left + width <= monitor.x + monitor.width and
                    top >= monitor.y and top + height <= monitor.y + monitor.height):
                    return True
            return False
        except Exception as e:
            return True # yolo

    def build(self):
        self.icon = ICON  # how you're supposed to set an icon

        self.title = f"KaTrain v{VERSION}"
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Gray"
        self.theme_cls.primary_hue = "200"

        kv_file = find_package_resource("katrain/gui.kv")
        popup_kv_file = find_package_resource("katrain/popups.kv")
        resource_add_path(PATHS["PACKAGE"] + "/fonts")
        resource_add_path(PATHS["PACKAGE"] + "/sounds")
        resource_add_path(PATHS["PACKAGE"] + "/img")
        resource_add_path(os.path.abspath(os.path.expanduser(DATA_FOLDER)))  # prefer resources in .katrain

        theme_files = glob.glob(os.path.join(os.path.expanduser(DATA_FOLDER), "theme*.json"))
        for theme_file in sorted(theme_files):
            try:
                with open(theme_file) as f:
                    theme_overrides = json.load(f)
                for k, v in theme_overrides.items():
                    setattr(Theme, k, v)
                    print(f"[{theme_file}] Found theme override {k} = {v}")
            except Exception as e:  # noqa E722
                print(f"Failed to load theme file {theme_file}: {e}")

        Theme.DEFAULT_FONT = resource_find(Theme.DEFAULT_FONT)
        Builder.load_file(kv_file)

        Window.bind(on_request_close=self.on_request_close)
        Window.bind(on_dropfile=lambda win, file: self.gui.load_sgf_file(file.decode("utf8")))
        self.gui = KaTrainGui()
        Builder.load_file(popup_kv_file)

        win_left = win_top = win_size = None
        if self.gui.config("ui_state/restoresize", True):
            win_size = self.gui.config("ui_state/size", [])
            win_left = self.gui.config("ui_state/left", None)
            win_top = self.gui.config("ui_state/top", None)
        if not win_size:
            window_scale_fac = 1
            try:
                from screeninfo import get_monitors

                for m in get_monitors():
                    window_scale_fac = min(window_scale_fac, (m.height - 100) / 1000, (m.width - 100) / 1300)
            except Exception as e:
                window_scale_fac = 0.85
            win_size = [1300 * window_scale_fac, 1000 * window_scale_fac]
        self.gui.log(f"Setting window size to {win_size} and position to {[win_left, win_top]}", OUTPUT_DEBUG)
        Window.size = (win_size[0], win_size[1])
        if win_left is not None and win_top is not None and self.is_valid_window_position(win_left, win_top, win_size[0], win_size[1]):
            Window.left = win_left
            Window.top = win_top

        return self.gui

    def on_language(self, _instance, language):
        self.gui.log(f"Switching language to {language}", OUTPUT_INFO)
        i18n.switch_lang(language)
        self.gui._config["general"]["lang"] = language
        self.gui.save_config()
        if self.gui.game:
            self.gui.update_state()
            self.gui.controls.set_status("", STATUS_INFO)

    def webbrowser(self, site_key):
        websites = {
            "homepage": HOMEPAGE + "#manual",
            "support": HOMEPAGE + "#support",
            "contribute:signup": "http://katagotraining.org/accounts/signup/",
            "engine:help": HOMEPAGE + "/blob/master/ENGINE.md",
        }
        if site_key in websites:
            webbrowser.open(websites[site_key])

    def on_start(self):
        self.language = self.gui.config("general/lang")
        self.gui.start()

    def on_request_close(self, *_args, source=None):
        if source == "keyboard":
            return True  # do not close on esc
        if getattr(self, "gui", None):
            self.gui.play_mode.save_ui_state()
            self.gui._config["ui_state"]["size"] = list(Window._size)
            self.gui._config["ui_state"]["top"] = Window.top
            self.gui._config["ui_state"]["left"] = Window.left
            self.gui.save_config("ui_state")
            if self.gui.engine:
                self.gui.engine.shutdown(finish=None)

    def signal_handler(self, _signal, _frame):
        if self.gui.debug_level >= OUTPUT_DEBUG:
            print("TRACEBACKS")
            for threadId, stack in sys._current_frames().items():
                print(f"\n# ThreadID: {threadId}")
                for filename, lineno, name, line in traceback.extract_stack(stack):
                    print(f"\tFile: {filename}, line {lineno}, in {name}")
                    if line:
                        print(f"\t\t{line.strip()}")
        self.stop()


def run_app():
    class CrashHandler(ExceptionHandler):
        def handle_exception(self, inst):
            ex_type, ex, tb = sys.exc_info()
            trace = "".join(traceback.format_tb(tb))
            app = MDApp.get_running_app()

            if app and app.gui:
                app.gui.log(
                    f"Exception {inst.__class__.__name__}: {', '.join(repr(a) for a in inst.args)}\n{trace}",
                    OUTPUT_ERROR,
                )
            else:
                print(f"Exception {inst.__class__}: {inst.args}\n{trace}")
            return ExceptionManager.PASS

    ExceptionManager.add_handler(CrashHandler())
    app = KaTrainApp()
    signal.signal(signal.SIGINT, app.signal_handler)
    app.run()


if __name__ == "__main__":
    run_app()

"""マニュアル用スクリーンショットの自動撮影ツアー。

KaTrain 自身を起動し、対局画面・メニュー・各設定ポップアップ・AI 戦略ごとの設定画面などを
Kivy の `Window.screenshot` で順に撮って `docs/manual/img/` に保存する。

    python tools/manual_screenshots.py [--out docs/manual/img] [--keep-home] [--groups play,ai,...]

設定の隔離: `USERPROFILE` を一時ディレクトリに向け、本物の `~/.katrain/config.json` の**コピー**で
起動する（起動中の設定書き戻しでユーザーの設定を汚さない）。エンジン・モデルのパスはコピー元の
絶対パスをそのまま使い、TensorRT のプランキャッシュもコピーして再構築を避ける。

グループ: play / menu / newgame / ai / settings / analyze / popups / zen / themes / tsumego
"""

import argparse
import faulthandler
import json
import os
import shutil
import sys
import tempfile
import time

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REAL_HOME = os.path.expanduser("~")
REAL_KATRAIN_DIR = os.path.join(REAL_HOME, ".katrain")

parser = argparse.ArgumentParser()
parser.add_argument("--out", default=os.path.join(REPO, "docs", "manual", "img"))
parser.add_argument("--keep-home", action="store_true", help="一時ホームを消さない")
parser.add_argument("--groups", default="", help="カンマ区切りのグループ名で絞る（空なら全部）")
args = parser.parse_args()

# ---- 設定の隔離（katrain を import する前に済ませる） ----
TMP_HOME = tempfile.mkdtemp(prefix="katrain_manual_home_")
tmp_katrain = os.path.join(TMP_HOME, ".katrain")
os.makedirs(tmp_katrain, exist_ok=True)
with open(os.path.join(REAL_KATRAIN_DIR, "config.json"), encoding="utf-8") as f:
    cfg = json.load(f)
for key in ("katago", "model", "humanlike_model", "config"):
    v = cfg["engine"].get(key, "")
    if v and v.startswith("~"):
        cfg["engine"][key] = os.path.expanduser(v)
cfg["general"]["debug_level"] = 0
cfg["general"]["lang"] = "jp"
cfg["general"]["board_theme"] = "default"
cfg["game"].update({"size": "19", "komi": 6.5, "handicap": 0, "rules": "japanese"})
cfg["ui_state"].update({"restoresize": True, "size": [1500, 1000], "left": 40, "top": 40})
cfg["tsumego_capture"]["enabled"] = False  # グローバルホットキーは撮影中に要らない
cfg["board_watch"]["enabled"] = False
cfg["tsumego_autoloop"]["enabled"] = False
with open(os.path.join(tmp_katrain, "config.json"), "w", encoding="utf-8") as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)
real_trt = os.path.join(REAL_KATRAIN_DIR, "trtcache")
if os.path.isdir(real_trt):  # TensorRT のプランを再構築させない（数分かかる）
    shutil.copytree(real_trt, os.path.join(tmp_katrain, "trtcache"), dirs_exist_ok=True)
TOUR_LOG = open(os.path.join(TMP_HOME, "tour.log"), "a", encoding="utf-8")


def tlog(*a):
    msg = " ".join(str(x) for x in a)
    TOUR_LOG.write(msg + chr(10))
    TOUR_LOG.flush()
    print(msg, flush=True)


faulthandler.dump_traceback_later(120, repeat=True, file=open(os.path.join(TMP_HOME, "trace.log"), "a"))
tlog("tmp home:", TMP_HOME)
os.environ["USERPROFILE"] = TMP_HOME
os.environ["HOME"] = TMP_HOME
os.environ["KIVY_HOME"] = os.path.join(TMP_HOME, ".kivy")
os.environ["KIVY_NO_ARGS"] = "1"

OUT = os.path.abspath(args.out)
os.makedirs(OUT, exist_ok=True)
RAW = os.path.join(TMP_HOME, "raw")
os.makedirs(RAW, exist_ok=True)
GROUPS = {s for s in args.groups.split(",") if s}


def want(group):
    return not GROUPS or group in GROUPS


sys.path.insert(0, REPO)

from kivy.clock import Clock  # noqa: E402
from kivy.core.window import Window  # noqa: E402

from katrain.__main__ import KaTrainApp  # noqa: E402  (Window はここで作られる)
from katrain.core.constants import AI_STRATEGIES_RECOMMENDED_ORDER, PLAYER_AI, PLAYER_HUMAN, PLAYING_NORMAL  # noqa: E402
from katrain.core.sgf_parser import Move  # noqa: E402
from katrain.gui import theme_manager  # noqa: E402

MANIFEST = []  # {name, raw, crop:[l,t,r,b] or None, desc}


def _widget_box(widget, margin=0):
    """Kivy 座標（左下 origin）のウィジェット矩形を画像座標（左上 origin）の crop box にする"""
    W, H = Window.size
    x, y = widget.to_window(*widget.pos)
    w, h = widget.size
    left = max(0, int(x - margin))
    right = min(W, int(x + w + margin))
    top = max(0, int(H - (y + h) - margin))
    bottom = min(H, int(H - y + margin))
    return [left, top, right, bottom]


def shoot(name, crop_widget=None, margin=8, desc=""):
    raw = Window.screenshot(os.path.join(RAW, name + ".png"))
    crop = _widget_box(crop_widget, margin) if crop_widget is not None else None
    MANIFEST.append({"name": name, "raw": raw, "crop": crop, "desc": desc, "size": list(Window.size)})
    tlog(f"[shot] {name} -> {raw} crop={crop}")


class Tour:
    """(名前, 関数, 待ち秒) のステップ列を Clock で順に流す。関数が callable を返したらそれが真になるまで待つ"""

    def __init__(self, app):
        self.app = app
        self.gui = app.gui
        self.steps = []
        self.i = 0
        self._wait_cond = None
        self._wait_deadline = 0

    def add(self, name, fn, delay=0.8, timeout=60):
        self.steps.append((name, fn, delay, timeout))

    def start(self):
        Clock.schedule_once(self._next, 1.0)

    def _next(self, _dt):
        if self._wait_cond is not None:
            if self._wait_cond():
                self._wait_cond = None
            elif time.time() > self._wait_deadline:
                tlog("[tour] WAIT TIMEOUT before step", self.steps[self.i][0] if self.i < len(self.steps) else "end")
                self._wait_cond = None
            else:
                Clock.schedule_once(self._next, 0.25)
                return
        if self.i >= len(self.steps):
            self.finish()
            return
        name, fn, delay, timeout = self.steps[self.i]
        self.i += 1
        tlog(f"[tour] step {self.i}/{len(self.steps)}: {name}")
        try:
            cond = fn()
        except Exception:  # 1ステップの失敗でツアーを止めない
            import traceback

            tlog("[tour] step failed:", name, traceback.format_exc())
            cond = None
        if callable(cond):
            self._wait_cond = cond
            self._wait_deadline = time.time() + timeout
        Clock.schedule_once(self._next, delay)

    def finish(self):
        with open(os.path.join(TMP_HOME, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(MANIFEST, f, ensure_ascii=False, indent=1)
        tlog("[tour] done, shots:", len(MANIFEST))
        try:
            if self.gui.engine:
                self.gui.engine.shutdown(finish=False)
        except Exception:
            pass
        Clock.schedule_once(lambda _dt: self.app.stop(), 0.5)


class ManualApp(KaTrainApp):
    def on_start(self):
        tlog("[tour] on_start")
        super().on_start()
        tlog("[tour] gui started, scheduling tour")

        def _go(_dt):
            try:
                # Kivy の Clock はバウンドメソッドを弱参照で持つので、Tour を app に留めないと GC されて
                # コールバックが二度と呼ばれない（初回実行で踏んだ）
                self.tour = build_tour(self)
                self.tour.start()
            except Exception:
                import traceback

                tlog("[tour] build_tour failed:", traceback.format_exc())

        Clock.schedule_once(_go, 2.0)


def gtp(s):
    return Move.from_gtp(s).coords


def build_tour(app):
    gui = app.gui
    t = Tour(app)

    # ---- 準備: エンジン起動を待つ ----
    t.add("_wait_engine", lambda: (lambda: gui.game is not None and gui.game.root.analysis_complete), delay=1.0, timeout=600)

    # ---- 対局モード ----
    def setup_players():
        gui.update_player("B", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL)
        gui.update_player("W", player_type=PLAYER_AI, player_subtype="ai:human")
        gui.update_state()

    if want("play"):
        t.add("_players", setup_players, delay=1.0)
        for mv in ["Q16", "D4", "Q4", "C16"]:  # 白 AI が応手する
            t.add(f"_play_{mv}", (lambda m: (lambda: (gui("play", gtp(m)), (lambda: gui.engine.is_idle()))[1]))(mv), delay=1.5, timeout=60)
        t.add("main_play", lambda: shoot("main_play", desc="対局モードのメイン画面"), delay=0.8)

    # ---- メニュー ----
    if want("menu"):
        t.add("_menu_open", lambda: gui.nav_drawer.set_state("open"), delay=1.2)
        t.add("menu", lambda: shoot("menu", desc="メインメニュー"), delay=0.5)
        t.add("_menu_close", lambda: gui.nav_drawer.set_state("close"), delay=0.8)

    # ---- 新規対局ダイアログ ----
    if want("newgame"):
        t.add("_newgame_open", lambda: gui("new-game-popup"), delay=1.5)
        t.add("popup_newgame", lambda: shoot("popup_newgame", gui.new_game_popup, desc="新規対局ダイアログ"), delay=0.5)
        t.add("_setup_mode", lambda: setattr(gui.new_game_popup.content, "mode", "setupposition"), delay=1.0)
        t.add("popup_setup_position", lambda: shoot("popup_setup_position", gui.new_game_popup, desc="局面を生成"), delay=0.5)
        t.add("_edit_mode", lambda: setattr(gui.new_game_popup.content, "mode", "editgame"), delay=1.0)
        t.add("popup_editgame", lambda: shoot("popup_editgame", gui.new_game_popup, desc="対局情報を編集"), delay=0.5)
        t.add("_newgame_close", lambda: gui.new_game_popup.dismiss(), delay=0.8)

    # ---- AI 設定（戦略ごと） ----
    if want("ai"):
        t.add("_ai_open", lambda: gui("ai-popup"), delay=1.5)
        for strat in AI_STRATEGIES_RECOMMENDED_ORDER:
            key = strat.replace("ai:", "").replace(":", "_")

            def _sel(s=strat):
                gui.ai_settings_popup.content.ai_select.select_key(s)

            t.add(f"_ai_sel_{key}", _sel, delay=1.2)
            t.add(f"ai_{key}", (lambda k=key: shoot(f"ai_{k}", gui.ai_settings_popup, desc=f"AI設定 {k}")), delay=0.4)

        # 説明欄をクリックしたときの拡大表示（項目の多い擬態で撮る）
        def _help_select():
            gui.ai_settings_popup.content.ai_select.select_key("ai:mimic13")

        def _help_popup():
            return gui.ai_settings_popup.content.help_popup

        t.add("_ai_help_sel", _help_select, delay=1.2)
        t.add("_ai_help_open", lambda: gui.ai_settings_popup.content.open_help_popup(), delay=1.2)
        t.add("ai_help_popup", lambda: shoot("ai_help_popup", _help_popup(), desc="AI設定 説明欄の拡大表示"), delay=0.4)
        t.add("_ai_help_close", lambda: _help_popup().dismiss(), delay=0.8)
        t.add("_ai_close", lambda: gui.ai_settings_popup.dismiss(), delay=0.8)

    # ---- 一般・エンジン設定 / 時間 / 指導 ----
    def cfg_title():  # 一時ホームのパスを本物の設定ファイルの場所に読み替える（撮影用）
        gui.config_popup.title = gui.config_popup.title.replace(TMP_HOME, REAL_HOME)

    if want("settings"):
        t.add("_cfg_open", lambda: gui("config-popup"), delay=2.0)
        t.add("_cfg_title", cfg_title, delay=0.5)
        t.add("popup_settings", lambda: shoot("popup_settings", gui.config_popup, desc="一般・エンジン設定"), delay=0.5)
        t.add("_cfg_close", lambda: gui.config_popup.dismiss(), delay=0.8)
        t.add("_timer_open", lambda: gui("timer-popup"), delay=1.5)
        t.add("popup_timer", lambda: shoot("popup_timer", gui.timer_settings_popup, desc="時間設定"), delay=0.5)
        t.add("_timer_close", lambda: gui.timer_settings_popup.dismiss(), delay=0.8)
        t.add("_teacher_open", lambda: gui("teacher-popup"), delay=1.5)
        t.add("popup_teacher", lambda: shoot("popup_teacher", gui.teacher_settings_popup, desc="指導・分析設定"), delay=0.5)
        t.add("_teacher_close", lambda: gui.teacher_settings_popup.dismiss(), delay=0.8)

    # ---- 分析モード（棋譜読込） ----
    sgf = os.path.join(REPO, "tests", "data", "ogs.sgf")

    def load_game():
        gui.update_player("B", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL)
        gui.update_player("W", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL)
        gui.load_sgf_file(sgf, fast=True, rewind=False)
        return lambda: gui.engine.is_idle()

    def to_analyze():
        if gui.play_mode.mode != "analyze":
            gui.play_mode.switch_ui_mode()
        gui("undo", 60)  # 中盤の局面へ
        return lambda: gui.engine.is_idle()

    def toggles(hints=True, eval_=True, own=True, policy=False):
        ac = gui.analysis_controls
        ac.hints.checkbox.active = hints
        ac.eval.checkbox.active = eval_
        ac.ownership.checkbox.active = own
        ac.policy.checkbox.active = policy
        gui.update_state(redraw_board=True)

    if want("analyze") or want("popups"):
        t.add("_load_sgf", load_game, delay=1.5, timeout=240)
        t.add("_analyze_mode", to_analyze, delay=1.5, timeout=120)
        t.add("_toggles", lambda: toggles(), delay=2.0)

    if want("analyze"):
        t.add("main_analyze", lambda: shoot("main_analyze", desc="分析モードのメイン画面"), delay=0.5)
        t.add("_toggles_policy", lambda: toggles(hints=False, eval_=False, own=False, policy=True), delay=2.0)
        t.add("main_policy", lambda: shoot("main_policy", gui.board_gui, margin=0, desc="第一感（policy）表示"), delay=0.5)
        t.add("_toggles_back", lambda: toggles(), delay=1.5)
        t.add("_dropdown", lambda: gui.analysis_controls.toggle_dropdown(), delay=1.2)
        t.add("analysis_menu", lambda: shoot("analysis_menu", desc="分析オプションのメニュー"), delay=0.5)
        t.add("_dropdown_close", lambda: gui.analysis_controls.toggle_dropdown(), delay=0.8)

    def dd():  # 分析オプションのメニュー本体（ポップアップを開くメソッドはここにある）
        return gui.analysis_controls.dropdown

    if want("popups"):
        t.add("_report_open", lambda: dd().open_report_popup(), delay=2.5)
        t.add("popup_report", lambda: shoot("popup_report", gui.popup_open, desc="評価レポート"), delay=0.5)
        t.add("_report_close", lambda: gui.popup_open.dismiss(), delay=0.8)
        t.add("_reanalyze_open", lambda: dd().open_game_analysis_popup(), delay=1.5)
        t.add("popup_reanalyze", lambda: shoot("popup_reanalyze", gui.popup_open, desc="一局全体を深く分析"), delay=0.5)
        t.add("_reanalyze_close", lambda: gui.popup_open.dismiss(), delay=0.8)
        t.add("_tframe_open", lambda: dd().open_tsumego_frame_popup(), delay=1.5)
        t.add("popup_tsumego_frame", lambda: shoot("popup_tsumego_frame", gui.popup_open, desc="詰碁用の外枠"), delay=0.5)
        t.add("_tframe_close", lambda: gui.popup_open.dismiss(), delay=0.8)
        t.add("_load_open", lambda: gui("analyze-sgf-popup"), delay=2.0)
        t.add("popup_load", lambda: shoot("popup_load", gui.popup_open, desc="棋譜読込"), delay=0.5)
        t.add("_load_close", lambda: gui.popup_open.dismiss(), delay=0.8)

    # ---- 最小表示 ----
    if want("zen"):
        t.add("_zen2", lambda: setattr(gui, "zen", 2), delay=1.2)
        t.add("zen", lambda: shoot("zen", desc="最小表示（F12）"), delay=0.5)
        t.add("_zen0", lambda: setattr(gui, "zen", 0), delay=1.0)

    # ---- 盤面テーマ ----
    if want("themes"):
        for name, _label in theme_manager.list_themes():

            def _apply(n=name):
                theme_manager.apply_theme(n, log=lambda *a, **k: None)
                gui.update_state(redraw_board=True)

            t.add(f"_theme_{name}", _apply, delay=1.5)
            t.add(f"theme_{name}", (lambda n=name: shoot(f"theme_{n}", gui.board_gui, margin=0, desc=f"盤面テーマ {n}")), delay=0.5)
        t.add("_theme_default", lambda: (theme_manager.apply_theme("default", log=lambda *a, **k: None), gui.update_state(redraw_board=True)), delay=1.5)

    if not want("tsumego"):
        return t

    # ---- 詰碁: 手製の問題に枠を張る ----
    tsumego_sgf = "(;GM[1]FF[4]SZ[13]KM[7.0]RU[japanese]PL[B]AW[bl][cl][dl][el][em]AB[bk][ck][dk][ek][fk][fl][fm])"

    def load_tsumego():
        from katrain.core.game import KaTrainSGF

        if gui.play_mode.mode != "play":
            gui.play_mode.switch_ui_mode()
        gui._do_new_game(move_tree=KaTrainSGF.parse_sgf(tsumego_sgf))
        return lambda: gui.engine.is_idle()

    t.add("_tsumego_load", load_tsumego, delay=1.5, timeout=120)
    t.add("tsumego_raw", lambda: shoot("tsumego_raw", gui.board_gui, margin=0, desc="枠を張る前の詰碁"), delay=0.5)

    def frame():
        gui("tsumego-frame", False, 4)
        return lambda: gui.engine.is_idle()

    t.add("_tsumego_frame", frame, delay=2.0, timeout=120)
    t.add("tsumego_frame_board", lambda: shoot("tsumego_frame_board", desc="詰碁の枠を張った盤"), delay=0.5)

    def tsumego_view():
        gui.tsumego_view = True
        gui.tsumego_book_ready = True
        gui.tsumego_book_status = "playing"

    t.add("_tsumego_view", tsumego_view, delay=1.5)
    t.add("tsumego_view", lambda: shoot("tsumego_view", desc="詰碁ビュー（回答帳バナー: 解答中）"), delay=0.5)
    t.add("_banner_off", lambda: setattr(gui, "tsumego_book_status", "off"), delay=1.0)
    t.add("tsumego_banner_off", lambda: shoot("tsumego_banner_off", desc="回答帳バナー: 記録外の手順"), delay=0.5)

    def banner_watch():
        gui.tsumego_book_status = ""
        gui.board_watch_status = "bw-watching"
        gui.board_watch_detail = "盤面監視中（相手の手を自動反映）"

    t.add("_banner_watch", banner_watch, delay=1.0)
    t.add("board_watch_banner", lambda: shoot("board_watch_banner", desc="盤面監視モードのバナー"), delay=0.5)

    def banner_warn():
        gui.board_watch_status = "bw-warn"
        gui.board_watch_detail = "同期できません: アプリの盤が KaTrain の局面＋1手で説明できません（Mismatch）"

    t.add("_banner_warn", banner_warn, delay=1.0)
    t.add("board_watch_warn", lambda: shoot("board_watch_warn", desc="盤面監視モードの警告バナー"), delay=0.5)

    def reset_view():
        gui.board_watch_status = ""
        gui.board_watch_detail = ""
        gui.tsumego_view = False
        gui.tsumego_book_ready = False
        gui.tsumego_book_status = ""

    t.add("_reset_view", reset_view, delay=1.0)
    return t


if __name__ == "__main__":
    from kivy.base import ExceptionHandler, ExceptionManager

    class CrashHandler(ExceptionHandler):
        def handle_exception(self, inst):
            import traceback

            traceback.print_exc()
            return ExceptionManager.PASS

    ExceptionManager.add_handler(CrashHandler())
    app = ManualApp()
    app.run()

    # ---- 後処理: 切り抜き・保存 ----
    from PIL import Image

    manifest_path = os.path.join(TMP_HOME, "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            shots = json.load(f)
        for s in shots:
            img = Image.open(s["raw"]).convert("RGB")
            if s["crop"]:
                l, t_, r, b = s["crop"]
                img = img.crop((l, t_, r, b))
            img.save(os.path.join(OUT, s["name"] + ".png"), optimize=True)
        mpath = os.path.join(OUT, "manifest.json")
        old = {}
        if os.path.exists(mpath):
            with open(mpath, encoding="utf-8") as f:
                old = {m["name"]: m for m in json.load(f)}
        for s in shots:
            old[s["name"]] = {k: v for k, v in s.items() if k != "raw"}
        with open(mpath, "w", encoding="utf-8") as f:
            json.dump(list(old.values()), f, ensure_ascii=False, indent=1)
        print(f"saved {len(shots)} images to {OUT}")
    if not args.keep_home:
        shutil.rmtree(TMP_HOME, ignore_errors=True)
    else:
        print("tmp home:", TMP_HOME)

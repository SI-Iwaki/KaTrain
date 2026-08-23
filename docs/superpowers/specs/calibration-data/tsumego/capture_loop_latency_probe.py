"""詰碁キャプチャの GUI パイプラインの所要時間が問題数とともに伸びないかを測るプローブ。

実際の KaTrain（Kivy + KataGo）をこのスクリプトから起動し、ADB や BlueStacks を使わずに
`tsumego-capture-apply`（キャプチャ認識後の盤への反映。ログ open → 枠の採否 → new-game →
finish_gui → autoloop.on_problem_ready）を N 回投げて、1 回ごとに

- ready: 投入→problem_ready までの秒数（本番の「ログ open→problem_ready」に相当）
- apply: メッセージループ側の本体（[start, end]）
- long_frames / busy: Kivy メインスレッドの長いフレーム（>30ms）＝メインスレッドの停止時間
- stack_inner_top: 停止中にメインスレッドが居た Python フレーム（GIL を握る C 呼び出し中は採れない）
- theme_obs: KivyMD theme_cls の observer 数（ウィジェットの作り直しが漏れていると単調増加する）
- gc_dur / gc_max: 世代別 GC の所要

を JSONL（PROBE_OUT）へ記録する。実測 2026-08-23（spec
`2026-08-23-tsumego-capture-latency-growth.md`）: 修正前は ready が +12〜16ms/問 で伸び
（CollapsablePanel のタブ作り直し → theme_cls への bind が O(observer 数)）、修正後は
0.13 秒で一定。

使い方: `PROBE_N=60 python docs/superpowers/specs/calibration-data/tsumego/capture_loop_latency_probe.py`
（KaTrain のウィンドウが開く。同時に本物の KaTrain を起動しないこと）
"""
import os, sys, time, threading, gc, json, ctypes, traceback
os.environ["KIVY_NO_ARGS"] = "1"
sys.argv = ["katrain"]
N = int(os.environ.get("PROBE_N", "150"))
OUT = os.environ.get("PROBE_OUT", os.path.join(os.path.dirname(__file__), "capture_loop_latency_probe.jsonl"))

from katrain import __main__ as km
from kivy.clock import Clock

SIZE = 13
RAW = [
    ("A7 B11 B12 B9 C12 C9 D8 E10 E11 E8 F10 F8 F9", "A6 A9 B13 B6 B7 B8 C13 C8 D12 D13 D7 D9 E12 E7 E9 F12 F7 G10 G11 G7 G8 G9"),
    ("E10 E11 E12 E13 F10 G9 H9 J11 J9 K11 K9 L10 L9 M11 M12 M13", "F11 F12 G11 H12 J10 J12 K10 K13 L11 L12"),
    ("B6 B7 C5 D5 D6 E3 E6 F1 F3 F4 F5 G2 H2", "A1 B1 B4 B5 D3 D4 E1 E2 F2"),
    ("F3 H3 H4 J2 J4 K5 L4 M5 M6", "J3 K2 K3 L3 M4"),
    ("E3 F2 G2 G3 G4 G5 H5 J3 J5 K3 K6 K7 L7 M1 M7 N2 N3 N4 N5 N6 N7", "G1 H2 H3 J4 K1 K4 K5 L2 L6 M2 M3 M4 M5"),
    ("A11 A12 B10 B8 B9 C8 D11 D8 E8 F10 F8 F9 G11 G12 H12", "B11 B12 C10 C9 D12 D13 D9 E10 E9 F11 F12"),
]
COLS = "ABCDEFGHJKLMNOPQRST"

def build_grid(black, white):
    g = [["."] * SIZE for _ in range(SIZE)]
    for s, c in ((black, "B"), (white, "W")):
        for tok in s.split():
            x = COLS.index(tok[0]); y = int(tok[1:]) - 1
            g[SIZE - 1 - y][x] = c
    return g
GRIDS = [build_grid(b, w) for b, w in RAW]

def handle_count():
    try:
        n = ctypes.c_ulong()
        ctypes.windll.kernel32.GetProcessHandleCount(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(n))
        return n.value
    except Exception:
        return None

class Stub:
    def __init__(self): self.reset()
    def reset(self):
        self.ready = threading.Event(); self.t_ready = None; self.t_black = None; self.route = None; self.failed = None
    def on_problem_ready(self, token, grid, key, route, log_name=None):
        self.t_ready = time.perf_counter(); self.route = route; self.log_name = log_name; self.ready.set()
    def on_black_move(self, token, coords):
        if self.t_black is None: self.t_black = time.perf_counter()
    def on_capture_failed(self, msg):
        self.failed = msg; self.ready.set()

def driver(app):
    try:
        _driver(app)
    except Exception:
        traceback.print_exc()
    finally:
        Clock.schedule_once(lambda dt: app.stop(), 1.0)

def _driver(app):
    import collections
    from kivy.core.window import Window
    for _ in range(600):
        gui = getattr(app, "gui", None)
        if gui is not None and getattr(gui, "engine", None) is not None and getattr(gui, "game", None) is not None:
            try:
                if gui.engine.is_idle(): break
            except Exception: pass
        time.sleep(0.5)
    time.sleep(5)
    gui = app.gui
    times = {}; calls = {}; marks = {}
    def wrap_obj(obj, name, label=None):
        label = label or name
        try:
            f = getattr(obj, name)
        except Exception as e:
            print(f"PROBE: cannot wrap {label}: {e}", flush=True); return
        def w(*a, **k):
            t = time.perf_counter()
            marks.setdefault("first_" + label, t)
            try: return f(*a, **k)
            finally:
                times[label] = round(times.get(label, 0) + time.perf_counter() - t, 4)
                calls[label] = calls.get(label, 0) + 1
                marks["last_" + label] = time.perf_counter()
        setattr(obj, name, w)
    for name in ["start_game_log", "_choose_tsumego_frame", "_do_new_game", "_apply_tsumego_region",
                 "_start_tsumego_watch", "_stop_board_watcher", "_tsumego_frameless_board", "update_player",
                 "update_gui", "_do_update_state"]:
        wrap_obj(gui, name)
    wrap_obj(gui.board_gui, "draw_board", "bg.draw_board")
    wrap_obj(gui.board_gui, "draw_board_contents", "bg.draw_contents")
    wrap_obj(gui.board_gui, "draw_hover_contents", "bg.draw_hover")
    wrap_obj(gui.controls, "update_evaluation", "ctl.update_eval")
    wrap_obj(gui.controls, "update_players", "ctl.update_players")
    wrap_obj(gui.controls, "set_status", "ctl.set_status")
    wrap_obj(gui.controls.graph, "initialize_from_game", "graph.init")
    wrap_obj(gui.controls.move_tree, "redraw", "mt.redraw")
    wrap_obj(gui.controls.move_tree, "draw_move_tree", "mt.draw")
    wrap_obj(gui.play_mode, "switch_ui_mode", "switch_ui_mode")
    wrap_obj(Window, "raise_window", "raise_window")
    orig_apply = gui._do_tsumego_capture_apply
    def apply_w(*a, **k):
        marks["apply_start"] = time.perf_counter()
        try: return orig_apply(*a, **k)
        finally: marks["apply_end"] = time.perf_counter()
    gui._do_tsumego_capture_apply = apply_w
    # frame-time sampler on main thread
    frames = {"last": None, "long": [], "n": 0, "busy": 0.0}
    def tick(dt):
        now = time.perf_counter()
        if frames["last"] is not None:
            d = now - frames["last"]
            frames["n"] += 1
            if d > 0.03:
                frames["long"].append((round(now - marks.get("t_post", now), 3), round(d, 3)))
                frames["busy"] += d
        frames["last"] = now
    Clock.schedule_interval(tick, 0)
    # main-thread stack sampler: when the Kivy loop has not ticked for >50ms, sample the main thread stack
    import traceback as _tb
    main_tid = threading.main_thread().ident
    stacks = {"samples": []}
    def stack_sampler():
        while True:
            time.sleep(0.005)
            last = frames["last"]
            if last is None or time.perf_counter() - last < 0.05:
                continue
            try:
                fr = sys._current_frames().get(main_tid)
                if fr is None: continue
                st = _tb.extract_stack(fr, limit=14)
                sig = " < ".join(f"{os.path.basename(f.filename)}:{f.lineno}:{f.name}" for f in reversed(st))
                stacks["samples"].append(sig)
            except Exception:
                pass
    threading.Thread(target=stack_sampler, daemon=True).start()
    # gc duration callbacks
    gcst = {"t": None, "dur": [0.0, 0.0, 0.0], "n": [0, 0, 0], "max": 0.0}
    def gccb(phase, info):
        if phase == "start":
            gcst["t"] = time.perf_counter()
        elif gcst["t"] is not None:
            d = time.perf_counter() - gcst["t"]; g = info.get("generation", 0)
            gcst["dur"][g] += d; gcst["n"][g] += 1; gcst["max"] = max(gcst["max"], d)
    gc.callbacks.append(gccb)
    theme_cls = app.theme_cls
    def theme_obs():
        try:
            return {p: len(list(theme_cls.get_property_observers(p))) for p in ("primary_palette", "accent_palette", "theme_style")}
        except Exception as e:
            return repr(e)
    stub = Stub(); gui._autoloop = stub
    prev_census = None
    print(f"PROBE: start N={N}", flush=True)
    with open(OUT, "a", encoding="utf-8") as out:
        for i in range(N):
            times.clear(); calls.clear(); marks.clear(); stub.reset()
            frames["long"] = []; frames["n"] = 0; frames["busy"] = 0.0; stacks["samples"] = []
            gcst["dur"] = [0.0, 0.0, 0.0]; gcst["n"] = [0, 0, 0]; gcst["max"] = 0.0
            time.sleep(0.3)
            grid = GRIDS[i % len(GRIDS)]
            t_post = time.perf_counter(); marks["t_post"] = t_post
            gui("tsumego-capture-apply", grid, False, 4, None, False, capture_note=None, view_kind="app")
            stub.ready.wait(90)
            for _ in range(100):
                if stub.t_black or stub.failed: break
                time.sleep(0.1)
            t_end = time.perf_counter()
            rel = lambda k: (round(marks[k] - t_post, 3) if k in marks else None)
            rec = dict(
                i=i, grid=i % len(GRIDS), route=stub.route, failed=stub.failed,
                apply_start=rel("apply_start"), apply_end=rel("apply_end"),
                ready=round((stub.t_ready or t_end) - t_post, 3),
                black=round(stub.t_black - t_post, 3) if stub.t_black else None,
                first_raise=rel("first_raise_window"), first_watch=rel("first__start_tsumego_watch"),
                first_update_gui=rel("first_update_gui"), last_update_gui=rel("last_update_gui"),
                first_draw_board=rel("first_bg.draw_board"), last_draw_board=rel("last_bg.draw_board"),
                phases=dict(times), calls=dict(calls),
                frames_n=frames["n"], long_frames=frames["long"][:40], busy=round(frames["busy"], 3),
                gc_dur=[round(x, 3) for x in gcst["dur"]], gc_n=list(gcst["n"]), gc_max=round(gcst["max"], 3),
                threads=threading.active_count(), handles=handle_count(),
                n_objects=(len(gc.get_objects()) if i % 5 == 0 else None),
            )
            try:
                cnt = collections.Counter(stacks["samples"])
                rec["stack_n"] = len(stacks["samples"])
                rec["stack_top"] = [(c, s) for s, c in cnt.most_common(6)]
                inner = collections.Counter(s.split(" < ")[0] for s in stacks["samples"])
                rec["stack_inner_top"] = inner.most_common(8)
            except Exception as e:
                rec["stack_err"] = repr(e)
            rec["theme_obs"] = theme_obs()
            try: rec["clock_events"] = len(Clock.get_events())
            except Exception: pass
            try: rec["canvas_len"] = gui.board_gui.canvas.length(); rec["canvas_before"] = gui.board_gui.canvas.before.length(); rec["canvas_after"] = gui.board_gui.canvas.after.length()
            except Exception: pass
            try: rec["queries"] = len(gui.engine.queries)
            except Exception: pass
            if i % 25 == 0:
                c = collections.Counter(type(o).__name__ for o in gc.get_objects())
                if prev_census is not None:
                    diff = {k: c[k] - prev_census.get(k, 0) for k in c}
                    rec["census_diff_top"] = sorted(diff.items(), key=lambda kv: -kv[1])[:25]
                rec["census_top"] = c.most_common(15)
                prev_census = c
            out.write(json.dumps(rec) + "\n"); out.flush()
            print(f"PROBE {i}: ready={rec['ready']} apply=[{rec['apply_start']},{rec['apply_end']}] raise={rec['first_raise']} busy={rec['busy']} gcmax={rec['gc_max']} gcdur={rec['gc_dur']} long={rec['long_frames'][:6]} upd_gui={times.get('update_gui')} draw={times.get('bg.draw_board')} cont={times.get('bg.draw_contents')} mt={times.get('mt.draw')} thr={rec['threads']} obs={rec['theme_obs']} stacks={rec.get('stack_n')} inner={rec.get('stack_inner_top', [])[:3]}", flush=True)
            time.sleep(1.0)
    print("PROBE: done", flush=True)

class ProbeApp(km.KaTrainApp):
    def on_start(self):
        super().on_start()
        threading.Thread(target=driver, args=(self,), daemon=True).start()

if __name__ == "__main__":
    app = ProbeApp()
    app.run()

"""対局アプリの盤面を監視して、相手の着手を KaTrain へ注入するためのロジック。

Kivy にも KataGo にも依存しない（テストから直接 import できるようにするため）。
設計は docs/superpowers/specs/2026-08-18-board-watch-design.md 参照。

座標系に注意: 認識グリッド grid[i][j] の i は**画面上origin**（tsumego_capture.py:100）、
KaTrain の Move.coords = (x, y) は **y が下origin**（sgf_parser.py:31-39）。
この変換漏れは実測済みのバグ源なので、変換は必ずこのモジュールの純関数を通す。
"""

import threading
import time
from typing import NamedTuple, Optional, Tuple

EMPTY = "."
BLACK = "B"
WHITE = "W"

_SGF_COORD = "abcdefghijklmnopqrstuvwxyz"


def stones_to_grid(stones, size):
    """(coords, player) の列（coords は KaTrain の下origin (x, y)）を上origin グリッドにする"""
    grid = [[EMPTY] * size for _ in range(size)]
    for coords, player in stones:
        if coords is None:  # パスは盤に石を置かない
            continue
        x, y = coords
        grid[size - 1 - y][x] = player
    return grid


def move_to_grid(coords, size):
    """KaTrain の Move.coords (x, y) → グリッド座標 (i, j)。パス（None）は None"""
    if coords is None:
        return None
    x, y = coords
    return (size - 1 - y, x)


def grid_to_move(i, j, size):
    """グリッド座標 (i, j) → KaTrain の Move.coords (x, y)"""
    return (j, size - 1 - i)


def board_sgf(grid, komi, rules, next_player):
    """監視モード用の SGF（配置のみ）。石が0個でも成立する。

    tsumego_capture.grid_to_sgf を流用しないのは、あれが石0個で CaptureError を投げ
    （詰碁向けの文言が出る）、PL[B] 固定でもあるため（spec §3.2）。
    """
    size = len(grid)
    black = [_SGF_COORD[j] + _SGF_COORD[i] for i, row in enumerate(grid) for j, v in enumerate(row) if v == BLACK]
    white = [_SGF_COORD[j] + _SGF_COORD[i] for i, row in enumerate(grid) for j, v in enumerate(row) if v == WHITE]
    sgf = f"(;GM[1]FF[4]CA[UTF-8]SZ[{size}]KM[{komi}]RU[{rules}]PL[{next_player}]"
    if black:
        sgf += "AB" + "".join(f"[{p}]" for p in black)
    if white:
        sgf += "AW" + "".join(f"[{p}]" for p in white)
    return sgf + ")"


def import_next_player(grid, human_color):
    """取り込み時の手番と、その根拠（ログ用の文字列）を返す（spec §3.2 / §12）。

    石数パリティは一般には手番を表さない: 盤上石数 b, w と取られた石数 cb, cw の
    間には b − w = cw − cb が成り立つので、取りが1回でも入るとパリティは崩れる
    （9路で双方6手ずつ・黒が白1子取った局面は 黒6/白5 だが手番は黒）。よって
    取りが起きうる局面では安全側の human_color に倒す（誤っていても KaTrain が
    誤った色で勝手に打ち出す事故は起きず、相手の手待ちのまま止まるだけ＝
    §2.5c のウォッチドッグが拾い、Enter の ai-move が脱出口になる）。

    ただし**盤上2子以内では取りが起き得ない**ので、この範囲のパリティは推測では
    なく確定である:

    - 空盤は対局の開始そのもの＝囲碁のルールで黒が先手
    - 最初の取りは3手目より前には起こせない（1手目の石は空盤上で呼吸点2以上を
      持ち、2手目の1子では詰められない）。その3手目の取り（B, W, B と進んで黒が
      白1子を取る）が作る盤は 黒2子・白0子＝ b − w = 2 で、下の b − w ∈ {0,1} ガードから
      外れる。したがって「2子以内 かつ b − w ∈ {0, 1}」を満たす盤は
      (0,0) / (1,0) / (1,1) の3通りだけで、どれも取りなしの交互着手でしか到達
      できない（3路・4路の合法手列の総当たりで確認＝
      tests/test_board_watch.py の test_import_next_player_agrees_with_every_reachable_small_position）

    これは「対局が始まってから監視を ON にする」という最もありふれた手順を救う。
    旧実装は石が1つでもあれば human_color に倒していたため、アプリ側 AI が初手を
    打った直後に ON にすると KaTrain 側 AI の手番が来ず対局が始まらなかった
    （実測 game_20260819_112356.log: 黒1子の9路盤を「手番=B・人間側に固定」で
    取り込み、白番の KaTrain AI が2手目を打てないまま停止）。

    前提: この2子以内の確定は**最初の2手にパスが無いこと**に依る（パスは盤に
    現れないので1枚の盤からは区別できない。そもそも監視はパスを検出対象外に
    している＝§0）。実戦の2手目までのパスは考えなくてよい。
    """
    stones = [cell for row in grid for cell in row if cell != EMPTY]
    if not stones:
        return BLACK, "空盤なので黒番"
    black, white = stones.count(BLACK), stones.count(WHITE)
    if len(stones) <= 2 and black - white in (0, 1):
        return (BLACK if black == white else WHITE), "2子以内なので石数から確定"
    return human_color, "人間側に固定"


def _neighbours(i, j, size):
    for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        ni, nj = i + di, j + dj
        if 0 <= ni < size and 0 <= nj < size:
            yield ni, nj


def _group_and_liberties(grid, i, j):
    """(i, j) の石と同色で連結した石の集合と、その呼吸点の集合を返す"""
    size = len(grid)
    color = grid[i][j]
    stack = [(i, j)]
    group = {(i, j)}
    liberties = set()
    while stack:
        ci, cj = stack.pop()
        for ni, nj in _neighbours(ci, cj, size):
            v = grid[ni][nj]
            if v == EMPTY:
                liberties.add((ni, nj))
            elif v == color and (ni, nj) not in group:
                group.add((ni, nj))
                stack.append((ni, nj))
    return group, liberties


def apply_move_to_grid(grid, i, j, color):
    """グリッドに1手打ち、取りを処理した新グリッドを返す。打てないときは None。

    コウは判定しない（グリッド1枚では履歴が無いため）。コウ違反はエンジン側が
    弾き、注入ガードのタイムアウトとして表面化する（spec §2.5b）。
    """
    size = len(grid)
    if not (0 <= i < size and 0 <= j < size) or grid[i][j] != EMPTY:
        return None
    opponent = WHITE if color == BLACK else BLACK
    new_grid = [row[:] for row in grid]
    new_grid[i][j] = color
    for ni, nj in _neighbours(i, j, size):
        if new_grid[ni][nj] == opponent:
            group, liberties = _group_and_liberties(new_grid, ni, nj)
            if not liberties:
                for gi, gj in group:
                    new_grid[gi][gj] = EMPTY
    _group, liberties = _group_and_liberties(new_grid, i, j)
    if not liberties:
        return None  # 自殺手（取りを処理した後でも呼吸点が無い）
    return new_grid


class WatchState(NamedTuple):
    """KaTrain 側の局面スナップショット（__main__ が作り、判定はここでだけ行う）"""

    current_grid: list
    last_move: Optional[Tuple[int, int, str]]  # (i, j, color)。root とパスは None
    to_play: str
    to_play_is_human: bool
    ai_can_respond: bool
    move_number: int
    board_size: int


class Verdict(NamedTuple):
    kind: str  # "in_sync" | "waiting" | "ahead" | "move" | "mismatch"
    move: Optional[Tuple[int, int]] = None
    reason: str = ""


def reconcile(state, observed):
    """観測グリッドが「現局面＋打つ側の1手」で説明できるかを判定する。

    表は**上から評価する優先順位**（spec §2.3）。特に「AI の手番なら絶対に注入しない」
    （waiting）を Move 判定より前に置くのが安全弁の要 — 色の割り当てが逆だと相手の石が
    常に to_play と同色になり、Move 判定が成立してしまう。
    """
    if len(observed) != state.board_size:
        return Verdict(
            "mismatch",
            reason=f"盤サイズが違います（アプリ {len(observed)}路 / KaTrain {state.board_size}路）",
        )
    if not state.ai_can_respond:
        return Verdict("mismatch", reason="AI が応手できない局面です（分岐・終局・解析モード・リージョン）")
    if not state.to_play_is_human:
        # KaTrain の AI が考えている最中。正常状態なので無音（数秒続くため警告にしてはいけない）。
        # 色の割り当てが逆でここから永久に出られないケースは BoardWatcher のウォッチドッグが拾う
        return Verdict("waiting")
    if observed == state.current_grid:
        return Verdict("in_sync")
    if state.last_move is not None:
        li, lj, lcolor = state.last_move
        if apply_move_to_grid(observed, li, lj, lcolor) == state.current_grid:
            return Verdict("ahead")
    matches = []
    for i in range(state.board_size):
        for j in range(state.board_size):
            if observed[i][j] == state.to_play and state.current_grid[i][j] == EMPTY:
                if apply_move_to_grid(state.current_grid, i, j, state.to_play) == observed:
                    matches.append((i, j))
    if len(matches) == 1:
        return Verdict("move", move=matches[0])
    return Verdict("mismatch", reason="盤面の差が1手で説明できません")


class WatchSettings(NamedTuple):
    poll_interval_ms: int = 400  # 相手の石が来ようがない局面（idle）の周期
    stable_frames: int = 2
    failure_warn_frames: int = 8
    inject_timeout_ms: int = 5000
    stall_warn_sec: float = 20.0
    resync_hint_frames: int = 10
    backoff_after_failures: int = 3
    backoff_factor: float = 2.0
    poll_interval_max_ms: int = 2000
    # 相手の着手を実際に待っている局面（in_sync・注入の反映待ち・確定途中）の周期。
    # 反映の体感遅延はほぼ「位相待ち＋確定待ち」＝この値2つぶんで決まる（spec 追記3）。
    # poll_interval_ms と同値にすれば適応をやめて従来どおりの固定周期に戻る。
    poll_interval_active_ms: int = 50


def watch_settings_from_config(cfg):
    d = cfg or {}
    default = WatchSettings()
    return WatchSettings(
        poll_interval_ms=int(d.get("poll_interval_ms", default.poll_interval_ms)),
        stable_frames=int(d.get("stable_frames", default.stable_frames)),
        failure_warn_frames=int(d.get("failure_warn_frames", default.failure_warn_frames)),
        inject_timeout_ms=int(d.get("inject_timeout_ms", default.inject_timeout_ms)),
        stall_warn_sec=float(d.get("stall_warn_sec", default.stall_warn_sec)),
        resync_hint_frames=int(d.get("resync_hint_frames", default.resync_hint_frames)),
        backoff_after_failures=int(d.get("backoff_after_failures", default.backoff_after_failures)),
        backoff_factor=float(d.get("backoff_factor", default.backoff_factor)),
        poll_interval_max_ms=int(d.get("poll_interval_max_ms", default.poll_interval_max_ms)),
        poll_interval_active_ms=int(d.get("poll_interval_active_ms", default.poll_interval_active_ms)),
    )


STATUS_WATCHING = "bw-watching"
STATUS_WARN = "bw-warn"
WATCHING_TEXT = "盤面監視中（相手の手を自動反映）"
RESYNC_HINT = "（監視トグルのホットキーで OFF にし、1秒ほどおいてからもう一度押すと現局面を取り込み直します）"


class PermanentCaptureError(Exception):
    """すぐ直らない失敗（ウィンドウが無い等）。過渡失敗と違い即警告する。

    tsumego_capture の CaptureError は1種類しかなく、app 経路と Web 経路のメッセージを
    連結して投げ直すため**型では切り分けられない**。そこで「どこで失敗したか」を
    知っている投げる側（AppBoardReader）に恒久かどうかを表明させる。
    """


def _grid_key(grid):
    return tuple("".join(row) for row in grid)


class BoardWatcher:
    """アプリ盤面をポーリングして相手の着手を検出する。KaTrain の型は一切知らない。

    外界とはコールバックだけで接する:
      capture_fn()    -> 観測グリッド（失敗は例外）
      get_state_fn()  -> WatchState または None
      on_move(i, j, color, move_number, board_size)
      on_status(kind, text)   kind: "bw-watching" / "bw-warn" / ""
    """

    def __init__(self, capture_fn, get_state_fn, on_move, on_status, settings, clock=time.monotonic):
        self.capture_fn = capture_fn
        self.get_state_fn = get_state_fn
        self.on_move = on_move
        self.on_status = on_status
        self.settings = settings
        self.clock = clock
        self.interval_ms = settings.poll_interval_ms
        self._stopped = threading.Event()
        self._thread = None  # start() 前に触っても None（AttributeError にしない）
        self._stable_move = None
        self._stable_count = 0
        self._fail_count = 0
        self._mismatch_count = 0
        self._pending = None  # (i, j, move_number, deadline)
        self._blocked = None  # (i, j, move_number) タイムアウトした手を同じ局面で再注入しない
        self._quiet_key = None
        self._quiet_since = None

    # --- 1周ぶんの判断（テストはここを直接叩く） ---
    def step(self):
        try:
            observed = self.capture_fn()
        except Exception as e:  # CaptureError も未知の例外もここで吸収する
            self._on_capture_failure(str(e), permanent=isinstance(e, PermanentCaptureError))
            return
        self._on_capture_success()
        state = self.get_state_fn()
        if state is None:
            return
        if self._pending is not None and not self._resolve_pending(state):
            if self._pending is not None:
                self._active()  # 注入した手が反映されるまでは速く確認する（タイムアウト後は idle へ戻す）
            return
        verdict = reconcile(state, observed)
        if verdict.kind == "mismatch":
            self._on_mismatch(verdict.reason)
            return
        self._mismatch_count = 0
        if verdict.kind == "move":
            self._on_move_verdict(state, verdict.move)
            return
        self._on_quiet(state, observed, verdict.kind)

    def _resolve_pending(self, state):
        """注入の反映を待っている間の処理。まだ待つなら False を返す。

        spec §2.5(b) は「期待グリッド」または「期待グリッド＋KaTrain の最終手」の
        いずれかで成立、と書いているが、実装は **move_number（= current_node.depth）が
        変わったか**で見る。これは spec の2条件を包含する（どちらの盤面になっていても
        手数は必ず増えている）うえ、期待グリッドが AI の応手で一瞬しか存在しない問題も
        同時に解ける。KaTrain 側が undo で戻った場合も「変わった」に入り、その後の
        reconcile が Mismatch として拾う。
        """
        i, j, move_number, deadline = self._pending
        if state.move_number != move_number:  # KaTrain 側で局面が進んだ＝反映された
            self._pending = None
            self._blocked = None
            return True
        if self.clock() >= deadline:
            self._pending = None
            self._blocked = (i, j, move_number)
            self._warn("着手が反映されませんでした（コウ・非合法手の可能性）" + RESYNC_HINT)
            return False
        return False

    def _on_move_verdict(self, state, move):
        self._quiet_key = None
        self._quiet_since = None
        if self._blocked == (move[0], move[1], state.move_number):
            return  # タイムアウトした手は局面が変わるまで投げ直さない（復帰待ちを速く回しても意味がない）
        self._active()  # 確定待ちの1周が体感遅延に直結するので詰める
        if self._stable_move == move:
            self._stable_count += 1
        else:
            self._stable_move = move
            self._stable_count = 1
        if self._stable_count < self.settings.stable_frames:
            return
        self._stable_move = None
        self._stable_count = 0
        self._pending = (move[0], move[1], state.move_number, self.clock() + self.settings.inject_timeout_ms / 1000.0)
        self._watching()
        self.on_move(move[0], move[1], state.to_play, state.move_number, state.board_size)

    def _on_mismatch(self, reason):
        self._stable_move = None
        self._stable_count = 0
        self._quiet_key = None
        self._quiet_since = None
        self._mismatch_count += 1
        message = reason
        if self._mismatch_count >= self.settings.resync_hint_frames:
            message += RESYNC_HINT
        self._warn(message)

    def _on_quiet(self, state, observed, kind):
        """waiting / ahead / in_sync = 無音の終端状態。長すぎたら警告する（spec §2.5c）"""
        self._stable_move = None
        self._stable_count = 0
        if kind == "in_sync":
            # 盤がアプリと一致している＝次に変わるのは相手の石。ここだけが低遅延を要する
            # 局面で、waiting（KaTrain の AI が思考中）と ahead（ユーザーがまだアプリへ
            # タップしていない）は相手の石が来ようがないので idle のままにする
            self._active()
        key = (kind, state.move_number, _grid_key(observed))
        now = self.clock()
        if key != self._quiet_key:
            self._quiet_key = key
            self._quiet_since = now
            self._watching()
        elif self._quiet_since is not None and now - self._quiet_since >= self.settings.stall_warn_sec:
            self._quiet_since = now  # 再警告は stall_warn_sec ごと
            # import_next_player の確定ゾーン（空盤・盤上2子以内）で対局開始まわりの
            # デッドロックは無くなったが、「対局が進んだ局面で、実は KaTrain 側の手番である
            # タイミングで監視を ON にする」ケースは1フレームの盤面（取られた石数が
            # 分からない）からは判定できず残る。この場合
            # ai-move（Enter / numpad-Enter、gui.kv:883）で AI に1手打たせれば動き出す。
            # もう一方のありふれた原因（アプリへのタップ忘れ）と合わせて両方を案内する。
            # どちらが実際の原因かは判定しない
            self._warn(
                "盤面が変化しません（着手をアプリへ入力し忘れていないか、"
                "または KaTrain の手番かもしれません。Enter で AI が着手します）"
            )

    def _on_capture_failure(self, message, permanent=False):
        self._fail_count += 1
        if self._fail_count >= self.settings.backoff_after_failures:
            self.interval_ms = min(
                int(self.interval_ms * self.settings.backoff_factor), self.settings.poll_interval_max_ms
            )
        # 恒久失敗は即警告、過渡失敗（アニメーション中の "?" 等）は連続 N 回まで黙る。
        # どちらも監視は止めない（最小化しただけで死なないように）
        if permanent or self._fail_count >= self.settings.failure_warn_frames:
            self._warn(f"盤面を認識できません: {message}")

    def _on_capture_success(self):
        self._fail_count = 0
        # 撮影に成功したらまず idle に戻す（＝バックオフの解除）。この後 step() の各分岐が
        # 「相手の着手を待っている」と判断したときだけ _active() で上書きする
        self.interval_ms = self.settings.poll_interval_ms

    def _active(self):
        self.interval_ms = self.settings.poll_interval_active_ms

    def _watching(self):
        self.on_status(STATUS_WATCHING, WATCHING_TEXT)

    def _warn(self, message):
        self.on_status(STATUS_WARN, message)

    # --- スレッド ---
    # stop() が join() まで面倒を見る＝「停止フラグ＋join のみ」（spec §3.3）。
    # join のタイムアウトは「一回のポーリングにかかる現実的な時間」より十分大きく取る
    # （AppBoardReader のキャッシュ有り1周は40〜85ms実測だが、認識器が固まった場合に
    # stop() の呼び出し元＝ホットキーのワーカースレッドを無期限にブロックしないため）。
    _STOP_JOIN_TIMEOUT_SEC = 5.0

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return  # 二重起動ガード。既に走っているスレッドがあれば何もしない
        self._stopped.clear()  # 前回の stop() で立てたフラグを下ろす。無いと再 start() 直後の
        # run() が最初の is_set() チェックで即 True を引き、1周も回らず終了する（無症状の停止）
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()

    def run(self):
        while not self._stopped.is_set():
            try:
                self.step()
            except Exception as e:
                # step() 内で吸収しきれなかった想定外の例外でもスレッドを殺さない。
                # 落ちると「緑バナーのまま1手も入らない」無症状の停止になる
                self._warn(f"監視でエラーが発生しました: {e}")
            self._stopped.wait(self.interval_ms / 1000.0)

    def stop(self):
        self._stopped.set()
        if self._thread is not None:
            # 進行中の1周（撮影・分類）が終わるまでは flag を見に行けないので join は要る。
            # タイムアウトしても例外にはしない＝daemon スレッドで Event は立ったままなので
            # 遅かれ早かれ自分で終わる。ここで固まると呼び出し元（ホットキー）まで止まる
            self._thread.join(self._STOP_JOIN_TIMEOUT_SEC)


def _capture_api():
    """tsumego_capture の関数群を遅延 import して返す（テストで差し替えられるように関数にする）"""
    from katrain.core.tsumego_capture import (
        capture_screen_rect,
        detect_board,
        detect_size_and_classify,
        find_window_rect,
    )

    return find_window_rect, capture_screen_rect, detect_board, detect_size_and_classify


def _board_fingerprint(img, board_rect):
    """盤矩形の画素そのもの（バイト列）を返す。取れなければ None＝「比較しない」に倒す。

    撮り直しても盤の画素が1ビットも変わっていなければ、格子検算も分類も同じ入力に対する
    純粋な関数なので結果は必ず同一になる。だから省ける（判定の意味論は変わらない）。
    """
    try:
        return img.crop(board_rect).tobytes()
    except Exception:
        return None


class AppBoardReader:
    """アプリ窓を撮って観測グリッドを返す。盤矩形・盤サイズ・直前フレームをキャッシュする。

    1周の実測は「撮影 21〜27ms ＋ 格子検算 5〜25ms ＋ 分類 7〜29ms」＝40〜85ms。
    毎周 detect_size_and_classify をキャッシュしたサイズ1候補で回すのは、これが
    「盤矩形と規則配置の仮定がまだ合っているか」の検算を兼ねるため。

    ただし対局中のフレームはほとんどが「前と同じ盤」なので、盤矩形の画素を前回と比較して
    同一なら分類ごと省く（**1周が 21〜23ms に落ちる**）。これが無いと 19路では1周 85ms
    かかり、50ms 周期を指定しても実際には 85ms 間隔でしか回れない＝低遅延化が成立しない。
    比較対象を窓全体でなく**盤矩形**にするのは、窓内の時計・通知などが毎フレーム変わると
    最適化が丸ごと効かなくなるため。
    """

    def __init__(self, window_title, board_sizes):
        self.window_title = window_title
        self.board_sizes = list(board_sizes)
        self.size = None
        self._window_rect = None
        self._board_rect = None
        self._fingerprint = None
        self._grid = None

    def read(self):
        find_window_rect, capture_screen_rect, detect_board, detect_size_and_classify = _capture_api()
        try:
            rect = find_window_rect(self.window_title)
        except Exception as e:
            # ウィンドウが無い＝最小化・終了。過渡失敗と違い連続 N 回待たずに即警告させる
            raise PermanentCaptureError(str(e)) from e
        if rect != self._window_rect:  # 窓が動いた・リサイズされた
            self._window_rect = rect
            self._board_rect = None
        img = capture_screen_rect(rect)
        if self._board_rect is None:
            self._forget_frame()
            board_rect = detect_board(img)
            size, grid = detect_size_and_classify(img, board_rect, self.board_sizes)
            self._board_rect = board_rect
            self.size = size
            self._remember_frame(_board_fingerprint(img, board_rect), grid)
            return grid
        fingerprint = _board_fingerprint(img, self._board_rect)
        if fingerprint is not None and fingerprint == self._fingerprint:
            return self._grid  # 盤の画素が1つも変わっていない＝分類しても同じグリッドになる
        try:
            _size, grid = detect_size_and_classify(img, self._board_rect, [self.size])
        except Exception:
            self._board_rect = None  # 次回はフル検出からやり直す
            self._forget_frame()  # 失敗した回の画素を覚えない（覚えると次周が古いグリッドを返す）
            raise
        self._remember_frame(fingerprint, grid)
        return grid

    def _remember_frame(self, fingerprint, grid):
        self._fingerprint = fingerprint
        self._grid = grid

    def _forget_frame(self):
        self._fingerprint = None
        self._grid = None

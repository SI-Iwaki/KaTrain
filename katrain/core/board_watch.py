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

from katrain.core.constants import AI_TSUMEGO, AI_TSUMEGO_SOLVER

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
    if all(cell == EMPTY for row in grid for cell in row):
        return BLACK, "空盤なので黒番"
    player = opening_next_player(grid)
    if player is not None:
        return player, "2子以内なので石数から確定"
    return human_color, "人間側に固定"


def opening_next_player(grid):
    """盤上2子以内で手番が確定する序盤形なら手番を、そうでなければ None を返す。

    import_next_player の確定ゾーン（空盤→黒 / 黒1子→白 / 黒白1子ずつ→黒）そのもの。取りが
    起きた形（黒2子・白0子など b − w ∉ {0, 1}）と3子以上は None。監視中の「アプリで次の対局が
    始まった」判定（BoardWatcher._new_game_seen・spec 追記10）も、この形を新しい対局の証拠に使う
    （対局の途中の盤は2子以内に戻らない）
    """
    stones = [cell for row in grid for cell in row if cell != EMPTY]
    black, white = stones.count(BLACK), stones.count(WHITE)
    if len(stones) <= 2 and black - white in (0, 1):
        return BLACK if black == white else WHITE
    return None


def watch_player_assignment(ai_colors, near_color):
    """監視を始めるときに KaTrain の AI を打たせる色を決める。(色, ログ用の根拠) を返す（spec 追記10）。

    ai_colors は今 AI になっている色のリスト。戦略は「今 AI にしている側」のものをそのまま使う
    （どの戦略で打つかはユーザーの選択＝勝手に選ばない）ので、AI がちょうど1人のときだけ開始できる。
    開始できなければ (None, バナーに出す理由)。near_color は対局者アイコンから読んだ手前（自分）の色で、
    読めなければ None＝従来どおりプレイヤー設定のまま
    """
    if len(ai_colors) != 1:
        return None, "片方を AI・片方を人間に設定してから開始してください"
    current = ai_colors[0]
    if near_color is None:
        return current, "対局者アイコンから手番を読めないため設定のまま"
    if near_color == current:
        return current, "手前の対局者の色＝設定どおり"
    return near_color, "手前の対局者の色に入れ替え"


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


def replay_grid(base_grid, moves, size):
    """キャプチャ時の認識グリッドに root からの着手列を再生して「アプリ側の盤」を再現する。

    詰碁では KaTrain の盤とアプリの盤が一致しない。枠は壁と充填を**足す**だけでなく、
    drop_non_core_stones（tsumego_frame.py）で枠矩形の境界線上・外側の非コア石を
    **盤から消す**ため、game.stones はアプリの盤と両方向にずれている。そこで監視の
    比較基準は「キャプチャ時の認識グリッド + root からの着手列」で作り直す。

    moves は (coords, color) の列で、coords は KaTrain の下origin (x, y)（パスは None）。
    取りはこのグリッド＝アプリの盤の上で計算されるので、枠石を巻き込む KaTrain 側の
    取りとずれない。

    キャッシュせず毎周 root から再生する前提の関数（13路×20手で apply_move_to_grid 20回＝
    無視できるコスト）。こうすると undo/redo/分岐が自動的に正しくなる。

    再現できない（アプリ側では既に石がある等）ときは None を返す＝「比較しない」に倒す。
    """
    if base_grid is None or len(base_grid) != size:
        return None
    grid = [row[:] for row in base_grid]
    for coords, color in moves:
        if coords is None:  # パスは盤に石を置かない
            continue
        i, j = move_to_grid(coords, size)
        grid = apply_move_to_grid(grid, i, j, color)
        if grid is None:
            return None
    return grid


def previous_app_grid(base_grid, moves, size, current_grid):
    """current_grid の1手前のアプリ盤（`ahead` 判定の基準）。作れないときは None。

    `ahead`（KaTrain が打ったがユーザーがまだアプリへタップしていない）は「アプリの盤 ＝
    1手前の局面」なので、直前局面そのものと突き合わせるのが正しい。逆再生（observed に
    最終手を打ち直して current と一致するか）だけでは**相手の応手が最終手を取った局面**
    でも成立してしまう — 取られた石を打ち直すと相手の石を取り返して current に戻る
    （スナップバック / コウ形）。実測 2026-08-22（回答帳キー 04b0a596ff・13路）: 黒 H13 の
    唯一の呼吸点 G13 に白が打って H13 を取った局面が `ahead` に化け、白の着手が永久に
    注入されなかった（詰碁モードは stall_kinds から ahead を外しているので警告も出ない）。

    再生が現盤と食い違うとき（途中の AB/AE 等）は None を返す＝呼び出し側は従来の
    逆再生判定に倒れる。**コウの取り返しは盤面が1手前に戻るので、この関数を使っても
    `ahead` と区別できない**（1枚のグリッドには履歴が無い）＝注入しない側に倒れる。
    """
    if not moves:
        return None
    coords, color = moves[-1]
    if coords is None:  # パス（ahead 判定自体が last_move=None でスキップされる）
        return None
    previous = replay_grid(base_grid, moves[:-1], size)
    if previous is None:
        return None
    i, j = move_to_grid(coords, size)
    if apply_move_to_grid(previous, i, j, color) != current_grid:
        return None  # 再現が現盤と食い違う＝信用しない
    return previous


class WatchState(NamedTuple):
    """KaTrain 側の局面スナップショット（__main__ が作り、判定はここでだけ行う）"""

    current_grid: list
    last_move: Optional[Tuple[int, int, str]]  # (i, j, color)。root とパスは None
    to_play: str
    to_play_is_human: bool
    ai_can_respond: bool
    move_number: int
    board_size: int
    # 1手前のアプリ盤（previous_app_grid）。None なら従来の逆再生で ahead を判定する
    previous_grid: Optional[list] = None


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
        if state.previous_grid is not None:
            # 直前局面そのものと突き合わせる（previous_app_grid のドキュメント参照）。
            # 逆再生だけだと「相手の応手が最終手を取った」局面が ahead に化ける
            is_ahead = observed == state.previous_grid
        else:
            is_ahead = apply_move_to_grid(observed, li, lj, lcolor) == state.current_grid
        if is_ahead:
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
    # 相手の着手を待つ状態（active_kinds）がこの秒数続いたら低遅延周期をやめて idle 周期に落とす
    # （spec 追記9）。アプリで投了・時間切れが起きても KaTrain には伝わらず、監視は in_sync のまま
    # 50ms で撮り続ける（実測 1コアの約25%）。代償はこの秒数を超える長考のあとの反映が最大
    # poll_interval_ms 遅れることだけ（着手が見えた周から確定待ちは再び低遅延）。0 以下で従来どおり
    active_slowdown_sec: float = 20.0
    # 対局（KaTrain の手数）がこの秒数進まなければ監視を自動停止する（spec 追記9）。基準はアプリの
    # 画素ではなく対局の進行＝終局後の結果ダイアログやロビー画面で画面が動いても止まる。0 以下で無効
    auto_stop_sec: float = 300.0


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
        active_slowdown_sec=float(d.get("active_slowdown_sec", default.active_slowdown_sec)),
        auto_stop_sec=float(d.get("auto_stop_sec", default.auto_stop_sec)),
    )


PREFETCH_REPLIES_DEFAULT = 5  # 相手の応手 top-K の子局面を先読みする既定本数（spec 追記4）


def apply_game_watch_flags(game, cfg):
    """対局監視モードの Game 側フラグを張り、先読み本数を返す。

    監視 ON（`_do_board_watch_start`）と、**監視中の新規対局**（`_do_new_game`）の両方から呼ぶ。
    監視スレッド（kind="game"）は新規対局をまたいで生きるが、`Game` を作り直すと
    `board_watch_active` / `board_watch_prefetch_replies` は初期値（False / 0）に戻る。張り直さないと
    応手先読みと難解のヨセ即応（enigma spec 追記7＝`board_watch_active` で発火）が2局目から
    黙って死ぬ（実測 2026-08-27 `game_20260827_155133`: ヨセ31手すべてが省けるはずの Probe 1.1 秒を払い、
    先読みは 0 本）。
    """
    prefetch = int((cfg or {}).get("prefetch_replies", PREFETCH_REPLIES_DEFAULT))
    game.board_watch_active = True
    game.board_watch_prefetch_replies = prefetch
    return prefetch


def clear_game_watch_flags(game):
    """apply_game_watch_flags の逆。対局監視を止めたら止め方を問わず呼ぶ（`__main__._stop_board_watcher`）。

    `board_watch_active` が残ると、監視を止めた後の普通の対局でも難解のヨセの Probe 省略（enigma spec
    追記7）と自ノード解析の後回し（同 追記9）が効き続ける（旧ホットキー OFF 経路は先読み本数しか
    戻していなかった）。走っている応手先読みも打ち切る（通常の対局・検討で GPU を焼かない）。
    """
    game.board_watch_active = False
    game.board_watch_prefetch_replies = 0
    game.board_watch_probe_warm = False
    game._cancel_board_watch_prefetch()


STATUS_WATCHING = "bw-watching"
STATUS_WARN = "bw-warn"
# 対局が進まないので自動停止した（auto_stop_sec）。警告ではなくお知らせなので色を分け、
# 監視トグルはこのバナーを「消すだけ」でなく1押しで再開する（watch_toggle_action）
STATUS_IDLE = "bw-idle"
WATCHING_TEXT = "盤面監視中（相手の手を自動反映）"
RESYNC_HINT = "（監視トグルのホットキーで OFF にし、1秒ほどおいてからもう一度押すと現局面を取り込み直します）"
# 対局モード向けの既定の停滞警告文（_on_quiet 参照）。詰碁モードは __main__._start_tsumego_watch が
# 別の文面（stall_text）を渡すので、これは stall_kinds/stall_text 未指定時の既定値として使う。
STALL_TEXT = (
    "盤面が変化しません（着手をアプリへ入力し忘れていないか、"
    "または KaTrain の手番かもしれません。Enter で AI が着手します）"
)
# 自動停止のお知らせの既定文面。{duration} に auto_stop_sec を「5分間」のように入れる
IDLE_STOP_TEXT = "対局が{duration}進まないため盤面監視を停止しました"
# 監視中にアプリで次の対局が始まったと判定した（spec 追記10）。この周で監視は止まり、呼び出し側が張り直す
NEW_GAME_TEXT = "アプリで新しい対局が始まりました（監視を張り直します）"
# 「次の対局が始まった」と判定するのに要る連続周数。張り直しは新規対局＝重いので Move の確定
# （stable_frames=2）より1周多く見る。確認中は低遅延周期（50ms）で回すので0.1〜0.2秒で決まる
NEW_GAME_STABLE_FRAMES = 3


def _duration_text(seconds):
    """auto_stop_sec をお知らせ用の「5分間」「90秒間」にする"""
    if seconds >= 60 and seconds % 60 == 0:
        return f"{int(seconds // 60)}分間"
    return f"{seconds:g}秒間"


# 強調表示の輪（screen_marker）を消すまでに許す連続の撮影失敗回数。アプリが盤以外の画面へ
# 遷移すると `detect_board` / `detect_size_and_classify` が毎周失敗するが、輪の位置は
# 「アプリ盤の交点」なので盤が見えていない間は意味を持たない＝出しっぱなしにしない。
# 警告と同じ `failure_warn_frames`(8) まで待たないのは、輪だけは早く消したいから
# （警告は連続8回＝バックオフ込みで約10秒後）。1 にすると1フレームの過渡失敗で瞬く
HIGHLIGHT_HIDE_AFTER_FAILURES = 2

# 盤矩形を測り直す間隔[秒]。窓が動けば `read()` が矩形キャッシュを捨てるが、**窓が動かなくても
# アプリの中で盤がずれる**ことがある（BlueStacks のツールバー表示・回転・アプリ側のレイアウト変更）。
# その場合キャッシュした盤矩形は永久に古いままで、分類は多少ずれても通ってしまうため、
# 強調表示の輪だけが交点の中心から少しずれ続ける。1秒に1回 detect_board を撃ち直して追従する。
# detect_board は窓の大きさに比例する純 Python の走査で、実測 7.3ms(560x900) / 19.0ms(900x1440) /
# 33.3ms(1200x1900)。撃つのは「盤の画素が動いた周」に限る（静止フレームは指紋の速い経路で先に返る）
# ので、上限は 1秒あたり1回＝1コアの 0.7〜3.3%。窓が動いた回に元から払っていたのと同じコスト
BOARD_RECT_RECHECK_SEC = 1.0


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
      on_status(kind, text)   kind: "bw-watching" / "bw-warn" / "bw-idle" / ""
      on_idle_stop()          対局が auto_stop_sec 進まず自分で止まった（省略可・後始末用）
      player_color_fn()       対局者アイコンから読んだ手前（KaTrain の AI）の色 "B"/"W"/None（省略可）
      on_new_game(grid, size, color)  アプリで次の対局が始まり自分で止まった（省略可・張り直し用）
    """

    def __init__(
        self,
        capture_fn,
        get_state_fn,
        on_move,
        on_status,
        settings,
        clock=time.monotonic,
        active_kinds=("in_sync",),
        stall_kinds=("in_sync", "ahead", "waiting"),
        stall_text=STALL_TEXT,
        on_ahead=None,
        on_idle_stop=None,
        idle_stop_text=IDLE_STOP_TEXT,
        player_color_fn=None,
        on_new_game=None,
    ):
        self.capture_fn = capture_fn
        self.get_state_fn = get_state_fn
        self.on_move = on_move
        self.on_status = on_status
        # 「KaTrain が打ったがアプリにまだ無い手」(i, j) を外へ知らせる省略可能なフック（spec 追記6）。
        # 対局モードは AI の手をユーザーが手でタップするので、その交点をアプリ盤の上に強調表示する
        # （screen_marker）。ahead の間は毎周呼ぶ（アプリの窓が動いたら座標を追い直せるように）、
        # ahead でなくなったら None を1回だけ。既定 None＝従来どおり何もしない
        self.on_ahead = on_ahead
        self._ahead_move = None
        self.settings = settings
        # 低遅延（poll_interval_active_ms）で回す無音状態の集合。既定は in_sync だけ＝対局
        # モードの従来どおり。詰碁は ahead（黒を打ったがまだアプリへタップしていない）が
        # 白の来る直前の状態なので ("in_sync", "ahead") を渡す（spec 2026-08-22 §5）
        self.active_kinds = tuple(active_kinds)
        # 停滞警告（_on_quiet）の対象 kind と文面。既定は対局モードの従来どおり
        # （in_sync/ahead/waiting すべてで20秒後に警告）。詰碁は ahead（ユーザーの思考時間）・
        # waiting（難問の探索時間）が正常な待ちなので、__main__._start_tsumego_watch は
        # stall_kinds=("in_sync",) だけを渡す（spec 2026-08-22 §5）
        self.stall_kinds = tuple(stall_kinds)
        self.stall_text = stall_text
        # 自動停止（auto_stop_sec）。止まったらループを抜ける前に on_status(STATUS_IDLE, 文面) と
        # on_idle_stop() を呼ぶ。監視スレッドから呼ばれるので、呼び出し側の後始末（強調表示の輪・
        # 先読みフラグ）は自分のスレッドへ回すこと（stop() は join するので監視スレッドから呼べない）
        self.on_idle_stop = on_idle_stop
        self.idle_stop_text = idle_stop_text
        # 連続対局（spec 追記10）。mismatch の周にアプリの盤が「次の対局の序盤」に見え、手前の色も
        # 読めたら on_new_game を呼んで自分は止まる。どちらかが None なら無効＝従来どおり
        # （詰碁の白番自動反映は渡さない＝詰碁の盤を「新しい対局」と取り違えない）
        self.player_color_fn = player_color_fn
        self.on_new_game = on_new_game
        self._new_game_key = None  # 確認中の (盤, 色)
        self._new_game_count = 0
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
        self._quiet_since = None  # 停滞警告の基準（警告のたびに打ち直す）
        self._quiet_started = None  # 今の無音状態に入った時刻（減速の基準。警告では打ち直さない）
        self._progress_move = None  # 最後に見た KaTrain の手数（自動停止の基準）
        self._progress_since = None  # その手数になった時刻

    # --- 1周ぶんの判断（テストはここを直接叩く） ---
    def step(self):
        if self._idle_expired():
            self._idle_stop()
            return
        try:
            observed = self.capture_fn()
        except Exception as e:  # CaptureError も未知の例外もここで吸収する
            self._on_capture_failure(str(e), permanent=isinstance(e, PermanentCaptureError))
            return
        self._on_capture_success()
        state = self.get_state_fn()
        if state is None:
            self._notify_ahead(None)  # 盤が読めない・対象外の盤＝輪を残さない
            return
        self._note_progress(state.move_number)
        if self._pending is not None and not self._resolve_pending(state):
            if self._pending is not None:
                self._active()  # 注入した手が反映されるまでは速く確認する（タイムアウト後は idle へ戻す）
            return
        verdict = reconcile(state, observed)
        self._notify_ahead(state.last_move[:2] if verdict.kind == "ahead" and state.last_move else None)
        if verdict.kind == "mismatch":
            if self._new_game_seen(state, observed):
                return
            self._on_mismatch(verdict.reason)
            return
        self._forget_new_game()
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

    @property
    def ahead_move(self):
        """直近の周で ahead だった手 (i, j)。ahead でなければ None（設定変更時の強調表示の当て直しに使う）"""
        return self._ahead_move

    def _notify_ahead(self, move):
        """ahead の最終手を on_ahead へ。ahead 中は毎周、解消（None）は1回だけ通知する"""
        if move is None and self._ahead_move is None:
            return
        self._ahead_move = move
        if self.on_ahead is not None:
            self.on_ahead(move)

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

    def _new_game_seen(self, state, observed):
        """mismatch の周に、アプリが次の対局へ移ったかを見る（spec 追記10）。確認中・張り直しなら True。

        条件は3つ: 観測が KaTrain の盤と違う（同じ盤で AI が応手できないだけの局面を張り直すと、
        取り込みが起きず同じ mismatch に戻って張り直しが止まらない）、盤上2子以内で手番が確定する
        序盤形（opening_next_player＝対局の途中には現れない形）、対局者アイコンから手前の色が読める。
        同じ (盤, 色) が NEW_GAME_STABLE_FRAMES 周続いたら on_new_game を1回呼んで自分は止まる
        （呼び出し側の張り直しが済むまでに同じ判定を何度も投げないため。stop() は join するので
        監視スレッド自身からは呼べない＝_idle_stop と同じ止まり方）
        """
        if self.on_new_game is None or self.player_color_fn is None:
            return False
        if observed == state.current_grid or opening_next_player(observed) is None:
            self._forget_new_game()
            return False
        try:
            color = self.player_color_fn()
        except Exception:
            color = None
        if color is None:
            self._forget_new_game()
            return False  # 手前の色が読めない＝従来どおりの警告（再同期はホットキー）
        key = (_grid_key(observed), color)
        if key == self._new_game_key:
            self._new_game_count += 1
        else:
            self._new_game_key = key
            self._new_game_count = 1
        if self._new_game_count < NEW_GAME_STABLE_FRAMES:
            self._active()  # 盤が見えている＝撮影は安い。確認の周を詰める
            return True
        self._forget_new_game()
        self._stopped.set()  # run() はこの周を最後に抜ける
        self._notify_ahead(None)
        self.on_status(STATUS_WATCHING, NEW_GAME_TEXT)
        self.on_new_game([row[:] for row in observed], len(observed), color)
        return True

    def _forget_new_game(self):
        self._new_game_key = None
        self._new_game_count = 0

    def _on_quiet(self, state, observed, kind):
        """waiting / ahead / in_sync = 無音の終端状態。長すぎたら警告する（spec §2.5c）"""
        self._stable_move = None
        self._stable_count = 0
        key = (kind, state.move_number, _grid_key(observed))
        now = self.clock()
        if kind in self.active_kinds and not self._waited_long(key, now):
            # 盤がアプリと一致している＝次に変わるのは相手の石。ここだけが低遅延を要する
            # 局面で、waiting（KaTrain の AI が思考中）は相手の石が来ようがないので idle の
            # まま。ahead（ユーザーがまだアプリへタップしていない）は対局モードでは同じく
            # idle だが、詰碁ではタップ直後にアプリが白を返すので active に含める。
            # ただし待ちが active_slowdown_sec を超えたら idle に落とす（終局後の空回り対策）
            self._active()
        if key != self._quiet_key:
            self._quiet_key = key
            self._quiet_since = now
            self._quiet_started = now
            self._watching()
        elif (
            kind in self.stall_kinds
            and self._quiet_since is not None
            and now - self._quiet_since >= self.settings.stall_warn_sec
        ):
            self._quiet_since = now  # 再警告は stall_warn_sec ごと
            # import_next_player の確定ゾーン（空盤・盤上2子以内）で対局開始まわりの
            # デッドロックは無くなったが、「対局が進んだ局面で、実は KaTrain 側の手番である
            # タイミングで監視を ON にする」ケースは1フレームの盤面（取られた石数が
            # 分からない）からは判定できず残る。この場合
            # ai-move（Enter / numpad-Enter、gui.kv:883）で AI に1手打たせれば動き出す。
            # もう一方のありふれた原因（アプリへのタップ忘れ）と合わせて両方を案内する。
            # どちらが実際の原因かは判定しない（対象 kind・文面は stall_kinds/stall_text 参照＝
            # 詰碁モードは ahead/waiting を対象から外し文面も専用のものに差し替える）
            self._warn(self.stall_text)

    def _waited_long(self, key, now):
        """同じ無音状態（key）が active_slowdown_sec 以上続いているか。新しい状態なら False"""
        limit = self.settings.active_slowdown_sec
        if limit <= 0 or key != self._quiet_key or self._quiet_started is None:
            return False
        return now - self._quiet_started >= limit

    def _note_progress(self, move_number):
        if move_number != self._progress_move:
            self._progress_move = move_number
            self._progress_since = self.clock()

    def _idle_expired(self):
        """対局（KaTrain の手数）が auto_stop_sec 進んでいないか。撮影失敗の周も数える"""
        limit = self.settings.auto_stop_sec
        if limit <= 0:
            return False
        now = self.clock()
        if self._progress_since is None:
            self._progress_since = now  # 最初の周から数える（撮影が一度も通らなくても止まる）
            return False
        return now - self._progress_since >= limit

    def _idle_stop(self):
        self._stopped.set()  # run() はこの周を最後に抜ける
        self.on_status(STATUS_IDLE, self.idle_stop_text.format(duration=_duration_text(self.settings.auto_stop_sec)))
        if self.on_idle_stop is not None:
            self.on_idle_stop()

    def _on_capture_failure(self, message, permanent=False):
        self._forget_new_game()  # 「次の対局」の確認は連続した周だけで数える
        self._fail_count += 1
        if self._fail_count >= self.settings.backoff_after_failures:
            self.interval_ms = min(
                int(self.interval_ms * self.settings.backoff_factor), self.settings.poll_interval_max_ms
            )
        # 恒久失敗は即警告、過渡失敗（アニメーション中の "?" 等）は連続 N 回まで黙る。
        # どちらも監視は止めない（最小化しただけで死なないように）
        if permanent or self._fail_count >= HIGHLIGHT_HIDE_AFTER_FAILURES:
            # 盤が見えていない＝輪の指す交点が画面に無い。警告より先に消す（上の定数の comment 参照）
            self._notify_ahead(None)
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


def _wood_api():
    """明るい木目盤（別アプリ）経路の関数群を遅延 import して返す（_capture_api と同じ流儀）。

    既存テストが monkeypatch する `_capture_api` の4タプルは変えられないので別口にする。
    この経路が走るのは detect_board（黄盤）が失敗したときだけ＝既存アプリの監視は不変
    """
    from katrain.core.tsumego_capture import classify_wood_intersections, detect_wood_board, detect_wood_grid

    return detect_wood_board, detect_wood_grid, classify_wood_intersections


def intersection_screen_point(window_rect, board_rect, size, i, j):
    """交点 (i, j) の画面座標 (x, y) とセル幅を返す（純関数）。

    格子は `tsumego_capture.classify_intersections` と同じ規則配置（セル幅 = 盤幅/size・第1線は盤端から
    半セル内側）で、autoloop の `board_to_device` の画面座標版。board_rect は窓画像内の座標なので
    窓の左上（`find_window_rect`＝GetWindowRect）を足す。AI の手の強調表示（screen_marker）に使う
    """
    wx, wy = window_rect[0], window_rect[1]
    x0, y0, x1, y1 = board_rect
    cell_w = (x1 - x0 + 1) / size
    cell_h = (y1 - y0 + 1) / size
    return wx + x0 + cell_w * (j + 0.5), wy + y0 + cell_h * (i + 0.5), min(cell_w, cell_h)


def grid_screen_point(window_rect, xs, ys, i, j):
    """交点 (i, j) の画面座標 (x, y) とセル幅を返す（純関数・木目盤経路用）。

    intersection_screen_point の「規則配置の割り算」の代わりに、検出済みの格子線位置
    （xs=縦線の x・ys=横線の y、窓画像座標）をそのまま使う。19 路の座標ラベル帯のように
    第1線が盤領域の縁から半セルでないレイアウトでも輪が交点の真上に出る
    """
    wx, wy = window_rect[0], window_rect[1]
    cell_w = (xs[-1] - xs[0]) / (len(xs) - 1)
    cell_h = (ys[-1] - ys[0]) / (len(ys) - 1)
    return wx + xs[j], wy + ys[i], min(cell_w, cell_h)


def _board_fingerprint(img, board_rect):
    """盤矩形の画素そのもの（バイト列）を返す。取れなければ None＝「比較しない」に倒す。

    撮り直しても盤の画素が1ビットも変わっていなければ、格子検算も分類も同じ入力に対する
    純粋な関数なので結果は必ず同一になる。だから省ける（判定の意味論は変わらない）。
    """
    try:
        return img.crop(board_rect).tobytes()
    except Exception:
        return None


# --- 対局者アイコンから手前（KaTrain の AI）の色を読む（spec 追記10） ---
# 囲碁クエスト系の対局画面は、盤のすぐ下（手前＝自分）の左端と、盤のすぐ上（相手）の右端に、その
# 対局者の石の色のアイコンを出す（tests/data/board_watch_start_black.png / _start_white.png /
# board_watch_before.png）。窓は盤矩形の幅 W に対する比で持つ＝ウィンドウの大きさが変わってもそのまま効く。
# 実測（W=547〜551）で石は盤の縁から 0.03〜0.095W・盤の端から 0.005〜0.075W の円（直径 約0.07W）、
# 隣のアバター画像は盤の端から 0.08W より内側に来ない
PLAYER_ICON_SPAN_RATIO = 0.072  # 窓の横幅（手前は盤の左端から右へ／相手は右端から左へ）
PLAYER_ICON_NEAR_RATIO = 0.02  # 盤の縁から窓の近い側まで
PLAYER_ICON_FAR_RATIO = 0.11  # 盤の縁から窓の遠い側まで
# 窓の中で「その色の石」とみなす画素の割合。実測: 石 0.50〜0.63・反対色 0〜0.037（背景の稲妻の筋）。
# 上限は「窓がまるごと同じ色」＝石ではなく背景を弾くため（木目盤アプリの黒い余白は 1.00）
PLAYER_ICON_MIN_FRACTION = 0.3
PLAYER_ICON_MAX_FRACTION = 0.85
PLAYER_ICON_MAX_OTHER = 0.1


def _icon_color(img, box):
    """窓 box に写っている石アイコンの色 "B"/"W"。どちらとも言えなければ None"""
    left, top, right, bottom = box
    width, height = img.size
    left, top, right, bottom = max(0, left), max(0, top), min(width, right), min(height, bottom)
    if right - left < 4 or bottom - top < 4:
        return None  # 窓が画面の外＝盤の上下に対局者の帯が写っていない
    data = img.crop((left, top, right, bottom)).convert("RGB").tobytes()
    total = len(data) // 3
    white = black = 0
    for k in range(0, len(data), 3):
        r, g, b = data[k], data[k + 1], data[k + 2]
        spread = max(r, g, b) - min(r, g, b)
        mean = (r + g + b) / 3
        if mean > 200 and spread < 40:  # 白石（無彩色で明るい）。背景の紺・青は spread が大きい
            white += 1
        elif mean < 60 and spread < 25:  # 黒石（無彩色で暗い）
            black += 1
    white_fraction, black_fraction = white / total, black / total
    if PLAYER_ICON_MIN_FRACTION <= white_fraction <= PLAYER_ICON_MAX_FRACTION and black_fraction < PLAYER_ICON_MAX_OTHER:
        return WHITE
    if PLAYER_ICON_MIN_FRACTION <= black_fraction <= PLAYER_ICON_MAX_FRACTION and white_fraction < PLAYER_ICON_MAX_OTHER:
        return BLACK
    return None


def player_icon_colors(img, board_rect):
    """(手前の対局者, 相手) のアイコンの色 "B"/"W"/None。board_rect は img 上の盤矩形 (x0, y0, x1, y1)"""
    x0, y0, x1, y1 = board_rect
    width = x1 - x0
    span = round(width * PLAYER_ICON_SPAN_RATIO)
    near, far = round(width * PLAYER_ICON_NEAR_RATIO), round(width * PLAYER_ICON_FAR_RATIO)
    near_box = (x0, y1 + near, x0 + span, y1 + far)
    far_box = (x1 - span, y0 - far, x1, y0 - near)
    return _icon_color(img, near_box), _icon_color(img, far_box)


def confirmed_near_color(near, far):
    """手前の対局者（＝KaTrain の AI が打つ側）の色。手前と相手が逆の色に読めたときだけ確定する。

    片方しか読めない・両方同じ色（背景を石と読んだ）は None＝判定しない側に倒す
    """
    if near is None or far is None or near == far:
        return None
    return near


class AppBoardReader:
    """アプリ窓を撮って観測グリッドを返す。盤矩形・盤サイズ・直前フレームをキャッシュする。

    対応する盤は2種類で、フル検出時に自動判別する（_full_detect）: 黄盤（囲碁クエスト系・
    従来の規則配置）が先勝ち、detect_board が失敗したら明るい木目盤（別アプリ・格子線検出）。
    木目盤は検出した格子線位置 `_lines` を分類と screen_point の両方が使う＝19 路の座標
    ラベル帯（第1線が縁から約 1.4 セル内側）でも輪が交点の真上に出る。

    1周の実測は「撮影 21〜27ms ＋ 格子検算 5〜25ms ＋ 分類 7〜29ms」＝40〜85ms。
    毎周 detect_size_and_classify をキャッシュしたサイズ1候補で回すのは、これが
    「盤矩形と規則配置の仮定がまだ合っているか」の検算を兼ねるため。

    ただし対局中のフレームはほとんどが「前と同じ盤」なので、盤矩形の画素を前回と比較して
    同一なら分類ごと省く（**1周が 21〜23ms に落ちる**）。これが無いと 19路では1周 85ms
    かかり、50ms 周期を指定しても実際には 85ms 間隔でしか回れない＝低遅延化が成立しない。
    比較対象を窓全体でなく**盤矩形**にするのは、窓内の時計・通知などが毎フレーム変わると
    最適化が丸ごと効かなくなるため。
    """

    def __init__(self, window_title, board_sizes, clock=time.monotonic):
        self.window_title = window_title
        self.board_sizes = list(board_sizes)
        self.size = None
        self.clock = clock
        self._window_rect = None
        self._board_rect = None
        self._rect_checked = None  # 盤矩形を最後に測り直した時刻（BOARD_RECT_RECHECK_SEC）
        self._fingerprint = None
        self._grid = None
        # 認識プロファイル。"quest"=従来の黄盤（規則配置）/ "wood"=明るい木目盤（格子線検出）。
        # フル検出（_full_detect）が detect_board の成否で決める＝設定キーは無い
        self._profile = None
        self._lines = None  # wood の格子幾何 (縦線 x のタプル, 横線 y のタプル)。quest では None
        # screen_point は監視スレッド以外（GUI の `_do_ai_move`・設定変更）からも呼ばれる。
        # 窓矩形・盤矩形・盤サイズを別々に読むと「新しい窓矩形＋古い盤矩形」という
        # ありえない組み合わせを引けてしまい、輪が窓の移動量ぶんずれる。まとめて
        # 1つの参照で差し替えることで、読む側は必ず整合した組を見る
        self._calibration = None  # (window_rect, board_rect, size, lines) or None
        # 直近に撮ったフレーム。盤の外にある対局者アイコン（player_icon_colors）を読むために持つ
        # （盤矩形の指紋は盤の中しか見ないので、指紋が同じ周でも毎回差し替える）
        self._last_img = None

    def read(self):
        find_window_rect, capture_screen_rect, detect_board, detect_size_and_classify = _capture_api()
        try:
            rect = find_window_rect(self.window_title)
        except Exception as e:
            # ウィンドウが無い＝最小化・終了。過渡失敗と違い連続 N 回待たずに即警告させる
            raise PermanentCaptureError(str(e)) from e
        if rect != self._window_rect:  # 窓が動いた・リサイズされた
            self._window_rect = rect
            self._forget_board_rect()
        img = capture_screen_rect(rect)
        self._last_img = img
        if self._board_rect is None:
            self._forget_frame()
            board_rect, grid = self._full_detect(img, detect_board, detect_size_and_classify)
            self._set_board_rect(board_rect)
            self._remember_frame(_board_fingerprint(img, board_rect), grid)
            return grid
        fingerprint = _board_fingerprint(img, self._board_rect)
        if fingerprint is not None and fingerprint == self._fingerprint:
            return self._grid  # 盤の画素が1つも変わっていない＝分類しても同じグリッドになる
        # 画素が動いた回だけ盤矩形を測り直す。静止フレームで撃たないのは上の速い経路
        # （1周 21〜23ms）を壊さないため＝盤が動けばその画素も必ず変わるので取りこぼさない
        if self._recheck_board_rect(img, detect_board):
            fingerprint = _board_fingerprint(img, self._board_rect)  # 矩形が変わった＝指紋も取り直す
        try:
            grid = self._classify_frame(img, detect_size_and_classify)
        except Exception:
            self._forget_board_rect()  # 次回はフル検出からやり直す
            self._forget_frame()  # 失敗した回の画素を覚えない（覚えると次周が古いグリッドを返す）
            raise
        self._remember_frame(fingerprint, grid)
        return grid

    def _full_detect(self, img, detect_board, detect_size_and_classify):
        """盤矩形・サイズ・グリッドを一から検出し (board_rect, grid) を返す。プロファイルもここで決める。

        黄盤（従来経路）が先勝ちで、成功したら以降は従来とビット同一。detect_board が失敗した
        ときだけ木目盤経路（detect_wood_board → 格子線検出 → 線位置ベース分類）を試す。
        木目盤ですらなければ従来の diagnostics（黄盤側のエラー）をそのまま投げる＝既存アプリの
        過渡失敗（盤以外の画面）の文言・型は変わらない
        """
        try:
            board_rect = detect_board(img)
        except Exception as yellow_err:
            detect_wood_board, detect_wood_grid, classify_wood_intersections = _wood_api()
            try:
                board_rect = detect_wood_board(img)
            except Exception:
                raise yellow_err from None
            size, xs, ys = detect_wood_grid(img, board_rect, self.board_sizes)
            grid = classify_wood_intersections(img, xs, ys)
            self.size = size
            self._profile = "wood"
            self._lines = (xs, ys)
            return board_rect, grid
        size, grid = detect_size_and_classify(img, board_rect, self.board_sizes)
        self.size = size
        self._profile = "quest"
        self._lines = None
        return board_rect, grid

    def _classify_frame(self, img, detect_size_and_classify):
        """画素が動いたフレームの分類。quest はキャッシュしたサイズ1候補の検算兼用（従来どおり）、
        wood はキャッシュした格子線位置で分類だけする（格子線検出は毎フレーム走らせない）"""
        if self._profile == "wood" and self._lines is not None:
            classify_wood_intersections = _wood_api()[2]
            return classify_wood_intersections(img, *self._lines)
        _size, grid = detect_size_and_classify(img, self._board_rect, [self.size])
        return grid

    def _recheck_board_rect(self, img, detect_board):
        """盤矩形を BOARD_RECT_RECHECK_SEC ごとに測り直し、ずれていれば張り替える。

        窓矩形が変わらないまま盤だけがアプリ内で動く場合の追従。張り替えたら True を返す。
        ここで detect_board が失敗したら盤が画面に無い（別画面へ遷移した）ということなので、
        そのまま撮影失敗として投げる＝監視の警告と強調表示の消去が最短で走る。
        """
        now = self.clock()
        if self._rect_checked is not None and now - self._rect_checked < BOARD_RECT_RECHECK_SEC:
            return False
        if self._profile == "wood":
            detect_wood_board, detect_wood_grid, _classify = _wood_api()
            board_rect = detect_wood_board(img)
            if board_rect == self._board_rect:
                self._rect_checked = now
                return False
            try:
                # 盤が動いた＝格子線位置も古い。張り替えられなければフル検出からやり直す
                # （quest と違い矩形だけでは分類できないので、ここで幾何が取れない盤は持ち越さない）
                _size, xs, ys = detect_wood_grid(img, board_rect, [self.size])
            except Exception:
                self._forget_board_rect()
                self._forget_frame()
                raise
            self._lines = (xs, ys)
            self._set_board_rect(board_rect)
            self._forget_frame()
            return True
        board_rect = detect_board(img)
        if board_rect == self._board_rect:
            self._rect_checked = now
            return False
        self._set_board_rect(board_rect)
        self._forget_frame()  # 矩形が変わった＝前回の指紋とは比べられない（分類し直す）
        return True

    def _set_board_rect(self, board_rect):
        self._board_rect = board_rect
        self._rect_checked = self.clock()
        self._calibration = (self._window_rect, board_rect, self.size, self._lines) if self.size else None

    def _forget_board_rect(self):
        self._board_rect = None
        self._rect_checked = None
        self._calibration = None
        self._profile = None
        self._lines = None

    def screen_point(self, i, j):
        """交点 (i, j) の画面座標 (x, y, セル幅)。盤矩形がまだ確定していなければ None"""
        calibration = self._calibration  # 別スレッドから呼ばれる＝1回で読み切る（上の comment 参照）
        if calibration is None:
            return None
        window_rect, board_rect, size, lines = calibration
        if lines is not None:  # 木目盤＝検出済みの格子線位置から引く（規則配置の割り算では帯ぶんずれる）
            return grid_screen_point(window_rect, lines[0], lines[1], i, j)
        return intersection_screen_point(window_rect, board_rect, size, i, j)

    def player_icon_colors(self):
        """直近のフレームの対局者アイコンの色 (手前, 相手)（spec 追記10）。

        黄盤（囲碁クエスト系）の対局画面だけが対象で、木目盤アプリ・盤が未確定・直前の read() が
        失敗した周は (None, None)。read() と同じスレッドから呼ぶこと（直近のフレームを共有する）
        """
        img, board_rect = self._last_img, self._board_rect
        if img is None or board_rect is None or self._profile != "quest":
            return None, None
        return player_icon_colors(img, board_rect)

    def near_player_color(self):
        """手前の対局者（＝KaTrain の AI が打つ側）の色。確定できなければ None（BoardWatcher の player_color_fn）"""
        return confirmed_near_color(*self.player_icon_colors())

    def _remember_frame(self, fingerprint, grid):
        self._fingerprint = fingerprint
        self._grid = grid

    def _forget_frame(self):
        self._fingerprint = None
        self._grid = None


# --- 詰碁モード（白番自動反映。spec 2026-08-22-tsumego-white-auto-apply-design.md） ---
TSUMEGO_AI_SUBTYPES = (AI_TSUMEGO, AI_TSUMEGO_SOLVER)


def tsumego_watch_can_start(watch_white, view_kind, auto_ai, black_subtype, white_is_human):
    """詰碁の白番自動反映を開始してよいか。(可否, 理由) を返す。

    黒が詰碁 AI・白が人間であることを要求するのが**色の割り当てが逆のまま走らせない**ための
    入口ゲート（reconcile の「AI の手番なら注入しない」行と二重の防御）。
    """
    if not watch_white:
        return False, "設定 watch_white が無効です"
    if view_kind != "app":
        return False, f"アプリ盤面以外のキャプチャ（{view_kind}）は監視しません"
    if not auto_ai:
        return False, "auto_ai_black が無効です（黒が AI でないと応手が返りません）"
    if black_subtype not in TSUMEGO_AI_SUBTYPES:
        return False, f"黒が詰碁戦略ではありません（{black_subtype}）"
    if not white_is_human:
        return False, "白が人間ではありません"
    return True, ""


def tsumego_watch_status(kind, text):
    """詰碁経路のバナー用に監視ステータスを絞る。

    TsumegoBookBanner（gui.kv）は watch_detail を回答帳ステータスより優先して表示するので、
    正常時の「監視中」を出しっぱなしにすると**回答帳バナーが恒久的に隠れる**（詰碁ビューでは
    右パネルごと非表示なので、回答帳の再生状況を知る手段がバナーしかない）。警告だけ通し、
    それ以外は空にして回答帳バナーへ譲る。
    """
    if kind == STATUS_WARN:
        return kind, text
    return "", ""


def watch_toggle_action(running, banner_kind):
    """監視トグル（ホットキー）を押したときの動作。"stop" / "clear" / "start" を返す。

    監視が走っていれば止める。走っていないのにバナーが残っているのは、認識失敗などで監視を
    作らずに出た警告なので1押しで消す（消せないとバナーが一生残る＝Finding A）。ただし自動停止
    のお知らせ（STATUS_IDLE）は「ホットキーで再開」と案内しているので、消すだけでなく再開する
    """
    if running:
        return "stop"
    if banner_kind and banner_kind != STATUS_IDLE:
        return "clear"
    return "start"

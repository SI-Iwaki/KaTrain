# 詰碁モードの白番自動反映（tsumego white auto-apply）設計

作成日: 2026-08-22

## 0. 目的とスコープ

詰碁キャプチャで出題した問題を解く間、**アプリ側が返す白の応手を KaTrain へ自動で反映する**。
現状はユーザーが (1) KaTrain の AI（黒）が打った手をアプリでタップし、(2) アプリが返した白を
KaTrain の盤でクリックする、の2操作を毎手繰り返している。(2) を自動化する。

同期は**片方向（アプリ→KaTrain）**。黒の自動クリック（KaTrain→アプリ）は対局監視モード
（`docs/superpowers/specs/2026-08-18-board-watch-design.md` §0）と同じくスコープ外。

### スコープ内
- 詰碁出題中に監視スレッドを1本立て、アプリ盤に現れた白石を人間側の手として注入する
- キャプチャ時の自動開始／`ctrl+alt+d` と新規対局での停止／回答帳の記録モード中の一時停止

### スコープ外
- Web 盤面（PlayGo.gg 等）の監視。`AppBoardReader` は BlueStacks 型の全面盤しか読まない
- 問題が切り替わったときの自動再キャプチャ（警告だけ出して監視は継続する）
- 対局監視モード（`board_watch`）の既存挙動の変更

### 決定事項（ユーザー確認済み）
| 項目 | 決定 |
|---|---|
| 開始方法 | 詰碁キャプチャ時に自動で開始（設定 `watch_white` で無効化可） |
| 対象 | BlueStacks の詰碁アプリのみ（`BoardView.kind == "app"`） |
| 盤面が大きく変わったとき | 盤には触らず警告のみ。監視は継続 |
| 停止方法 | `ctrl+alt+d`（既存トグルの停止分岐）／新規対局／次のキャプチャで張り替え |
| 判定方式 | 影グリッド方式（`reconcile` は無変更） |

## 1. なぜ board_watch をそのまま使えないか

3つの前提が詰碁では成り立たない。

**(a) KaTrain の盤 ≠ アプリの盤。** 枠あり出題は壁と充填を**足す**だけでなく、
`drop_non_core_stones`（`tsumego_frame.py:938`）で枠矩形の境界線上・外側の非コア石を
**盤から消す**。したがって `game.stones` はアプリの盤と両方向にずれており、
`reconcile`（`board_watch.py:172`）が `game.stones` と観測グリッドを直接比較する現行の
使い方では毎周 `Mismatch` になる。

**(b) `ai_can_respond` が ROI を禁じている。** `_board_watch_state`（`__main__.py:1463`）は
`game.region_of_interest is None` を条件に含む。詰碁では ROI が立っているのが正常状態。

**(c) 入口で拒否されている。** `_do_board_watch_start`（`__main__.py:618`）は AI の
player_subtype が `ai:tsumego` / `ai:tsumego_solver` なら開始しない。

一方で、board_watch が積み上げた安全弁（`waiting` を `move` より先に評価する優先順位、
注入時の手数・手番の再検証、注入後の反映待ち、進捗ウォッチドッグ、キャプチャ失敗の
バックオフ）は詰碁でもそのまま要る。したがって**機構は流用し、比較の基準だけ差し替える**。

## 2. 影グリッド方式

### 2.1 考え方

`WatchState.current_grid`（`board_watch.py:154`）に渡すグリッドを、`game.stones` ではなく
**アプリ側の盤の再現**にする。再現は

```
影グリッド = キャプチャ時の認識グリッド + root からの着手列
```

で作る。これだけで `reconcile` の6行の表がそのまま詰碁の意味になる。

| verdict | 詰碁での意味 |
|---|---|
| `mismatch`（盤サイズ違い） | アプリが別の盤サイズになった |
| `mismatch`（`ai_can_respond` 偽） | 分岐・終局・解析モード＝黒が応手できない |
| `waiting` | 黒（`ai:tsumego`）が考えている最中。**注入しない** |
| `in_sync` | 黒をアプリへタップ済み。白の応手待ち |
| `ahead` | KaTrain が黒を打ったが、まだアプリへタップしていない |
| `move` | 白が来た → 注入 |
| `mismatch`（その他） | 問題リセット・次の問題・認識ミス → 警告のみ |

`ahead` の判定（`apply_move_to_grid(observed, last_move) == current_grid`）も影グリッド上で
正しく成立する。影グリッドは「アプリの盤に最終手を打った結果」なので、観測に最終手を
打てば影グリッドに一致する。

### 2.2 新しい純関数

`board_watch.py` に1本だけ足す（判定ロジックを `__main__.py` に置かない方針は
board_watch design §1 のまま）。

```python
def replay_grid(base_grid, moves, size):
    """キャプチャ時の認識グリッドに root からの着手列を再生してアプリ盤を再現する。

    moves は (coords, color) の列（KaTrain の下origin 座標。パス = coords None は飛ばす）。
    非合法（アプリ側では既に石がある等）になった時点で None を返す＝「比較しない」に倒す。
    """
```

- `apply_move_to_grid`（`board_watch.py:130`）をそのまま使う。**取りはアプリの盤の上で
  計算される**ので、枠石を巻き込む KaTrain 側の取りとずれない。
- **キャッシュしない。毎周 root から再生する。** 13路×20手で `apply_move_to_grid` 20回＝
  無視できるコストで、undo/redo/分岐が自動的に正しくなる（キャッシュ無効化のバグ源を作らない）。
- `None` を返す条件が実際に起きうるのは、枠が消した非コア石の位置に AI が打った場合。
  アプリ側ではその点に石があるので再生できない。このときは監視を1周飛ばす（§3.3）。

### 2.3 影グリッドの種

`_do_tsumego_capture_apply`（`__main__.py:1575`）が受け取る `grid` は**枠を張る前の認識
グリッド**そのもの。これを `game.tsumego_app_grid = grid` として新しい Game に持たせる
（`tsumego_solver_problem` / `tsumego_book_key` / `tsumego_book_stones` と同じ引き渡し方）。

`tsumego_book_stones` を流用しない理由: あちらは `try` の中で設定され、回答帳の照合に
失敗すると設定されない。監視の基準を「別機能の副産物」に依存させない。

枠なし経路・ソルバ経路では影グリッド ≡ `game.stones` になるので、経路ごとの分岐は不要。

### 2.4 詰碁版の状態取得

`__main__.py` に `_tsumego_watch_state()` を足す。中身は `_board_watch_state`（:1463）と
同型で、差は2点だけ。

```python
current_grid = replay_grid(game.tsumego_app_grid, moves_from_game(game), size)   # 差1
ai_can_respond = (self.play_analyze_mode == MODE_PLAY
                  and not node.children
                  and not game.end_result)                                        # 差2: ROI 条件を落とす
```

`not node.children` は**残す**。これが回答帳の記録モード（`game.undo(9999)` 後の打ち直し、
`__main__.py:495`）で誤注入を止める既存の安全弁になる（§3.3 の一時停止と二重の防御）。

## 3. ライフサイクル

### 3.1 開始

`_do_tsumego_capture_apply` の `finish_gui`（`__main__.py:1838`〜）の**末尾**で起こす。
`finish_gui` より前に置かない理由: 対局者ウィジェットの Clock 経由の更新が
`player_subtype` を `ai:default` へ巻き戻すことがあり、`finish_gui` がその実効値を検証して
入れ直している（実測 2026-07-30）。監視の入口ゲートは検証後の値で判定する必要がある。

全部満たすときだけ起こす:

| 条件 | 理由 |
|---|---|
| `tsumego_capture.watch_white` が真 | 機能の ON/OFF |
| `view_kind == "app"` | `AppBoardReader` は Web フォールバックを持たない |
| `auto_ai` が真 かつ B=`ai:tsumego(_solver)` かつ W=人間 | 黒が AI でないと注入しても応手が返らない。**色の割り当てが逆のまま走らせない**入口ゲート |

`view_kind` は `_tsumego_capture_trigger`（:1037）が `view.kind` をそのまま
`tsumego-capture-apply` メッセージの引数に足して渡す（`capture_note` と同じ流し方）。

`AppBoardReader(title, sizes)` は構築時にキャプチャしない（最初の `read()` で盤矩形と
盤サイズを確定する）ので、メッセージループを画面キャプチャで塞がずに `BoardWatcher` を
作れる。盤サイズの食い違いは `reconcile` の1行目が拾う。

**格納先は既存の `self._board_watcher`** とし、併せて `self._board_watch_kind = "tsumego"`
を立てる。これで `ctrl+alt+d` の停止分岐（:1509-1524）がそのまま OFF スイッチになり、
新しいホットキーを増やさずに済む。

`_board_watch_kind` は **`_do_board_watch_start` 側でも `"game"` を立てる**こと。片方だけ
書くと「詰碁監視を止めた後に対局監視を始める」と kind が `"tsumego"` のまま残り、§3.2 の
`_do_new_game` フックが対局用ウォッチャを巻き添えで止める。

### 3.2 停止

- `ctrl+alt+d` — 既存の停止分岐。バナーも一緒にクリアされる
- `_do_new_game`（:388）の冒頭で、**`_board_watch_kind == "tsumego"` のときだけ**停止する。
  これで「次のキャプチャで張り替わる」「通常の新規対局・SGF 読み込みで消える」が両方成立する。
  対局用ウォッチャの挙動は変えない（board_watch のスコープに触らない）
- 枠ありが枠なしにフォールバックしても経路は同じなので、停止条件は増えない

### 3.3 一時停止（`get_state_fn` が `None` を返す＝無音で1周飛ばす）

| 条件 | 理由 |
|---|---|
| `self.tsumego_recording` が真 | 回答帳の記録モード。`undo(9999)` 後の打ち直しで誤注入しない |
| `self.game` が開始時の Game オブジェクトでない | 張り替え・停止と競合した瞬間 |
| `game.tsumego_app_grid` が無い | 監視対象の出題ではない |
| `replay_grid` が `None` を返した | アプリ盤を再現できない＝比較しない側に倒す。理由はログに1回だけ出す（毎周出さない） |

### 3.4 注入

`board-watch-play`（`_do_board_watch_play`、`__main__.py:587`）を**無変更で流用**する。
手数と手番を再検証してから打つ TOCTOU 対策、取り音、`IllegalMoveException` の警告落ちが
そのまま効く。

枠の壁石の位置に白が来るケース（case AG 型＝正解手順が枠の外へ走る問題）は、ここで
非合法として警告に落ちる。盤は壊れない。

### 3.5 バナー

`TsumegoBookBanner`（`gui.kv:323-341`）の表示優先順位は **`flash` > `watch_detail` >
回答帳ステータス**。監視中に `bw-watching` を出しっぱなしにすると**回答帳バナーが恒久的に
隠れる**（詰碁ビューでは右パネルごと非表示なので、回答帳の再生状況を知る手段がここしかない）。

そこで詰碁経路では `on_status` にアダプタをかませ、**`bw-watching` は空文字に落として
警告（`bw-warn`）だけ帯に出す**。開始したことは `_tsumego_message("白番の自動反映を
開始しました", kind="info")` の数秒フラッシュとログで伝える。

## 4. 先読み

**追加実装はしない。** `_maybe_region_prefetch`（`game.py:638`、`ponder_replies`=3）が既に
「次番が人間」で白の有力応手 top-K の子局面をリージョン実クエリと同条件（同 visits・同
リージョン・同 wideRootNoise・ownership=True）で温めている。board_watch 側の
`_maybe_board_watch_prefetch`（`game.py:756`）は `if replies <= 0 or self.region_of_interest:
return` で詰碁経路を明示的に避けているので、**二重発火もしないし移植するものもない**。

変わるのは温め窓の長さだけ: 従来「ユーザーがアプリをタップ＋KaTrain の盤をクリック」
だったのが「タップ＋アプリが白を返す」に縮む。**既定値は動かさない**（`ponder_replies`=3
のまま）。詰碁の白の応手は対局より一本道なので top-3 の的中率は board_watch の実測
（top-1 32.1% / top-3 58.2%）より高いはずだが、推測で既定を動かすと校正のやり直しになる。
既存の `着手決定に X.X 秒` ログ（`ai.py` の per-move 時間ログ）で実測してから判断する。

## 5. 遅延

反映の体感遅延は「位相待ち＋確定待ち」で決まる（board_watch design 追記3）。詰碁で白が
来る直前の状態は **`ahead`**（黒を打ったがまだタップしていない）で、`_on_quiet`
（`board_watch.py:365`）は `in_sync` のときだけ active 周期（50ms）に落とし、`ahead` は
idle（400ms）のまま置いている。

`ahead` を active に含めると **最大 450ms → 100ms**。代償はタップ待ちの間ずっと 50ms 周期で
回ること（画素が変わらないフレームは 21〜23ms なので CPU 1コアの約45%、idle なら約5%）。
`ahead` から「黒＋白が同時に現れた観測」への遷移は**1周で検出できる**ので、
**正しさは変わらず遅延だけの話**。

実装は `BoardWatcher.__init__` に active 扱いする verdict の集合を引数で持たせる
（既定 `("in_sync",)`＝現行どおり）。詰碁は `("in_sync", "ahead")` を渡す。
設定 `tsumego_capture.watch_active_on_ahead`（既定 true）で切れるようにする。

## 6. 設定

パッケージ `katrain/config.json` と `~/.katrain/config.json` の**両方**に追加する
（ローカル側はメインセッションで直接編集する）。

| キー | 既定 | 意味 |
|---|---|---|
| `tsumego_capture.watch_white` | `true` | 詰碁の白番自動反映の ON/OFF |
| `tsumego_capture.watch_active_on_ahead` | `true` | §5 の遅延／CPU トレードオフ |

ポーリング周期・`stable_frames`・`inject_timeout_ms` 等は既存の `board_watch` セクションを
流用する（詰碁用に別系統を増やさない）。

## 7. テスト

**純関数**（`tests/test_board_watch.py` に追加）:
- `replay_grid`: 枠ありで KaTrain 盤と食い違う盤を正しく再現する／アプリ側で取りが起きる
  手順／非合法で `None` を返す／パス（coords None）を飛ばす
- `reconcile` に影グリッドを渡したときの4状態（`waiting` / `ahead` / `in_sync` / `move`）

**ウォッチャ**（偽フレーム列。既存69本と同じ流儀）:
- 黒着手 → `ahead` → タップ → 白 → `stable_frames` 後に注入
- `tsumego_recording` 中は状態が `None` で無音
- `node.children` ありでは `ai_can_respond` が偽＝注入しない
- active verdict 集合の既定が `("in_sync",)` で現行挙動が変わらないこと

**手動 E2E**: BlueStacks で1問キャプチャ → 白が自動で入るか／記録モードで止まるか／
`ctrl+alt+d` で切れるか／問題を切り替えたら警告だけ出て盤が壊れないか。

## 8. ドキュメント更新

- `.claude/rules/tsumego.md`（機能の全体像・落とし穴に §1(a) の「KaTrain の盤 ≠ アプリの盤」を追加）
- `.claude/rules/tsumego-parameters.md`（§6 の新しい2キー）
- `docs/superpowers/specs/INDEX.md`（詰碁の節に本 spec を実装済みとして追加）

## 追記1（2026-08-22）: 相手の応手が「黒の最終手を取る」と `ahead` に化けて白が入らない

### 症状

回答帳キー `04b0a596ff951b523dd78d072672751a3bc3d3b8`（13路）の再生中、黒 H13 のあとアプリが
返した**白 G13 が永久に反映されなかった**。警告も出ない（詰碁モードは `stall_kinds=("in_sync",)`
＝`ahead` を停滞警告の対象から外しているため、§5 のとおり `ahead` はユーザーの思考時間そのもの）。
それまでの白 J13 / F8 は `board_watch: 相手の着手 … を反映しました` が出ており、
**この1手だけが黙って落ちた**。

### 根本原因

`reconcile` の `ahead` 判定（spec §2.3 行5、board_watch design）は**逆再生**で書かれていた:

```python
if apply_move_to_grid(observed, li, lj, lcolor) == state.current_grid:  # 最終手を打ち直す
    return Verdict("ahead")
```

この式は「アプリ盤にまだ最終手が無い」ときだけでなく、**相手の応手が最終手を取った**ときにも
成立する。取られた石を打ち直すと相手の石を取り返して current に戻るからで、
スナップバック / コウ形が丸ごとこれに当たる。

実測局面: 黒 H13 は W J13・W H12 に接していて呼吸点が G13 だけ。アプリの白 G13 が H13 を取ると
`observed = current − 黒 H13 + 白 G13`。ここに黒 H13 を打ち直すと白 G13（呼吸点は H13 だけ）を
取り返して current と一致する ⇒ 行5が成立し、行6（Move）に到達しない。`ahead` は無音の終端
状態なので、以後ずっと「ユーザーのタップ待ち」として黙る。

盤1枚では **本物のコウ**（盤面が1手前に戻る）と区別できないため、判定には履歴が要る。

### 修正

「アプリの盤 ＝ **1手前の局面**」を直接突き合わせる。`WatchState` に `previous_grid`
（省略時 None）を足し、渡された場合は `observed == previous_grid` を `ahead` の条件にする
（None なら従来の逆再生＝後方互換）。

- `board_watch.previous_app_grid(base_grid, moves, size, current_grid)` を追加。
  `replay_grid(base, moves[:-1])` に最終手を打ち直して `current_grid` と一致することを
  確かめてから返す（食い違えば None ＝従来判定に倒す）。
- 詰碁: `_tsumego_watch_state` が影グリッドと同じ `base_grid` / `moves` から作る（構成上必ず整合）。
- 対局: `_board_watch_state` が root の配置（`game.root.move_with_placements`）＋
  `moves_from_node` から作る。**同じバグが対局監視にもある**（アプリ側 AI が KaTrain の
  最終手を取る形）ため、あちらも直す。途中の AB/AE で再生が現盤と食い違う SGF では
  None が返り従来動作。

**コウは従来どおり `ahead`**（取り返しで局面が1手前に戻るので `observed == previous_grid` が
成立する）＝注入しない側に倒れる。これは意図した安全側の挙動で、`apply_move_to_grid` が
コウを判定しない（§2.5b・board_watch design）ことと整合する。

コストは1周につき replay 1回（実測: 19路200手で 1.2ms、詰碁は数手）。

### 回帰

`tests/test_board_watch.py`（+6本）:
- `test_reconcile_detects_opponent_move_that_captures_our_last_stone` — 本件（`move` を返す）
- `test_reconcile_without_previous_grid_keeps_legacy_ahead` — 後方互換
- `test_reconcile_ko_recapture_shape_still_waits_for_the_tap` — 本物のコウは `ahead` のまま
- `previous_app_grid` の3本（1手戻す / 現盤と食い違えば None / 着手0手なら None）

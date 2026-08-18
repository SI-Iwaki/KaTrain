# 対局盤面の監視モード（board_watch）設計

作成日: 2026-08-18

## 0. 目的とスコープ

BlueStacks 上の囲碁**対局**アプリと KaTrain を並べて使い、**アプリ側 AI の着手を KaTrain の盤面へ自動で反映する**。KaTrain 上の役割は「AI vs 人間」で、アプリ側 AI の手は**人間側の着手**として入る。

既存の詰碁キャプチャ（`tsumego_capture`）はホットキー1回＝1局面のスナップショットで、数十手の対局には向かない（毎手ホットキーを押す運用になる）。本モードは監視スレッドを1本立て、盤面の変化を検出して着手を注入する。

### スコープ内
- アプリ→KaTrain の**片方向**同期（相手の1手を検出して注入）
- ホットキー1本でのトグル（ON で現在の局面を取り込んでから監視、OFF で停止）
- 盤上バナーによる状態表示

### スコープ外（今回作らない）
- KaTrain の AI 手をアプリへ**自動クリック**する逆方向（ユーザーが手動でタップする）
- アプリ側の**パス**の自動検出（盤面が変化しないため原理的に不可能。KaTrain 側で手動パス）
- 終局・整地の自動処理（盤面が大きく変わるので `Mismatch` 警告に落ちる）

### 決定事項（ユーザー確認済み）
| 項目 | 決定 |
|---|---|
| 同期の向き | 片方向（アプリ→KaTrain）のみ |
| 開始方法 | ホットキーでトグル。ON 時に現在の局面を取り込んでから監視 |
| 不一致時 | 盤面には触らず**警告だけ**出して監視継続 |
| 色と手番 | 現在の KaTrain のプレイヤー設定をそのまま使う（新設定を増やさない） |
| 画面配置 | BlueStacks と KaTrain を**並べて表示**できる前提 |
| ホットキー | `ctrl+alt+b` |
| ウィンドウタイトル | `tsumego_capture.window_title` を継承（BlueStacks） |

**ホットキー既定を `f9` にしてはいけない**。`RegisterHotKey` はシステムグローバルで、登録するとそのキーは**フォーカス窓に配送されなくなる**。`f9` は `Theme.KEY_CONTRIBUTE_POPUP`（`theme.py:191`）で、F2/F3/F5〜F10/F12 も全部 `Theme.KEY_*` に埋まっている（`theme.py:185-192`, `:233`, `:235`）。詰碁ホットキーが f4 系に寄せてあるのはこの回避の結果。**グローバルホットキーは `Theme.KEY_*` と重ねない**という制約が本機能にも掛かる。

## 1. 全体構成

```
[BlueStacks 対局アプリ]
        |  (画面)
        v
BoardWatcher スレッド (katrain/core/board_watch.py)
  1. capture_fn()   -> 観測グリッド
  2. get_state_fn() -> KaTrain の現局面グリッド・最終手・手番・応手可否
  3. reconcile()    -> InSync / Ahead / Move / Mismatch
  4. on_move()      -> katrain("board-watch-play", coords, color, move_number)
     on_status()    -> board_watch_status / board_watch_detail
        |
        v
[KaTrain: 専用ハンドラが手番を再検証して着手 -> AI が自動で応手]
```

### モジュール境界

`katrain/__main__.py` は Kivy 依存でテストから import できず、既存テストは「本番の式をテスト側に複製して同期を明記する」流儀（`tests/test_tsumego_capture.py:384-386`）を強いられている。したがって**判定ロジックを1行も `__main__.py` に置かない**。座標変換は §2.1 が実測済みのバグ源と呼ぶ対象なので、これも純関数として `board_watch.py` に置く（`__main__.py` に残すと、テストが検証するのは複製式だけで本番の式は無検証になる＝既存テストが陥った構図の再生産）。

| 単位 | 責務 | 依存 |
|---|---|---|
| `stones_to_grid(stones, size)` | `(coords, player)` のタプル列（下origin）を上origin グリッドへ変換 | なし（純関数） |
| `apply_move_to_grid(grid, i, j, color)` | グリッドに1手打ち、取りを処理した新グリッドを返す。既石・自殺手は `None` | なし（純関数） |
| `reconcile(state, observed)` | 観測が「現局面＋打つ側の1手」で説明できるかを判定 | 上2つ（純関数） |
| `board_sgf(grid, komi, rules, next_player)` | 監視用の SGF 生成（**空盤でも成立**・`PL` を指定できる） | なし（純関数） |
| `BoardWatcher` | ポーリング、盤矩形・盤サイズのキャッシュ、デバウンス、注入ガード、進捗ウォッチドッグ、バックオフ | `tsumego_capture` の認識関数のみ |

`BoardWatcher` は KaTrain の型を一切知らず、**コールバック注入**（`capture_fn` / `get_state_fn` / `on_move` / `on_status`）だけで外界と接する。これによりスレッド挙動まで偽フレーム列で単体テストできる。

`katrain/core/tsumego_solver/board.py:85-110` に既存の `try_play` があるが `model.py` への依存を引き込むため、グリッド用の小さな純関数を新設する。

## 2. 検出アルゴリズム

### 2.1 座標系

認識グリッド `grid[i][j]` の **i は画面上origin**（`tsumego_capture.py:100` の `cy = y0 + cell_h * (i + 0.5)`）。KaTrain の `Move.coords = (x, y)` は **y が下origin**（`sgf_parser.py:31-39`）。

- grid → KaTrain: `x = j`, `y = size - 1 - i`
- KaTrain → grid: `i = size - 1 - y`, `j = x`

この変換漏れは実測済みのバグ源（`__main__.py:702-714` の docstring）。`Game.__repr__`（`game.py:390-394`）と `utils.var_to_grid`（`utils.py:15-22`）は**下origin**なので流用しない。

### 2.2 ポーリング1周（既定 400ms）

1. `GetWindowRect` で窓矩形を取得（安価）。前回と違えば盤矩形キャッシュを破棄。
2. 画面キャプチャ。**bbox 指定は速くならない**（Pillow は Windows で全画面 BitBlt 後に crop する。実測: 暖機後 full 27〜28ms / bbox 27〜28ms で同値）。
3. **キャッシュした盤サイズ1候補だけ** `detect_size_and_classify` を回す（`sizes=[cached_size]`）。これは盤サイズ判定であると同時に「盤矩形と規則配置の仮定がまだ合っているか」の検算になる。`GRID_SCORE_MIN`(0.5) を割れば `detect_board` からやり直す。
4. `classify_intersections` → 観測グリッド。
5. `get_state_fn()` で KaTrain 側の状態を取得（2.4）。
6. `reconcile()` で判定（2.3）。
7. `Move` は**同じ `Move(i, j)` が `stable_frames`（既定2）連続**で出たときだけ確定し、注入する（2.5）。
8. 注入後は反映が確認できるまで新規注入を止める（2.5）。

キャッシュの入口は `recognize_board` ではなく `detect_board` → `detect_size_and_classify` の組み合わせを直接使う（`recognize_board` は盤矩形を返さない便宜ラッパで、外部呼び出し側は既に `tests/test_tsumego_capture.py:29,46,56` で分解して使っている）。

実測コスト（キャッシュ有り・本機）: 撮影 27ms ＋ 格子検算 9路5.5/13路11.5/19路25.3ms ＋ 分類 9路9.6/13路15.8/19路29.2ms ＝ **40〜85ms/回**。400ms 周期なら CPU 1コアの 10〜20%。

### 2.3 `reconcile` の判定（**表は上から評価する優先順位**）

入力は `state`（`get_state_fn` の戻り値、2.4）と `observed`。

| # | 条件 | 結果 | 動作 |
|---|---|---|---|
| 1 | 観測の盤サイズ ≠ `state.board_size` | `Mismatch` | 警告（アプリ側で盤サイズが変わった） |
| 2 | `state.ai_can_respond` が偽 | `Mismatch` | 警告（AI が構造的に応手できない＝分岐・終局・解析モード・ROI 残り） |
| 3 | `state.to_play_is_human` が偽 | `Waiting` | **無音で待つ**（KaTrain の AI が考えている最中）。注入は絶対にしない |
| 4 | `observed == current` | `InSync` | 無音 |
| 5 | `last_move` があり pass でなく、`apply_move_to_grid(observed, last_move) == current` | `Ahead` | **無音で待つ**（KaTrain の AI が打った直後で、ユーザーがまだアプリにタップしていない） |
| 6 | `observed[i][j] == to_play` かつ `current[i][j] == "."` の点のうち、`apply_move_to_grid(current, i, j, to_play) == observed` が成立するものが1つ | `Move(i, j)` | 注入 |
| 7 | それ以外 | `Mismatch(理由)` | 警告のみ。盤面には触らない |

行6の候補が複数一致することは構造上あり得ない（着手点が異なれば結果盤面も異なる）。

**行3を行6より前に置くのが安全弁の要**。もし色の割り当てが逆なら、アプリ側 AI の石は常に `to_play` と同色になって行6が成立してしまう。優先順位を明示しないと「静かに逆色で進行する」事故に戻る。

**行3は警告ではなく無音**にする。`to_play_is_human` が偽なのは「KaTrain の AI が考えている最中」という**正常状態**で、AI の思考時間ぶん（数秒）ずっと成立するため、ここを `Mismatch` にすると正常な1手ごとに警告が2〜20回出る（400ms 周期）。色の割り当てが逆で永久にこの状態から出られないケースは、§2.5(c) の進捗ウォッチドッグが20秒で拾う（`Waiting` も無音の終端状態なのでウォッチドッグの対象に含める）。

**行5は `last_move` が `None`（root 局面）または pass のときスキップする**。`current_node.move` は「無ければ `None`」だが、**パスは `coords=None` の `Move` を返す**（`sgf_parser.py:288-293` / `:68-71`）ので `None` チェックだけでは弾けない。この2ケースは通常運用で必ず起きる（KaTrain 側 AI が白＝相手が先着の対局、§0 が運用に組み込んでいる手動パス、§3.2 の取り込み直後の配置のみ局面）。

**「打ってみて完全一致するまで確定しない」**という規則で、取り（石が消える）・着手アニメーション途中のフレーム・半透明ホバー石（`_classify_patch:74-79` で空点扱い）が吸収される。**置石は吸収されない**（アプリが1手ずつ置くなら1手ずつ `Move` として入り、まとめて置くなら `Mismatch`）ので、置石局は §3.2 の取り込みから始める。

### 2.4 KaTrain 側の状態取得（`get_state_fn`）

`__main__.py` 側に置くが、**中身は `board_watch.stones_to_grid` を呼ぶだけ**にする（判定ロジックを持たせない）。返す内容:

| 項目 | 由来 |
|---|---|
| `current_grid` | `game.stones`（`game.py:316-318`。`stones` プロパティ自身が `_lock` を取るので**呼び出し側でロックを取らない**） |
| `last_move` | `current_node.move`（pass は `coords=None`） |
| `to_play` | `current_node.next_player` |
| `to_play_is_human` | 打つ側のプレイヤー設定 |
| `ai_can_respond` | `play_analyze_mode == MODE_PLAY` かつ `not current_node.children` かつ `not game.end_result` かつ `game.region_of_interest is None` |
| `move_number` | 注入時の再検証用（2.5） |
| `board_size` | `game.board_size`（タプルなので正方形前提で1値に落とす） |

`ai_can_respond` を状態に含めるのは、**AI が応手できない局面が無症状のデッドロックになる**ため。AI 自動応手の条件には `not cn.children`（`__main__.py:302`）があり、`SGFNode.play` は同じ手の既存の子を再利用する（`sgf_parser.py:331-336`）。したがって「AI が応手済み → undo → watcher が同じ手を再注入」の順で、ノードに旧応手が子として残り **AI は二度と打たない**。このとき盤面はアプリと一致しているので `reconcile` は `InSync` を返し、緑バナーのまま対局が止まる。行2はこれを警告として表に出すためにある。ROI（`region_of_interest`）が残っていると AI はリージョン解析完了まで打たず打っても枠内に縛られる（`:306-314`）ので同じ扱いにする。teaching undo（`not (teaching_undo and cn.auto_undo is None)`、`:303-305`）も同経路で AI を止める。

### 2.5 安全弁

**(a) 注入は `("play", coords)` を流用せず専用メッセージにする。**

`_do_play`（`__main__.py:568-579`）は色を引数に取らず**その時点の `next_player_info.player` で打つ**。ワーカーが検査した `to_play` はキュー投入前のスナップショットなので、投入から実行までの間に1手ぶん parity が動くと検査は無効になる（TOCTOU）。実際の経路として、盤上のホイール undo/redo（`__main__.py:1737-1739`）とキーボード undo（`:1833`）は**1手単位で parity を反転させる**（`gui.kv:636` のボタンは "smart" で2手戻すので parity は保つ）。反転後に注入が実行されると、空点への合法手なので `IllegalMoveException` も出ず、**例外もログも無しに逆色の石が入る**。

よって `("board-watch-play", coords, color, expect_move_number)` を追加し、メッセージループ側のハンドラで `current_node.next_player == color` と手数の一致を**再検証してから** `game.play(Move(coords, player=color))` を呼ぶ。不一致なら着手せず破棄し、`Mismatch` として警告する。

**(b) 反映確認は2通りのどちらかで成立とする。**

注入後の期待グリッド（`apply_move_to_grid` の結果）は**盤上に一瞬しか存在しない**ことがある。メッセージループは `_do_play` の直後に `_do_update_state()` を回し、解析が返ると同じスレッドで AI が応手する（`:299-309`）。ポーリングがその窓に当たらないと期待グリッドは永久に観測されず、`inject_timeout_ms` まで注入が止まり「反映されませんでした」の**偽警告が正常動作のたびに出る**。

したがって反映確認は「期待グリッド」**または**「期待グリッドに KaTrain の最終手を足したもの（＝行5の `Ahead` 判定と同じ式）」のいずれかが観測されたら成立とする。タイムアウトした場合は**同じ手を再注入せず**、`Mismatch` として再同期を案内する（コウ再取り等の本物の乖離を、無限リトライではなくユーザー操作へ渡す）。

**(c) 進捗ウォッチドッグ。**

`Waiting` / `Ahead` / `InSync` は無音の終端状態なので、**誤認識が両者に化けると警告ゼロで機能が止まる**。§8 のとおり白石上の有彩色マーカーは `spread>90 and mr>mb` で「空点」に化けうる（`"?"` と違って `CaptureError` にならない）。マーカーは常に最終手の石の上にあるため、化けたグリッドは「最終手の石だけが欠けた盤」＝行5の成立条件そのものになり、以後 `Ahead` と `InSync` を交互に返して1手も注入しない。黒石上の白マーカーは `"?"`→`CaptureError`→警告に落ちるので、**片方の色だけが黙って死ぬ**。

対策として、**`state` が変化しないまま `Waiting`/`Ahead`/`InSync` が `stall_warn_sec`（既定20秒）続いたら警告**を出す。これは誤認識だけでなく「ユーザーがアプリへのタップを忘れている」場合と、行3の `Waiting` から永久に出られない場合（色の割り当てが逆）にも効く。

**(d) `Mismatch` からの復帰。**

`Mismatch` は自然には解消しない。KaTrain の undo ボタンは play モードで2手戻す（`gui.kv:636`）ので `current` が2手前になり、行6の「1手で説明」が原理的に成立せず以後ずっと `Mismatch` になる。アプリ側の待ったも同様。よって `Mismatch` が `resync_hint_frames`（既定10）続いたらバナーに**再同期の案内**（ホットキーで OFF→ON し直すと現局面を取り込み直す）を出す。自動で盤面を書き換えることはしない（ユーザー決定事項）。

## 3. トグルと局面の取り込み

### 3.1 ホットキー登録

`GetMessageW` のメッセージループを外から止める手段がコードベースに無い（`PostQuitMessage` / `WM_QUIT` / `PostThreadMessage` の呼び出しは0件）。登録解除方式は停止機構の新設が必要で既存4本を巻き込むため、**ホットキーは登録したままフラグでトグル**し、監視スレッドの起動/停止だけを行う。

既存に触るのは2箇所:

1. **登録関数の一般化**: `_setup_tsumego_capture`（`__main__.py:793-832`）を `_setup_global_hotkeys` に改め、`tsumego_capture.enabled` と `board_watch.enabled` を**独立に評価**して表を組む。現状は冒頭の `if not settings.get("enabled", False): return`（`:796-797`）で丸ごと早期 return するため、詰碁キャプチャを無効にしているユーザーでは `board_watch.enabled: true` でも監視ホットキーが1本も登録されず、ログにも何も出ない。詰碁4本を全部空文字にしたときの `if not hotkeys: return`（`:829-830`）も同じ理由で監視を巻き込む。各行の設定はそれぞれのブロックから読み（`board_watch.hotkey` は `board_watch` ブロック）、ログのプレフィクスも機能別（`tsumego_capture:` / `board_watch:`）にして登録可否を切り分けられるようにする。
2. **dispatch の一般化**: 表（`:814-818`）が `(role, frameless)` の位置引数タプル固定で、dispatch（`:872-876`）が `target=self._tsumego_capture_trigger` を決め打ちしている。表を `(ハンドラ名, args)` の形にし、dispatch は `getattr(self, name)` を使う。既存4本は `("_tsumego_capture_trigger", (role, frameless))` になるだけで挙動不変。ID の自動採番（`_TSUMEGO_HOTKEY_ID + len(hotkeys)`）はそのまま。

デバウンス（2秒）と `_tsumego_capture_busy` は詰碁トリガーのインスタンス属性（`:886-892`）なので**共有せず別に持つ**（共有すると詰碁キャプチャと監視トグルが相互に塞ぎ合う）。

### 3.2 トグル ON

1. **前提チェック**（満たさなければ ON にせず理由を表示）
   - 片方が AI・片方が人間であること（両者人間なら注入した手に誰も応じない、両者 AI なら行2で永久 `Mismatch`）
   - `game.region_of_interest` が残っていないこと（直前が詰碁キャプチャだと ROI と `B=ai:tsumego` が残る。`_do_capture_fullboard_apply` がわざわざ両者を人間に戻しているのと同じ事故）。残っていれば解除する
2. アプリを認識（`detect_board` → `detect_size_and_classify`）→ 観測グリッド・盤サイズ・盤矩形をキャッシュ。失敗ならエラー表示して ON にしない
3. KaTrain の現局面と**一致していればそのまま監視開始**（同一サイズの空盤同士を含む通常ケース）
4. 不一致なら局面を取り込む。**既存の `_do_capture_fullboard_apply` は流用しない** — 両者を人間に戻す（`:1313-1315`）・`raise_window` でフォーカスを奪う（`:1318-1328`）・解析モードに入る、の3つが監視モードに不都合。新しい `_do_board_watch_start` を**1メッセージ内**で完結させる（`new-game` を別メッセージに分けると `game_id` 更新で後続が黙って破棄される。`:1339-1340` のコメントと `_do_tsumego_capture_apply` が前例）
5. プレイモードへは既存の作法で入れる: `Clock.schedule_once(lambda _dt: self.play_mode.play.trigger_action(duration=0))`（`:1576-1587`）。`switch_ui_mode` のトグルは他所の予約済みクリックと競合して `mode` の読み値が狂う、というコメント付きの既知の罠

**取り込みの SGF は `grid_to_sgf` を流用しない**。あれは石が1つも無いと `CaptureError("石が1つも見つかりません（詰碁が表示されているか確認してください）")` を投げ（`tsumego_capture.py:110-116`）、`PL[B]` 固定でもある。「前局が残った KaTrain＋新規対局（空盤）のアプリ」「19路の KaTrain＋9路の空盤アプリ」という**この機能で一番普通の開始手順**がそこで失敗し、しかも詰碁の文言が出て原因が読めない。`board_sgf()`（§1）を持ち、空盤なら `AB`/`AW` 無しで `SZ`/`KM`/`PL` だけを書く。

**取り込み後の手番は「人間側（アプリ AI）の色」に固定する。石数からは決められない**。盤上石数 `b, w` と取られた石数 `cb, cw` の間には `b − w = cw − cb` が成り立つので、取りが1回でも入ると石数パリティは手番を表さない（9路で双方6手ずつ・黒が白1子取った局面は 黒6/白5 だが手番は黒）。人間側に固定するのは安全側の選択で、KaTrain が誤った色で勝手に打ち出す事故が構造的に起きない（誤っていた場合は「相手の手待ちのまま止まる」だけで、§2.5(c) のウォッチドッグが20秒で気づかせる）。バナーには「取り込み: アプリ側の手番として開始しました」と出し、KaTrain の手番から始めたい場合はユーザーが KaTrain 側で1手進める運用にする。

プレイヤー設定は触らない（`sgf_filename` を渡さなければ維持される）。この経路では**手順が失われ配置のみの局面**になる。空盤から始めれば全手が棋譜に残るので通常運用では発生しない。

AI が自動応手する前提条件（`_do_update_state`、`:281`・`:299-314`）: `MODE_PLAY` / nav drawer 閉 / popup なし / `analysis_complete` / `next_player.ai` / `not cn.children` / `not game.end_result` / `not (teaching_undo and cn.auto_undo is None)`、さらに ROI があれば `analysis["region_completed"]`。監視 ON でプレイモードへ入れ、ROI を解除するのはこのため。ユーザーが途中で解析モードへ移った場合は §2.3 行2が警告として拾う。

### 3.3 トグル OFF

スレッド停止フラグ＋join のみ。ホットキーは登録したままで何度でも ON/OFF できる。スレッドは daemon。

## 4. 状態表示

盤の真上の全幅バナー（`gui.kv:325-341` のクラスルール、配置は `:1199-1206`）を再利用するが、**既存プロパティには相乗りしない**:
- `tsumego_book_status` は `update_gui` が毎メッセージ後に無条件で上書き（`:258`）
- `tsumego_banner_flash` は必ずタイマーで消える（`:476-485`）

**プロパティは2本に分ける**。既存の `status` は表示テキストではなく**状態トークン**で、色は `TSUMEGO_BOOK_BANNER_COLORS.get(...)`（`gui.kv:329`）の辞書キー、テキストは `'playing'/'done'/'off'` を i18n へ写す入れ子三項（`gui.kv:341`）で決まる。未知の値を入れると**色は既定へフォールバックし、テキストは空になる**ので、「同期できません: 理由」のような可変文言は1本のプロパティでは載らない。

| プロパティ | 型 | 用途 |
|---|---|---|
| `board_watch_status` | トークン `""` / `watching` / `warn` | 表示条件と背景色 |
| `board_watch_detail` | 自由文 | 警告理由（あれば i18n トークンより優先して表示） |

kv 側で触るのは4系統: ラベルのテキスト式（`detail` を最優先に差し込む）、背景色式、`height`、`opacity`。テーマ色キーは既存の `off`/`warn`（回答帳の意味で使用中、`theme.py:155-163`）と**衝突しない名前**（`bw-watching` / `bw-warn`）を使う。

| 状態 | トークン | 色 | 文言 |
|---|---|---|---|
| 監視中 | `watching` | 緑 | 盤面監視中（相手の手を自動反映） |
| 警告 | `warn` | 橙 | `board_watch_detail` の内容 |
| OFF | `""` | — | 空文字（高さ0＝従来レイアウト不変） |

右パネルの `set_status` は着手のたびに自動クリアされる（`controlspanel.py:123-131`）ので常時表示には使わない。注入した手はログにも1行出す（`OUTPUT_INFO`）。ワーカー→GUI は `Clock.schedule_once` を挟む既存の作法に従う。

## 5. 設定

`config("a/b")` は2階層固定（`base_katrain.py:261-270`）なので、新しいトップレベルブロック `board_watch` にフラットに置く。

| キー | 既定 | 意味 |
|---|---|---|
| `enabled` | `true` | 機能ごと無効化（`tsumego_capture.enabled` とは独立。§3.1） |
| `hotkey` | `ctrl+alt+b` | 監視トグル（`Theme.KEY_*` と重ねないこと。§0） |
| `window_title` | `""` | 空なら `tsumego_capture.window_title` を継承 |
| `poll_interval_ms` | `400` | ポーリング周期 |
| `stable_frames` | `2` | 同じ `Move(i, j)` が何回連続で出たら確定するか |
| `failure_warn_frames` | `8` | 認識失敗を何回連続で見たら警告するか |
| `inject_timeout_ms` | `5000` | 注入後、反映が確認できるまで次を止める上限 |
| `stall_warn_sec` | `20` | 状態が変化しないまま無音が続いたら警告（§2.5c） |
| `resync_hint_frames` | `10` | `Mismatch` が続いたら再同期を案内（§2.5d） |
| `backoff_after_failures` | `3` | 連続失敗が何回でバックオフを始めるか |
| `backoff_factor` | `2.0` | バックオフ時に周期を何倍にするか |
| `poll_interval_max_ms` | `2000` | バックオフの上限（成功1回で既定周期へ即復帰） |

パッケージ `katrain/config.json` と `C:\Users\iwaki\.katrain\config.json` の**両方**に追加する（後者はマージされない: `base_katrain.py:210-238` はファイル不在か `version < CONFIG_MIN_VERSION` のときだけ丸ごとコピーし、実測でユーザーの `general.version` は `1.17.0`）。ローカル側は **KaTrain を終了した状態でメインセッションから直接編集**する（起動中の編集は終了時の全体書き戻しで消える。`base_katrain.py:254-259`）。

`tsumego_capture` と同様、GUI 設定ポップアップには出さない（`popups.py:430-458` の動的生成は `ai/<strategy>/<key>` 専用で、他は kv への手書きが必要）。

## 6. エラー処理

`CaptureError` は1種類しかなく、`recognize_board`（`:654-665`）が app 経路と Web 経路のメッセージを連結して投げ直すため**型では切り分けられない**。よって発生元の状況で3階層に分ける。

| 階層 | 例 | 動作 |
|---|---|---|
| 過渡失敗 | 判定できない交点（`:106`）、盤サイズ判定不可（`:214`）、格子線不足（`:300`） | 黙ってスキップ。連続 `failure_warn_frames` 回で初めて警告 |
| 恒久失敗 | ウィンドウ無し（`:155`）、盤面未検出（`:48`） | 即警告、ただし監視は継続（最小化しただけで死なないように） |
| 同期ずれ | `Mismatch` | 警告のみ。盤面には触らない。`resync_hint_frames` で再同期案内 |

**監視ループ全体を包括 `try/except` で包む**。想定外の例外（座標の `None`、盤サイズ変化による `IndexError` 等）でスレッドが死ぬと、バナーは緑の「監視中」のまま1手も注入されない無症状の停止になる。未知例外は `Mismatch` 相当の警告に落として監視を続ける。

**バックオフ**: 連続失敗が `backoff_after_failures` 回に達したら周期を `backoff_factor` 倍にし、`poll_interval_max_ms` で頭打ち。**成功1回で既定周期へ即復帰**。失敗フレームは app 経路が失敗すると Web 経路へフォールバックするため高コスト（実測 470ms、`_web_thin_profile` が 313ms）で、これを抑えるのがバックオフの目的。

Windows のグローバルフックが GIL 長時間保持で外された実測経緯（`__main__.py:836-842`）があるため、監視スレッドは**認識処理を自スレッドで完結**させ、GUI スレッドを塞がない。

## 7. テスト計画

1. **pytest（Kivy・KataGo 不要）** — `tests/test_board_watch.py` を新設
   - `stones_to_grid`: 座標変換の往復（grid ↔ KaTrain coords）、上下反転していないこと
   - `apply_move_to_grid`: 単石の取り／連の取り／自殺手 `None`／取りを伴う自殺回避／既石 `None`
   - `reconcile` の**7行すべて**: 盤サイズ不一致 / `to_play_is_human` 偽（**行6が同時成立する配置で行2が勝つこと**）/ `ai_can_respond` 偽 / `InSync` / `Ahead` / `last_move` が `None`（root）/ `last_move` が pass / 取りを伴う `Move` / 2手ずれ `Mismatch` / ノイズ1点 `Mismatch`
   - `board_sgf`: 空盤（`AB`/`AW` 無し）・`PL` 指定・盤サイズ
   - `BoardWatcher`: 偽フレーム列（`capture_fn` を差し替え）でデバウンス・注入ガードの2通りの成立条件・タイムアウト後に再注入しないこと・進捗ウォッチドッグ・`Mismatch` の再同期案内・バックオフと復帰・未知例外で死なないこと。既存の monkeypatch 流儀は `tests/test_tsumego_capture.py:296-309`
2. **実スクショ回帰** — 対局アプリの連続する2手のスクショを `tests/data/` に置き、「認識が通る」と「差分がちょうどその1手になる」を固定
3. **実機での通し確認** — 実対局を数手。特に「KaTrain の undo」「アプリ側の待った」で `Mismatch` → 再同期案内 → OFF/ON で復帰できること

**詰碁 E2E（`e2e_suite.py`・約20分）は不要**（選択則・枠判定・解析まわりを触らないため）。ただし `tsumego_capture.py` に手を入れる場合は認識系の回帰（`tests/test_tsumego_capture.py` 36件＋`validate_web_capture.py` 5枚）を回す。

## 8. リスクと最初のタスク

**最初のタスクは実装ではなくスパイク**: 対局アプリのスクショを1枚撮り、既存の認識器がそのまま通るかを確かめる。**確認の最優先項目は最終手マーカー**で、「例外が出るか」ではなく「マーカーの乗った石が何と分類されるか」を見る（`"?"` なら `CaptureError` で警告に落ちるが、`"."` に化けると §2.5(c) のウォッチドッグ無しでは無音停止する）。

コード上の根拠がある未検証リスク:

- **最終手マーカー**: 黒石上の白マーカーは面積比が約3割を超えると `brightness<90`（`_classify_patch:59-80`）を外れて `"?"`。白石上の有彩色マーカーは `spread>90 and mr>mb` で**空点**に化けうる（例外にならないので黙って効く）
- **盤外UI**: 時計や取り石カウンタが `_is_yellow`（`:27-30`）の色域に入ると `detect_board` の bbox が崩れる（連結性を要求せず行/列の50%しきい値のみ）
- **座標ラベル帯・余白**: 規則配置前提（`:84-86`）が崩れると毎フレーム Web 経路へ落ちて 470ms かかる

**対局アプリ用に閾値調整が必要になっても、詰碁経路の関数は一切変えず別経路として足す**。認識条件を変える改修は「以前成功していた側の破損率」も測る必要があり（CLAUDE.md の禁止事項）、詰碁の校正資産（`tests/data` 3枚＋`validate_web_capture.py` 5枚＋E2E）を巻き込むと高くつく。

## 9. 実装順序

1. スパイク: 対局アプリのスクショ1枚で認識が通るか（最終手マーカーの分類結果を最優先で確認）
2. `board_watch.py` の純関数（`stones_to_grid` / `apply_move_to_grid` / `reconcile` / `board_sgf`）＋ pytest
3. `BoardWatcher`（スレッド・キャッシュ・デバウンス・注入ガード・ウォッチドッグ・バックオフ）＋ 偽フレームでの pytest
4. `__main__.py` の配線: ホットキー登録の一般化（`_setup_global_hotkeys` と dispatch）、トグル、`get_state_fn`、`board-watch-play` ハンドラ、局面取り込み
5. バナー（プロパティ2本＋kv 4系統＋テーマ色2キー）
6. 設定キーを両方の `config.json` へ追加
7. 実スクショ回帰＋実機で通し確認

## 10. レビューで確認した「そう見えるが違う」点

多エージェントの敵対的レビュー（51エージェント・確定24件／棄却23件）で出た指摘のうち、**実コードで棄却されたもの**を再燃防止のため記録する。

- **`game.stones` を読むのに `with game._lock:` を取ると自己デッドロックする**という指摘 → 誤り。`stones` プロパティ自身が `_lock` を取る（`game.py:316-319`）ので**呼び出し側は取らない**。リポジトリに外から `game._lock` を取るコードは0件
- **`ImageGrab.grab(bbox=...)` で撮影が速くなる** → 誤り。Pillow は Windows で全画面 BitBlt 後に crop する（実測: 暖機後 27〜28ms で同値）。最初にこれを「3倍速い」と測ったのは**1回目の DLL 初期化込みの値と2回目を比べた**方法論エラー
- **contributing モードで注入が握り潰される** → 別モードで本機能と同時に使わないため無関係
- **監視中の SGF ロードで AI が応じなくなる** → `load_sgf_file` は必ず `move_tree` を渡すので解析モードへ入り、§2.3 行2が警告として拾う
- **監視中に詰碁キャプチャを撮ると詰碁盤へ注入される** → 枠石が約80子乗るので行6の完全一致が成立せず `Mismatch` に落ちる

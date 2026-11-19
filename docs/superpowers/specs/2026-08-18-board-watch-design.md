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
| ホットキー | `ctrl+alt+d` |
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

**修正（2026-08-19・レビュー Finding B）**: 上記の「OFF→ON し直す」を初版の `RESYNC_HINT` は「ホットキーを2回押す」と文言化していたが、これは実際には機能しない。`_board_watch_trigger` の2秒デバウンスは分岐に入る**前**にタイムスタンプを更新するため、STOP を選ぶ押下でも更新される。人間の二度押し（0.2〜0.5秒間隔）は「1回目=停止・2回目=デバウンスで無視」にしかならず、監視が OFF のまま空のバナーが残るだけで再取り込みは起きない（デバウンス自体・その2秒という長さ・トリガーの分岐構造はこの修正の対象外＝spec 上の要求であり変更は別の設計判断）。文言はキー名を具体的に書かず（`board_watch.hotkey` はユーザー設定なので変わりうる）、「OFF にしてから一呼吸おいてもう一度押す」という手順を案内する形に直した（`RESYNC_HINT = "（監視トグルのホットキーで OFF にし、1秒ほどおいてからもう一度押すと現局面を取り込み直します）"`）。テキストのみの修正で、デバウンス・タイムアウト・トリガーの分岐構造は変更していない。

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
   - AI 側の `player_subtype` が詰碁専用戦略（`AI_TSUMEGO` / `AI_TSUMEGO_SOLVER`）でないこと（**修正（2026-08-19・レビュー Finding C）**: 初版はこのチェックを持たず ROI だけを解除していたため、詰碁キャプチャ直後に監視を ON にすると `B=ai:tsumego(_solver)` のまま対局が始まっていた。`PlayerInfo.ai` は `player_type` しか見ず、自動応手ゲートも詰碁戦略も ROI 不在を要求しないため何も止めない。しかも `tsumego_view=True` で対局者パネルごと隠れているため気づく手段が無い。`_do_capture_fullboard_apply` の前例に倣い「両方の残骸を扱う」のが設計意図だったが実装は ROI だけだった。**修正は自動でリセットしない** — どの戦略に差し替えるかはユーザーの選択であり、勝手に選ぶと別の事故になる。代わりに ON を拒否し、`self.tsumego_view = False` でパネルを復元してから警告バナーを出す（拒否だけだとパネルが隠れたままで設定を直す手段が無くなるため）。この分岐は ROI クリアより前に置き、拒否時は ROI にも触らない — 開始しない前提チェックの失敗で盤面状態を変える副作用は避ける）
2. アプリを認識（`detect_board` → `detect_size_and_classify`）→ 観測グリッド・盤サイズ・盤矩形をキャッシュ。失敗ならエラー表示して ON にしない
3. KaTrain の現局面と**一致していればそのまま監視開始**（同一サイズの空盤同士を含む通常ケース）
4. 不一致なら局面を取り込む。**既存の `_do_capture_fullboard_apply` は流用しない** — 両者を人間に戻す（`:1313-1315`）・`raise_window` でフォーカスを奪う（`:1318-1328`）・解析モードに入る、の3つが監視モードに不都合。新しい `_do_board_watch_start` を**1メッセージ内**で完結させる（`new-game` を別メッセージに分けると `game_id` 更新で後続が黙って破棄される。`:1339-1340` のコメントと `_do_tsumego_capture_apply` が前例）
5. プレイモードへは既存の作法で入れる: `Clock.schedule_once(lambda _dt: self.play_mode.play.trigger_action(duration=0))`（`:1576-1587`）。`switch_ui_mode` のトグルは他所の予約済みクリックと競合して `mode` の読み値が狂う、というコメント付きの既知の罠

**取り込みの SGF は `grid_to_sgf` を流用しない**。あれは石が1つも無いと `CaptureError("石が1つも見つかりません（詰碁が表示されているか確認してください）")` を投げ（`tsumego_capture.py:110-116`）、`PL[B]` 固定でもある。「前局が残った KaTrain＋新規対局（空盤）のアプリ」「19路の KaTrain＋9路の空盤アプリ」という**この機能で一番普通の開始手順**がそこで失敗し、しかも詰碁の文言が出て原因が読めない。`board_sgf()`（§1）を持ち、空盤なら `AB`/`AW` 無しで `SZ`/`KM`/`PL` だけを書く。

**取り込み後の手番は「盤上2子以内なら石数から確定、それ以外は人間側（アプリ AI）の色に固定」（2026-08-19 修正2。経緯は §11・§12）**。石数パリティが一般に手番を表さないのは、盤上石数 `b, w` と取られた石数 `cb, cw` の間に `b − w = cw − cb` が成り立つためで、取りが1回でも入るとパリティは崩れる（9路で双方6手ずつ・黒が白1子取った局面は 黒6/白5 だが手番は黒）。この場合に人間側へ固定するのは安全側の選択で、KaTrain が誤った色で勝手に打ち出す事故が構造的に起きない（誤っていた場合は「相手の手待ちのまま止まる」だけで、§2.5(c) のウォッチドッグが20秒で気づかせる）。**ただし盤上2子以内では取りが起き得ないので、この範囲のパリティは推測ではなく確定である** — 最初の取りは3手目より前には起こせず（1手目の石は空盤上で呼吸点2以上を持ち、2手目の1子では詰められない）、その3手目の取りが作る盤は 黒2子・白0子＝`b − w = 2` なので `b − w ∈ {0,1}` のガードから外れる。よって確定できるのは `(b,w) = (0,0) → 黒` / `(1,0) → 白` / `(1,1) → 黒` の3通りで、いずれも取りなしの交互着手でしか到達できない（3路・4路の合法手列を深さ7/5まで総当たりして確認。前提は「最初の2手にパスが無い」ことだけで、パスは §0 のとおりそもそも監視の検出対象外）。純関数は `board_watch.import_next_player(grid, human_color)` で、**手番と根拠の文字列を組で返す**（根拠の分岐を `__main__` 側で再計算しない＝§1 の「判定ロジックを1行も `__main__.py` に置かない」）。ログは「空盤なので黒番」／「2子以内なので石数から確定」／「人間側に固定」で書き分ける。3つ目に落ちた局面で KaTrain 側から始めたい場合は、ユーザーが `ai-move`（Enter）で1手進める運用にする。

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
| `hotkey` | `ctrl+alt+d` | 監視トグル（`Theme.KEY_*` と重ねないこと。§0） |
| `window_title` | `""` | 空なら `tsumego_capture.window_title` を継承 |
| `poll_interval_ms` | `400` | ポーリング周期（**idle**＝相手の石が来ようがない局面。追記3） |
| `poll_interval_active_ms` | `50` | ポーリング周期（**active**＝相手の着手を実際に待っている局面。`poll_interval_ms` と同値にすれば適応が消えて従来の固定周期に戻る。追記3） |
| `stable_frames` | `2` | 同じ `Move(i, j)` が何回連続で出たら確定するか |
| `prefetch_replies` | `5` | 相手の応手 top-K の子局面を先読みして NN キャッシュを温める本数（0で無効。追記4） |
| `failure_warn_frames` | `8` | 認識失敗を何回連続で見たら警告するか |
| `inject_timeout_ms` | `5000` | 注入後、反映が確認できるまで次を止める上限 |
| `stall_warn_sec` | `20` | 状態が変化しないまま無音が続いたら警告（§2.5c） |
| `resync_hint_frames` | `10` | `Mismatch` が続いたら再同期を案内（§2.5d） |
| `backoff_after_failures` | `3` | 連続失敗が何回でバックオフを始めるか |
| `backoff_factor` | `2.0` | バックオフ時に周期を何倍にするか |
| `poll_interval_max_ms` | `2000` | バックオフの上限（成功1回で既定周期へ即復帰） |
| `highlight_color` | `"cyan"` | AI の着手をアプリ盤の該当交点の真上に出す輪の色（追記6）。`"off"` で表示しない。値は `screen_marker.highlight_choices()`＝off / cyan / magenta / lime / red / orange / white。設定画面 general 節のドロップダウン |
| `highlight_difficulty` | `false` | 輪の色を局面の難しさで塗り分ける（追記11）。明らか＝緑・難解＝赤・普通＝`highlight_color`。ON の間だけ相手の着手ごとに humanSL 9段 8visits を1本先回りで撃つ。設定画面は輪の色と同じ行のチェック |

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

## 11. 追記1（2026-08-19）: 空盤の手番を人間側に固定していた欠陥

§3.2 の初版は、取り込み後の手番を石数に関わらず**一律**「人間側（アプリ AI）の色」に固定していた。石が1つでもある局面ではこれは正しい（`b − w = cw − cb` のパリティ論法、上記の通り）。しかし**空盤（対局の開始そのもの）にも同じ規則を適用したため、KaTrain 側 AI が黒番で対局を始める最も普通のケースが到達不能になっていた**。

実機ログで確認（ユーザーの実対局・`~/.katrain/logs/game_20260819_012616.log`）:

```text
board_watch: アプリの局面（9路）を取り込みました（手番=W）
board_watch: 監視を開始しました
```

ユーザーは9路の新規対局をアプリで黒番として開始した（アプリ側 AI は白＝KaTrain 側では黒が AI・白が人間）。取り込みは空盤に「手番=W」を書き込んだため、KaTrain の黒番 AI は一度も着手できず、ユーザーは KaTrain の着手を待ち・KaTrain は人間（＝アプリ AI の反映）の着手を待ち・監視スレッドはアプリ側 AI の着手を待つ**三者デッドロック**になった。20秒の進捗ウォッチドッグ（§2.5c）は作動するので無症状ではないが、**対局を開始することそのものができない**。

**修正**: 空盤（石が0個）は「対局の開始」以外にあり得ず、開始時点では取りが発生している余地が無い。したがって空盤では黒番を返してよい — これは石数からの推測ではなく囲碁のルール（黒が先手）そのものである。石が1つでもある局面は従来どおりパリティ論法により人間側へ固定する。純関数 `board_watch.import_next_player(grid, human_color)` に実装し、`tests/test_board_watch.py` の3ケース（空盤は `human_color` に依らず黒番／単石の局面は `human_color`／多石の局面も `human_color`）で回帰する。`_do_board_watch_start` のログは根拠を「空盤なので黒番」／「人間側に固定」で書き分け、診断可能な状態を保つ。

**残る限界**: 対局**途中**で、たまたま KaTrain 側 AI の手番であるタイミングで監視を ON にするケースは、この修正では救えない。ON 時点で KaTrain の現局面とアプリの盤面が一致していれば取り込みは行われず（§3.2 手順3）、reconcile がそのまま現在の手番で判定に入る。手番が本当に AI 側かどうかは、1フレームの観測盤面（取られた石数が分からない）からは判定できない。この場合の脱出口は既存の `ai-move` アクション（Enter / numpad-Enter に割り当て、`theme.py:184` / `gui.kv:883`）— 手動で AI に1手打たせれば、以後は監視が正常に追随する。20秒の進捗ウォッチドッグ（§2.5c）の警告文は、ありふれた2つの原因（アプリへの着手入力をまだしていない／実は KaTrain の手番）を両方案内するように改めた。**どちらが実際の原因かを判定する仕組みは意図的に持たない**（1フレームからは区別できないため。設定も追加しない）。

## 12. 追記2（2026-08-19）: 相手の初手が乗った盤の取り込みで手番を人間側に倒していた欠陥

§11 の修正は空盤だけを例外にしたため、**アプリ側 AI が初手を打ってから監視を ON にする**という同じくらいありふれた手順が §11 とまったく同じ形で止まっていた。

ユーザー報告: アプリで自分が白・アプリ AI が黒（KaTrain 側では人間=黒／AI=白＝難解（9路））で対局を始めたところ、KaTrain の白番 AI が2手目を打ち始めない。

実機ログ（`~/.katrain/logs/game_20260819_112356.log`・全4行）:

```text
board_watch: アプリの局面（9路）を取り込みました（手番=B・人間側に固定）
Sending query QUERY:887: {... "initialStones": [["B", "F4"]], "initialPlayer": "B", "moves": [] ...}
board_watch: 監視を開始しました
[0.5][QUERY:887][done] KataGo analysis received: 81 candidate moves, 2020 visits
```

黒1子の盤を「手番=B（＝人間側）」で取り込んだため、`_do_update_state` の自動応手ゲート（`__main__.py:299-309`）の `next_player.ai` が偽になり、解析は完了しているのに AI は一度も呼ばれない。ウォッチャー側は「アプリの盤＝KaTrain の盤」なので `InSync`（§2.3 行4）を返し続け、20秒のウォッチドッグが鳴くまで無音。§11 の三者デッドロックと同じ膠着が、開始が1手ずれただけで再発していた。

**修正**: 上記 §3.2 のとおり「2子以内は確定」を加えた。これは §11 の空盤ルール（`(0,0) → 黒`）を、取りが原理的に起き得ない範囲へ広げた一般化で、空盤ルールは新しい式の特殊ケースとして吸収される。これで監視 ON の自然な入口3つがすべて動く:

| ON した時点の盤 | 手番 | 動き |
|---|---|---|
| 空盤（両者これから） | 黒 | KaTrain の AI が黒なら初手を打つ／人間が黒ならアプリ AI の初手を待つ |
| 黒1子（アプリ AI が黒で先着） | 白 | KaTrain の AI が白なら2手目を打つ（**本報告のケース**） |
| 黒1子・白1子（自分が黒で先着し AI が応じた） | 黒 | KaTrain の AI が黒なら3手目を打つ |

**回帰**: `tests/test_board_watch.py`
- 単体4件（1子→白／各1子→黒／黒2子（取りの証拠）→人間側／多石→人間側）と根拠文字列が3分岐を区別すること
- **総当たり**（`test_import_next_player_agrees_with_every_reachable_small_position`）: 3路を深さ7・4路を深さ5まで合法手列を全展開し、到達した `(局面, 手番)` のうち関数が「確定できる」と言うものが実際の手番と必ず一致することを確認。同時に「2子以内でも `b − w ∉ {0,1}` で到達する局面（＝取りが起きた証拠）が実在すること」も assert して、ガードが空回りしていないことを固定する（0.95 秒）
- **実スクショ**（`test_real_screenshot_before_imports_as_white_to_play`）: スパイクで保存した `tests/data/board_watch_before.png` が今回の報告と同じ局面（アプリ AI=黒の初手だけが乗った9路）だったので、この1枚の認識結果をそのまま取り込みに通して白番になることを固定した

**残る限界（不変）**: 3子以上進んだ局面で、たまたま KaTrain 側 AI の手番であるタイミングで ON にするケースは依然として判定できない（1フレームからは取られた石数が分からない＝パリティの議論そのもの）。脱出口は従来どおり `ai-move`（Enter / numpad-Enter）で、ウォッチドッグの警告文もそのまま。ここを埋めるなら盤面以外の情報（アプリ画面の最終手マーカーの色や、`1. 黒4-5` という着手履歴バーの表示＝スパイクで実在を確認済み）を読む必要があり、認識器の新経路になるので本修正には含めない。

## 13. 追記3（2026-08-21）: 反映遅延を平均700ms→150ms に短縮

### 問題

ユーザー報告「アプリの着手が KaTrain に乗るまで体感0.5秒以上」。実測の内訳は下のとおりで、
**最悪990ms のうち800ms が純粋な待ち（ポーリング周期2回ぶん）**、実作業は90〜170ms しかない。

| 段 | 時間 |
|---|---|
| 次のポーリングまでの位相待ち | 0〜400ms（平均200） |
| 1周目の撮影＋認識 → `Move` 判定（`stable_count=1`） | 40〜85ms |
| `stable_frames=2` のための次周待ち | 400ms |
| 2周目の撮影＋認識 → 確定・注入 | 40〜85ms |
| メッセージキュー→`game.play`→Kivy 再描画 | 5〜20ms |
| **合計** | **平均 ≒700ms / 最悪 ≒990ms** |

つまり遅延の主犯は認識コストではなく**周期の置き方**で、`reconcile` の判定表・注入経路・
`__main__.py` には一切触らずに直せる。

### 対策1: 変化なし早期打ち切り（`AppBoardReader`）

盤矩形の画素（`_board_fingerprint` = `img.crop(board_rect).tobytes()`）を前フレームと比較し、
**同一なら分類も格子検算も省いて前回のグリッドをそのまま返す**。判定の意味論は変わらない
——格子検算も分類も同じ入力に対する純粋な関数なので、画素が1ビットも変わっていなければ
結果は必ず同一だからである。

実測（本機・BlueStacks 起動中・1920x1080・盤矩形 700x700 想定）:

| | 1周のコスト |
|---|---|
| 変化あり（従来どおり分類する） | 40〜85ms |
| **変化なし（早期打ち切り）** | **21〜33ms（中央値27ms）** — 撮影 21〜27ms ＋ 画素比較 1.7ms |

**この最適化が50ms周期の前提**になっている。無しでは19路の1周が85ms かかるので、50ms を
指定しても実際には85ms 間隔でしか回れず低遅延化が成立しない。

比較対象を窓全体でなく**盤矩形**にするのは、窓内の時計・通知などが毎フレーム変わると
最適化が丸ごと効かなくなるため。画像が `crop`/`tobytes` を持たない場合（テストのスタブ等）は
`None` を返して「比較しない」に倒す。分類が失敗した回の画素は**覚えない**
（覚えると次周が古いグリッドを返す＝`_forget_frame`）。

### 対策2: 適応ポーリング周期（`BoardWatcher`）

直前の verdict で次の待ち時間を決める。`_on_capture_success` がまず idle に戻し
（＝バックオフ解除を兼ねる）、`step()` の各分岐が「相手の着手を待っている」と判断したときだけ
`_active()` で上書きする。

| verdict | 意味 | 周期 |
|---|---|---|
| `in_sync` | 盤がアプリと一致＝次に変わるのは相手の石 | **active（50ms）** |
| `move`（確定途中） / 注入の反映待ち | 確定と反映の1周が体感遅延に直結する | **active（50ms）** |
| `waiting` | KaTrain の AI が思考中 | idle（400ms） |
| `ahead` | ユーザーがまだアプリへタップしていない | idle（400ms） |
| `mismatch` / `state is None` / `_blocked` | 相手の石が来ようがない・復帰待ち | idle（400ms） |

`_blocked`（タイムアウト済みで再注入しない手）で `_active()` を**呼ばない**のが要点で、
呼ぶと局面が動かない error 状態を50ms で回り続ける。

**確定判定（`stable_frames=2`）のロジックは触っていない。** 周期が50ms になることで確認
コストが自動的に400ms→50ms になるだけである。2回の撮影が同じ表示フレームから取られると
確認が無意味になるが、**誤認識が起きうるのはアニメーション中＝アプリが30〜60fps
（17〜33ms/フレーム）で描画している最中**なので、50ms 間隔なら必ず別フレームになる。

### 結果と代償

想定の内訳: 位相待ち25 ＋ 撮影23 ＋ 確認待ち50 ＋ 撮影23 ＋ Kivy 再描画16 ＝ **平均約140ms**。

代償は active 中の CPU で、27ms/50ms ＝ **1コアの約54%**（＋毎秒20回の全画面 BitBlt）。
`ImageGrab` は Windows では bbox 指定でも全画面 BitBlt してから crop するため、この21〜27ms は
Pillow のままでは削れない（実測: full 21ms / bbox 21ms で同値）。**削るなら DXGI Desktop
Duplication（`dxcam`）や WGC（`windows-capture`）への置き換えが要る**（1フレーム1〜5ms、かつ
「次のフレームまでブロック」できるので位相待ちも消えて80〜100ms まで届く）が、新規バイナリ
依存とフォールバック経路が必要なので今回は見送った。

### KataGo との GPU 取り合い: 測れなかった（計測ハーネスの限界）

19路111局面を1局面ごとに arm を切り替えて解析時間を比べたところ、**キャプチャ ON のほうが
中央値で28%「速い」**という因果的にありえない結果になった（OFF 中央値 1071ms / ON 773ms・
n=55/arm・IQR は 383〜1253ms と3倍幅）。局面ごとの解析コストの分散が大きすぎて、この設計では
contention を分離できない。同一局面を繰り返す設計はさらに悪く、**2巡目以降は NN キャッシュで
解析が即返る**（16局面の合計が 52.0s → 2.9s）ため GPU 負荷そのものが消えて何も測れない。

したがって言えるのは「**ノイズ床（±28%）より小さい**」までで、影響が無いことの証明ではない。
実使用での確認が要る。なお計測中の実効キャプチャレートは 14.6 frames/s だった。

### 設定を戻す方法

`poll_interval_active_ms` を `poll_interval_ms` と同値（400）にすれば適応が消えて従来と
完全に同じ挙動に戻る。この約束は
`test_watcher_backs_off_and_recovers_with_adaptive_polling_disabled` で固定してある。

### テスト

`tests/test_board_watch.py` に9本追加（合計69本）。早期打ち切り側は「画素が同じなら分類を
呼ばない／同じグリッドを返す」「画素が変われば読み直す」「窓が動けば盤矩形ごと作り直す」
「分類失敗の回の画素を覚えない」、適応周期側は verdict ごとの周期と、バックオフが idle を
基準に倍化して成功1回で verdict に応じた周期へ復帰すること。

## 14. 追記4（2026-08-22）: 相手の応手を先読みして KaTrain の着手を 1.55秒 → 0.5秒 に

### 問題

追記3で「アプリの手が KaTrain の盤に乗るまで」は速くなったが、**そこから KaTrain の AI が
指すまで**が遅い。実測の内訳（`game_20260822_000147`・Jigo9・9路 2000visits）:

| 段 | 中央値 |
|---|---|
| 相手の手が入った局面の **root 解析**（`update_state` は `cn.analysis_complete` を待って初めて `_do_ai_move` を呼ぶ） | **1.25秒** |
| Jigo の Stage1（humanSL・1visit） | 0.00秒 |
| Jigo の Stage2（2000visits・**同じ局面**） | 0.30秒 |

**root が約8割**。同じ2000visits でも Stage2 が 0.3 秒で返るのは、直前の root 解析で NN
キャッシュが温まっているから＝**温めれば効く**ことをログ自体が示している。

### 却下: 内蔵 ponder（`analyze_extra("ponder")`）

「現局面を読み続ければ PUCT が有力な子に visits を配る」＝汎用の先読みになるはずだが、
**約10%しか効かない**（実測 2026-08-22・別プロセス A/B・18局面: 先読みなし 1029ms →
ponder 3秒後 921ms）。木全体に visits が散るので特定の1局面が十分に温まらない。

### 採用: 応手 top-K の子局面を狙い撃ちで温める

`_maybe_board_watch_prefetch` / `_board_watch_prefetch_worker` / `_cancel_board_watch_prefetch`
（`game.py`）。詰碁の `_maybe_region_prefetch` の鏡像で、`Game.play()` のリージョンなし分岐
から起動する。

- **発火条件は「次番が人間（＝アプリ側）」だけ**。相手の着手が入った直後は次番が AI に
  なるので、この1条件で「相手が考えている手番」を正しく選べる。リージョンがあるときは
  詰碁経路の担当なので撃たない（二重発火の防止）。
- **クエリは `child.analyze(engine, priority=PRIORITY_BOARD_WATCH_PREFETCH)` を既定引数の
  まま**＝実クエリ（`played_node.analyze(engine)`）と visits・ownership・リージョンが1つ
  残らず一致する。条件がずれると NN キャッシュは温まらない（詰碁で ownership を揃えな
  かったときの実測: 先読み直後の実クエリ 2.70秒＝コールドと同一）。
- **使い捨ての複製ゲームの子ノードで撃つ**＝本譜のツリーを汚さず、terminate が先読み
  クエリだけに当たる。
- **相手の着手が入った瞬間に未消化分を terminate**（`Game.play()` 冒頭）。的中していた
  応手のクエリも止まるが、同一局面の実クエリが直後に走るので温めた NN キャッシュは
  失われない。

### K を 5 で打ち切る理由

実対局134局面（9路・KataGo 2000visits）で測った的中率と、K を増やす限界効率:

| top-K | 的中率 | K を増やす効率 |
|---|---|---|
| 1 | 32.1% | — |
| 3 | 58.2% | 1→3 で +26pt / +2秒 ＝ 13pt/秒 |
| 5 | 68.7% | 3→5 で +11pt / +2秒 ＝ 5.5pt/秒 |
| 8 | 78.4% | 5→8 で +9pt / +3秒 ＝ 3pt/秒 |

policy 順（33.6/56.0/67.2/80.6）は visits 順とほぼ同じなので、**すでに走っている解析の
候補リストをそのまま使える**（予測用の追加クエリは不要）。集中度で層別すると
「2位/1位の visits < 0.15（独走・24%）」で top-3 78.1%、「>= 0.5（拮抗・45%）」で 46.7%。

**「絞れる局面だけ先読みする」ゲートは入れなかった** — 相手の思考中の GPU はどのみち
遊んでいるので外れのコストは電力だけであり、拮抗局面（＝解析が重く一番待たされる局面）で
先読みを切ることになるため。ユーザーの実測によればアプリ側 AI の応答は**明らかな手ほど
速く（〜1秒）難しい手ほど遅い（10秒以上）**ので、予算が必要量に比例して増える。

### 実測（実配線 E2E・`prefetch_e2e.py`・別プロセス arm・18局面）

| 相手の思考時間 | 実クエリ中央値 | 的中時 | 外れ時 | 的中 |
|---|---|---|---|---|
| 先読みなし | 1177ms | — | — | — |
| 1秒 | 596ms | 452ms | 988ms | 13/18 |
| 5秒 | **191ms** | 184ms | 1105ms | 14/18 |

K=5 の5本は並列に走るので**1秒の窓でも中央値が半減する**。外れた手番は baseline と同等
＝キャンセルが効いており遅くならない。AI 1手は **1.55秒 → 約0.5秒**（的中時）。

**最初の E2E は null 実験だった**: 偶数 ply を「白の手番」と取り違えたため全局面で
next_player が AI 側になり、**先読みが1本も発火しないまま両アームが同一設定で走っていた**
（off 1379ms / on 1386ms ＝「効果なし」に見えた）。arm の設定が実際に効いていることを
`fired > 0` の assert で確かめてから測ること。

### 電力・発熱の実測（RTX 3080・320W上限）

| 状態 | 消費電力 | GPU温度 | 利用率 |
|---|---|---|---|
| アイドル | 27〜42W | 49〜51℃ | — |
| KataGo 解析中 | 平均278W / 最大301W | 70℃（最大73℃） | 85% |

増分は解析中 +240W。1手あたりの追加 GPU 時間は的中時の節約を差し引いて +2〜5秒程度、
1局60手で **+16Wh**＝31円/kWh で**1局あたり約0.5円**。金額は無視できる。実質的なコストは
**GPU がほぼ 70℃ に張り付く（＝ファンの音が連続する）**ことで、スロットリング域
（83℃〜）には届かない。気になる場合は `prefetch_replies` を下げる。

### テスト

`tests/test_board_watch_prefetch.py`（10本）。実クエリと同条件で撃つこと・複製ゲームの
子ノードに紐づくこと・top-K の打ち切り・pass の除外・相手の手番でだけ発火すること・
リージョンありでは発火しないこと・cancel が先読みノードだけを terminate すること。

---

## 15. 追記5（2026-08-27）: 新規対局で監視フラグが落ちるバグと、難解の ponder との一本化

- **バグ**: `_do_new_game` は `Game` を作り直すので `board_watch_active` / `board_watch_prefetch_replies` が
  初期値（False / 0）に戻るが、対局監視スレッド（kind="game"）は `_stop_board_watcher(kinds=("tsumego",))`
  で生き残る。セッション2局目以降、応手先読み（追記4）と難解のヨセ即応（enigma spec 追記7＝
  `board_watch_active` で発火）が黙って死んでいた（実測 `game_20260827_155133`: 先読み 0 本・ヨセ31手すべてが
  省けるはずの Probe 1.1 秒を払う）。`board_watch.apply_game_watch_flags(game, cfg)` を新設し、
  `_do_board_watch_start` と `_do_new_game`（kind=="game" のとき）の両方から呼ぶ。静的検査
  `test_new_game_reapplies_the_watch_flags_while_the_game_watcher_runs` が両方の呼び出しを固定する。
- **一本化**: 難解（enigma）の着手後 ponder がその着手で発火済み（`game._enigma_ponder_owner == node.move.player`）
  なら `_maybe_board_watch_prefetch` は撃たない。両方が撃つと 2000visits の root が 9 本横並びになり
  アプリの約 2.8 秒では 1 本も温まり切らない（実測 `game_20260827_154802`: 的中 28%）。ponder が発火しない
  手番（難解の早期 return や他の戦略）は従来どおりここが担当。`board_watch_probe_warm` の Probe 温めは
  ponder 側にも同条件で足してある。
- **自ノード解析**: 監視モードで ponder が armed なら `Game.play` は自ノードに fast（100v）解析だけを出し、
  フル解析は ponder が温めの後に発行する（`Game._enigma_ponder_defers_own_analysis`）。詳細・実測は
  enigma spec 追記9。

## 16. 追記6（2026-08-28）: AI の着手をアプリ盤の真上に強調表示する（`screen_marker`）

**動機**: 同期は片方向（§1）なので KaTrain の AI が打った手はユーザーが手でアプリへタップする。そのたびに
KaTrain の盤とアプリの盤を見比べる往復が要る（ユーザー報告）。自動タップ（ADB・autoloop と同じ機構）は
今回も入れない＝対局アプリでは誤タップの取り消しが利かないため、輪を出すだけに留める。

**設計**（`katrain/core/screen_marker.py`・Kivy 非依存・Windows 専用）:
- 最前面（`WS_EX_TOPMOST`）・クリック透過（`WS_EX_TRANSPARENT`）・非アクティブ（`WS_EX_NOACTIVATE`）・
  タスクバー非表示（`WS_EX_TOOLWINDOW`）の**ピクセル単位の透明度を持つレイヤード窓**（`WS_EX_LAYERED` +
  `UpdateLayeredWindow`）に、アンチエイリアスした輪（外径＝セル幅・太さ 14%。PIL で 8 倍解像度に描いて
  面積平均＝BOX で縮小・事前乗算 BGRA＝`ring_bgra`。LANCZOS は2値マスクでリンギングし線の内側が 253〜254 になる）を 1 枚載せてアプリ盤の交点の真上に置く。当初は窓を輪の形に
  切り抜く `SetWindowRgn` 方式だったが、領域は画素単位の階段状にしかならず輪が荒かった（ユーザー報告・
  同日差し替え。描画は表示・移動・色変更のたびに 80px 四方を 1 回作るだけで常時の負荷なし）。
  **アプリには入力もフックも送らない**（DWM が上に合成するだけ。Android 側からは存在を知る手段がない）。
- 窓の生成・移動・破棄は専用スレッド（メッセージループ）。他スレッドは目標状態を書いて `PostMessage`
  （`WM_APP+1`）で起こすだけ＝`show`/`hide`/`close` はどのスレッドから呼んでもよい。
- **要点＝監視スレッド自身の `ImageGrab` に写り込ませない**。写ると輪の画素が石でも空点でもない色なので
  交点分類が `?`→認識失敗になり、盤矩形の fingerprint も毎周変わる。`SetWindowDisplayAffinity(hwnd,
  WDA_EXCLUDEFROMCAPTURE=0x11)` で BitBlt から除外する。スパイク実測（2026-08-28・build 26200・
  scale 100%・80px の輪）: 対照（region 窓）＝輪が **1764 画素**写る／`WDA_EXCLUDEFROMCAPTURE`＝差分
  **0 画素**／`WS_EX_LAYERED` だけ＝1764 写る（レイヤードは除外にならない）／layered+WDA＝0。
  AA レイヤード窓（`UpdateLayeredWindow`・採用版）でも 対照 2788 画素 → WDA で **0 画素**。
  除外に失敗した環境（Win10 2004 未満）では `capture_excluded=False` にして**輪を出さない**
  （監視を壊すより表示を諦める側に倒す。ログに1行）。

**座標**: `board_watch.intersection_screen_point(window_rect, board_rect, size, i, j)`＝
`classify_intersections` と同じ規則配置（セル幅＝盤幅/size・第1線は盤端から半セル内側）で、autoloop の
`board_to_device` の画面座標版。`AppBoardReader.screen_point(i, j)` がキャッシュ済みの窓矩形＋盤矩形から
毎回引くので、アプリの窓が動いても次の周で追い直す（reader が窓矩形の変化で盤矩形を再検出する）。
座標系は `find_window_rect`（GetWindowRect）と同じ＝同一プロセス内で `CreateWindowExW` も同じ空間。

**タイミング**（`__main__`）:
- 表示: `_do_ai_move` が `generate_ai_move` から戻った直後（`_board_watch_kind == "game"` のとき）に
  `_board_watch_ahead((i, j))`＝**着手と同時**。監視スレッドの ahead 判定（idle 周期 400ms）を待たない。
- 監視側: `BoardWatcher(on_ahead=...)`（省略可能・既定 None＝従来どおり）。verdict が `ahead` の間は
  毎周 `(i, j)` を、`ahead` でなくなったら `None` を**1回だけ**通知する（`_notify_ahead`）。
  同じ `_board_watch_ahead` に入るので、ユーザーがタップしてアプリ盤に石が出た周（`in_sync`）で消え、
  `mismatch`／`waiting` でも消える。undo 等で GUI 側フックを通らない ahead はここが拾う。
- 後始末: `_stop_board_watcher` とトグル OFF（`_board_watch_trigger` の停止分岐）の両方が
  `_board_watch_marker_close()` で窓を破棄する。開始時は前回の輪を捨ててから作り直す。

**設定**: `board_watch.highlight_color`（既定 `"cyan"`・§5 表）の1キーだけ。`"off"` で表示しない＝ON/OFF と色を
設定画面の**1つのドロップダウン**に統合する（パッケージとローカルの両 `config.json` に追加済み）。当初は チェックボックス＋色 の
2行にしたが、設定画面の一般設定欄はエンジン設定欄と同じ高さに固定されており、5→7 行にすると既存の2行ラベル
（手順アニメーション・デバッグレベル等）まで重なった（実測 2026-08-28・ユーザー報告のスクリーンショット）。6 行に戻し、
あわせて `popups.kv` の高さ配分を Main Content Area 6→5.5 / Settings Area 4→4.5 に寄せている。
**設定画面に出す**（`board_watch` 節で GUI に出す初のキー）: `popups.kv` の general 節「盤面テーマ」の下に手書き
（動的生成は `ai/<strategy>` 専用のため）。選択肢は `screen_marker.highlight_choices()` を `ConfigPopup.fill_highlight_colors`
が `value_refs` に流し込み、表示名は `I18NSpinner.i18n_prefix`（新設）＋キー＝`board_watch:highlight_color:<キー>` で
i18n（en/jp）。保存時に `board_watch/highlight_*` が変わっていれば `_board_watch_highlight_refresh` が走っている監視の輪へ
即反映（`BoardWatcher.ahead_move` を当て直す。`_board_watch_ahead` が毎回 config を読むので監視の再起動は不要）。
色の差し替えは輪のビットマップを描き直して `UpdateLayeredWindow` で載せ直す（`ScreenMarker.set_color`）。

**テスト**: `tests/test_screen_marker.py`（幾何の純関数／実窓を作って「画面には見える（`IsWindowVisible`）が
自分の `ImageGrab` には写らない」、対照として除外を外すと同じ撮り方で写る／除外失敗時は出ない／close 後の
show は無視）、`tests/test_board_watch.py`（`intersection_screen_point`・`screen_point` 未校正 None・
`on_ahead` の「毎周／解消1回／mismatch で解消／未指定で不変」）、`tests/test_board_watch_prefetch.py`
（配線の静的検査: `_do_ai_move`→`_board_watch_ahead`・`BoardWatcher(on_ahead=)`・停止2経路→`_board_watch_marker_close`）。

**未検証・既知の限界**: 実対局での体感は未計測。BlueStacks を排他フルスクリーンにすると最前面窓が出ない
可能性がある（ウィンドウモードで使う）。DPI 100% 以外は既存のキャプチャ座標系にそのまま従う。

## 追記7（2026-09-01）: 明るい木目盤の BlueStacks 囲碁アプリ対応（自動フォールバック経路）

対局監視を、囲碁クエスト系（黄盤）とは別の BlueStacks 囲碁アプリ（明るい木目盤・9/13/19路）でも
使えるようにした。ウィンドウタイトルは既存と同じ「BlueStacks App Player …」なので窓の特定は不変、
変わるのは盤の認識だけ。**設定キーは追加していない**（下記の色域の相互排他で自動判別できる）。

### 実測（ユーザー提供スクショ4枚: 19路 before/after の1手差ペア・13路・9路 → tests/data/board_watch_wood*.png）

- **木地の色**: median RGB≈(227,208,159)・brightness 192-207・spread 67-69・r-b 67-69。
  `_is_yellow` は `b < 150` で不成立＝ `detect_board` が全く動かない。逆に黄盤 (247,193,62) は
  b=62・r-b=185 で `_is_bright_wood`（`b > 100` かつ `r-b < 130`）に掛からない＝**色域が相互排他**。
  「detect_board 失敗 → 木目盤」の自動ディスパッチが成立し、黄盤経路（詰碁・autoloop 含む）はビット不変
- **レイアウトはサイズで異なる**: 19路は盤領域の四辺内側に座標ラベル帯があり第1線が縁から約 1.4 セル
  （50.5px/セル36px）内側＝「縁から半セル」の規則配置前提が破れる。13路・9路は帯なしで約半セル。
  → 幾何は規則配置の割り算でなく**検出した格子線の実位置**から取る
- **格子線検出**: 盤 bbox の縁 6px（`WOOD_EDGE_PAD`）を除いた内側で「両側 6px が非暗」の細線マスク
  （PIL の point/offset/invert/multiply、`WEB_THIN_GAP` と同思想）を BOX リサイズで軸ごとに畳む。
  縁除外が無いと bbox 縁の暗帯で幻線が1本出る（実測 19路で 20 本）。4枚とも 19/19/13/9 本を正確に検出、
  間隔は等差（gap 35.9 / 57.2 / 82.2、残差 ±0.5px）。検出ピークは等差数列にフィットして欠け線を補完
  （`_wood_fit_line_progression`。合成密集盤 30/50/90% 占有で 19 本を復元、70% の1ケースは較正不可＝過渡失敗）
- **石の分類は per-channel median**（`_classify_wood_patch`）: 黒 38-42 / 白 232-241 は既存の B/W 閾値のまま、
  空点の木地に新しい受理条件（spread>=55 ∧ r-b>=40 ∧ brightness>=150）。**mean（既存 `_classify_patch` と
  同方式）だと星点の暗ドットが spread を潰して空点の星点が偽 W になる**（実測5点）。median は格子線・星点・
  直前着手マーカーの少数派画素を自然に無視する
- **直前着手マーカー（石上の輪）**: 白輪付き黒石が median でも "?"（brightness 111）になる1件が実測にある。
  "?" のときだけ小半径 `WOOD_MARKER_PATCH_RATIO`(0.08)（19路で 2px）で再判定すると輪の内側の石地色で
  確定する（0.12 では不足＝実測 brightness 93）。黒輪付き白石（13路）は通常半径の median で直接 "W"
- **時間**: フル検出 65ms 程度（detect 26-27ms ＋ 格子線 19-23ms ＋ 分類 6-17ms）。毎フレームは分類のみ
  （格子線検出は較正時と1秒ごとの盤矩形再測時だけ）＝画素不変フレームの指紋短絡（21-23ms）は完全に同経路

### 実装（feat コミット参照）

- `tsumego_capture.py` 末尾に木目盤セクションを追加（`detect_wood_board` / `detect_wood_grid` /
  `classify_wood_intersections` ほか）。**既存関数は不変**
- `board_watch.py`: `AppBoardReader._full_detect` が黄盤先勝ちで自動ディスパッチ（`_profile` = "quest"/"wood"）。
  wood は格子線位置 `_lines` をキャッシュし、分類（`_classify_frame`）と輪の座標（`screen_point` →
  新純関数 `grid_screen_point`）の両方が同じ幾何を使う。`_calibration` は (窓矩形, 盤矩形, サイズ, lines) の
  4タプルに拡張（quest は lines=None＝従来式）。盤矩形の1秒再測（`_recheck_board_rect`）は wood では
  bbox が動いたら格子線も張り替え、張り替えられなければ忘れて次周フル検出
- `__main__.py`・config.json・screen_marker.py は変更なし

### 既知の限界

- **第1線/最終線が石で完全に覆われた盤で監視を開始**すると等差フィットの基点がずれ較正できない
  （合成70%占有で1件）。対局開始時に ON にする主用途では起きない。較正失敗はバナー警告として見える
- アプリのテーマ変更・アップデートで盤色が変われば較正失敗（無症状停止にはならない）。そのときに
  `board_watch` 節へのプロファイルキー追加を再検討する
- 同一タイトルの BlueStacks 2窓は従来どおり区別できない（切り替え運用・先勝ち）

### テスト

`tests/test_board_watch_wood.py`（16件）: 実スクショ4枚の認識回帰（サイズ＋非空セルの完全一致＝星点と
輪マーカーの回帰を同時に固定）・before→after の reconcile E2E（白 G17 を move と裁定）・実スクショでの
`screen_point`（規則配置なら約 0.8 セルずれる位置に第1線が出ること）・等差フィットの純関数・
ディスパッチ単体（黄盤成功時に wood API 不使用／両方失敗は黄盤側の診断／指紋短絡／盤移動時の張り替え／
分類失敗→フル検出）。既存 `tests/test_board_watch.py`（150件）は無変更で緑。

## 追記8（2026-09-10）: AI の着手の交点へマウスカーソルを運ぶ（`screen_cursor`）

**動機**: 追記6 の輪で「どこにタップするか」は分かるようになったが、ポインタは毎手ユーザーが盤の上まで
動かす必要がある。将棋側の同種ツール（`C:/Users/iwaki/Documents/将棋` の `tools/watch/autoclick.py`）は
移動元をクリックしたあとカーソルを移動先へ「置いて」おり、その**カーソル部分だけ**を囲碁へ移した。

**クリックはしない**（`SetCursorPos` のみ）。将棋側も移動先は押していない — 押すと盤の読み違いが
そのまま手を進めてしまう。運ぶだけなら最悪でもポインタの位置がずれるだけで、対局は壊れない。
囲碁は「移動元」が無い（打つ点は1つ）ので、実装は将棋のカーソル部分と1:1に対応する。

**設計上の要点は2つ**:

1. **同じ手では1回しか運ばない**。`_board_watch_ahead` は ahead の間ずっと毎周（400ms／50ms）呼ばれる
   （窓が動いても輪が追えるように）ので、毎周運ぶとカーソルがその交点に貼り付いて動かせなくなる。
   `CursorParker` が「最後に運んだ手」だけを持ち、手が変わったときにだけ運ぶ。ahead が解消（None）
   したら忘れる＝同じ交点へもう一度打たれたらまた運ぶ。
2. **アプリが前面のときだけ運ぶ**。別のアプリで作業している最中にポインタを奪わないため。判定は
   前面窓のタイトルで、規則は `find_window_rect` と同じ（カンマ区切り候補・大小無視の部分一致）。
   **前面化（`SetForegroundWindow`）はしない**＝画面を奪わない（将棋側は「押す」ので前面化するが、
   こちらは運ぶだけなので待てばよい）。前面でなかった手番は「運んでいない」ままなので、ユーザーが
   アプリへ切り替えた次の周に運ばれる。盤矩形がまだ確定していない（`screen_point` が None）ときも同じ。

**設定**: `board_watch/move_cursor`（bool・既定 OFF）。設定画面の「AI 着手の強調表示（監視モード）」の
**行の中**にチェックボックスとして同居させる — 追記6 の実測どおり一般設定の節は行を増やすと2行ラベルが
重なる（実際に8行にして撮って再現した）。輪の色とは独立した設定なので、輪「表示しない」でも
カーソルだけ運べる。設定変更は走っている監視へ即反映（`popups.update_config` の判定を
`board_watch/highlight_` から `board_watch/` へ広げた）。

**実装**: `katrain/core/screen_cursor.py`（Kivy 非依存・`move_cursor` / `foreground_matches` / `CursorParker`）。
呼び出しは `__main__._board_watch_ahead` の1箇所で、輪と同じ `reader.screen_point(*move)` の座標を使う
（輪が使えない環境でもカーソルは動くよう、`marker is None` の早期 return をやめた）。
テストは `tests/test_screen_cursor.py`（Win32 を呼ばず `move_fn` / `foreground_fn` を注入）。

## 追記9（2026-09-11）: 終局後も監視が回り続ける問題（待ちが長いと減速・対局が5分進まなければ自動停止）

**問題**: アプリ側の投了・時間切れ・中断は KaTrain に伝わらない（§0 スコープ外「終局・整地の自動処理」）ので、
監視はホットキーで止めるまで回り続けていた。GPU は焼かない（先読み・ponder は着手ごとに数本で終わる）が、
キャプチャの CPU が残る。終局後のアプリの見え方で3通りある（本機 1920×1080・監視と同じ
`capture_screen_rect`＋盤矩形の指紋を各周期で10秒回した実測）:

| 終局後 | 判定 | 周期 | CPU（1コア比） |
|---|---|---|---|
| 盤が見えたまま・KaTrain は相手番（こちらの着手後に相手が投了・時間切れ＝最も多い） | in_sync | 50ms | **24.8%**（11.2 frames/s） |
| 結果ダイアログ等で食い違う／自分の手番で投了（ahead） | mismatch / ahead | 400ms | 5.4% |
| 盤が消えた（ロビーへ移った・最小化） | 撮影失敗→バックオフ | 2000ms | 1.2% |

1周のコストはキャプチャ（22〜28ms）がほぼ全部で、`_board_watch_state` の盤再生（`previous_app_grid`）は
19路200手でも 1.7ms。追記3 の「27ms/50ms＝約54%」は待ち時間を周期に含めない見積もりで、実際は
撮影＋50ms 待ちで1周約 77ms になる。

**やらなかったこと: アプリの終局画面の認識**。結果ダイアログやロビー画面の判定はアプリの版が上がると
静かに壊れる（自動ループ spec 追記9: 3.0.72 でヘッダが消え、固定の箱で書いた判定が全問失敗した）。
判定は時間と対局の進行だけで行う。

**対処1（減速）**: `active_slowdown_sec`（既定20）。相手の着手を待つ無音状態（active_kinds）が同じまま
20秒続いたら 50ms → idle（400ms）に落とす。最悪ケースが 24.8% → 5.4%。代償は20秒を超える長考のあとの
反映が最大 +350ms 遅れることだけ（着手が見えた周から確定待ちは `_on_move_verdict` が 50ms に戻す）。
基準は `_quiet_started`（今の無音状態に入った時刻）で、停滞警告の `_quiet_since` は使わない — 警告の
たびに打ち直すので、それを基準にすると永久に減速しない（`test_slowdown_counts_from_the_start_of_the_wait_not_from_the_last_stall_warning`）。
0 以下で従来動作。詰碁（active_kinds に ahead を含む）にも同じく効く。

**対処2（自動停止）**: `auto_stop_sec`（既定300＝5分・ユーザー指定）。**KaTrain の手数
（`WatchState.move_number`）が300秒変わらなければ**監視スレッドが自分で止まる。基準をアプリの画素・観測
グリッドにしなかったのは、結果ダイアログのアニメーションやロビー画面で観測が揺れ続けると止まらないから
（`test_app_screen_changes_alone_do_not_keep_the_watch_alive`）。撮影失敗の周も時計は進む（ロビーへ移った場合）。
止まるときは `on_status(STATUS_IDLE="bw-idle", 文面)` → `on_idle_stop()` の順に呼ぶ。`__main__` は後始末
（`_stop_board_watcher`＝輪・カーソル・先読みフラグ）を Kivy スレッドへ回す（`stop()` は join するので
監視スレッド自身からは呼べない）。張り替え・手動停止とすれ違った古い監視の後始末は identity で弾く。

- 対局: 青い帯「対局が5分間進まないため盤面監視を停止しました（ctrl+alt+d で再開）」。トグルの判断を
  純関数 `watch_toggle_action` に出し、このお知らせからは**1押しで再開**する（従来の「監視なし＋バナーあり
  ＝消すだけ」＝Finding A の経路に落とすと、2秒のデバウンスを挟んで2回押す必要があった）。再開は通常の
  開始と同じ＝盤が一致していれば取り込み直さず、アプリが次の対局に移っていればその盤を取り込む。
- 詰碁: 帯は出さない（`tsumego_watch_status` が握りつぶす）。出すと回答帳バナーを覆い、しかもホットキーの
  「再開」は対局監視を起動しようとして詰碁専用戦略で拒否され、詰碁ビューまで解除してしまう。一時メッセージ
  「白番の自動反映を停止しました」だけ出す。次のキャプチャで張り直される。

**既知の代償**: 相手が5分以上長考すると監視が止まる。再開は1押しだが、その間に相手が打っていれば盤は
「新しい局面」として取り込み直され、KaTrain 側の棋譜が分かれる。気になるなら `auto_stop_sec` を延ばす（0 で無効）。

**テスト**: `tests/test_board_watch.py` に17本（減速5・自動停止6・設定読み込み1・詰碁のバナー1・トグル4）。

**同時に直したバグ: ホットキー OFF で `board_watch_active` が戻らない**。停止経路が2系統あり、
`_stop_board_watcher`（詰碁の出題・自動停止）は `board_watch_active` / `board_watch_prefetch_replies` /
`board_watch_probe_warm` を戻すのに、ホットキー OFF（`_board_watch_trigger`）は自前で片付けて**先読み本数しか
戻していなかった**。監視を止めた後の普通の対局でも、難解のヨセの Probe 省略（enigma spec 追記7）と自ノード解析の
後回し（同 追記9）が効き続ける（電力ではなく挙動の問題）。フラグの戻しを `board_watch.clear_game_watch_flags`
（`apply_game_watch_flags` の逆・走っている応手先読みの打ち切り込み）に集め、`_stop_board_watcher` だけが呼ぶ。
ホットキー OFF と自動停止はその `_stop_board_watcher` を通す＝止め方でフラグの戻り方が変わらない。
テストは `tests/test_board_watch_prefetch.py`（`clear_game_watch_flags` の単体＋停止経路の静的検査）。

## 追記10（2026-09-11）: 連続対局（対局者アイコンから KaTrain の AI の色を読み、次の対局で監視を張り直す）

**動機**（ユーザー要望）: KaTrain の AI とアプリの AI Bot を続けて打つとき、対局ごとに KaTrain 側で手番
（どちらを AI にするか）を設定し、新規対局を作ってから `ctrl+alt+d` を押していた。アプリの対局画面は
手前（下）が自分なので、色は画面から判定できる。

**決定事項（ユーザー確認済み）**: 開始のきっかけは「連続対局で自動」。一度 ON にしたら、アプリで次の対局が
始まるたびに 色の判定・新規対局・監視の張り直し を自動で行う（1局目もホットキー1回で色を自動判定）。
止まるのは従来どおりホットキー OFF と5分放置の自動停止（追記9）だけ。設定キーは増やしていない。

**色の読み方**（`player_icon_colors` / `confirmed_near_color`）: 囲碁クエスト系の対局画面は、盤のすぐ下の左端
（手前＝自分）と盤のすぐ上の右端（相手）に、その対局者の石の色のアイコンを出す。窓は盤矩形の幅 W に対する比
（横 0.072W・盤の縁から 0.02〜0.11W）で持ち、窓の中の「明るい無彩色（白石）」「暗い無彩色（黒石）」の画素比で
読む。実スクショ3枚（`tests/data/board_watch_start_black.png` / `_start_white.png` / `board_watch_before.png`・
W=547〜551・BlueStacks の枠あり/なし）の実測は 石 0.50〜0.63・反対色 0〜0.037（背景の稲妻の筋）で、
隣のアバター画像は窓に入らない。受理は 0.3〜0.85 かつ反対色 < 0.1。**手前と相手が逆の色に読めたときだけ確定**
する（片方だけ・同じ色は None）。上限 0.85 と逆色の要求で、窓がまるごと黒い木目盤アプリ（黒 1.00）は
None＝従来どおり。`AppBoardReader` は直近フレームを保持し（アイコンは盤の外＝盤矩形の指紋とは独立に毎周
差し替え）、`quest` プロファイルのときだけ読む。

**AI の色**（`watch_player_assignment`）: 戦略は「今 AI にしている側」のものをそのまま手前の色へ移し、反対側を
人間にする（人間側の通常／指導の設定は入れ替え前に人間だった側のもの）。AI が0人・2人は従来どおり拒否
（どの戦略で打つかはユーザーの選択＝勝手に選ばない）。色が読めなければ従来どおり設定のまま。ホットキーの
開始時はログに `board_watch: 対局者アイコン 手前=B 相手=W` と `KaTrain の AI は黒（<戦略>・<根拠>）` を出す。

**次の対局の検出**（`BoardWatcher._new_game_seen`）: mismatch の周に3条件 — (1) 観測が KaTrain の盤と違う、
(2) 盤上2子以内で手番が確定する序盤形（`opening_next_player`＝`import_next_player` の確定ゾーン。対局の途中の
盤は2子以内に戻らない）、(3) 手前の色が読める — が同じ (盤, 色) で `NEW_GAME_STABLE_FRAMES`(3) 周続いたら、
`on_new_game(grid, size, color)` を1回呼んで自分は止まる。確認中は警告を出さず 50ms で回す（0.1〜0.2秒で決まる）。
アプリ AI が黒で初手をすぐ打つ場合は空盤の確認中に1子の盤へ変わるが、変わった盤で数え直すだけ。

- (1) を外すと「盤は同じで AI が応手できないだけ（分岐・終局）」の局面で、張り直しても取り込みが起きず同じ
  mismatch に戻り、張り直しが止まらない
- 自分で止まるのは、メッセージループが前の対局の AI 着手などで塞がっている間に同じ判定を何度も投げないため
  （`stop()` は join するので監視スレッドから呼べない＝追記9 の `_idle_stop` と同じ止まり方）
- フックを渡さない監視（詰碁の白番自動反映）では無効＝詰碁の盤を「次の対局」と取り違えない

**張り直し**（`__main__._do_board_watch_new_game`）: identity 判定（張り替え・手動停止とすれ違った古い監視は無視）
→ `_stop_board_watcher`（輪・カーソル・先読みフラグ）→ `_do_board_watch_start(..., near_color, force_import=True)`。
`force_import` で盤が一致していても取り込み直す＝前の対局の棋譜に次の対局を積まない（対局ログも新しく作られる）。
開始の前提チェックで拒否されたら監視は残らず、バナーの警告だけが残る（ホットキー1回で消える＝Finding A の経路）。

**誤検出の余地**: 対局の途中でアプリの盤が「2子以内」に見えるのは盤が隠れた場合くらいで、ダイアログ等は交点が
`?` になって認識失敗に落ちる（撮影失敗の周は確認の連続を切る）。そのうえ逆色のアイコンと3周の安定を要求する。
仮に発火しても、この状態は従来の実装では同期ずれの警告が出続けるだけ（mismatch は自然に解消しない＝§2.5d）で、
取り込み直しで失うものはない。KaTrain 側の打ち間違いの修正（アプリに誤タップした2手目まで）も同じ経路で再同期される。

**既知の限界**:

- 木目盤アプリ（追記7）は対局者アイコンが無い → 色は設定のまま・次の対局の自動張り直しもしない（従来どおり
  警告→ホットキー OFF/ON）
- 盤サイズ専用の戦略（難解（9路）等）は盤サイズが変わっても切り替えない（設定中の戦略をそのまま使う）
- 対局と対局の間が5分を超えると追記9 の自動停止で監視が止まる（次の対局でホットキー1回＝色判定込みで再開）
- アプリの UI 変更でアイコンの位置が変わると色が読めなくなる（None＝従来動作に倒れる。逆色の要求があるので
  無症状の誤判定にはなりにくい）。そのときは実スクショを撮り直して窓の比を直す

**テスト**: `tests/test_board_watch_new_game.py`（実スクショ3枚の色＝手前黒/白・木目盤で None・窓が画面外・
一様背景／`AppBoardReader` 経由＝指紋の速い経路でも読める・木目盤で読まない／AI の色の決定／序盤形／次の対局の
検出＝3周で1回だけ・自分で止まる・色なし/非序盤/KaTrain と同じ盤/フックなしでは発火しない・盤が変わったら
数え直し・撮影失敗で連続が切れる・盤サイズの変化／実画面の列＝前の対局→次の対局を `AppBoardReader` から
`on_new_game` まで本物で通す／`run()` が自分で抜ける／`__main__` 配線の静的検査）。

## 追記11（2026-11-06）: 輪の色を「人間にとっての局面の難しさ」で塗り分ける（明らか／普通／難解）

**動機**（ユーザー要望）: 輪（追記6）はどの手も同じ色。**どの手が人間にとって難しい局面だったかを対局中に確認したい**（学習・振り返り用）。人間なら長考するであろう局面（難解）と、他に有力候補が無く humanPolicy も圧倒的な局面（明らか）を色で分ける。**条件は「輪の表示を一切遅らせない」**＝遅くなるなら機能ごと諦める（ユーザー指定）。

**前提の実測（2026-11-06・読み取りのみ）**:
- 着手を返した時点で手元に必ずあるのは **親局面（AI が打つ前）の KataGo 通常解析だけ**（`strategy.cn` ＝ `played_node.parent`。候補手の visits・`relativePointsLost`・KataGo の policy。監視モードでも親局面はフル解析＝`_enigma_ponder_defers_own_analysis` が縮めるのは AI 自身の着手ノードだけ）。**humanPolicy は戦略が内部で取っても `generate_ai_move` が戦略オブジェクトごと捨てる**し、取らない手番も多い（一致率ひかえめの実戦 1237 判断のうち 520 で `best_hp` なし＝no_pool 232・研究外しの委譲 258 ほか。難解の admissible が空の出口はクエリ 0 本）。戦略側で回収する案は判定基準が手番ごとに混ざるので採らない。
- 輪の色は `_do_ai_move`（着手直後）と監視スレッドの毎周（`on_ahead`・50〜400ms）と設定変更の当て直しの**3か所から**付け直される（`_board_watch_ahead` は `(i, j)` しか受け取らない）。手ごとに違う答えを返すと `ScreenMarker._apply` が毎回描き直して**輪がちらつく**＝判定は手ごとに1回だけ計算して記憶する。
- 分布（既存データ）: 最善手の humanPolicy（9段・8visits）>= 0.8 は 実戦 一致率ひかえめ9路 24%・13路 26%・難解＋13路 20%、自己対局 28〜29%。次善手（visits>=10）との差 >= 1目は 13路 35%・9路 44%＋他に候補なし 11.4%（`calibration-data/selfplay/recon*/report_game_*.json` の `alt_min_loss`）。9段の期待損失 E（難解の子局面プローブの最善手の行・実戦 307 局面）は p50 0.56・p80 1.71・**>= 1.5目が 23%**・>= 2目 17%。KataGo の policy は humanPolicy の代用にはなりきらない（13路自己対局: prior >= 0.8 のうち hp >= 0.8 は 83%、hp >= 0.8 のうち prior >= 0.8 は 65%）。

**設計（案A＝humanPolicy の先回り。案B＝KataGo の解析だけ、は速度実測で負けたときの退避先）**:

1. **先回り**: 相手の手が `Game.play` に入って通常解析を発行した直後に、**その局面の humanSL（`rank_9d`・8visits・`include_policy=True`・`ownership=False`・`ignorePreRootHistory=False`）を1本**、`PRIORITY_EXTRA_AI_QUERY` で発行する（`Game._maybe_ring_hp_prefetch`）。条件は難解・一致率ひかえめ・擬態の親局面クエリ（`_probe_children(parent_hp=True)` / `_veil_parent_hp`）と同一＝それらの戦略では NN キャッシュが共有されるだけで判定の分布は変わらない（応手先読み 追記4 と同じ理屈）。結果の `humanPolicy` は**そのノードに保存**（`node.ring_human_policy`、エンジンのコールバックスレッドから1回代入＝読み手はロック不要）。AI の思考（通常解析 0.3〜1 秒＋戦略）の間に終わるので、輪を出す時点では揃っている。発火は **監視中（`board_watch_active`）× 色分け ON × 輪が「表示しない」でない × 次番が AI × リージョンなし（詰碁経路でない）** の AND。どれかが偽なら**クエリも判定も走らない＝ビット同一**。監視開始・監視中の新規対局（`apply_game_watch_flags`）と設定変更の当て直しでも現在ノードに1回撃つ（AI 黒番の初手＝root を拾うため）。
2. **判定**（`katrain/core/move_difficulty.py` の純関数 `classify_ring_difficulty`・Kivy 非依存）: 入力は親局面の解析（生 moveInfos と `candidate_moves`）・親局面の humanPolicy・AI の着手 gtp・盤サイズ。
   - **難解** `"hard"`: 9段がこの局面で打った場合の期待損失 `E = enigma9_expected_punish(enigma9_reply_table(親局面の moveInfos, 手番側), hp_of)` が `RING_HARD_MIN_E`(1.5目) 以上。**難解戦略の E と同じ関数**（基準は visits >= 10 の最善・算入は visits >= 2・1手の損失は 8目で頭打ち）。
   - **明らか** `"obvious"`: (a) AI の着手が KataGo の最善手（`candidate_moves[0]`）、(b) 9段の第一感（`enigma9_human_top`）がその手で humanPolicy >= `RING_OBVIOUS_MIN_HP`(0.8)、(c) visits >= 10 の他候補の `relativePointsLost` の最小値 >= `RING_OBVIOUS_MIN_GAP`(1.0目)、または該当する他候補が無い、の AND。**AI が意図して最善手を外した手は (a) で落ちる**＝「明らか」の色を最善でない手に付けない。
   - 優先は **難解 > 明らか**（9段の第一感が 8割でも、残り 2割が大損する局面は明らかではない）。どちらでもなければ **普通** `"normal"`。
   - humanPolicy が無い（間に合わない・humanSL 失敗・`humanlike_model` 未設定）・親局面の解析が無い・パス、は **`None`＝判定なし**。
3. **記憶と表示**: 判定は着手ノードに**最初の1回だけ**計算して記憶する（`node.ring_difficulty`。判定なしも記憶＝後から humanPolicy が届いても色を変えない＝ちらつかない）。`_board_watch_ahead(move)` は色分け ON なら `game.current_node` の着手が `move` と一致するときだけその判定で色を選び、一致しなければ設定色。`_do_ai_move` と監視スレッドのどちらが先に呼んでも同じ記憶を読む（監視スレッドは `generate_ai_move` 内の `game.play` 直後から ahead を見うる＝先に呼ばれても同じ答え）。計算は解析と保存済み humanPolicy を読むだけ（クエリの待ち合わせなし）。
4. **色**: 普通＝ドロップダウンで選んだ色（従来の `highlight_color`）、明らか＝緑（lime）、難解＝赤（red）。普通の色が緑なら明らかを水色（cyan）に、赤なら難解をマゼンタに自動で替える（純関数 `difficulty_ring_colors`）。緑・赤・水色・マゼンタは黄盤・木目盤のどちらでも見える組（橙は黄盤で、白は白石と木目盤で弱い）。
5. **ログ**: 着手ごとに1行（OUTPUT_INFO＝対局ログに残る）。例 `盤面監視: 難易度 明らか（9段の第一感 R10 92%・次善 -2.1目）` / `難易度 難解（9段の期待損失 1.8目）` / `難易度 判定なし（humanPolicy が間に合わず）`。閾値の見直しと対局中の確認に使う。

**設定**: `board_watch.highlight_difficulty`（bool・既定 `false`）。パッケージ `katrain/config.json` とローカル `C:\Users\iwaki\.katrain\config.json` の両方に追加（ローカルは KaTrain を終了した状態でメインセッションから直接編集）。設定画面は**一般設定の輪の色の行に「難易度で色分け」のチェックを1つ足す**（行は増やさない＝一般設定欄は 7 行で一度重なった経緯がある・§16）。閾値 1.5 / 0.8 / 1.0 はコード定数（GUI に出さない。ログで見直す）。

**速度の検証（採用ゲート）**: 実戦 SGF（9路・13路の main line）の局面で、「相手の手を `Game.play` に入れてから `generate_ai_move` が返るまで」を **色分け ON/OFF の別プロセス・ABBA** で測る（プローブ `calibration-data/board-watch/ring_difficulty_latency_probe.py`。戦略はユーザー設定の一致率ひかえめ9路／難解＋13路）。**差が run 間ノイズを超えたら案B（判定から humanPolicy を外し KataGo の policy で代用）へ切り替える**。同時に「輪を出す時点で humanPolicy が揃っていた割合」を数える（95% 未満なら先回りの発火位置を見直す）。KataGo を使うので**ユーザーが対局していない時間に**走らせる（実戦と GPU を取り合わない）。

**テスト**: 判定の純関数（難解・明らか・普通・判定なし・優先順・最善手を外した手）、色の衝突回避、ちらつき防止（同じ手に対し `_board_watch_ahead` を3経路から呼んでも `set_color` が同じ色）、先回りの発火条件（監視中×ON×次番 AI のときだけ・OFF でクエリ0本）、静的テスト（`tests/test_board_watch_prefetch.py` の kv・i18n・`_board_watch_ahead` の `"highlight_color"` リテラル）。

**既知の限界**: humanPolicy は別プロセス間で ±0.05〜0.09 揺れるので、閾値近くの局面は対局ごとに明らか／普通が入れ替わりうる（判定は手ごとに1回なので同じ手の中では揺れない）。E は親局面の候補手の探索の深さに依存する（浅い候補の損失は小さめ＝E は保守的に出る）。人間の実際の考慮時間との対応は未測定（記録が無い）。

**実測（2026-11-06・速度ゲート）**: 相手の手から親局面の解析完了までの時間の比（先回り ON/OFF・別プロセス ABBA・局面ごとの対）は 9路 1.009（95% 区間 0.990〜1.030）・13路 1.014（1.000〜1.0301＝事前に決めた上限 1.03 を 0.0001 超過）。humanPolicy は 134/134 局面で解析の完了より前に届いた。平均の遅れ約 0.02 秒（13路の解析 1.65 秒に対して）をユーザーが「体感できない」として許容し、**案A（先回り）を採用**（案B への切り替えは行わない）。判定の分布（最善手を打った場合・humanPolicy）: 9路 明らか 16%・難解 31%、13路 明らか 18%・難解 21%（KataGo の policy で代用すると 13路の明らかは 11%）。記録は `calibration-data/board-watch/ring-difficulty-latency-results-20261106.md`。設定画面は輪の色の行に3つ並べると「カーソル」が折れたので、この欄の右列だけ幅を広げた（`popups.kv` の MDBoxLayout `size_hint_x: 1.3`）。
## 追記12（2026-11-14）: 野狐囲碁（PC 版・淡い黄の盤）対応

対局監視を野狐囲碁の PC クライアント（`foxwq.exe`・BlueStacks ではない）でも使えるようにした。使い方は従来と
同じ片方向（相手の手を取り込み、KaTrain の AI がもう片方を打つ）。**観戦（黒白とも画面から来る）は対象外**。

### 実測（ユーザー提供の盤の切り抜き4枚 → tests/data/board_watch_fox19_*.png・19路・セル 37px）

- **盤の色は黄盤と木目盤の両方の色域に入る**: 木地 RGB≈(247,217,138)（b=138 < 150 で `_is_yellow`、
  b > 100・r−b=109 < 130 で `_is_bright_wood`）。追記7 の「色域は相互排他」は囲碁クエストと木目盤アプリの間の話で、
  野狐はその中間にいる。`detect_board` が通るので従来は黄盤経路（規則配置＋平均色）で読みに行き、
  4枚中1枚は直前手の三角印つきの黒石が平均 (98,98,98) で「判定できない交点」、通った1枚は四角カーソルを石と読む。
  しかも通った周は `_profile == "quest"` になり、囲碁クエスト用の対局者アイコン読み（追記10）が野狐の画面に対して動く
- **判別**: `detect_board` の盤矩形を 64×64 に縮め、黄色い画素のうち木目盤の色域にも入る割合を見る
  （`is_pale_wood_board`・閾値 0.5）。実測は野狐 0.94、囲碁クエスト系 8 枚 0.00〜0.02。淡い黄の盤は**必ず**
  格子線検出の経路（プロファイル "wood"）で読み、格子線が取れない周は失敗させる（黄盤経路へ戻さない＝経路が
  フレームごとに入れ替わらない）。囲碁クエストの盤では木目盤経路の関数に触れないという既存の保証は不変
- **空点の四角カーソル**（マウス位置に出る・次の手番の色・一辺 18px＝約 0.49 セル）: 中心パッチ（半径 0.25 セル）が
  丸ごと四角の中に入るので "B"/"W" と確定してしまい、"?" の再判定（追記7）には掛からない。**カーソルを AI の
  着手点へ運ぶ設定（追記8）ではちょうどその点に AI の色の四角が出る**ので、石と読むと reconcile が「もうタップした」と
  誤読する。石と読んだ交点は斜め4方向へ 0.3 セルずらした点（中心から 0.42 セル＝石の内側・四角の外側）を見て、
  4点中3点以上が揃った色（木地なら空点・石の色ならその石）を採る（`_wood_diagonal_verdict`・`WOOD_STONE_CHECK_RATIO`。空点と読んだ交点には掛けない）。斜めなのは格子線を踏まないため。
  実測（野狐4枚＋木目盤4枚の全 162 石）: ずらし 0.26〜0.32 で本物の石は木地 0/4・四角は 4/4、0.35 から石の縁が混じる。
  木目盤アプリ（追記7）にも同じ検算が掛かるが、実スクショ4枚の認識は不変
- **直前手の印**（石の右下の三角）と**残り秒数**（直前手の石の上の数字。少し経つと出る）: 中心パッチの median が
  石の地色のままなので石と読める（三角 2 枚・白石の上の「1」2 枚で確認）。**2 桁の秒数は実物が無いので合成で確かめた**（太字 16〜22px・黒石に白字／白石に黒字）: 中心パッチだけだと「30」「60」が "?"、黒石の上の白い 2 桁は "W" に化ける。数字は石の縁まで届かないので、上と同じ斜め4点の多数決で石の地色に戻る（合成 15 通りすべて一致）
- **窓**: タイトルは「> [高級対局室1] > 45906号対局室　観戦中 [60手目] - レーティング」の形で手数ごとに変わり、
  「野狐」を含まない。`board_watch.window_title` を `"BlueStacks,Puzzle Run,PlayGo,対局室"` にした（空のときに使われていた
  詰碁側の候補をそのまま前に残した＝先に書いた候補が優先で、BlueStacks が開いていれば従来どおりそちら）。`tsumego_capture.window_title` は変えていない＝詰碁キャプチャは対象外
- **config.json には日本語を生で書かない**（JSON のエスケープで書く）: Kivy の `JsonStore` は encoding を指定せずに開くので、日本語 Windows では cp932 で読み、UTF-8 の生の「対局室」は化けたまま保存し直される（実測: 初版はこれで「ウィンドウが見つかりません」）。エスケープなら読みも書き戻し（`json.dump` の既定）も ASCII のまま
- 窓全体（1180×901・盤は左側 704×708）での盤矩形・19 本の格子線・輪の座標は、暗く写った1枚を 2.5 倍に明るくした
  画像でしか確かめていない（フル検出 73ms）

### 未確認（実機で要確認）

- **自分の対局中の窓タイトル**に「対局室」が含まれるか（確認できたのは観戦中だけ）
- 暗くない窓全体のスクショでの盤矩形（右側の対局者写真・チャット欄の色が行列ヒストグラムを乱さないか）
- **2 桁の残り秒数**・黒石の上の秒数の実物（サンプルは白石の上の「1」だけ。合成では読める）
- 自分の色の読み取りは追記13

### テスト

`tests/test_board_watch_fox.py`（29件。自分の色は追記13）: 判別（野狐 4 枚は淡い・黄盤 8 枚は淡くない）／実スクショ4枚の石の並びの
完全一致／合成した四角カーソル（黒・白 × 隅・辺・星・天元）を石にしない／`AppBoardReader` 経由でプロファイル "wood"・
輪の座標が格子線位置／囲碁クエストの盤は quest のまま／格子線が取れない周は黄盤経路へ戻さない／合成した残り秒数（1〜2 桁 × 3 サイズ）で石の色が変わらない／0.6〜1.7 倍に拡縮しても同じ並び（セル 22〜63px）。
## 追記13（2026-11-14）: 野狐囲碁で自分の色を読む（ユーザー一覧のピン）

**動機**: 追記12 の時点では野狐の AI の色は KaTrain の設定どおりで、相手（AI ボット）側の色が KaTrain でも AI に
なっていた（ユーザー報告）。対局開始時に自分の色を読み、KaTrain の AI をその色へ移す。

**どこから読むか**（ユーザー提供の対局中の窓全体2枚 → tests/data/board_watch_fox_game_white*.png）:
- 対局者パネル（写真の下の「名前 段 ○ VS ● 段 名前」）は**使えない**: 左右は色で決まっていて（観戦でも自分の
  対局でも左が白）、どちらが自分かを表さない。盤の四角カーソルの色もマウスが盤の外なら出ない
- **ユーザー一覧の自分の行**だけに赤いピンが付き、「名前・石アイコン・ピン」と並ぶ（相手の行にピンは無い。
  観戦中の自分の行は石アイコンが無くピンだけ）。ピンの左隣の石アイコンの色が自分の色

**実装**（`board_watch.fox_self_color`）: 盤の右端より右で赤い画素（r>170・g,b<110）のかたまりを拾い、外接矩形
9〜13px 四方・35〜70 画素（実測 11×11・50 画素）で、輪の中が一覧の地の色（明るい無彩色）のものをピン候補にする。
その左 4px から 14px 四方の箱が、暗い画素 60 以上なら黒石、灰色の縁（170〜205）12 以上＋明るい面 100 以上＋暗い
画素 0 なら白石。石つきのピンがちょうど1つのときだけ確定する。寸法は画素の絶対値（一覧の文字とアイコンは窓の
大きさで拡縮しない＝幅 1181 と 1171 の2枚で同寸）。`AppBoardReader.player_icon_colors` は淡い黄の盤（`_pale`）の
とき (自分, 逆の色) の形で返すので、開始時の色の入れ替え（`watch_player_assignment`）も、次の対局の自動張り直し
（追記10）も黄盤と同じ経路で動く。所要 23〜25ms（開始時と、序盤形で盤が食い違った周だけ）。

**実測**: 自分が白の対局中2枚 → W／観戦中（実機の窓・暗い1枚を明るくした画像）→ None。窓全体の盤の認識も
この2枚で一致（3手目・11手目。白い四角カーソルは石にならない・直前手の印つきの黒石は黒）。

**未確認**: **自分が黒の対局**（黒の石アイコンは相手の行のものを見ただけで、テストは合成）。Windows の表示倍率が
違う環境（アイコンの寸法が変わる）。ユーザー一覧をスクロール・並べ替えして自分の行が見えないときは None＝設定どおり。
## 追記14（2026-11-14）: 野狐囲碁の取り込み時の手番（直前手の印から読む）

**症状**（ユーザー報告）: 対局の途中（黒 8・白 7）で監視を ON にすると、次は白番（自分＝KaTrain の AI）なのに
黒番で取り込まれ、AI が動かない。`import_next_player` は 3 子以上の盤を「人間側に固定」する（石数のパリティは
取りで崩れるので、誤った色で AI が打ち出さない側に倒す＝§3.2）。追記13 で AI の色が自分の色へ移るようになった
結果、「人間側」は常に相手の色になり、自分の手番で ON にすると必ず外れる。

**修正**: 野狐の盤は直前手の石に印（三角。少し経つと残り秒数）が付く＝最後に打った色が分かる。黒石の印は白、
白石の印は黒で描かれるので、石の内側（半径 0.3 セルの円）に「逆の明るさ」の画素が 5% 以上ある石を印つきとし、
**ちょうど1つ**のときだけその色を直前手とする（`tsumego_capture.wood_last_move_color` →
`AppBoardReader.last_mover_color`・淡い黄の盤だけ）。`import_next_player(grid, human_color, last_mover)` は
2 子以内の確定の次にこれを見て、逆の色を手番にする（根拠「直前手の印から確定」）。読めなければ従来どおり。
実測（7 枚）: 印つきの石の割合 0.16〜0.86、ほかの石は全部 0.000。

**未確認**: 黒石の上の残り秒数の実物（白い数字のはず＝同じ規則で拾える見込み）。相手のパスの直後は印が
自分の石に残るので、手番を相手と読む（パスは監視の対象外＝§0）。

**別件（同じ報告のスクショ）**: バナー「盤面の形が不正です（検出領域 1168x708）」は、盤の検出が窓のほぼ全幅を
黄色と読んだ周。原因は未確定（その周の画像が残っていない）。KaTrain 自身の盤（木目のテーマ）は `_is_yellow` に
入る（窓の 27%）ので、KaTrain の窓が野狐の窓の上に重なると起きうる。撮影は画面の矩形なので、重なった部分は
手前の窓が写る。

**囲碁クエスト（黄盤）にも同じ修正を入れた**（同日・ユーザーの確認を受けて）: 追記10 で AI の色が手前の色へ移るので、
途中から ON にしたときの症状は野狐と同じ。囲碁クエストの直前手の印は石の中心の**赤い四角**＝石の中心から半径
0.2 セルの円の赤い画素（r>180・g<100・b<120）の割合が 0.1 以上の石（`tsumego_capture.quest_last_move_color`）。
実測（対局画面 4 枚）: 印つき 0.35〜0.38・ほかの石 0.000。詰碁アプリの画面 4 枚（印なし）は None。
**木目盤アプリ（追記7）も同じ**: 印は石の上の輪で、野狐と同じ「石と逆の明るさ」の検出器がそのまま拾う（実スクショ 4 枚で印つき 0.09〜0.24・ほかの石 0.000。19路 before→after の1手差ペアで 黒→白 と入れ替わる）＝`last_mover_color` は対応する盤すべてで読む。ただし木目盤アプリは自分の色を読まない（AI の色は設定どおり）。**どのアプリも実機の通しは未確認**。

## 追記15（2026-11-19）: 複数の候補を輪＋字で出す・表示した候補をアプリで打ったら差し替える

ユーザー要望: 輪が KaTrain の決定手しか出ない。難解＋の決定手（罠かどうかも）・一番人間らしい手・第一感・KataGo の
最善手を並べて見たい。色分けは覚えるのが大変なので字で示す。着手箇所が重なる場合の見え方も決めたい。

### 表示（設定 `board_watch.highlight_candidates`・設定画面の輪の行の「候補」チェック・既定 OFF）

- 1 交点＝1 窓（`screen_marker.MarkerSet`・最大 4 窓）。決定手は従来どおり太い輪、ほかの候補は細い輪
  （`RING_THIN_THICKNESS_RATIO` 0.07）。字は**輪の内側**に白＋黒い縁取りで描く（`mark_bgra`）。
- 字の意味（判定は `katrain/core/move_candidates.py`）:

  | 字 | 意味 | 判定 |
  |---|---|---|
  | 最 | KataGo の最善手 | 親局面の通常解析の先頭（`candidate_moves[0]`） |
  | 感 | 第一感 | humanSL 9段の humanPolicy が最大の盤上の手（悪手でもそのまま。パスが最大なら無し） |
  | 人 | 一番人間らしい手 | 悪手でない手の中で humanPolicy 最大。第一感の損失が `candidates_max_loss`（2.0 目）以下なら第一感そのもの＝**字は出さない**（感がその意味を兼ねる）。第一感が悪手（損失が上限超）か KataGo が読んでいない手のときだけ、最善手か visits >= 10 で損失が上限以下の手の中の humanPolicy 最大を別の点に出す |
  | 全 | 最善手＝第一感 | 3 つとも同じ点（明らかな一手） |
  | 罠 | 決定手が罠 | 難解 / 難解＋の賭け罠・捨て身の罠・劣勢演出の罠、または通常の外しで E − 最善手の E >= 0.5（`TRAP_MIN_DELTA_E`）。擬態の罠・一致率ひかえめの罠の層も同じ |

- 同じ点の役割は 1 つの輪にまとめる（字は 罠 → 最／全 → 人 → 感 の順）。上の規則で 1 点の字は最大 2 字
  （罠＋感、最＋人 など）、輪は最大 4 つ。
- 材料は難易度の色分け（追記11）と同じ＝親局面の通常解析＋先回りの humanSL 9段（`Game._maybe_ring_hp_prefetch`。
  候補の表示だけが ON でも撃つ＝`apply_game_watch_flags`）。追加の待ち時間は無い。humanPolicy がまだ届いていない
  周は「最」だけ出し、届いた周から全部出る。届いた後の役割は着手ノードに 1 回だけ記憶する（`ring_roles_of`）。
- **罠かどうかは記憶しない**: 着手ノードは `game.play` の中で現局面になり、戦略の記録（`node.ai_decision`）が付くのは
  その後（`generate_ai_move`）。すき間で監視スレッドが先に計算すると「罠でない」が固定される。毎回ノードから読む。
- 戦略側の記録は `Enigma9Strategy.ring_decision`（kind best / deviate / gamble / overdraft / underdog と trap）。
  **`last_decision_info` には書かない**＝自己対局ハーネス（`_decision_metrics`）と batch_eval は `last_decision_info` を
  持つ戦略を「判定情報あり」として集計するので、難解に生やすと集計が変わる。記録だけで採用判断はビット同一。
- 第一感が悪手かどうかの判定に visits の下限は掛けない。通常解析は visits を数手に集中させる（13路の実局面で 98 候補中
  visits >= 10 は 7 手）ので、掛けると第一感が浅くしか読まれていないだけの手番で「人」が別の点へ飛び、「第一感は悪手」と
  読めてしまう（最初の実装がこれ）。浅い候補の損失は打つ側に楽観的なので、「損失 > 上限」は visits によらず悪手と言える。
  人が感と分かれる頻度は実戦では未計測。
- 候補は AI の最終手にだけ出す（KaTrain の盤で直接打った人間側の手には出さない）。ほかの候補の輪は難易度で
  塗り分けず設定色のまま。

### 見え方を決めた経緯

- 将棋の `tools/watch/marker.py` は輪の右上／左上にバッジを出す。囲碁でそのまま使うと、候補が隣の交点に並んだとき
  バッジ同士が重なる（モックで「罠」が隣の「最」に隠れた）。囲碁の候補点は必ず空点なので、字を輪の内側に置けば
  隣とは決して重ならない。ユーザーが B 案（輪の内側）を選択。
- 字を輪の色で塗る最初の実装は、2 字のとき輪の線に掛かった部分が同じ色に沈んだ（難易度の赤い輪の上の「罠感」）。
  白＋黒い縁取りに変更＝盤・輪のどの色の上でも読める（実寸の描画 `calibration-data/board-watch/candidate-marks-20261119.png`
  ＝上から 56px〈13路相当〉・38px〈19路相当〉・30px）。
- 設定画面の輪の行は 4 つ目のコントロールでラベルが 2 行に折れた（別プロファイルで起動して撮影）ので、この行だけ
  チェックボックスとラベルを小さくし右列の幅を広げた（`popups.kv`）。

### 差し替え（設定 `board_watch.candidate_swap`・既定 ON・候補の表示が ON のときだけ）

監視は「KaTrain が決定手を自分の盤に打ち済み」の前提なので、アプリで別の点に打つと従来は
「盤面の差が1手で説明できません」で止まった。表示した候補のどれかをアプリで打ったら、KaTrain の最終手をその手に
差し替えて続行する（ユーザーの選択 2026-11-19）。

- 判定は `reconcile` の新しい verdict `swap`（純関数 `swap_candidate`）。`WatchState.swap_moves`（差し替えを受け付ける
  交点）が空なら判定しない＝**既定では従来とビット同一**。観戦の `spectate_sync`・詰碁の影グリッドは無関係。
- 「1 手前の盤＋候補手」に加えて「1 手前＋候補手＋相手の 1 手」も同じ候補手の差し替えとみなす。対局監視の ahead は
  400ms 周期×確定 2 周なので、早碁では差し替えの確定前に相手の石が載る（これを拾わないと KaTrain の状態が永久に
  変わらず mismatch のまま）。差し替えた後の周で、相手の石は通常の `move` 判定が拾う。
- 監視は swap を見た周から低遅延周期（50ms）に上げ、`stable_frames` 周そろったら `on_swap` を 1 回呼ぶ。反映待ちは
  手数では見られない（差し替えは手数が変わらない）ので、KaTrain の最終手が差し替え先になったら反映済み
  （`_resolve_swap`）。`inject_timeout_ms` で反映されなければ警告して同じ局面では投げ直さない。
- KaTrain 側は `_do_board_watch_swap` → `Game.replace_last_move`: 最終手のノードを**親から外して**打ち直す
  （分岐として残すと `children[0]` を辿る集計・保存が打たれなかった手の側へ進む）。置き換える手の応手を温めている
  難解の先読みは同じ色の着手でも止める（`_stop_enigma_ponder`）。非合法なら元の局面に戻して警告。
  実行時に「最終手が監視の見た手のまま・その色・手数・先が無い」を確かめ直す（`_do_board_watch_play` と同じ作法）。
- 差し替えた手のノードには、元の決定手と残りの候補を引き継ぐ（`watch_swap_carry`）＝アプリの仮置きや読み違いで
  差し替えても、同じ規則で元の手へ戻せる。
- 受け付けるのは**表示した候補だけ**。候補以外の点は従来どおり警告（色の割り当てが逆のまま黙って追従し続ける、を
  避ける）。輪が出ていない間（輪「表示しない」・候補 OFF）は差し替えも起きない。

### 既知の限界

- 差し替えた手は戦略が選んだ手ではない。難解の先読みは止まり、一致率ひかえめの ledger（`game._veil_state`）には
  打たれなかった決定手の記録が残る（対局中の判断のうち、失着・forced の 1 局あたりの回数だけがこれを数える）。
- 相手の応手が差し替えた石を取った盤（「1 手前＋候補手＋相手の 1 手」で候補手の石が消える）は判定できず mismatch。
- 差し替えた後にアプリの盤が 1 手前へ戻った場合（仮置きの取り消しなど）、太い輪は差し替えた手に出て、元の決定手の輪は
  出ない（元の決定手へ打てば差し替え直しはされる）。
- 実機（BlueStacks・野狐）での確認は未実施（仮置きの石がどう認識されるかを含む）。確認したのは、純関数・監視の 1 周・
  `replace_last_move`・窓の生成のテストと、別プロファイルで起動した KaTrain に `board-watch-swap` を流す通し
  （AI の Q3 を K10 に差し替え → 木から Q3 が外れ、盤・棋譜ツリーの更新で例外なし → 続けて打つと AI が応手）。

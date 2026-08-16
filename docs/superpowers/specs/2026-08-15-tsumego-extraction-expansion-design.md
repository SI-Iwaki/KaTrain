# 抽出器拡張（開いた盤の閉包）— 設計スペック: 枠あり基板でのソルバ採用

> **改訂 2026-08-15（4レンズ反証レビュー後）— 先に読むこと。** 本文 §1〜§8 は初稿で、下の
> §0 がレビューで覆った点と改訂後の判断。要約: **設計（枠あり基板）は仮想壁より正しいが、
> 期待値は初稿の +8 手順ではなく −4〜+4 手順（run 間ノイズの内側）**。実効母数は 49 問→**33 手順**、
> 現状正解率は 57% ではなく **67%**、5 秒予算での root TIMEOUT **17/49**、解けた 32 問の初手一致 22。
> しかも対象の不一致は verify 分類で **alternative 7 / undecided 7 / true_miss 0**＝ソルバが
> 「正すべき検証済み誤答」は 0 件。加えて枠あり基板固有の欠陥が 1 つ実在する（§0.2 壁の呼吸点）。
> **本件を「+19 手順の伸びしろ」として投資する前提は成立しない**。実装するなら §0.4 の縮小版。

## 0. レビュー後の改訂（結論の差し替え）

### 0.1 期待値の訂正（measurement #1/#2・risk #2・自分で追試）

| 初稿の前提 | 実測 |
|---|---|
| 母数 49 問 | ベースライン `20260815b` に載るのは **40 手順**（9 キーは記録手順が 1〜3 手で `--min-line 5` の外）。うち **7 手順は今日 frameless**（`_choose_tsumego_frame` が枠を捨てた盤・全部 DEFEND）＝§4.1 の規則では新経路に入らない → **33 手順** |
| 現状 57%（枠経路平均） | 対象 33 手順の現状 **22/33 = 66.7%**（40 なら 26/40。小さく閉じる問題ほど枠経路も得意＝選択効果） |
| ソルバ 73% | 別母集団（生盤で閉じる 111 手順）の line-match。**枠あり基板 49 問を本番予算 5000ms・cold で直接 solve**（レビュー実測 2 系統・KataGo ヒント無し）: **TIMEOUT 17〜18/49**（空点 10〜12 帯 55%・≤9 帯 1/18）、解けた 31〜32 問で回答帳初手＝root_moves[0] **22**、root_moves 内 29〜30、同格タイ 14/32、クラス KO 25〜27 / UNCOND 4〜5 / SEKI 1 |
| 差 = 正答の伸びしろ | line-match と正答は別物。verify（`answer-book-verify-20260815b.jsonl`）の **true_miss は枠 4/385=1.0% ／ ソルバ 1/111=0.9% で同率**。対象 33 手順の不一致 11 は **alternative 7（別解＝chosen も成立）／ undecided 4（枠なし分を足すと 7）／ true_miss 0**。別解の並びは df-pn でも KataGo 本命順（§6.5.1-3）で決めるので構造的優位は無い |
| 期待値 +8 | ベースラインと solve 結果の join: **回復候補 4 / 破損候補 4 / 不変 16**（TIMEOUT 16/33 は今日の答え）→ **−4〜+4**。538 手順の run 間シャッフル ±5%（≈±27）の内側 |

**含意**: 「ソルバに乗る問題を増やす」ことは、この母集団では正答も line-match もほぼ動かさない。
動くとすれば (a) 枠が捨てられた 7 手順（ソルバは 7/7 が単一初手＝回答帳一致・うち 3 は今日不一致）、
(b) undecided 4 手順、の範囲。回答帳なし line-match の残る伸びしろは **alternative 126 / undecided 87**
（全経路）＝**「別解の中からアプリの作意手を選ぶ」問題**であって「閉包を広げる」問題ではない（§0.5）。

### 0.2 枠あり基板固有の欠陥（risk #1・自分で追試＝再現）

**Problem 盤（fill 込み）で、region に隣接する壁連の呼吸点が region 内にしか残らない盤がある**
（`scratchpad/wall_libs_probe.py`: 49 問中 **ko_p=False 1 / ko_p=True 4**＝3dee3cdd2d 黒 70 子・呼吸点 3、
2b553dec0b 74 子・呼吸点 1 など。現行ソルバ経路 134 問は 0）。ソルバの壁は「region 外に空の呼吸点が
1 つでも残る」ことでしか不可侵にならない（§2.3）ので、その壁は守り方が region 内の呼吸点を詰めれば
**取れる**＝case AA「取れる連を壁にする」の別経路での再発。実測: 3dee3cdd2d は SEKI [C1,E2]→壁に外側
呼吸点を 1 つ与えると KO [C1]（クラスと同格集合が変わる）／124de7898f は ko_p=False KO [A8,B9]（回答帳
初手 A8）・ko_p=True **SEKI [B9]**（誤答。KO 答えは cross-check の対抗馬成立要件を満たせず却下不能）／
2b553dec0b は ko_p=True FAILED 0.2s（hopeless→枠経路＝無害だが採否がコウダテ形で反転）。原因は
「孤立リング（外側が反対色の代償地）」の内側の帯を閉包 fill が全部埋めること。**「ko_p は抽出に無関係」も偽**
（Problem.black/white は fill 込み全石なので変種で解く問題が変わる）。§1 表の「新規リスク面: 枠経路が既に
持つもののみ」は撤回。**対策**: 静的ゲート `frame_walls_immortal(problem)`（region 隣接の region 外連は
Problem 盤で region 外呼吸点 ≥1）を採用条件に加える（満たさない盤は今日の枠経路のまま）。fill を 1 点だけ
空ける案は空けた点が region 石の永久呼吸点になりうるので採らない。

### 0.3 その他の反証で直す点

- **役割整合検査（§4.2）は検出力なし**（extractor #2・measurement #4・risk #5。session-flow のみ「110/113
  を捕まえる」と出たが他 3 レンズと数値が合わず、少なくとも「型は壁色に追従する」の指摘は正しい）。
  at_risk は「同色の壁/fill に到達できない連」なので型は壁色からほぼ恒等に決まる＝49/49 整合は検査が
  効いている証拠ではない。役割反転を実際に落としているのは規模ゲート（反転で 0/592・2 系統で追試）・
  hopeless・cross-check・役割ホットキー。検査はコスト 0 のアサーションとして残してよいが期待値は書かない。
- **守り方（白）の帯着手で再抽出が同じ閉包にならない**（3 レンズ一致）: ATTACK 33 問で枠内の帯（fill 点／穴）
  に白 1 子を置いて hint 付き再抽出すると 1224 点中 same 0・region 拡大 1139（gates 超過 1160/1167・
  平均 +16.5 点）・open_rect 28。DEFEND 16 問は 606/635 が same。セッションは再抽出後にゲートを課さず
  5 秒 solve → ほぼ TIMEOUT → `_gave_up`（次の帯着手で `_gave_up=False` に戻りまた 5 秒）。記録手順の
  白手で region 外は 4/49 手順（3 は再 solve で MATCH・bfeaacb707 は region 19→43 で TIMEOUT）。
  コウダテを探す白は帯に打つのが自然なので実戦では多い。**対策**: 枠あり基板のセッションは
  (a) 再抽出直後に `solver_capture_within_gates` を掛け超過なら即 FALLBACK、(b) 再抽出にも
  `allow_open_rect=False` を渡す（session に持たせる）、(c) 再抽出結果が同一（region/target 不変）なら
  kernel と `_gave_up` を保持する。既存ソルバ経路はフラグで従来どおり。
- **センサスが `problem_is_hopeless` を写していない**（measurement #3）: 生盤抽出がゲート通過→hopeless で
  却下された盤（538 中 9 手順）は今日枠経路に落ち、★はその枠あり盤にも掛かる（3 手順で gates 通過＝
  region 10〜22 点の小問題）。生盤側で「別物」と証明済みの盤なので **★は「生盤抽出が hopeless で
  却下された盤では発火しない」** とする。
- **初手コスト**（measurement #7・risk #3/#4）: hopeless は FAILED でない限り予算 1 秒を使い切り（49/49）、
  presolve は `_lock` を握るので初手 generate は最大 5 秒待つ。しかも 5000ms 予算では第 2 段階（opt）が
  **毎回 3 秒を燃やして成果ゼロ**（`OPT_TIME_MIN_MS`=3000、`solver_opt_skip_after_ms`=5000 は予算 5000
  では構造的に発火しない＝30000→5000 変更で無意味化した組合せ。E2E 枠ありケースで opt 有/無: D 5.0/3.3s・
  E 3.7/0.8s・K 3.3/0.3s・O 3.6/0.6s・V 3.2/0.2s、いずれも plies=0）。**これは現行ソルバ経路にも効く独立の
  改善候補**（§0.6）。フォールバック時は subtype が ai:tsumego_solver のままなので段階 3 の前倒し投機が
  発火せず今日の枠経路より 0.3〜0.8 秒/手遅い（game.py:761-765）。
- **リプレイの GUI 乖離**（extractor #4・measurement #5）: `answer_book_replay.py` は判断ごとに session を
  作り直し `_gave_up` を持ち越さない（持ち越すのは cross-check 却下だけ）＝TIMEOUT 問題で GUI と別経路。
  `--keys` は 40 桁完全一致・`--repeats` は argparse に無い・`--min-line 5` で 9 キーが落ちる・
  `--route` に solver_frame が無い・永続キャッシュが run2 以降に効く（独立標本にならない）。**A/B の前に
  ハーネス改修が必要**（§0.4）。
- **機構の記述訂正**: 壁リングは候補には入る（除外は pass-alive と hint のみ）。外側フィルと連なるリング
  （317/409）は hint 外＝無条件壁、孤立リング（92）は壁判定を通らず単色帯の fill 境界として数えられる
  だけ。「outside libs<3 で吸収」は 0/385。／「P1 スイートは同じ経路」は抽出 API と hint 形式の回帰に
  限る（E2E CASES で枠あり＋閉包＋gates 内は 10、P1 は既定 300 秒予算で 5 秒予算の挙動は見ていない）。／
  cross-check は現行ソルバ経路でも `problem_type` から役割を得ており、枠あり基板が強いのはフォールバック
  ai:tsumego 側の役割依存機構だけ。／9 路の回答帳 2 問は枠が退化して★は no-op。／presolve スレッドは
  `_apply_tsumego_region` より前に起動されるため `build_session_from_game` が ROI=None を読む run では
  hint が閉包 bbox に落ちる（既存経路にもある競合。ROI 設定後に起動する）。／初稿 §2.2 の 2 件
  （0bf0d74992: app C4 vs UNCOND [B1,C2]、2f4172f211: app C1=KO ko1 vs KO ko0 [A3]）は「fill 由来の
  別問題」か「本物の別解」か KataGo で切り分けが要る。

### 0.4 改訂後の Phase 1（縮小版・実装するなら）

採用判断を **キャプチャ時に実際に solve して決める**（TIMEOUT 帯 35% を初手で 5 秒待たせない）:

```
枠候補（両変種・KataGo 抜き）→ 変種で framed extraction（allow_open_rect=False）→ gates 23/12
  → frame_walls_immortal → 生盤 hopeless 却下盤は除外 → solve（予算 solver_time_limit_ms）
  → 非 FAILED で解けた: 枠を採用（KataGo の枠採否判定は省略可＝df-pn の LIVE/KILL 証明が
     frame_destroys_problem より強い証拠。枠が捨てられていた 7 手順の回収経路）→ solver_frame
  → FAILED / TIMEOUT / ゲート外: 今日の枠経路（KataGo 採否判定 → ai:tsumego）
```
- 上記に §0.3 の再抽出ゲート・allow_open_rect 貫通・kernel/gave_up 保持・ROI 先行を含める。
- **判定則**（A/B）: 主指標＝両アームの不一致を `answer_book_verify.py` で分類した **true_miss/undecided の
  増減**、副指標＝line-match。採否は「破損ゼロ」（followup §5.2 と同じ）。標的 33（＋frameless 7）手順×
  両アーム 3 起動・cold（`--no-solver-cache`）・行ごと多数決。フル run は correct 数でなく **非対象行の
  route がベースラインと同一・error 0** で合否。
- 期待値: 回復 ≤4（＋枠棄却 7 手順の一部）／破損 ≤4。**+8 を根拠にした投資判断はしない**。

### 0.5 本当の伸びしろへの手掛かり（別プロジェクト候補）

回答帳なし line-match の不一致 218 のうち true_miss は 5。残りは alternative 126（chosen も成立）＋
undecided 87。アプリは解答樹に無い別解を不正解にするので、ユーザー体験を動かすのは
**「成立する複数手からアプリの作意手を当てる」**信号。df-pn の順序（クラス > sub_demotion > ko_level >
plies > material）は作意の慣習（無条件優先・最短手数・石損最小）を部分的に表現しており、枠経路の
タイブレーク（visits 本命）に載せる価値がある。**まず測ること**: 枠経路の alternative 115 手順で、
アプリの手と chosen を同じ枠あり Problem 上で solve し、クラス/plies/material の順序がアプリの手を上に
置く割合（置くなら df-pn を選択則のタイブレークとして使う設計、置かないなら別の慣習を探す）。

**測定結果 → §0.7（2026-08-16）。方向は正しいが、タイブレークとしては使えない。**

### 0.6 独立に価値のある小改修（本件と切り離して起票）

> **状態（2026-08-16 のトリアージ後）**: 1=実施済み ／ 3=**5行に縮小して実施** ／
> 5=**観測だけ実施・並べ替えは保留** ／ 2=**DROP** ／ 4=**測定基盤待ち**。根拠は §0.8。

1. ~~`solver_opt_skip_after_ms` を予算比例に~~ → **実施済み（2026-08-16）だが、直したのは別の場所**。
   `opt_skip_after_ms` の予算比例化は実測で **−3.8% しか効かない**（燃えているのは第1段階が*速い*問題で、
   stage1 の遅さを見るゲートでは原理的に捕まらない）。真犯人は `NativeSolver.OPT_TIME_MS` の下限 3000ms
   ＝5000ms 予算では opt 1本に予算の 60%。`min(現行式, 0.3×予算)` に締めて **−26%**（P1 スイートの
   per-move では **−46%**）、134問すべてでソルバ出力はビット一致。詳細は
   `2026-08-01-tsumego-solver-design.md` **追記15**。あわせて `opt_skip_after_ms<=0`（常にスキップの番兵）が
   Windows の `time.time()` 分解能 15.6ms で効かず既存テストが run ごとに落ちていたのも修正。
2. Rust カーネルの Err 種別（deadline/node/ply）を Python 側ログへ（49 問中 2 問が 1.4〜1.8 秒で Err→
   TIMEOUT 扱い・予算に比例して伸びる＝MAX_PLY だけでは説明がつかない）。
3. `answer_book_replay.py`: `_gave_up` の持ち越し・`--keys` プレフィックス一致・`--min-line`・
   `--route solver_frame`・cold/warm 分離。
4. `game.py:761-765` 段階 3 投機を ai:tsumego_solver のフォールバック手番にも（判定不変・温めのみ）。
5. presolve スレッドの起動を `_apply_tsumego_region` の後へ（ROI 競合）。

### 0.7 §0.5 の測定結果（2026-08-16）— 向きは正しいが、機構としては net ≈ 0

`calibration-data/tsumego/frame_dfpn_tiebreak_probe.py`（KataGo 不要）。枠あり盤に prefix を打ち、
枠リージョンを hint に `extract_problem` → **1回の `solve()`** で root 全手の分類（`Solution.move_values`）を
取り、アプリの手 `want` と戦略の手 `chosen` が **クラスキー (class, sub, ko_level) 最良の集合**に入るかを見る。
`root_moves` ではなく `move_values` から最良集合を作るのは、`root_moves` が `max_alternatives`(8) で
**打ち切られる**のと、opt が省かれると plies が全部 0 に潰れて集合の意味が変わるため。floor 刈りの
WORSE は**厳密に下位**のときだけ返る（reference.py:474/488/495）ので、この集合は打ち切られない。

**処置群**（route=frame・class=alternative の 115 手番・30 秒予算）と、
**対照群**（今日**一致している**枠経路の手番 947 から 120 をシード固定サンプル。処置群だけで測ると
「結果で選別した標本」になる＝CLAUDE.md の禁止事項）:

| | 処置群 115 | 対照群 120 |
|---|---|---|
| solved | **33（29%）** | **56（47%）** |
| timeout / 空点>20 で棄却 / 抽出失敗 | 46 / 27 / 9 | 29 / 28 / 7 |
| solved の内訳 | want_only 8・both 23・chosen_only 2・neither 0 | both 51・**neither 5** |

1. **向きは正しい**: df-pn が差をつけた 10 件で **8:2** でアプリの手が上位。典型は
   `want=UNCONDITIONAL` / `chosen=KO`＝「無条件優先」という作意の慣習そのもの。
2. **タイブレークとしては使えない**。タイブレークが触れるのは KataGo の同着バンド
   （`points_epsilon=0.25`）の内側だけで、want_only 8 件のうちバンド内は **3 件**（他は
   ΔpointsLost 2.25〜18.8、うち2件は want が `min_visits=10` 未満）。chosen_only 2 件は**両方バンド内**。
   → バンド内では **3 対 2**＝ノイズ。
3. **オーバーライド（目数ガードを df-pn のクラスで覆す）にしても net ≈ 0**。獲得は処置群の 8/115。
   破損側は対照群の neither 5 だが、**うち4件は「正解手が抽出 region の外」**（＝別の問題を解いている。
   case AF/AG と同型）で、region 外を発火条件から外せば残る真の破損は **1/56＝1.8%**。しかし対照の母数は
   正解手番 947 なので 947×(56/120)×(1/56) ≈ **8 手番**の破損見込み＝獲得 8 と相殺する。
4. **そもそも GUI に載らない**。5 秒以内に解けるのは 115 中 18（16%）で、しかも差がつく want_only 8 件の
   所要は 3.4 / 3.5 / 5.8 / 10.3 / 10.3 / 27.4 / 27.9 / 30.2 秒＝**信号は遅い側に偏っている**。
   5 秒予算だと獲得 2・破損候補 1。

**結論**: §0.5 の「df-pn の順序を枠経路のタイブレークに載せる」は**却下**。ただし否定されたのは
*機構*であって*仮説*ではない（作意＝無条件優先は 8:2 で確認された）。効かない理由は §0.4 と同じ
**coverage** で、解けた問題の空点は中央値 10・タイムアウト側は 13 に集中する（枠あり閉包の 279/385 が
空点13+）。**A も B も同じ1点で詰まっている＝「枠あり盤から取れる問題が df-pn には大きすぎる」**。
次に投資するならタイブレークでも出題経路でもなく、**抽出をより小さく閉じる**こと。

### 0.8 §0.6 の小改修の実測トリアージ（2026-08-16）

§0.6 の残り4項目（2/3/4/5）を実コードで検証し、反証レビューを掛けた。**起票時の見立ては
4件中3件が実測で覆った**。以下の数値はすべてこのセッションで自分で再現したもの。

#### §0.6-2（Rust の Err 種別を Python 側ログへ）→ **DROP**

- **問いは `opt-budget.jsonl`（938行・コミット済み・`fac1edb` の副産物）が既に答えている。**
  cap を 500/1000/1500/3000ms と**6倍振った因果操作**で、optimize の中央値経過が
  **507 / 1008 / 1506 / 3003ms** と cap を 1:1 で追い、optimize タイムアウトは全 arm で 76〜92/134。
  ＝**optimize の Err は deadline** で確定している。壁時計から推測する Python 側ログを足しても
  この表以上のものは出ない。
- **問題レベルの status は 7 arm すべてで不変（変化 0/134）**＝問題レベル TIMEOUT は opt 非依存。
  「0.4〜0.5 秒 TIMEOUT」も `solver_verdict_ms`=1000 の検算経路では opt cap が 300ms ＝設計どおりの値。
- 本環境では **`cargo` が WDAC でブロック**（`os error 4551`）＝ DLL を再ビルドできない。
  ソースだけ変えると git 追跡済み DLL と乖離し、「ソースにあるのにログに出ない」で次の人が溶かす。
- 種別が判った後に取れる唯一の行動（`OPT_TIME_MIN_MS` / `solver_time_limit_ms` を緩める）は
  `fac1edb` が**逆方向に締めて −26%** を取ったばかりで正面衝突する。
  **動かせる意思決定が無い診断は実装しない。**

#### §0.6-3（`answer_book_replay.py`）→ **5行に縮小して実施**

- **`_gave_up` の持ち越しは不要だった。** `_generate_locked` は永続キャッシュ照会
  （`tsumego_solver_api.py:339-367`）を `_gave_up` ゲート（`:372-373`）より**前**に置いているので、
  GUI も give-up 後にキャッシュがあれば同じ手を返す。「ハーネスだけが解き直して当てている」は偽。
  ベースライン `20260815b` の route=solver 111手順・383判断の内訳は
  **キャッシュ即答 309 / ai:tsumego フォールバック 72 / 新規 solve 2**、
  **フォールバック後に新規 solve が成功した判断は 0**。持ち越しても選択手は1手も動かない。
- 実施したのは3点（`git diff` で 25 行）:
  - **(a) `--no-solver-cache` / `--no-solver` を `host._config` へ伝播** ← **本物の負債**。
    `_solver_settings`（`ai.py:4803-4810`）は `katrain.config("tsumego_capture")` を自分で引き直すので、
    ローカル settings dict だけを書き換えた旧実装では**出題前検算しか cold にならず、手番ごとの
    solve は永続キャッシュ（1673件）を引いたまま**だった＝「cold で測った」と記録した過去の A/B は
    手番側が warm。同じ取りこぼしは `--capture-settings` 側で 2026-08-09 に一度直されている
    （`:499-503` のコメントがその経緯）のに、フラグ側に適用されていなかった。
    - **この負債で意味が変わった過去の記録の全数調査（2026-08-16）**: 影響するのは
      **`2026-08-09-tsumego-answer-book-replay-design.md` §9.5 の `solver_cache=false` の1行だけ**
      （同じ主張の写しが `ai.py` の `_solver_answer_rejected` docstring と
      `2026-08-01-tsumego-solver-design.md` 追記14 にある）。当時のセッション記録に残る実コマンドが
      `--no-solver-cache` だったことを確認済み。他は無傷: 他の probe（`virtual_wall_solver_probe.py` /
      `frame_dfpn_tiebreak_probe.py` / `opt_budget_probe.py`）は `NativeSolver.solve()` を直接呼ぶので
      セッション層の永続キャッシュを通らず、`calibration-data` で `solver_cache` を触る script は
      `answer_book_replay.py` ただ1本。§0.4 の cold プロトコルは**未実施の計画**なので結果への影響なし。
    - **該当13件は cold で再走済み・結論は不変**（判定 13/13 が warm と一致）。詳細と生データは
      §9.5.1 / `calibration-data/tsumego/answer-book-truemiss13-coldwarm-20260816.jsonl`。
  - (b) `--keys` を前方一致に（進捗ログも結果集計も `key[:8]` を出すのに、8桁を渡すと
    **旧実装は黙って0件を選ぶ**＝実測 old 0件 → new 1件）。
  - (c) docstring から実在しない `--repeats` を削除（指定すると argparse が exit 2）。あわせて
    「3run はケースごとに新規プロセス」を明記（1プロセス反復は NN キャッシュとソルバ永続キャッシュの
    両方が run2 以降に効いて独立標本にならない）。
- **既定走行の等価性を確認済み**: `--keys` 無しのケース選択は旧新で **537キー・完全一致**
  ＝ベースライン `20260815b` はそのまま比較対象に使える（再ベースライン不要）。
  40桁完全一致も 1件のまま。**破損の母集団が構造的に存在しない**形の改修。
- **却下**: `--route solver_frame` と 49キーの `--keys-file`（唯一の消費者が §8 の Phase 1 で、
  それは §0.1/§0.7 で却下済み）／`--min-line` 既定変更（538 と 594 のどちらのベースラインか
  分からなくなる副作用のほうが大きい。必要なときに `--min-line 1` と明示すればよい）。

#### §0.6-5（presolve の ROI 競合）→ **観測だけ実施・並べ替えは保留**

- 機構は実在する（`__main__.py:1551` のスレッド起動が `:1572` の ROI 設定より前にあり、
  presolve が先に読んだ run では hint=閉包 bbox のセッションが立ち、`ai.py:4960` がそれを
  **全手番で再利用する**）。**が、実運用の発火は 0**（詰碁ログ 159本・ソルバ出題 27問に
  「再抽出」「region の外」の行なし＝再抽出は `_needs_reextract` のときしか走らない）。
- **どちらの hint が正しいかが未測定**。`tsumego_solver_api.py:95-99` は逆に
  「緩い hint はデタラメな小問題に成功する」（ply8 の hint なし再抽出が SEKI/L1 と誤答）と
  記録しており、ROI へ広げると `_open_rect_problem`（`tsumego_problem.py:383-388`）経由で
  再抽出 region が膨らむ向きの力も同時に入る（再抽出には `solver_capture_within_gates` が
  掛かっていない＝§0.3 の既知欠陥）。
- **提案されていた A/B は null 実験になる**: `answer_book_replay.py` の `build_game`
  （`:219` で ROI を設定し、セッションは入れない）も `generate_move_e2e.py:62` も、戦略に
  `build_session_from_game` を呼ばせるので**すでに hint=ROI 側**で走っている。両アーム同一。
- **この調査の一番の収穫は「本番とハーネスで hint の出所が食い違いうる」という事実そのもの**
  （本番=閉包 bbox になりうる／ハーネスは必ず ROI）。そこで今回は**出所を観測可能にするだけ**に
  した＝`build_session_from_game` の抽出ログに `再抽出hint=[...]（GUI ROI / 閉包 bbox）` を追加。
  挙動不変。
- **並べ替えるなら**: §0.3(a) の再抽出ゲートと同一コミットで、かつ先に df-pn の決定性を使った
  KataGo 抜きの裁定（両 hint で solve して回答帳の記録手順と突き合わせ）を済ませること。
  盤全体リージョンの盤（`game.py:871-874` / `tsumego_frame.py:617-618` が None に正規化）では
  移動しても no-op である点も、コメントに残すこと。

#### §0.6-4（段階3投機を ai:tsumego_solver のフォールバック手番へ）→ **測定基盤が先**

- **利得が小さい**。実 GUI ログのソルバ出題 27問で内側 ai:tsumego が走った手番は **24**、
  所要は**合計 29.6 秒・平均 1.23 秒・中央値 1.00 秒**で、**12手番（半分）が 1.0 秒未満**、
  1.8 秒以上は 6手番だけ（再現: 27本の詰碁ログを `[TsumegoOwnershipStrategy] 着手決定に X 秒`
  で集計）。しかも**ウォッチャは `Game.play()` からしか起動しないので ply0 には構造的に効かず**、
  速い手番は root 解析が閾値 630v を観測される前に終わって `game.py:788` の `region_completed`
  で bail する＝実際に縮む母数は 24 よりさらに小さい。段階3 の既往実測（−0.33〜−0.80 秒）は
  generate 2.7〜3.9 秒級の手番の値なので、外挿しても **1問 0.2〜0.5 秒**＝ユーザー要件 20 秒の
  1〜2.5%。§0.6-1 の `OPT_TIME_MS` 下限（per-move −46%）とは桁が2つ違う。
- **破損側を測る手段が現状ゼロ**: `answer_book_replay.py` / `generate_move_e2e.py` /
  `e2e_suite.py` はどれも `players_info` を設定しないので段階3 が1行も走らない。
  `early_speculation_e2e.py` は `AI_TSUMEGO` 決め打ち（`:51` / `:89-90` / `:209-210`）。
  **`--subtype ai:tsumego_solver` の配線が未起票の先行タスク**で、§0.6-3 はそれを含まない。
- **発火手番はビット同一ではない**。クエリ内容・visits・判定順序は不変（`_wait_region_roots` が
  全ハンドル待ち＝到着順非依存・`_start_region_root` は `time_limit=False`）だが、実クエリが読む
  NN キャッシュ値の出自が「温めラン中の GPU バッチ構成で計算された値」に変わる＝本リポジトリが
  実測済みの TensorRT バッチ非決定性（max|Δ| 0.05〜0.09・上位10手の順位入替）がそこに乗る。
  **`promotion_dominant_requires_success` のような真にビット同一な改修と同列に扱わないこと**
  （字義では `analysis_conditions_change=false` だが、運用上はシャッフル測定が要る第3の型）。
- **実装するなら** `session._gave_up` の private 読みではなく **Game 属性のフラグ**
  （`ai.py` のフォールバック確定地点で `game._tsumego_solver_fell_back = True`、`game.py:764` で読む）。
  実ログでカバレッジは 17/17 同一で、(a) private 結合、(b) 永続キャッシュ照会が `_gave_up` より
  先である点の誤予測、(c) 再抽出リセット（`tsumego_solver_api.py:333`）の誤予測、を構造的に持たない。
  **順序は「測定基盤 → 実測 → 判断」**。1手 0.3 秒を超えないなら製品コードは書かない。

---
（以下は初稿。§0 で訂正された箇所は初稿の記述より §0 を優先する）

- 日付: 2026-08-15（設計。実装は Phase 1 から着手）
- 入口文書: `2026-08-15-tsumego-extraction-expansion-handoff.md`（動機・398問の全数調査・却下実験・検証プロトコル）
- 調査: 6本の精読地図（`_closure`／ソルバの壁セマンティクス／セッション動線／枠経路／過去 spec の教訓）
  ＋ 仮想壁閉包プローブ（`calibration-data/tsumego/virtual_wall_closure_probe.py`・399盤×4変種×2色×hole_fix）
  ＋ 枠あり基板の静的センサス（`calibration-data/tsumego/framed_extraction_census.py`・592問・3.6秒）
- **結論を先に**: handoff §3 の本命「仮想境界壁」は**採らない**。代わりに handoff §4-2 の
  「途中フォールバックの受け皿を枠あり盤にする」を主軸に据え、**枠あり盤そのものを df-pn の基板にする**
  （枠経路が張った盤に hint=枠リージョンを渡して既存 `_Extractor` を掛ける＝GUI に P1 スイートと同じ
  経路を通らせるだけ）。封筒は仮想壁と同等（49問）で、途中フォールバックが枠あり経路に落ちる
  （ゲート拡大却下の原因を根治）・役割が GUI 盤から読める・新しい壁セマンティクスを一切導入しない。

## 1. 結論（TL;DR）

| | 仮想境界壁（handoff 本命） | **枠あり基板（本設計）** |
|---|---|---|
| 閉包が閉じる盤（399の失敗盤中） | A2 387 / A3 379（hole_fix 込み。無しなら 344/328） | 385/458（枠あり＋hint・閉包モード。open_rect 28 は除外） |
| ソルバ封筒（gates 23/12 ＆ 全記録手 region 内） | A2 48 / A3 52 | **49**（48 が全手 region 内・初手 49/49） |
| 途中フォールバックの受け皿 | **枠なし盤**（handoff §4-1 の弱点をそのまま継承） | **枠あり盤**（今日その盤で戦っている経路そのもの） |
| 役割（cross-check・裁定） | GUI 盤に壁が無い→ `tsumego_solver_attacks` None | 壁の色から読める（枠経路と同一） |
| 抽出器の変更 | 壁の注入経路（案A/B/C）＋穴処理＋fill 扱い＋再抽出時の再注入＋リング点への人間の着手処理 | **なし**（`allow_open_rect` フラグ1個・既定値で既存呼び出しはビット同一） |
| 出題時の追加コスト | 抽出 ms | 抽出 ms ＋ 出題前検算 ≤1 秒（枠の採否判定は**今日も払っている**） |
| 新規リスク面 | AA/AD 型（攻め方色の連が構造的に壁へ届く）・AF 型の新入口（リング上の実石）・fill が正解手を食う | ~~枠経路が既に持つもののみ~~ → **§0.2 の壁呼吸点欠陥（1〜4/49・ko_p 依存）が固有に存在**（静的ゲートで塞ぐ）。役割反転は規模ゲートが落とす（反転で 0/592）＝整合検査は検出力なし（§0.3） |

**判断の根拠**は §3。要点は「仮想壁で得られる封筒は枠あり基板と同じ 50 問弱で、
違いは**受け皿と役割**にしか無い。その2つは仮想壁が構造的に持てず、枠あり基板は無料で持っている」。

## 2. 実測（KataGo 不要・再現は秒単位）

### 2.1 仮想壁閉包プローブ（`virtual_wall_closure_probe.py`、399盤）

| 変種 | closed（hole_fix 無/有） | gates ＆ 全手 region 内 | 空点≤12 ＆ 全手 region 内 | 初手が壁線に乗る |
|---|---|---|---|---|
| A1（bbox+1 リング） | 373 / 390 | 42 | 74 | **78/373**（狭すぎ） |
| A2（bbox+2） | 344 / 387 | 48 | 81 | — |
| A3（bbox+3） | 328 / 379 | 52 | 83 | 0 |
| F（枠幾何を再現した壁だけ） | 327 / 380 | 51 | 79 | 1/380 |

- **役割を逆にすると gates を通る問題は全変種で 0**（inverse 色: closed A2 183 / F 222 だが e≤12 は 0〜31・gates 0）。
  誤った役割の壁は本当の攻め方の石を at_risk に落として region が守り方の囲い全体に膨らむ＝規模ゲートが役割反転を構造的に落とす。
- 閉じない主因は**穴**（`_closure` :233-240 が「石に接しない空点成分」を failed に落とす。閉じた詰碁盤では成分丸ごと吸収で顕在化しなかった）。
  hole_fix は rescue 17〜53 / break 0 だが、救った盤はほぼ 13+ 空点＝**封筒への寄与は +2 程度**。
- **fill が正解手を食う**: F で閉じたが記録手が region 外の 26 盤のうち 17 が fill 点（攻め方の地として埋めた遠地帯）。fill は Problem 上だけの石で GUI では空点＝そこが正解ならソルバは打てない。
- ソルバ動作確認 10 件（F・空点≤12・5000ms）: KO 8 / TIMEOUT 2、root 同格手のいずれか一致 8/8、3.2〜5.1 秒/件（**3 秒はほぼ `OPT_TIME_MIN_MS`**）。KO 偏重は既存の抽出成功問題 12 件も KO 7 なので仮想壁の産物ではない。
- 0.4〜0.5 秒で TIMEOUT する件あり（`lib.rs:201` が Err を全部 timeout で返す＝node/深さ系の打ち切りの可能性・未追跡）。

### 2.2 枠あり基板センサス（`framed_extraction_census.py`、回答帳 592問・3.6秒）

`_do_tsumego_capture_apply` の分岐を KataGo 抜きでなぞる: 生盤抽出＆ゲート → solver（134・現行不変）／
それ以外は `tsumego_frame_board(grid, 7.0, True, ko_p=False, margin=4)`（本番と同じ引数）＋ hint=枠リージョンで
`extract_problem` → 閉包モードのみ → gates 23/12 → 役割整合。

| 項目 | 値 |
|---|---|
| route | solver 134 / **solver_frame 49** / frame 409 |
| 枠あり抽出 | 試行 458 → 成功 413（閉包 385・open_rect 28）・失敗 45 |
| 閉包の空点 | ≤9: 29 / 10〜12: 77 / 13+: 279 |
| gates 通過 | 49（**役割整合 49/49・不整合 0**） |
| 記録手順 | 全黒手が region 内 48/49・初手は 49/49・fill 点に乗る黒手 0 |
| 型 | attack 33 / defend 16 |
| Phase 2 帯（閉包・空点≤12・region>23・役割整合） | **57**（region 最大 37） |

`solver_frame` 49 キー: 002fd977d3 0889919374 0bf0d74992 0e4553cfc0 0f25edb323 124de7898f 1354e479c1 17f3075c6a
1ef5ed5cff 1f0c28c018 2192dd79bc 22c770f75a 240674ed2a 2610ce3e0d 27043ec1d8 2929f234d6 2b553dec0b 2ce911bdcf
2f4172f211 3dee3cdd2d 3f0e90144f 43b56d6350 44c76318d6 4a70b24b77 4c8124dee5 543256fb5f 60f40be39e 625e2c7c7e
86bb39143c 98360aeeba aa317f8083 b46aa67d53 bfeaacb707 c0a2b9d5af c54f5ef48b c788cd67f9 c925d66b5b ce80514f16
cf2fd9fa26 d1c17fc93f d92aa8607d db5e1475c9 dc00efbd09 e70c61a30b e70f107502 e99ea673d0 f430f24998 f9a3db45c7 fed096c4bf

（handoff §2.1 の実例 e70c61a30b を含む。ゲート拡大却下で破損した eaef4cb07f は region>23 のまま＝本設計の
Phase 1 では**触らない**）

### 2.3 事実の確認（地図から）

- **ソルバに「壁」というフィールドは無い**。壁＝「region 外の石」で、不可侵性は「region 外に空の呼吸点が1つでも残る」ことから創発する（`model.py:80`・`solver-design.md:577-580`・小盤実測: 唯一の呼吸点が region 内の壁石は取られる／region 外に1つ残すと取れない）。**壁を置かずに region だけ切る案は不可**（box の縁に届く連が埋められない呼吸点を得て不死→SEKI。実測 B2〜B4）。
- **P1 スイート（`solver_p1_suite.py`）は SGF の root 配置＝枠あり GUI キャプチャ盤に `region_hint=枠リージョン` で `extract_problem` → solve** している。つまり「枠あり基板」は**既に21ケースで回帰が回っている経路**で、GUI のソルバ経路（枠なし盤・hint なし）のほうが例外だった。
- 枠の壁リングは Benson pass-alive でない（380/389）が呼吸点≥7（389/389）＝候補にも種にもならず、hint 外連の無条件壁か outside libs≥3 で壁になる。遠地帯 fill が region 外に残るぶんが実質の永久呼吸点。
- 役割は回答帳に保存されていない（entry は size/to_play/canonical_black/canonical_white/lines/created のみ）＝handoff の「回答帳の black_to_attack」は誤り。役割はログ行「認識盤面 … black_to_attack=」にしか無い。
- セッション盤は `problem − fill`（api:89）。仮想壁を fill チャネルに入れるとセッション盤とカーネル盤で壁の有無がずれる（取りの発生が食い違う可能性）。枠あり基板なら壁は GUI 盤の実石なので**この問題が存在しない**。
- キャプチャ経路は `extract_problem` に `region_hint` を渡していない（`__main__.py:1388-1392`）＝矩形 region モードには到達しない。役割ホットキーは枠経路にだけ届く。

## 3. なぜ枠あり基板か（判断）

1. **封筒が同じ**: 2.1 と 2.2 で「gates ＆ 全手 region 内」は A2 48 / A3 52 / F 51 / 枠あり基板 49。仮想壁は問題を「より多く閉じる」（387 vs 385）が、閉じた問題の大半は 13+ 空点で df-pn の封筒外。**封筒の真の次元は空点数**（handoff §4-3）で、壁の置き方はそれを動かさない。
2. **受け皿の問題を根治する**: ゲート拡大却下（followup §5.2）の破損機構「root が解けても途中で証明範囲外の応手→枠なし盤の KataGo フォールバック」は、仮想壁でも**同じ**（仮想壁は GUI 盤に壁が無い）。枠あり基板ではフォールバック先が**今日その盤で戦っている枠あり経路そのもの**＝下限が現状に固定される。これは handoff §4-2 が「これが解けると却下自体を再検討できる」と書いた条件で、Phase 2（§7）で実際に再検討する。
3. **新セマンティクスを持ち込まない**: 仮想壁は `_closure` への注入経路（地図の案A/B/C）・穴処理・fill と壁の分離・再抽出時の再注入・人間がリング点（実盤では空点）に打ったときの扱い（`_apply` が region 外→再抽出→hint 付き再抽出はリングを知らない）を全部新設する必要がある。抽出器は過去5回の外科的ガード（AA/AC/AD/AE/AF）が乗った最退行サブシステムで、handoff §3.1 が「全ケースの再発リスク」と書いたのはこの新設面。枠あり基板は**抽出器を変えない**。
4. **役割が読める**: `tsumego_solver_attacks` は GUI 盤の壁の色から役割を読む。枠あり基板では cross-check・格上げ／格下げ・脱出の役割依存の裁定がすべて枠経路と同じ精度で働く。仮想壁（枠なし GUI 盤）では None に落ちて役割非依存の弱い挙動になる（case R/W の枠なし限界がそのまま乗る）。
5. **役割反転はゲートが落とす**: 2.1 の inverse 色で gates 0、2.2 の役割整合 49/49。さらに §4.2 の整合検査を無料で足す。

**代償**: 仮想壁なら不要だった「枠の採否判定（KataGo 1〜6 秒）」が要る——が、この 49 問は**今日も枠経路で出題されておりその判定を既に払っている**。追加は抽出 ms ＋ 出題前検算 ≤1 秒（`solver_verdict_ms`）だけ。

## 4. 設計

### 4.1 出題フロー（`_do_tsumego_capture_apply` の差分）

現行:
```
生盤抽出(hint なし) → gates → hopeless → [solver: board=grid, region=frameless]
                                        → else 枠 → [_choose_tsumego_frame] → (board, region) or None
                                                                                → else 枠なし
```
本設計（★が追加。既存の3経路は不変）:
```
生盤抽出(hint なし) → gates → hopeless → [solver: 従来どおり frameless 基板]      … 134問・不変
  else 枠 → _choose_tsumego_frame → (board, region)
       ★ settings["solver_on_frame"] かつ枠が採用されたら:
       ★   problem = extract_problem(grid=board, region_hint=region_of_interest(region),
       ★                             allow_open_rect=False)          … 閉包モードのみ
       ★   → solver_capture_within_gates（23/12・共有ヘルパー）
       ★   → 役割整合（§4.2）
       ★   → problem_is_hopeless（既存・solver_verdict_ms）
       ★   → 通れば solver_problem を立てる。board/analysis_region は枠のまま
                                          → [solver_frame: board=枠あり盤, region=枠リージョン, subtype=AI_TSUMEGO_SOLVER]
       → 通らなければ従来どおり [frame: ai:tsumego]
  else 枠なし（不変）
```
以降（`_do_new_game` → `game.tsumego_solver_problem` → 回答帳照合 → 投機 presolve → `_apply_tsumego_region` →
subtype 決定）は現行コードがそのまま面倒を見る（`solver_problem is not None` で分岐しているため）。

- **hint は `analysis_region` と同じ矩形**（壁の線を含む・region_of_interest 形式）。セッションの再抽出 hint
  （`build_session_from_game` → `game.region_of_interest`）と同一にして、キャプチャ時の抽出と再抽出が同じ問題を出すようにする。
- **`allow_open_rect=False`**（`extract_problem` の新 kwarg・既定 True）: 矩形 region モードは region＝矩形全点で壁の石点まで region に入る（ソルバの意味論と食い違う）。gates 23 でほぼ落ちる（open_rect 28/413 のうち gates 通過 0）が、意味論として閉包モードに限る。既存の呼び出し（キャプチャ hint なし・再抽出・P1）は既定値で**ビット同一**。
- **枠が採用されなかった盤**（`_choose_tsumego_frame` が None＝frame_destroys_problem）は従来どおり枠なし。仮想壁を試す価値があるのはここだけ（Phase 3 候補・§7）。
- **枠なしホットキー**（`use_frame=False`）は枠を張らないので新経路に入らない（従来どおり）。

### 4.2 役割整合検査（追加クエリ 0 本）

枠の壁色（=役割仮定）と抽出器の型を突き合わせ、食い違えばソルバを採らず従来の枠経路へ（ログを残す）:

| 壁色 | ATTACK（白が target） | DEFEND（黒が target） | SEMEAI |
|---|---|---|---|
| 黒（黒が攻め方） | 整合 | **不整合** | 整合（両様） |
| 白（白が攻め方） | **不整合** | 整合 | 整合（両様） |

- 壁色は**張った盤から読む**（`_choose_tsumego_frame` が返した board のリージョン境界線の石の色。`tsumego_solver_attacks` と同じ占有率/純度で読む純関数を `tsumego_frame.py` に置く）。`guess_black_to_attack_for_board` の再計算は「ログ用の写し」なので使わない（写しが乖離すると黙って壊れる）。
- 実測では発火 0/49（センサス）だが、役割反転が gates をすり抜けた1件が「別問題を自信たっぷりに即答」（case S/X の構図）になるのを塞ぐ最後の静的ゲート。コスト 0。

### 4.3 既存の安全網を全部通す

- `solver_capture_within_gates`（23/12）: **Phase 1 では動かさない**（拡大は Phase 2）。
- `predetermined_reason`（MIN_TARGET_SPACE・`_captured_in_one`）: `extract_problem` 内で既に走る。
- `problem_is_hopeless`（FAILED 証明・1000ms）: そのまま。解けたら永続キャッシュに載り初手が速い。
- `solver_cross_check`（役割石の同深さ ownership・sticky 却下）: 役割は GUI 盤の壁から読めるので**枠経路と同じ精度**（現行ソルバ経路より強い）。
- 再抽出サニティガード（元 target の生存石 ⊂ 新 region）: そのまま。hint が枠リージョンなので再抽出は同じ閉包を出す。
- `_gave_up` sticky（solve タイムアウト）→ `ai:tsumego` on **枠あり盤**＝今日の経路。

### 4.4 セッション・キャッシュ・フォールバック（変更なし・確認事項）

- セッション盤 = `problem − fill` = 枠あり GUI 盤（fill は遠地帯の埋め・GUI 空点）。壁は実石なので kernel/セッション/GUI で一致。
- 人間が region 外（枠内の帯・枠外の代償地帯・コウダテ）に打つ → `_apply` が `_needs_reextract` → hint 付き再抽出 → 同じ閉包（新石は壁側）→ 続行。コウダテ後の取り返しはカーネル再構築で ko 禁止が解けるので正しい。**現行ソルバ経路と同じ挙動**（枠なし盤でも人間はどこにでも打てた）。
- 永続キャッシュのキーは black/white 全石を含む → frame_ko の 2 変種でキーが分かれる（同一セッション内は一致。別セッションで変種が変わればミス＝再 solve ≤5 秒）。許容。
- native 上限 target ≤64 石は枠あり基板でも同じ（超えると参照実装へ退避）。gates 23 の内側では起きない。

### 4.5 設定・ログ・リプレイ

- 新キー `tsumego_capture.solver_on_frame`（bool・既定 **true**）: A/B のトグル（リプレイの `--capture-settings solver_on_frame=false`）兼ユーザーの逃げ道。**両方の config.json**（パッケージ＋ユーザーローカル＝メインセッションで直接 Edit）に追加。
- ログ（OUTPUT_INFO・1問1ファイルの詰碁ログに残る）: `tsumego_capture: 枠あり盤でソルバ用の問題を抽出 type=… target=…子 region=…点/空点…（役割 壁=B/W・整合）` ／ ゲート超過・不整合・hopeless の各理由 ／ `tsumego_capture: ソルバモード（枠あり基板）で出題します … [抽出+検算 X.XX 秒]`。
- `answer_book_replay.py`: `choose_board` に同じ分岐を写し route=`solver_frame` を返す。`--route solver_frame` の事前フィルタ `static_solver_frame_eligible`（枠を KataGo 抜きで張って抽出＋ゲート＝上界）。
- センサス `framed_extraction_census.py` は Phase 2 の帯の見積りにも使う（`phase2 band` 行）。

## 5. 却下・保留した案（数値つき）

| 案 | 判断 | 理由 |
|---|---|---|
| 仮想境界壁（案A: リング石を fill に／案B: hint で無条件壁／案C: `virtual_walls` 明示パラメータ） | **却下**（Phase 3 で「枠が採用されない盤」限定の再検討余地） | §3。封筒同等（48〜52 vs 49）・受け皿が枠なし・役割 None・抽出器の新設面が大きい。fill が正解手を食う 17/26 盤 |
| 穴処理（`_closure` の colors==∅ を吸収） | **保留** | rescue 17〜53 / break 0 だが封筒寄与 +2。`_closure` は全抽出に効くので 300 抽出 A/B（差分 0 件要求）が要る。Phase 3 |
| 規模ゲート拡大 | **Phase 2 へ**（Phase 1 では触らない） | 却下理由（枠なし受け皿）が本設計で消えるので、**枠あり基板の経路に限って**再測定する。帯は 57 問（空点≤12・region 24〜37） |
| 既存ソルバ経路（134問）も枠あり基板へ移す | **保留** | 解析条件が変わる（枠の KataGo 判定・役割推定が新たに乗る）＝シャッフルと役割誤り（case X）の新リスク。フォールバックの強化は魅力だが別 A/B |
| `_choose_tsumego_frame` の返り値に役割を足す | 不採用 | 壁色は盤から読める（ground truth）。シグネチャ変更はリプレイにも波及 |
| 枠なし盤（frame_destroys_problem で枠が捨てられた盤）へのソルバ | 対象外 | 今回の 49 問はすべて枠採用が前提。枠が捨てられる盤は今日も枠なし |

## 6. リスクと再発面（case AA〜AF の枠あり基板での位置づけ）

| case | 枠あり基板での状態 | 塞ぐもの |
|---|---|---|
| AA（取れる連を壁） | 攻め方色の実石は空点経由で枠の壁に届き `_reaches_safety` が真になりやすい＝AD と同じ「開いた盤」の性質。**ただし枠は認識石の外側だけに壁を置くので、盤の内側の取れる連はまず壁の色（攻め方）**＝攻め方の取れる連が壁扱いされるのは正しい側 | hopeless（FAILED）＋ cross-check |
| AC/AE（退化形） | `predetermined_reason` がそのまま効く。枠で region が帯ぶん広がるので発火はむしろ減る | 同左 |
| AD（的を壁に） | 物理枠でも起きた形。抽出は的を壁にできる | hopeless（FAILED 証明）。捕まらない「別問題が解けてしまう」形は cross-check |
| AF（石隣接のアタリ連が黙って境界） | 不変。`analysis_region` は枠リージョン（枠経路と同じ）なので KataGo 側は狭められない | 枠経路と同一 |
| X（役割反転） | 枠経路が今日も持つリスク。ソルバ側は gates（inverse で 0/399）＋整合検査（§4.2）で漏れゼロ実測 | 役割ホットキー |
| AG（正解が枠の外） | 枠経路が今日も持つ。記録手順は bbox+2 の外に出ない（398問）・枠あり基板の 49 問は全手 region 内 48/49 | `hotkey_noframe` |
| S/N（枠が詰碁を壊す） | `_choose_tsumego_frame` が捨てる盤は新経路に入らない | 同左 |
| ソルバの KO 偏重・0.4 秒 TIMEOUT | 現行ソルバ経路と同じ性質（別途追跡）。TIMEOUT は `_gave_up` sticky → 枠あり盤 `ai:tsumego`＝今日の挙動 | — |
| 9路: 枠が認識石を上書きしうる（`fit_margin` が占有を避けられないとき） | 今日の枠経路と同じ盤で戦う。抽出はその盤から | hopeless・cross-check |

**「やってはいけないこと」との整合**: 本設計は既存3経路の**解析条件を変えない**。新経路が発火するのは 49 問だけで、
その 49 問のフォールバック先は今日の経路そのもの＝A/B の破損側は「ソルバが自信を持って別解/誤答を即答した」形に限られ、
それは cross-check の実測（ソルバ経路 62%→71%）が既に押さえている帯。

## 7. Phase 計画

| Phase | 内容 | 判定 |
|---|---|---|
| **1** | 枠あり基板でのソルバ採用（§4）。`solver_on_frame` 既定 true | 標的リプレイ 49 キー×3run（回復/破損の両側）＋フル 538 手順×1（他の 543 行がビット同一に近いことの確認・シャッフル±5%）＋ E2E 29 ＋ P1 `--native`（抽出器は既定値でビット同一のはず） |
| **2** | 枠あり基板の経路に限り規模ゲートを再測定（帯 57 問: 空点≤12・region 24〜37。設定キー `solver_on_frame_max_region` 等で枠あり経路だけ別ゲート） | 同上。solve 封筒（空点 10〜12 は 6〜18 秒＝5 秒予算では TIMEOUT→sticky→今日の経路）なので下限は現状。上限見積り +57×0.16 ≈ +9 |
| **3**（保留） | (a) 穴処理（300 抽出 A/B 差分 0 件要求）(b) 枠が捨てられた盤への仮想壁 (c) TIMEOUT Err 分類（`lib.rs:201`）(d) キャッシュキーの region 限定 | それぞれ独立 |

**期待値**: ~~Phase 1 = 49 × (73% − 57%) ≈ +8~~ → **レビューで訂正: −4〜+4（§0.1）**。母数 33 手順・現状 67%・
TIMEOUT 17/49・verify で true_miss 0。Phase 2 の +9 も同じ理由で成立しない（帯 57 問は空点 10〜12 が主で
5 秒予算では TIMEOUT 帯）。下振れは cross-check が沈黙する KO 答え（枠あり 49 問はソルバ結果の 81% が KO
クラス）＝§0.2 の欠陥が歪めた答えが素通りする経路。

## 8. 実装計画（Phase 1）

1. `katrain/core/tsumego_problem.py`: `extract_problem(..., allow_open_rect: bool = True)` → `_Extractor(..., allow_open_rect)`。False なら :383 の矩形モードへ落ちず `ProblemError(last_kind, last_reason)`。既定 True で全既存呼び出し不変。
2. `katrain/core/tsumego_frame.py`: `frame_wall_color(board, region) -> "B"|"W"|None`（境界線の石の占有率/純度で読む・`tsumego_solver_attacks` と同じ閾値）と `role_consistent(black_to_attack, problem_type)`（純関数・単体テスト）。
3. `katrain/__main__.py` `_do_tsumego_capture_apply`: 枠採用直後に §4.1 の★ブロック（`solver_on_frame` ゲート・抽出・gates・整合・hopeless・ログ）。solver_problem を立てるだけで以降は既存コード。
4. `katrain/config.json` ＋ `~/.katrain/config.json`: `solver_on_frame: true`。
5. `answer_book_replay.py`: `choose_board` に同分岐・route `solver_frame`・`--route solver_frame` の静的フィルタ。
6. テスト: `tests/test_tsumego_problem*.py` に `allow_open_rect=False` の挙動、`frame_wall_color`/`role_consistent` の単体、センサスの数値（49）は spec に記録。
7. 検証（順に）: P1 `--native` ／ pytest ソルバ系 ／ 標的リプレイ 49 キー ×3（`--keys` は上のリスト、`--capture-settings solver_on_frame=false` を対照）／ フル 538 ×1 ／ E2E 29。
8. 文書: CLAUDE.md（詰碁節に1段落）・`.claude/rules/ai-parameters.md`（設定表に `solver_on_frame`）・本 spec に実測追記・handoff §3 に「本設計へ」の注記。

## 9. 参照

- 精読地図（セッション scratchpad・本 spec に要点を転記済み）: closure / solver-walls / session-flow / frame / spec-lessons
- プローブ: `calibration-data/tsumego/virtual_wall_closure_probe.py`（変種 A/F・hole_fix・失敗理由の分類。出力 6384 行 JSONL は 32 秒で再生成できるので未コミット）／`virtual_wall_solver_probe.py`（閉じた問題の native solve・`--limit 10` 動作確認済み）／`framed_extraction_census.py` → `framed-extraction-census.jsonl`
- 既存: `closure_failure_census.py`（398問の失敗分類）・`solver_p1_suite.py`（枠あり基板の回帰＝同じ入口）・`answer_book_replay.py`

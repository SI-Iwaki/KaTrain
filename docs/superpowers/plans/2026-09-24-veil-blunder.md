# 韜晦の失着オプション 実装計画

日付: 2026-09-24
Spec: `docs/superpowers/specs/2026-09-23-veil-strategy-design.md` §13（この計画の最初のコミットで追記）
実行: サブエージェント駆動（worktree `.claude/worktrees/veil-blunder`・ブランチ `veil-blunder`）。タスクは順に1つずつ、実装 → レビュー → 修正。

**Goal:** 韜晦（veil9/13/19）に、9段でも迷う局面でまれに人間らしい失着（通常の支払い上限を超える損失）を打つ層を足す（既定 OFF・LOG＝記録のみ・ON）。
**勝ちの安全条件（reserve・min_winrate）は変えない**。mode 0 の挙動は今と1バイトも変えない。

## Global Constraints


1. **CRLF・black 未整形の既存ファイル**（`katrain/core/ai.py`・`katrain/core/constants.py`・`katrain/config.json`・`katrain/i18n/locales/*/LC_MESSAGES/katrain.po`・`docs/**/*.md`・`docs/manual/src/*.html`・`.claude/rules/*.md`）は **python のパッチスクリプトだけで変える**（下の `crlf_patch.py` を import して `patch(path, [(old, new, count)])`）。Edit / Write ツールで `.py` を書くと PostToolUse の black フックがファイル全体を整形してしまう（ai.py は 1 万行超の未整形ファイル＝差分が壊れる）。パッチスクリプトは `<scratchpad>`（下記）に置いて実行する。
   - 例外: `tests/test_ai_veil.py` は black 整形済み（CRLF）なので Edit ツールで直接変えてよい（black フックが走っても差分は出ない）。
2. 触ってよいのは韜晦（veil 純関数群・Veil9/13/19）とその登録・文書・テストだけ。**難解（Enigma*）・擬態（Mimic13）・その他の戦略のコードは変えない**（`_probe_children` などの共有メソッドも変えない＝シグネチャの追加も不可）。
3. KataGo を起動しない（テストはすべてスタブ）。`C:/Users/iwaki/.katrain/config.json`（ユーザー設定）は触らない（メインセッションの仕事）。
4. 既存のテストを弱めない。既存の韜晦の挙動（blunder_mode 0＝既定）は1バイトも変えない＝mode 0 ではクエリ数・`Decision:` の中身・選ぶ手が今と同じ（`blunder` キーも足さない）。
5. コミットは日本語の Conventional Commits、末尾に `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。
6. テスト: 自分のタスクの focused テスト（`python -m pytest tests/test_ai_veil.py -q` など）と、brief が挙げる関連テスト。**全体スイートはコントローラが後で流す**（別の GPU ジョブが走っていて時間系のテストが揺れるため）。
7. i18n を変えたら `python tools/compile_mo.py`、マニュアルの src を変えたら `python tools/build_manual.py`（どちらも worktree のルートで）。


---

## Task 1: 失着の定数・純関数・不変条件（TDD）

状態: 完了（`8b5426f2`）。

要件の正本: spec §13（`docs/superpowers/specs/2026-09-23-veil-strategy-design.md`・worktree 内）。この brief はその §13.2 の定数と §13.3 手順4・6・8 の純関数部分。

### 1. 定数（ai.py・`VEIL_HP_TIE = 0.02 ...` の行の直後、`_VEIL_EPS` の前に挿入）

コメントのスタイルは周りに合わせる（値の後に `# 日本語の説明`）:

```python
VEIL_BLUNDER_MIN_HP = 0.15       # 失着の手に要る humanPolicy の絶対床（spec §13）
VEIL_BLUNDER_MIN_WR = 0.95       # 失着の前の root 勝率と、打った後の検証済み勝率の床（min_winrate より厳しい）
VEIL_BLUNDER_MARGIN = 5.0        # 失着の後の検証済みリードに要る reserve の上積み（目）
VEIL_BLUNDER_VISITS = 1500       # 失着の検証プローブ（クリーン解析）の visits
VEIL_BLUNDER_PROBES = 2          # 深く検証する失着候補の数（hp の高い順）
VEIL_BLUNDER_RAW_MARGIN = 2.0    # 失着候補の生の loss の上の足切りに持たせる余裕（目）
VEIL_BLUNDER_PROB = 0.5          # ON で資格のある手番に実際に打つ確率（影の計測の後に見直す）
```

### 2. 純関数（ai.py・`def veil_invariant_ok` の直前に、この順で）

```python
def veil_blunder_candidates(candidates, best_gtp, best_hp, hp_of, ratio, cap, max_loss,
                            min_hp=VEIL_BLUNDER_MIN_HP, raw_margin=VEIL_BLUNDER_RAW_MARGIN,
                            limit=VEIL_BLUNDER_PROBES):
```
- candidates は `_veil_candidates` の返り値と同じ形の dict の列（`{"gtp", "loss", "visits", "wr"}`）。hp_of は gtp → humanPolicy。
- 返り値: best_gtp・"pass" 以外で、`hp_of(gtp) >= max(min_hp, ratio * best_hp)` かつ `cap < loss <= max_loss + raw_margin + _VEIL_EPS` の手を、**hp の降順・同点は gtp の昇順**に並べ、先頭 `limit` 手。各要素は元の dict のコピーに `"hp": hp_of(gtp)` を足したもの（元の dict は変えない）。
- docstring に「spec §13.3 手順4。hp が最善手の ratio 倍以上＝9段 humanSL 自身が迷う局面なので『難しい局面』の条件を兼ねる」と書く。

```python
def veil_blunder_ok(row, cap, max_loss, reserve, lead, margin=VEIL_BLUNDER_MARGIN, min_wr=VEIL_BLUNDER_MIN_WR):
```
- row は `{"vloss", "lead_after", "wr_after", ...}`、lead は root リード（Task 3b で追加）。**lead かどれかが None なら False**。
- True の条件: `cap < vloss <= max_loss + _VEIL_EPS` かつ `lead_after >= reserve + margin - _VEIL_EPS` かつ `lead - max(0.0, vloss) >= reserve + margin - _VEIL_EPS`（Task 3b）かつ `wr_after >= min_wr - _VEIL_EPS`。
- docstring: spec §13.3 手順6。

```python
def veil_blunder_pick(rows):
```
- rows（資格のある手）から hp 最大を1つ返す。同点は vloss の小さい方、さらに同点は gtp の昇順。空なら None。

### 3. 不変条件（`veil_invariant_ok` に kind `"blunder"` を足す）

- 共通の規則（chosen が cand_gtps に含まれ best・pass・None でない）はそのまま。
- `kind == "blunder"`: bounds のキーは `vloss` `max_loss` `lead` `reserve` `margin` `wr_after` `min_wr`。
  True の条件: `vloss <= max_loss + _VEIL_EPS` かつ `lead - max(0.0, vloss) >= reserve + margin - _VEIL_EPS` かつ `wr_after >= min_wr - _VEIL_EPS`。キー欠落・None は既存の `except (KeyError, TypeError)` で False になる形にする（`wr_after` が None なら TypeError になる比較でよい）。
- docstring の種類ごとの上限の説明に blunder の行を足す。

### 4. テスト（tests/test_ai_veil.py・TDD＝先にテストを書いて RED を確認）

import に `veil_blunder_candidates, veil_blunder_ok, veil_blunder_pick` と定数 `VEIL_BLUNDER_MIN_HP` などを足す（既存の import 群に合わせる）。既存の `cand(gtp, loss, visits=100)`・`hp_table(values)` ヘルパーを使ってよい。新しいクラスを `TestInvariant` の近くに置く:

- `TestBlunderCandidates`:
  - 帯（cap < loss <= max_loss + raw_margin）の内だけ残る: cap 4.5・max_loss 10 で loss 4.5（ちょうど cap＝除外）・4.6・12.0（ちょうど上限＝残る）・12.1（除外）。
  - hp の床: best_hp 0.4・ratio 0.7 → 0.28 未満は除外。best_hp 0.1 なら絶対床 0.15 が効く（0.14 は除外・0.15 は残る）。
  - best と pass は除外。
  - 並び: hp 降順・同点は gtp 昇順。limit で切る（limit 2 で3手→2手）。
  - 元の dict が変わらない（"hp" は返り値にだけある）。
- `TestBlunderOk`:
  - cap 4.5・max_loss 10・reserve 5（margin 5・min_wr 0.95）で: vloss 6・lead_after 15・wr 0.97 → True。
  - vloss 4.5（= cap）→ False・10.0 → True・10.1 → False。
  - lead_after 9.9 → False・10.0 → True。wr_after 0.949 → False。
  - vloss / lead_after / wr_after のどれかが None → False。
- `TestBlunderPick`: hp 最大・同点は vloss 小・さらに同点は gtp 昇順・空は None。
- `TestInvariant` に `test_blunder_bounds` を足す: 通る例と、vloss > max_loss・lead − vloss < reserve + margin・wr_after < min_wr・wr_after None・キー欠落のそれぞれが False。候補に無い手も False（共通規則）。

### 5. 手順

1. テストを書く → `python -m pytest tests/test_ai_veil.py -q` で RED（import エラーか失敗）を記録。
2. パッチスクリプト `<scratchpad>/patch_blunder_t1.py` を書いて ai.py を変える（crlf_patch・Global Constraint 1）。
3. GREEN: `python -m pytest tests/test_ai_veil.py -q`（全件）と `python -m pytest tests/test_ai_mimic13.py tests/test_ai_enigma*.py -q`（既存戦略が無変更で通る。ファイル名は `ls tests | grep -i enigma` で確かめて存在するものだけ）。
4. `git diff --stat` で ai.py の変更が挿入だけ（既存行の変更は `veil_invariant_ok` の docstring と分岐だけ）であることを確かめる。
5. コミット: `feat(veil): 失着の定数・候補・資格・不変条件の純関数を追加` ＋本文1〜2行＋ `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`。

---

## Task 2: 失着の設定4キー（既定値と登録）

状態: 完了（`bab11c18`）。

要件の正本: spec §13.2（設定4キー × 3盤・スライダーの候補値）。この Task は**設定を足して登録するだけ**で、判定フローでは使わない（Task 3 で使う）。Task 1 の定数・純関数はコミット済み。

### 1. 既定値（ai.py の SETTING_DEFAULTS）（`SETTING_DEFAULTS` の末尾＝`trap_min_delta_e` の後に4キー）

| クラス | blunder_mode | blunder_max_loss | blunder_per_game | blunder_hp_ratio |
|---|---|---|---|---|
| Veil9Strategy | 0 | 6.0 | 1 | 0.7 |
| Veil13Strategy | 0 | 10.0 | 1 | 0.7 |
| Veil19Strategy | 0 | 15.0 | 1 | 0.7 |

Veil9 だけ既存と同じ書式で行末コメントを付ける: `# 失着の層（spec §13）: 0 OFF / 1 記録のみ（影）/ 2 ON`・`# 失着の上限（検証済み損失・目）`・`# 1局で打つ失着の上限（ON のとき）`・`# 失着の手の hp ÷ 最善手の hp の下限（9段 humanSL）`。値の型は mode と per_game が int、他は float。

tests/test_ai_veil.py の `SPEC_DEFAULTS`（凍結した spec の既定値）の 9 / 13 / 19 にも同じ4キーを足す（§13.2 は spec の一部なので「凍結」の対象）。`test_defaults_match_the_spec` などが通ることを確かめる。

### 2. 登録（既存の veil の16キーと同じ場所・同じ書式で、4キー × 3盤）

1. `katrain/core/constants.py`:
   - 候補値のリスト（`_VEIL_TRAP_MIN_DELTA_E` の直後）:
     ```python
     _VEIL_BLUNDER_MODE = [(0, "OFF"), (1, "LOG"), (2, "ON")]
     _VEIL_BLUNDER_MAX_LOSS = {
         9: [4.0, 5.0, 6.0, 8.0],
         13: [6.0, 8.0, 10.0, 12.0, 15.0],
         19: [8.0, 10.0, 12.0, 15.0, 20.0],
     }
     _VEIL_BLUNDER_PER_GAME = [1, 2, 3]
     _VEIL_BLUNDER_HP_RATIO = [(0.5, "50%"), (0.7, "70%"), (0.8, "80%"), (1.0, "100%")]
     ```
   - 候補値の辞書（`"veil9_trap_min_delta_e": _VEIL_TRAP_MIN_DELTA_E,` などの後）に `veil{9,13,19}_blunder_mode` / `_blunder_max_loss`（盤サイズ別の `_VEIL_BLUNDER_MAX_LOSS[n]`）/ `_blunder_per_game` / `_blunder_hp_ratio`。
   - 並び順の辞書（`"veil9_trap_min_delta_e": 15,` などの後）に 16・17・18・19（mode・max_loss・per_game・hp_ratio の順）。
   - 既定値がそれぞれの候補値に含まれること（9路 6.0・13路 10.0・19路 15.0・per_game 1・hp_ratio 0.7・mode 0）。
   - int の候補値（mode・per_game）が GUI で扱えるか、既存の int の候補値（例: `mimic13_endgame_move` や enigma の int 設定）の書き方を確かめてそれに合わせる。
2. `katrain/config.json`: `ai:veil9` / `ai:veil13` / `ai:veil19` の各ブロックの末尾（`trap_min_delta_e` の後）に4キー（既定値。mode と per_game は整数 `0` / `1` で書く）。JSON として読めることを確かめる。
3. `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`: 既存の `aiopt:veil*_trap_min_delta_e` の後に4つの `aiopt:veil*_blunder_*`（1行目が見出し、2行目以降が説明。`{p}` はキー接頭辞に置き換わる既存の仕組み）:
   - `aiopt:veil*_blunder_mode` 見出し「失着の層」: 9段でも迷う局面（失着の手の humanPolicy が最善手の {p}_blunder_hp_ratio 倍以上かつ 15% 以上）で、通常の支払い上限を超える人間らしい失着をまれに打つ層。LOG（記録のみ）は条件を満たす手を探してログに書くだけで打たない（頻度の確認用）。ON で実際に打つ（条件を満たした手番の半分・1局 {p}_blunder_per_game 回まで）。ヨセ・接戦では打たず、打った後もリードが {p}_reserve ＋5目以上・勝率 95% 以上残る手だけ（深い読み 1500 visits で確かめる）。一致率はほとんど変わらない（損失の分布を人間に近づけるための層）。既定 OFF。
   - `aiopt:veil*_blunder_max_loss` 見出し「失着の上限（目）」: 失着 1 回で許す損失（着手後の局面を深く読んだ値）の上限。通常の支払い上限（{p}_max_loss）を超える損失だけが失着の対象。上げると大きな失着も出るが、打てる局面（大差のとき）は減る。
   - `aiopt:veil*_blunder_per_game` 見出し「1局の失着の上限（回）」: ON のとき 1 局で打つ失着の回数の上限。
   - `aiopt:veil*_blunder_hp_ratio` 見出し「失着の自然さ（最善手比）」: 失着の手を 9段が選ぶ確率が、最善手を選ぶ確率のこの割合以上の局面だけで失着を打つ。上げると 9段でも本当に迷う局面だけになり（頻度が下がる）、下げると頻度が上がるが不自然な失着が混ざる。
   文面は既存の veil の aiopt と同じ調子（です・ます、短め）で整える。`aihelp:veil9` / `aihelp:veil13` / `aihelp:veil19` の本文の「罠（…）は {prefix}_trap_mode で足せます（測定用・既定 OFF）。」の後に1文「9段でも迷う局面でまれに人間らしい失着を打つ層は veilN_blunder_mode で足せます（既定 OFF・LOG で記録のみ）。」を足す（N は各盤）。
   - en の .po は既存の veil の扱い（aiopt:veil* の英語エントリがあるか）に合わせる。無ければ足さない。
   - `python tools/compile_mo.py` で .mo を作り直す。
4. `katrain/gui/ai_help.py`: `_VEIL_FAMILY` は接尾辞を問わない正規表現なので変更は要らないはず。確かめて、要るときだけ直す。
5. tests/test_ai_veil.py: `SPEC_DEFAULTS` の 9 / 13 / 19 に4キーを足す（§13.2 の値）。登録の整合（constants の候補値・並び順・config.json のキーと値・.po の aiopt・SETTING_DEFAULTS が揃っていること）を確かめている既存のテストがあれば、キー数の期待値を 16 → 20 に更新し、4キーが確かに入っていることを assert する。無ければ `TestBlunderRegistration` を足す（4キー × 3盤が constants の候補値・並び順（16〜19）・config.json に既定値で入っていて、既定値が候補値に含まれ、jp の .po に `aiopt:veil*_blunder_*` の4つがある）。

### 3. 手順

1. テストを先に（SPEC_DEFAULTS の4キーと登録の assert）→ RED を記録。
2. ai.py（SETTING_DEFAULTS）・constants.py・config.json・.po はパッチスクリプト `<scratchpad>/patch_blunder_t2.py`（crlf_patch・Global Constraint 1）。
3. `python tools/compile_mo.py`。
4. GREEN: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q`、それと i18n・設定の整合を見る既存のテスト（`git grep -ln "compile_mo\|katrain.po\|config.json" tests` で見つかるもの）。GUI の設定画面の表示はコントローラがあとでユーザーに確認してもらう。
5. コミット: `feat(veil): 失着の設定4キー（既定 OFF）を登録する`。

---

## Task 3: 失着の層を韜晦の判定フローに組み込む（S9b・TDD）

状態: 完了（`2f57c438`。資格と不変条件の食い違いは Task 3b で直した）。

要件の正本: spec §13.2〜13.3。Task 1 の定数・純関数・不変条件（kind `blunder`）と Task 2 の設定4キー（SETTING_DEFAULTS・登録・テストの SPEC_DEFAULTS）はコミット済み。

### 1. sticky 状態

`_veil_state` の `setdefault` の既定の dict に `"blunders": 0` を足す（今局で打った失着の数）。

### 2. 新メソッド（Veil9Strategy・`_veil_terminal` の後、`_generate_move` の前）

```python
    def _veil_blunder_draw(self):
        """ON で資格のある手番に打つかの乱数（テストで差し替える）。"""
        return random.random()

    def _veil_blunder_probe(self, gtps, player):
        """失着の深い検証（spec §13.3 手順5）: 各手を1手進めた子局面のクリーン解析を VEIL_BLUNDER_VISITS で1バッチ撃ち、
        {gtp: analysis|None} を返す。_probe_children（クリーン 500v＋hp）を変えずに visits だけ深くするための別経路。"""
```
- 実装は `_probe_children` と同じ方式（`self.game.engines[self.cn.player].request_analysis(self.cn, callback=..., error_callback=..., priority=PRIORITY_EXTRA_AI_QUERY, next_move=Move.from_gtp(gtp, player=player), include_policy=False, visits=VEIL_BLUNDER_VISITS, extra_settings={"ignorePreRootHistory": False})` を全部発行してから `while` で待つ。待ちのループは `_probe_children` と同じく `self.raise_if_discarded()`・`time.sleep(0.01)`・`engine.check_alive(exception_if_dead=True)`）。エラーの手は None。この十数行の類似は plan が求める重複（plan-context の「既存コードの要点」）。

```python
    def _veil_blunder(self, cands, player, best_gtp, lead, root_wr, in_yose, reserve, cap, info):
        """S9b 失着の層（spec §13.3）。返り値 (outcome, stage_hp, fetched)。

        outcome は打つときだけ (result, tier, kind, fields)、それ以外は None。stage_hp は親局面の humanSL（撃っていなければ
        None）、fetched はこの手番で親局面の humanSL を撃ったか（S11 が同じ手番で2回撃たないため）。
        mode 0 なら何もしない（クエリ 0 本・info に何も足さない）。"""
```
手順（§13.3 のとおり。`info["blunder"]` にその手番の結末を1つ書く）:
1. `mode = int(self._setting("blunder_mode"))`。`mode <= 0` → `return None, None, False`。
2. 関門（クエリ 0 本）: `in_yose` が真・`root_wr is None`・`root_wr < VEIL_BLUNDER_MIN_WR`・`lead < reserve + VEIL_BLUNDER_MARGIN + cap`・（`mode >= 2` のとき）`state["blunders"] >= int(self._setting("blunder_per_game"))` のどれか → `info["blunder"] = "gate"`・`return None, None, False`。
3. `stage_hp = self._veil_parent_hp(info)`（info["queries"] はこのメソッドの中で +1 される）。humanPolicy が無い → `info["blunder"] = "no_hp"`・`return None, stage_hp, True`。
4. `hp_of = enigma9_hp_lookup(human_policy, self.game.board_size)`・`best_hp = hp_of(best_gtp)`・`max_loss = float(self._setting("blunder_max_loss"))`・
   `rows0 = veil_blunder_candidates(self._veil_candidates(cands, player), best_gtp, best_hp, hp_of, float(self._setting("blunder_hp_ratio")), cap, max_loss)`。空 → `"no_cand"`（stage_hp, True を返す）。
5. `probes = self._veil_blunder_probe([best_gtp] + [c["gtp"] for c in rows0], player)`・`info["queries"] += 1 + len(rows0)`。best の `enigma9_verified_metrics(probes.get(best_gtp), player)` の lead_after が None → `"no_probe"`。
6. 各候補: `lead_after, wr_after = enigma9_verified_metrics(probes.get(gtp), player)`。lead_after None の候補は捨てる（ログ）。`row = {**c, "vloss": best_lead_after - lead_after, "lead_after": lead_after, "wr_after": wr_after}`。1行ログ（`self._log(f"Blunder {gtp}: raw=.. vloss=.. hp=.. wr=.. lead_after=.. ok=..")`）。`veil_blunder_ok(row, cap, max_loss, reserve, lead)` の手だけ集めて `pick = veil_blunder_pick(ok_rows)`。None → `"rejected"`。
7. `fields = {"blunder_gtp": pick["gtp"], "blunder_vloss": pick["vloss"], "blunder_hp": pick["hp"], "blunder_best_hp": best_hp, "blunder_wr": pick["wr_after"], "blunder_lead_after": pick["lead_after"]}`。
   - `mode == 1`（影）: `info["blunder"] = "shadow"`・`info.update(fields)`・ログ `Blunder shadow: ...`・`return None, stage_hp, True`（上限は数えない）。
   - `mode >= 2` で `self._veil_blunder_draw() >= VEIL_BLUNDER_PROB`: `info["blunder"] = "skipped"`・`info.update(fields)`・`return None, stage_hp, True`。
   - 打つ: `bounds = {"vloss": pick["vloss"], "max_loss": max_loss, "lead": lead, "reserve": reserve, "margin": VEIL_BLUNDER_MARGIN, "wr_after": pick["wr_after"], "min_wr": VEIL_BLUNDER_MIN_WR}`。`veil_invariant_ok(pick["gtp"], best_gtp, {d["move"] for d in cands}, "blunder", bounds)` が偽 → `return (self._veil_violation(pick["gtp"], "blunder", bounds), "failsafe", "best", {"why": "invariant"}), stage_hp, True`（`info["blunder"]` は `"invariant"`）。
     真 → `state["blunders"] += 1`・`info["blunder"] = "played"`・ログ `Blunder: played X (vloss .., hp .., best hp ..) instead of best`・
     `return ((Move.from_gtp(pick["gtp"], player=player), f"{self.LABEL}: human-like blunder {gtp} (verified loss {vloss:.2f}, hp {hp:.1%} vs best {best_hp:.1%}) instead of {best_gtp}."), "blunder", "blunder", {**fields, "raw": pick["loss"], "vloss": pick["vloss"], "hp": pick["hp"]}), stage_hp, True`。

### 3. `_veil_move` への組み込み

- S9（予算）のログの直後、`# ---- S10 生の候補プール` の前に:
```python
        # ---- S9b 失着（spec §13。blunder_mode 0 なら何もしない）----
        blunder, stage_hp, hp_fetched = self._veil_blunder(
            cands, player, best_gtp, lead, root_wr, in_yose, reserve, cap_phase, info
        )
        if blunder is not None:
            result, tier, kind, fields = blunder
            return finish(result, tier, kind, **fields)
```
- S11 の `stage_hp = self._veil_parent_hp(info)` を `if not hp_fetched:` の条件付きにする（同じ手番で親局面の humanSL を2回撃たない。fetched が真で stage_hp が None なら S11 の「HumanSL unavailable」の分岐にそのまま落ちる）。
- mode 0 のときは今と完全に同じ（クエリ数・info のキー・選ぶ手）。

### 4. テスト（tests/test_ai_veil.py・TDD）

`_Harness` を継承した `TestBlunder`（9路・Veil9Strategy）を足す。`_strategy` に手を入れず、テストの中で `s._veil_blunder_probe = lambda gtps, player: {...}`・`s._veil_blunder_draw = lambda: 0.0` のように差し替える（子局面は `_child(lead, wr)["clean"]` を使うと打つ側視点で作れる）。
9路の既定（SPEC_DEFAULTS）: reserve 3.0・max_loss 3.0（cap）・blunder_max_loss 6.0 → 関門の lead は 3 + 5 + 3 = 11 以上、root 勝率 0.95 以上。
候補の作り方の例: `hp={"E5": 0.40, "G3": 0.35, "D4": 0.10, "F6": 0.08}`（G3 の hp 0.35 >= 0.7 × 0.40 = 0.28・`_Harness.CANDS` の G3 は loss 3.8 > cap 3.0）。プローブ: E5 → lead 20・wr 0.99、G3 → lead 15.5・wr 0.97（vloss 4.5）。`settings={"veil9_blunder_mode": 1}` など。

テストすること（どれも `logs`・`s.last_decision_info`・`s.queries`・返り値の手で確かめる）:
1. mode 0（既定）: `last_decision_info` に `"blunder"` キーが無い・`_veil_blunder_probe` が呼ばれない・parent hp のクエリ数が今と同じ。
2. mode 1（影）: `blunder == "shadow"`・`blunder_gtp == "G3"`・`blunder_vloss ≈ 4.5`・打った手は G3 の失着ではない（kind が "blunder" でない）・`s.queries.count("parent hp") == 1`（S11 と共有）・state の blunders は 0 のまま。
3. mode 2・draw 0.0: 打つ手が G3・`tier == kind == "blunder"`・`game._veil_state["veil9"]["blunders"] == 1`・`Decision:` 行がログにある。同じ game で2手目（同じ条件）→ 上限で `blunder == "gate"`（プローブが呼ばれない）。
4. mode 2・draw 0.99: `blunder == "skipped"`・通常の流れの手。
5. 関門: lead 10.9（< 11）→ "gate"・parent hp は失着の層から撃たれない（通常の流れの分だけ）。wr 0.94 → "gate"。ヨセ（`game._veil_state = {"veil9": {"endgame": True, "close_drift": 0.0, "ledger": [], "blunders": 0}}` などで sticky のヨセにする）→ "gate"。
6. 候補なし（G3 の hp 0.20 < 0.28）→ "no_cand"・プローブが呼ばれない。
7. 資格なし: G3 の検証済み vloss 6.5（> 6.0）→ "rejected"。wr_after 0.94 → "rejected"。lead_after 7.9（< 3 + 5）→ "rejected"。
8. best のプローブが None → "no_probe"。
9. 不変条件の違反（monkeypatch で `ai_module.veil_invariant_ok` を kind "blunder" のとき False にする）→ ERROR ログ（OUTPUT_ERROR）＋最善手・tier "failsafe"・kind "best"・why "invariant"。
10. `_veil_blunder_probe` が例外 → S0 のフェイルセーフで最善手（既存の例外経路）。
11. 白番（`player="W"`）でも mode 2 で同じ手を打つ（lead / wr は打つ側視点で渡す既存の仕組み）。

### 5. 手順

1. テスト → RED を記録。
2. パッチスクリプト `<scratchpad>/patch_blunder_t3.py`（crlf_patch）で ai.py を変える。
3. GREEN: `python -m pytest tests/test_ai_veil.py -q` と、既存の戦略テスト（`python -m pytest tests/test_ai_mimic13.py -q` と enigma 系のテストファイル）と登録系（`python -m pytest tests/test_ai_help_text.py -q` ほか Task 2 が挙げたもの）。
4. コミット: `feat(veil): 失着の層（S9b）を判定フローに組み込む（既定 OFF・記録のみ／ON）`。

---

## Task 3b: 失着の資格に root リードの条件を足す（Task 3 のレビューで追加）

状態: 完了（`c23977b8`）。

目的: 資格 `veil_blunder_ok` は深い読みの lead_after だけを見ていたので、root リードが深い読みより小さい（探索のゆれ）と、
資格を通った失着が不変条件（kind `blunder`・root リード基準）で落ちて ERROR＋最善手になった。資格にも
`lead − max(0, vloss) >= reserve + margin` を足し（シグネチャに `lead`）、候補の値（`blunder_gtp` ほか）はどの結末でも
`Decision:` に残す。spec §13.3 手順6 も同じ条件に直した。

変えたファイル: `katrain/core/ai.py`・`tests/test_ai_veil.py`・spec §13.3。
コミット: `fix(veil): 失着の資格に root リードの条件を足し、不変条件との食い違いをなくす`

---

## Task 4: 文書（後で・段階3b の校正結果を master に入れてから）

状態: Task 6a・6b に分けて行った（master の校正結果は `8274ab16` で取り込み済み）。

spec §13 の状態の行、`.claude/rules/ai-parameters.md` の veil の表（4キー）・定数・`Decision:` の kind / why、`.claude/rules/ai-strategies.md` の韜晦の段落、マニュアル `docs/manual/src/06d_ai_parity.html` の表と説明（`python tools/build_manual.py`）、ai.py の Veil9Strategy の docstring。
校正結果の文書（同じファイルの別の段落）と衝突しないよう、コントローラが master の校正コミットをこのブランチに取り込んでから行う。

## Task 5: 13路の既定値を段階1b の loose にする（ユーザーの決定 2026-09-25）

状態: 完了（`fe9979c3`）。

目的: 13路の既定を loose の7キー（free_loss 0.4・spend_rate 1.0・max_loss 6.0・yose_max_loss 2.0・dominant_hp 1.01〈OFF〉・
dominant_max_loss 3.0・natural_ratio 0.1）にする。安全条件（reserve 5.0・min_winrate 0.85）・失着の4キー・9路・19路は変えない。
根拠は `docs/superpowers/specs/calibration-data/selfplay/veil13-campaign.md` の「段階1b」「段階3b」「境界線と推奨」。

変えたファイル: `katrain/core/ai.py`（`Veil13Strategy.SETTING_DEFAULTS` と docstring）・`katrain/config.json`（`ai:veil13`）・
`tests/test_ai_veil.py`（`CALIBRATED_DEFAULTS[13]`・パッケージ config.json と既定値の一致の assert）。
コミット: `feat(veil): 13路の既定値を段階1b の loose にする（安全条件は据え置き）`

---

## Task 7: 決着局面の即決（S13）を打つ前に2手だけプローブで確かめる（勝ちの安全の修正）

状態: 完了（`3f2cda6d`）。

目的: 失着 ON の接戦ストレス（`blunder13-on-p3`・seed 1010）で、S13 が生の loss だけで打った手（生 0.36 目 → 実損 16.3 目）で
勝ちが持碁になった。打つ前に best と候補の子局面をクリーン 500v＋hp でプローブし、純関数 `veil_decided_verified_ok`
（vloss <= F_eff + 0.3・lead − vloss >= reserve・着手後勝率 >= min_winrate）を満たさなければ打たずに S14 以降の通常の流れへ
進む（`decided_rejected`）。

変えたファイル: `katrain/core/ai.py`・`tests/test_ai_veil.py`・spec §4 S13（と §4.1 のクエリ数・§9）。
コミット: `fix(veil): 決着局面の即決を打つ前に2手だけプローブで確かめる`

### Task 7b: Task 7 のレビューの軽微な指摘

状態: 完了（`7cd69593`）。

目的: 退けた即決の値（`decided_vloss`・`decided_wr`）も `Decision:` に残す。通しテストで F_eff と reserve の渡し方を境界の両側で
固定し、13路（`Veil13Strategy`）でも事件の形の即決を打たないことを確かめる。

変えたファイル: `katrain/core/ai.py`・`tests/test_ai_veil.py`。
コミット: `test(veil): 即決の検証のフローを F_eff・reserve・13路で固定し、却下の値を記録する`

---

## Task 6a: 文書の仕上げ（spec・計画・開発者向けルール・INDEX）

目的: 失着の層（§13）・13路の既定 loose・S13 の2手プローブを、spec（状態の行・§6.1・§13.3・§13.4・§13.5）・この計画・
`plans/2026-09-23-veil-strategy.md`（Task 17 の追記）・`.claude/rules/ai-parameters.md`・`.claude/rules/ai-strategies.md`・
`docs/superpowers/specs/INDEX.md` に反映する。数値は `veil13-campaign.md` から写す。

コミット: `docs(veil): 失着の層・13路の既定 loose・即決の検証を spec とルールに反映`

## Task 6b: 文書の仕上げ（マニュアル・GUI のヘルプ文・ai.py の docstring）

目的: 同じ内容をユーザー向けの文書に反映する: マニュアル `docs/manual/src/06d_ai_parity.html`（→ `python tools/build_manual.py`）・
jp / en の `katrain.po` の `aihelp:veil*`（→ `python tools/compile_mo.py`）・`Veil9Strategy` / `Veil13Strategy` の docstring。

コミット: `docs(veil): マニュアルと GUI のヘルプに失着の層・13路の既定 loose・即決の検証を反映`

---

## 仕上げ（コントローラ・当初の Task 5）

当初の順（全体スイート → マージ → ユーザー設定 → 影 → ON）ではなく、マージの前に計測した。実際に行った順:

1. 全体スイート（Task 3b の後・`c23977b8`）: 実施済み。
2. 影の計測（spec §13.4 の 1・`blunder13-shadow`・`c23977b8`）: 実施済み。
3. ON の計測（§13.4 の 2・通常の相手 `blunder13-on`）: 実施済み（その前に Task 5 で 13路の既定を loose にした＝`fe9979c3`）。
4. ON の接戦ストレス（`blunder13-on-p3`）: 実施済み。持碁の1局から Task 7・7b（S13 の検証）を足した。
5. 結果とユーザーの決定の記録（`veil13-campaign.md`・`24576557` / `cc8cf778`）: 実施済み。続けて文書（Task 6a → 6b）。
6. master へのマージ: **未実施**（コントローラが後で行う）。
7. ユーザー設定（`~/.katrain/config.json` の `ai:veil*` に失着の4キー × 3盤・`ai:veil13` を loose に揃える。編集前の写しを残す。
   メインセッション・KaTrain 停止中）: **未実施**（マージの後にコントローラが行う）。

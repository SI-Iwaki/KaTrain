# 一致率ひかえめ（韜晦）の「序盤の研究外し」実装計画（Plan A）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

日付: 2026-09-26
実行: サブエージェント駆動（worktree `C:\Users\iwaki\Documents\katrain-1.17.1.1\katrain-1.17.1.1\.claude\worktrees\veil-opening`・ブランチ `veil-opening`）。タスクは順に1つずつ、実装 → レビュー → 修正。**この計画（Plan A）を先に終え、その後に同じブランチで Plan B（spec §16 のハーネスの 9路対応と計測）を実行する。** master へのマージは Plan B の後。

**Goal:** 韜晦（veil9/13/19・画面の名前は「一致率ひかえめ」）に、序盤の窓（打つ手の番号〈両者の通算〉が `<prefix>_open_moves` 以下）の手番を同じ盤サイズの難解＋にユーザー設定のまま任せる層（既定 OFF）を足し、相手に定跡を打たせない研究外しの手を打てるようにする。あわせてハーネスの韜晦の要約を、この層の手を別に数える形にする。

**Architecture:** `Veil9Strategy._veil_move` の S4（一致率）の直後・S5（リード）の前に S4b として新メソッド `_veil_open` を呼ぶ。窓の判定・確認は純関数（`veil_open_index` / `veil_open_window` / `veil_open_ok`）、任せる先は差し替えられるメソッド `_veil_open_delegate()`（ponder を止めただけの難解＋の派生クラス `VeilOpenEnigma{9,13,19}PlusStrategy` を作る）。`open_moves` 0 では S4b は何もしない（root に触れず、記録も足さない）。ハーネスの `_decision_metrics` は tier `opening` を安全の警報から外し、要約 `opening` を足す。

**Tech Stack:** Python 3.12・pytest・KaTrain（`katrain/core/ai.py` の韜晦）・gettext（`.po` → `tools/compile_mo.py`）・マニュアル（`tools/build_manual.py`）・自己対局ハーネス（`katrain_debug/selfplay_stats.py`）。

**Spec:** `docs/superpowers/specs/2026-09-23-veil-strategy-design.md` の §15（要件の正本）。文脈は §3.1（ponder を使わない理由）・§4（1手の決定フロー）・§5（一致率）・§11（登録・触るファイル）・§13・§14（前の2層）。§16 は Plan B の範囲。

## Global Constraints

1. **CRLF・black 未整形の既存ファイルは python のパッチスクリプトだけで変える。** 対象: `katrain/core/ai.py`・`katrain/core/constants.py`・`katrain/config.json`（LF。crlf_patch は LF のファイルもそのまま扱う）・`katrain/i18n/locales/*/LC_MESSAGES/katrain.po`・`docs/**/*.md`・`docs/manual/src/*.html`・`.claude/rules/*.md`・`CLAUDE.md`、**そして `tests/test_ai_veil.py`**（CRLF。forced のテストの数行が black 未整形なので、Edit / Write で触ると PostToolUse の black フックがその行まで整形してしまう）。Edit / Write で `.py` を書くと black フックがファイル全体を整形する（ai.py は 1 万行超の未整形ファイル）。
   - パッチの道具は `crlf_patch.py`（`patch(path, [(old, new, count)])`＝old/new は LF で書く。件数が合わなければ何も書かずに止まる。`append(path, text)`）。**コピー元: `C:\Users\iwaki\AppData\Local\Temp\claude\C--Users-iwaki--katrain\fa4754c0-234e-47cd-8f07-eff2747ac3ec\scratchpad\crlf_patch.py`**。自分のセッションの scratchpad ディレクトリ（システムプロンプトに書かれている。以下 `<scratchpad>`）にコピーして使う。コピー元が消えていたら File Structure 節の全文で作り直す。
   - パッチスクリプトは `<scratchpad>/patch_open_tN.py` に書き、worktree のルートで `python <scratchpad>/patch_open_tN.py` と実行する。スクリプトの先頭で `sys.path.insert(0, r"<scratchpad の実パス>")` してから `from crlf_patch import patch`。old/new は `r'''...'''`（raw の三重単引用符）で書く（`.po` の `\n` を文字のまま保つため。中身に `'''` は無い）。
   - 例外: `katrain_debug/selfplay_stats.py` と `tests/test_selfplay_stats.py` は black 整形済み（CRLF）なので Edit ツールで直接変えてよい（フックの black は新しい行しか変えない）。変えた後に `file` で CRLF のままか確かめる。
   - `tests/test_ai_veil.py` に足すコードは black 形式（行長 120・二重引用符・分割した呼び出しは末尾カンマ）で書く。貼った後に `python -m black --check --diff -l 120 -t py312 tests/test_ai_veil.py` を見て、**自分が足した行に差分が出ていたら、その行を crlf_patch のパッチスクリプトで直す**（Edit / Write は使わない＝black フックがファイル全体を整形し、下の残すべき既存の差分まで変えてしまう）（forced のテストの既存の差分〈SPEC_DEFAULTS の9路の2行の行末コメント・`Forced C7:` の長い assert・`veil_invariant_ok` の lambda・`("failsafe", "best", "invariant", "invariant")` の assert・`cheap = [...]` の行。ハンク 3 つ〉は無視・直さない）。
2. 触ってよいのは韜晦（veil の純関数・`Veil9/13/19Strategy`・新しい `VeilOpenEnigma*PlusStrategy`）とその登録・文書・テスト、それに `katrain_debug/selfplay_stats.py` の `_decision_metrics`（spec §15.4）。**難解（Enigma*）・擬態（Mimic13）・その他の戦略のコードと共有メソッド（`_probe_children`・`_start_ponder` など）は変えない**（派生クラスを足すのは可）。Plan B の範囲（spec §16.2 のすべて＝`recon_logs` / `offline_report` / `calib_targets` / `CALIB_BINS` / プール / calibrate / 投了の手数 / 定跡を知る相手 / `window_stats.py` / 設定の写しと任せる先の指紋）には触らない。
3. KataGo・KaTrain・ハーネスを起動しない（テストはすべてスタブ）。`C:\Users\iwaki\.katrain\config.json`（ユーザー設定）は**どのタスクでも触らない（コントローラも）**。GUI にスライダーを出すにはユーザー設定の `ai:veilN` に `"veilN_open_moves": 0` が要る（`katrain/gui/popups.py` 491 行の `mode_settings = self.katrain.config(f"ai/{strategy}")` と 497 行のループがユーザー設定にあるキーしか出さない）が、それは Plan A の範囲外＝Task 7 でコントローラが結果の報告と一緒にユーザーに伝え、編集するかは Plan A の外で決める。変えるのはパッケージの `katrain/config.json` だけ。
4. 既存のテストを弱めない。**`open_moves` 0（既定）の挙動は1バイトも変えない**＝クエリ数・`Decision:` の中身・選ぶ手・`_veil_state` の中身が今と同じで、`game.root` にも触れない。窓の外の手番も同じ（`open` で始まるキーを足さない）。
5. 安全条件の値（reserve・min_winrate・`SAFETY_DEFAULTS`）と既存の既定値は変えない。新しいキーのコードの既定は3盤とも 0（OFF）。
6. コミットは日本語の Conventional Commits、末尾に空行＋`Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`（`git commit -m "<件名>" -m "<本文>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`）。
7. テスト: 自分のタスクの focused テストと、タスクが挙げる関連テスト。**全体スイートはコントローラが Task 7 で流す**。既知の失敗 `tests/test_ai.py::TestAI::test_ai_strategies` は対象外（`--ignore=tests/test_ai.py`）。
8. i18n を変えたら `python tools/compile_mo.py`、マニュアルの src を変えたら `python tools/build_manual.py`（どちらも worktree のルートで）。
9. 行番号は 2026-09-26 のブランチ先頭（`76105598`）で確かめた値。前のタスクの挿入でずれるので、パッチは行番号ではなく old の文字列で当てる（crlf_patch が件数を確かめる）。

## 共有インターフェース（Plan B と同じ名前を使う）

- 設定キー `f"{prefix}_open_moves"`（prefix は veil9 / veil13 / veil19）。int。コードの既定は3盤とも 0（OFF）。`SETTING_DEFAULTS` の forced の4キーの直後（最後）・`AI_OPTION_ORDER` は 24。
- `katrain/core/ai.py` のモジュール定数 `VEIL_OPEN_DELEGATES = {9: AI_ENIGMA_9_PLUS, 13: AI_ENIGMA_13_PLUS, 19: AI_ENIGMA_19_PLUS}`（値は `"ai:enigma9plus"` など）。Plan B のハーネスがこれを import して、`open_moves` > 0 のアームが任せる先の設定の節を知る。
- 純関数 `veil_open_index(depth, n_setup) -> int`・`veil_open_window(index, open_moves) -> bool`（`open_moves > 0 and index < open_moves`）・`veil_open_ok(chosen) -> bool`（`chosen is not None and chosen != "pass"`）。
- `Veil9Strategy._veil_open_delegate(self) -> (strategy_instance, strategy_key)`: 同じ盤の `Enigma*PlusStrategy` の派生クラス（`VeilOpenEnigma9PlusStrategy` / `VeilOpenEnigma13PlusStrategy` / `VeilOpenEnigma19PlusStrategy`。登録しない・`_ponder_applies` が False・`KEY_PREFIX` / `SETTING_DEFAULTS` はそのまま）を `dict(self.game.katrain.config(f"ai/{key}") or {})` で作り、`delegate.cn = self.cn`・`delegate.query_generations = self.query_generations` にして返す。
- 任せた手番の記録（`last_decision_info`。ハーネスは moves.jsonl の列 `decision_<field>` に平らにする）: tier `"opening"`・kind `"opening"`（手が best と違う）/ `"best"`・why `"opening"` / `"opening_best"`・`open` `"played"`・`open_index`（int）・`open_src`（`"ai:enigma9plus"` など）・`open_in_cands`（bool）・`open_secs`（float）・`open_thoughts`（str・先頭 200 字）・`lead` と `root_wr`（打つ側視点・None もありうる）。
  - 任せた手が None / pass の手番: tier `"opening"`・kind `"best"`・why `"invariant"`・`open` `"invariant"`（任せた手番は played でも invariant でも tier `opening`＝Plan B は窓の手番を `decision_tier == "opening"` で数えられる。ほかの不変条件違反の出口の tier failsafe とは違う）。`open_index` `open_src` `open_secs` `open_thoughts` `lead` `root_wr` も残す。
  - 関門の手番（窓の中だが相手の直前パス、または p_match <= `VEIL_TARGET_FLOOR`）: `open` `"gate"` と `open_index` を記録して通常の流れへ（tier / kind / why は通常の流れのもの）。
  - 窓の中の例外の手番（S0 のフェイルセーフ。S4b より前＝S1〜S4 の例外も含む）: `_veil_error` の記録（tier failsafe・kind best・why exception）に `open_index` を足す（`open` は無い）。
  - 窓の外の手番と `open_moves` 0: `open` で始まるキーを1つも足さない。
- `_veil_state()[prefix]["opening"]`: `open` が played かつ kind `"opening"` の手番の数。最初に数えるときだけキーを作る。

## File Structure

| ファイル | 役割 | この計画での変更 |
|---|---|---|
| `katrain/core/ai.py`（CRLF・未整形） | 韜晦の本体 | Task 1: `VEIL_OPEN_DELEGATES`・3 純関数。Task 2: 3 クラスの `SETTING_DEFAULTS` に `open_moves`。Task 3: `VeilOpenEnigma*PlusStrategy`・`_VEIL_OPEN_CLASSES`・`_veil_open_delegate`。Task 4: `_veil_open`（S4b）・`_veil_open_index_or_none`・`_generate_move` / `_veil_error` の `open_index`・docstring |
| `katrain/core/constants.py`（CRLF） | GUI のスライダー | Task 2: `_VEIL_OPEN_MOVES`・`AI_OPTION_VALUES` 3 行・`AI_OPTION_ORDER` 3 行 |
| `katrain/config.json`（LF・パッケージ） | 既定の設定 | Task 2: `ai:veil9/13/19` に `"<prefix>_open_moves": 0` |
| `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po`（CRLF）＋ `.mo` | 画面の説明 | Task 2: jp の `aiopt:veil*_open_moves`・jp の `aihelp:veil9/13/19` に1文・en の `aihelp:veil9/13/19` に1箇条 → `compile_mo` |
| `docs/manual/src/06d_ai_parity.html`（CRLF）＋ `docs/manual/index.html` | ユーザーマニュアル | Task 2: 設定の表に1行。Task 6: 本文の箇条に1つ → `build_manual` |
| `tests/test_ai_veil.py`（CRLF） | 韜晦のテスト | Task 1: `TestOpenPure`。Task 2: `SPEC_DEFAULTS`・`test_open_moves_is_registered`。Task 3: `_Harness` の拡張・`TestOpenDelegate`。Task 4: `TestOpening`・`TestOpening13` |
| `katrain_debug/selfplay_stats.py`（CRLF・black 済み） | ハーネスの集計 | Task 5: `_opening_metrics`・`_veil_unpaid`・`_decision_metrics` |
| `tests/test_selfplay_stats.py`（CRLF・black 済み） | 集計のテスト | Task 5: 2 テスト |
| `.claude/rules/ai-parameters.md`・`.claude/rules/ai-strategies.md`・`CLAUDE.md`・spec・`docs/superpowers/specs/INDEX.md`（すべて CRLF） | 文書 | Task 6 |
| `katrain/gui/ai_help.py` | `aiopt:veil*_<suffix>` の共通文面 | **変更なし**（`_VEIL_FAMILY = re.compile(r"^(veil(?:9|13|19))_(.+)$")`〈29 行〉が接尾辞を問わない） |

`crlf_patch.py` の全文（コピー元が無いときだけ `<scratchpad>/crlf_patch.py` にこの内容で作る）:

```python
"""CRLF のファイルを LF で書いた old/new で置換する（件数が合わなければ何も書かずに止まる）。"""
import sys


def patch(path, edits):
    with open(path, "rb") as f:
        raw = f.read()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    for old, new, count in edits:
        found = text.count(old)
        if found != count:
            sys.exit(f"{path}: expected {count} match(es), found {found}: {old[:80]!r}")
        text = text.replace(old, new)
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def append(path, addition):
    with open(path, "rb") as f:
        raw = f.read()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8").replace("\r\n", "\n")
    if not text.endswith("\n"):
        text += "\n"
    text += addition
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
```

注意: 1つのスクリプトで同じファイルに複数の edit を渡すと、先の edit の結果に後の old を当てる（順に置換）。

---

## Task 1: 序盤の研究外しの純関数と任せる先の表（TDD）

**Files:**
- Modify: `katrain/core/ai.py`（定数は `_VEIL_EPS = 1e-9` の行〈4448〉の直前＝`VEIL_FORCED_PROBES`〈4447〉の後。純関数は `def veil_decided_verified_ok`〈4843〉の直前＝`veil_forced_pick`〈4836〉の後）
- Test: `tests/test_ai_veil.py`（import 群〈16-62〉・`class TestDecidedVerified:`〈693〉の直前に `TestOpenPure`）

**Interfaces:**
- Consumes: `AI_ENIGMA_9_PLUS` / `AI_ENIGMA_13_PLUS` / `AI_ENIGMA_19_PLUS`（ai.py の 21 行目で constants から import 済み）。
- Produces（Task 3・4 と Plan B が使う）:
  - `VEIL_OPEN_DELEGATES = {9: AI_ENIGMA_9_PLUS, 13: AI_ENIGMA_13_PLUS, 19: AI_ENIGMA_19_PLUS}`
  - `veil_open_index(depth, n_setup) -> int`
  - `veil_open_window(index, open_moves) -> bool`
  - `veil_open_ok(chosen) -> bool`

- [ ] **Step 1: 失敗するテストを書く**（パッチスクリプト `<scratchpad>/patch_open_t1_test.py`）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

T = "tests/test_ai_veil.py"
IMPORT1_OLD = r'''    VEIL_FORCED_PROBES,
    VEIL_TERMINAL_MIN_VISITS,
'''
IMPORT1_NEW = r'''    VEIL_FORCED_PROBES,
    VEIL_OPEN_DELEGATES,
    VEIL_TERMINAL_MIN_VISITS,
'''
IMPORT2_OLD = r'''    veil_near_free_ok,
    veil_paid_ok,
'''
IMPORT2_NEW = r'''    veil_near_free_ok,
    veil_open_index,
    veil_open_ok,
    veil_open_window,
    veil_paid_ok,
'''
CLASS_OLD = r'''
class TestDecidedVerified:
'''
CLASS_NEW = r'''
class TestOpenPure:
    """序盤の研究外し（spec §15.3 手順2・6）の純関数と任せる先の表。"""

    def test_delegates_are_the_enigma_plus_of_the_same_board(self):
        assert VEIL_OPEN_DELEGATES == {9: "ai:enigma9plus", 13: "ai:enigma13plus", 19: "ai:enigma19plus"}

    def test_index_is_the_depth_plus_the_root_placements(self):
        assert veil_open_index(0, 0) == 0
        assert veil_open_index(11, 0) == 11
        assert veil_open_index(11, 1) == 12  # board_watch が相手の初手を root の置き石として取り込んだ局

    @pytest.mark.parametrize(
        "index,open_moves,inside",
        [
            (0, 12, True),
            (11, 12, True),  # open_moves − 1
            (12, 12, False),  # open_moves
            (0, 0, False),  # OFF
            (0, None, False),
            (5, 12.0, True),  # スライダーの値は float で来ることがある
        ],
    )
    def test_window(self, index, open_moves, inside):
        assert veil_open_window(index, open_moves) is inside

    def test_window_counts_the_root_placements(self):
        assert veil_open_window(veil_open_index(10, 1), 12) is True
        assert veil_open_window(veil_open_index(11, 1), 12) is False

    @pytest.mark.parametrize("chosen,ok", [(None, False), ("pass", False), ("D4", True), ("J9", True)])
    def test_ok_needs_a_board_move(self, chosen, ok):
        """None と pass は通さない。通常解析の候補に無い手（J9）も通す（難解と同じ）。"""
        assert veil_open_ok(chosen) is ok


class TestDecidedVerified:
'''
patch(T, [(IMPORT1_OLD, IMPORT1_NEW, 1), (IMPORT2_OLD, IMPORT2_NEW, 1), (CLASS_OLD, CLASS_NEW, 1)])
```

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q -k TestOpenPure`
Expected: 収集エラーで FAIL（`ImportError: cannot import name 'VEIL_OPEN_DELEGATES' from 'katrain.core.ai'`）。出力を report に写す。

- [ ] **Step 3: 実装する**（パッチスクリプト `<scratchpad>/patch_open_t1.py`）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

AI = "katrain/core/ai.py"
CONST_OLD = r'''_VEIL_EPS = 1e-9'''
CONST_NEW = r'''# 序盤の研究外し（spec §15.3）で窓の手番を任せる戦略キー＝同じ盤サイズの難解＋（ハーネスもこの表で任せる先の設定の節を知る）
VEIL_OPEN_DELEGATES = {9: AI_ENIGMA_9_PLUS, 13: AI_ENIGMA_13_PLUS, 19: AI_ENIGMA_19_PLUS}
_VEIL_EPS = 1e-9'''
PURE_OLD = r'''
def veil_decided_verified_ok('''
PURE_NEW = r'''
def veil_open_index(depth, n_setup):
    """序盤の窓の番号（spec §15.3 手順2）: 打つ手の直前の手数 depth ＋ root の置き石の数 n_setup。打つ手の番号は index + 1。

    board_watch が相手の初手を root の置き石として取り込んだ局でも手数がずれない。局の途中で盤を取り込み直すと
    盤上の石はすべて root の置き石になる＝index が大きく窓の外になる（途中から研究外しを始めない）。
    """
    return int(depth) + int(n_setup)


def veil_open_window(index, open_moves):
    """序盤の窓の中か（spec §15.3 手順2）: open_moves > 0 かつ index < open_moves。open_moves は float や None で
    来ることがあるので int に丸める（None・0 以下は OFF）。"""
    n = int(open_moves or 0)
    return n > 0 and index < n


def veil_open_ok(chosen):
    """任せた手の確認（spec §15.3 手順6）: None でも pass でもないこと。通常解析の候補に無い手も通す（難解と同じ）。"""
    return chosen is not None and chosen != "pass"


def veil_decided_verified_ok('''
patch(AI, [(CONST_OLD, CONST_NEW, 1), (PURE_OLD, PURE_NEW, 1)])
```

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q`
Expected: すべて PASS（`TestOpenPure` の 13 件を含む）。`git diff --stat` で ai.py の変更が挿入だけ。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 序盤の研究外しの窓・確認の純関数と任せる先の表を追加" -m "spec §15.3 手順2・6。判定フローへの組み込みは後のタスク。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: 設定 `open_moves`（既定値・登録・GUI の説明・マニュアルの表）

**Files:**
- Modify: `katrain/core/ai.py`（`SETTING_DEFAULTS`: Veil9 の `"forced_max_loss": 5.0, ...`〈4979〉・Veil13 の `"forced_max_loss": 10.0,`〈5845〉・Veil19 の `"forced_max_loss": 15.0,`〈5885〉の後）
- Modify: `katrain/core/constants.py`（`_VEIL_FORCED_MAX_LOSS`〈262-266〉の後に `_VEIL_OPEN_MOVES`。`AI_OPTION_VALUES` の `"veilN_forced_max_loss": _VEIL_FORCED_MAX_LOSS[N],`〈574・598・622〉の後。`AI_OPTION_ORDER` の `"veilN_forced_max_loss": 23,`〈873・897・921〉の後）
- Modify: `katrain/config.json`（`"veilN_forced_max_loss": ...`〈394・420・446〉の後）
- Modify: jp の `katrain.po`（`aihelp:veil9/13/19`〈986・992・998〉と、`aiopt:veil*_forced_max_loss`〈2600-2603〉の後に `aiopt:veil*_open_moves`）・en の `katrain.po`（`aihelp:veil9/13/19`〈1298・1304・1310〉）→ `python tools/compile_mo.py`
- Modify: `docs/manual/src/06d_ai_parity.html`（設定の表の `veil*_forced_max_loss` の行〈144〉の後）→ `python tools/build_manual.py`
- Test: `tests/test_ai_veil.py`（`SPEC_DEFAULTS`〈794-876〉の3盤・`TestRegistration` の `def test_debug_cli_names(self):`〈2686〉の直前）

**Interfaces:**
- Produces（Task 4 が `self._setting("open_moves")` で読む）: 接尾辞 `open_moves`（int・既定 0）。画面の並び 24（最後）。候補値は spec §15.2 の表: 9路 0/6/8/10/12/16/20・13路 0/12/20/24/30/40・19路 0/20/30/40/50/60（0 は `OFF`）。

この Task は設定を足して登録するだけで、判定フローでは使わない（Task 4 で使う）。

- [ ] **Step 1: 失敗するテストを書く**（パッチスクリプト `<scratchpad>/patch_open_t2_test.py`）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

T = "tests/test_ai_veil.py"
S9_OLD = r'''        "forced_max_loss": 5.0,      # 13路 10.0・19路 15.0
    },
'''
S9_NEW = r'''        "forced_max_loss": 5.0,      # 13路 10.0・19路 15.0
        # spec §15.2（2026-09-26）
        "open_moves": 0,
    },
'''
S13_OLD = r'''        "forced_max_loss": 10.0,
    },
'''
S13_NEW = r'''        "forced_max_loss": 10.0,
        "open_moves": 0,
    },
'''
S19_OLD = r'''        "forced_max_loss": 15.0,
    },
'''
S19_NEW = r'''        "forced_max_loss": 15.0,
        "open_moves": 0,
    },
'''
REG_OLD = r'''    def test_debug_cli_names(self):
'''
REG_NEW = r'''    @pytest.mark.parametrize("cls,size,prefix,ai_key,const", VEILS, ids=VEIL_IDS)
    def test_open_moves_is_registered(self, cls, size, prefix, ai_key, const):
        """序盤の研究外しの1キー（spec §15.2）: 画面の並びは 24（最後）、候補値は spec の表どおり（0 は OFF）、既定は
        整数の 0（OFF）、jp の概要がこの層（<prefix>_open_moves）を案内する。"""
        from katrain.core.constants import AI_OPTION_ORDER, AI_OPTION_VALUES

        with open(Path(katrain.__file__).parent / "config.json", encoding="utf-8") as f:
            package_ai_conf = json.load(f)["ai"][ai_key]
        windows = {9: [6, 8, 10, 12, 16, 20], 13: [12, 20, 24, 30, 40], 19: [20, 30, 40, 50, 60]}
        key = f"{prefix}_open_moves"
        assert AI_OPTION_ORDER[key] == 24 and list(cls.SETTING_DEFAULTS)[-1] == "open_moves"
        assert AI_OPTION_VALUES[key] == [(0, "OFF")] + [(n, str(n)) for n in windows[size]]
        assert cls.SETTING_DEFAULTS["open_moves"] == 0 and type(cls.SETTING_DEFAULTS["open_moves"]) is int
        assert package_ai_conf[key] == 0 and type(package_ai_conf[key]) is int
        po = (Path(katrain.__file__).parent / "i18n" / "locales" / "jp" / "LC_MESSAGES" / "katrain.po").read_text(
            encoding="utf-8"
        )
        m = re.search(rf'msgid "aihelp:{prefix}"\s*\nmsgstr "(.*)"', po)
        assert m and f"{prefix}_open_moves" in m.group(1), prefix

    def test_debug_cli_names(self):
'''
patch(T, [(S9_OLD, S9_NEW, 1), (S13_OLD, S13_NEW, 1), (S19_OLD, S19_NEW, 1), (REG_OLD, REG_NEW, 1)])
```

既存の `test_defaults_match_the_spec`（`TestStrategyClass`）・`test_defaults_match_the_spec_table`（`TestBoardFamily`）・`test_defaults_in_gui_options_and_package_config`・`test_jp_explains_every_slider_once_for_the_family`・`test_en_overview_has_one_bullet_per_slider`・`test_manual_defaults_table_matches_setting_defaults`（`TestRegistration`）と `tests/test_ai_help_text.py` の `TestJapaneseCoverage` は、キーが増えると自動で新しいキーも確かめる（テストは変えない）。

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q -k "Registration or defaults or Board or Japanese"`
Expected: FAIL（`SETTING_DEFAULTS` に `open_moves` が無い〈`EXPECTED_DEFAULTS` と不一致〉・`AI_OPTION_ORDER` に `veil9_open_moves` が無い〈KeyError〉など）。出力を report に写す。

- [ ] **Step 3: 実装する**（パッチスクリプト `<scratchpad>/patch_open_t2.py`）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

# ---- 1. ai.py の SETTING_DEFAULTS（3 クラス・最後のキー）----
patch(
    "katrain/core/ai.py",
    [
        (
            r'''        "forced_max_loss": 5.0,     # 1手の損の上限（検証済み・目。ヨセは yose_max_loss）
    }
''',
            r'''        "forced_max_loss": 5.0,     # 1手の損の上限（検証済み・目。ヨセは yose_max_loss）
        "open_moves": 0,            # 序盤の研究外し（spec §15）: 打つ手の番号（両者の通算）がこの値以下の手番を難解＋に任せる（0 = OFF）
    }
''',
            1,
        ),
        (
            r'''        "forced_max_loss": 10.0,
    }
''',
            r'''        "forced_max_loss": 10.0,
        "open_moves": 0,
    }
''',
            1,
        ),
        (
            r'''        "forced_max_loss": 15.0,
    }
''',
            r'''        "forced_max_loss": 15.0,
        "open_moves": 0,
    }
''',
            1,
        ),
    ],
)

# ---- 2. constants.py ----
edits = [
    (
        r'''    19: [8.0, 10.0, 15.0, 20.0],
}

AI_OPTION_VALUES = {
''',
        r'''    19: [8.0, 10.0, 15.0, 20.0],
}
# 韜晦の序盤の研究外し（veil*_open_moves・spec §15.2）。打つ手の番号（両者の通算）がこの値以下の手番を難解＋に任せる。0 = OFF
_VEIL_OPEN_MOVES = {
    9: [(0, "OFF"), (6, "6"), (8, "8"), (10, "10"), (12, "12"), (16, "16"), (20, "20")],
    13: [(0, "OFF"), (12, "12"), (20, "20"), (24, "24"), (30, "30"), (40, "40")],
    19: [(0, "OFF"), (20, "20"), (30, "30"), (40, "40"), (50, "50"), (60, "60")],
}

AI_OPTION_VALUES = {
''',
        1,
    ),
]
for n in (9, 13, 19):
    edits.append(
        (
            f'    "veil{n}_forced_max_loss": _VEIL_FORCED_MAX_LOSS[{n}],\n',
            f'    "veil{n}_forced_max_loss": _VEIL_FORCED_MAX_LOSS[{n}],\n    "veil{n}_open_moves": _VEIL_OPEN_MOVES[{n}],\n',
            1,
        )
    )
    edits.append(
        (
            f'    "veil{n}_forced_max_loss": 23,\n',
            f'    "veil{n}_forced_max_loss": 23,\n    "veil{n}_open_moves": 24,\n',
            1,
        )
    )
patch("katrain/core/constants.py", edits)

# ---- 3. パッケージの config.json（LF）----
patch(
    "katrain/config.json",
    [
        (
            f'            "veil{n}_forced_max_loss": {v}\n',
            f'            "veil{n}_forced_max_loss": {v},\n            "veil{n}_open_moves": 0\n',
            1,
        )
        for n, v in ((9, "5.0"), (13, "10.0"), (19, "15.0"))
    ],
)

# ---- 4. jp の .po: aiopt（共通文面）と aihelp（3盤に1文ずつ）----
JP = "katrain/i18n/locales/jp/LC_MESSAGES/katrain.po"
AIOPT_OLD = r'''6 目を超えるような大きな損の手も出ます。"
'''
AIOPT_NEW = r'''6 目を超えるような大きな損の手も出ます。"

msgid "aiopt:veil*_open_moves"
msgstr ""
"序盤の研究外し（手数）\n"
"打つ手の番号（両者の通算）がこの値以下の手番を、同じ盤サイズの難解＋に、難解＋の画面の設定のまま任せます（相手に定跡どおりに打たせない研究外しの手。9路 12 なら各色 6 手）。窓の中は難解＋と同じ挙動で、この戦略の勝ちの安全条件（{p}_reserve・{p}_min_winrate）・一致率の目標・自然さの床は使わず、難解＋の損の上限と勝率の下限に従います（難解＋並みの危険を受け入れる設定です）。相手が直前にパスした手番と、一致率が 15% 以下の手番は任せません。窓の後の手番はふつうの一致率ひかえめに戻ります。難解＋（13路・19路）の序盤を HumanStyle 9段で打つ手数の間は、研究外しではなく 9段の手になります。窓の中も着手後の先読みはしないので、難解＋を単独で使うより着手が遅くなることがあります。OFF で使いません（既定）。"
'''
FORCED_SENTENCE = "で足せます（既定 OFF・LOG で記録のみ。ON にすると 20 局に 1 局ほどの負けを許します）。"
OPEN_SENTENCE = {
    9: "序盤の研究外しの層は veil9_open_moves で足せます（既定 OFF。ON にすると、打つ手の番号〈両者の通算〉がこの値以下の手番を難解＋（9路）に難解＋の設定のまま任せ、相手に定跡どおりに打たせない手を打ちます。窓の中は難解＋と同じ挙動で、この戦略の勝ちの安全条件と一致率の目標は使いません）。",
    13: "序盤の研究外しの層は veil13_open_moves で足せます（既定 OFF。ON にすると、打つ手の番号〈両者の通算〉がこの値以下の手番を難解＋（13路）に難解＋の設定のまま任せ、相手に定跡どおりに打たせない手を打ちます。窓の中は難解＋と同じ挙動で、この戦略の勝ちの安全条件と一致率の目標は使いません。難解＋（13路）の序盤を HumanStyle 9段で打つ手数の間は 9段の手になります）。",
    19: "序盤の研究外しの層は veil19_open_moves で足せます（既定 OFF。ON にすると、打つ手の番号〈両者の通算〉がこの値以下の手番を難解＋（19路）に難解＋の設定のまま任せ、相手に定跡どおりに打たせない手を打ちます。窓の中は難解＋と同じ挙動で、この戦略の勝ちの安全条件と一致率の目標は使いません。難解＋（19路）の序盤を HumanStyle 9段で打つ手数の間は 9段の手になります）。",
}
jp_edits = [(AIOPT_OLD, AIOPT_NEW, 1)]
for n in (9, 13, 19):
    old = f"veil{n}_forced_mode {FORCED_SENTENCE}"
    jp_edits.append((old, old + OPEN_SENTENCE[n], 1))
patch(JP, jp_edits)

# ---- 5. en の .po: aihelp の最後の箇条の後に1箇条（3盤とも同じ文・\n は文字のまま）----
EN = "katrain/i18n/locales/en/LC_MESSAGES/katrain.po"
EN_OLD = r'''but also moves that lose more than 6 points."'''
EN_NEW = r'''but also moves that lose more than 6 points.\n* Opening window: turns whose move number (both players counted) is at most this value are handed to Enigma+ for the same board size, with Enigma+'s own settings, to play moves that take the opponent out of the opening they know (12 on 9x9 means 6 moves per color). Inside the window Enigma+ decides alone: this mode's reserve, winrate floor, target rate and naturalness floor do not apply (Enigma+'s own loss cap and winrate floor do). Not right after an opponent pass or when the match rate is 15% or lower. After the window the normal rules return. OFF by default."'''
patch(EN, [(EN_OLD, EN_NEW, 3)])

# ---- 6. マニュアルの設定の表（既定欄は 13路が本文、9路・19路は span）----
MAN = "docs/manual/src/06d_ai_parity.html"
MAN_OLD = r'''6 目を超える損の手も出る）</td></tr>
'''
MAN_NEW = r'''6 目を超える損の手も出る）</td></tr>
      <tr><td>veil*_open_moves</td><td>OFF<span class="jp">9路 OFF・19路 OFF</span></td><td>9路 OFF/6〜20・13路 OFF/12〜40・19路 OFF/20〜60</td><td>序盤の研究外し。打つ手の番号（両者の通算）がこの値以下の手番を、同じ盤サイズの難解＋に難解＋の設定のまま任せる（9路 12 なら各色 6 手）</td><td><span class="up">上げる</span>相手に定跡を打たせない手番が増え、一致率が下がる。窓の中は勝ちの安全条件より研究外しを優先する（難解＋並みの危険）</td></tr>
'''
patch(MAN, [(MAN_OLD, MAN_NEW, 1)])
```

続けて worktree のルートで:

```bash
python -c "import json;json.load(open('katrain/config.json',encoding='utf-8'))"
python tools/compile_mo.py
python tools/build_manual.py
```

`katrain/gui/ai_help.py` は変えない（`_VEIL_FAMILY` が `aiopt:veil*_open_moves` を3盤で共有する。`{p}` は `veil9` などに置き換わり、`tests/test_ai_help_text.py` の `test_referenced_sibling_keys_exist_in_the_same_strategy` は説明文中の `veilN_reserve`・`veilN_min_winrate` が同じ戦略にあることを確かめる＝**説明文に `enigma*plus_…` のキー名を書かない**）。

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q`
Expected: すべて PASS。`git status` に `katrain/i18n/locales/*/LC_MESSAGES/katrain.mo` と `docs/manual/index.html` の変更があること。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py katrain/core/constants.py katrain/config.json katrain/i18n docs/manual tests/test_ai_veil.py
git commit -m "feat(veil): 序盤の研究外しの設定 open_moves（既定 OFF）を登録する" -m "spec §15.2。GUI の説明（jp / en）とマニュアルの設定の表も足す。判定フローへの組み込みは後のタスク。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: 任せる先の派生クラスと `_veil_open_delegate`（テストハーネスの拡張を含む）

**Files:**
- Modify: `katrain/core/ai.py`（`veil_decision_record` の末尾〈4923 `return json.dumps(...)`〉と `@register_strategy(AI_VEIL_9)`〈4926〉の間に派生クラス 3 つと `_VEIL_OPEN_CLASSES`。`Veil9Strategy` の `def _generate_move`〈5419〉の直前＝`_veil_forced` の後に `_veil_open_delegate`）
- Test: `tests/test_ai_veil.py`（`_Harness._strategy`〈964-1019〉に `placements`・`ai_config`・`players_info`。`MANUAL_PARITY_PAGE = Path(`〈2543〉の直前＝`TestForced` の後に `_ai_vs_human` と `TestOpenDelegate`）

**Interfaces:**
- Consumes: Task 1 の `VEIL_OPEN_DELEGATES`。既存の `Enigma9PlusStrategy`（4004）・`Enigma13PlusStrategy`（4014）・`Enigma19PlusStrategy`（4068）・`Enigma9Strategy._ponder_applies`（3140）・`AIStrategy.__init__`（515-530。`self.cn = game.current_node`・`self.query_generations`）。
- Produces（Task 4 が使う）:
  - `class VeilOpenEnigma9PlusStrategy(Enigma9PlusStrategy)` / `VeilOpenEnigma13PlusStrategy(Enigma13PlusStrategy)` / `VeilOpenEnigma19PlusStrategy(Enigma19PlusStrategy)`（`_ponder_applies(self) -> False` だけを上書き）
  - `_VEIL_OPEN_CLASSES = {9: ..., 13: ..., 19: ...}`（モジュール内部用）
  - `Veil9Strategy._veil_open_delegate(self) -> (delegate, key)`
  - テストハーネス: `_Harness._strategy(..., placements=(), ai_config=None, players_info=None, **game_attrs)`。`game.root` は `game_attrs` に `root` が無ければ `SimpleNamespace(placements=list(placements))`。`katrain.config(setting, default=None)` は `setting` の `/` の後ろ（`ai:enigma9plus` など）を `ai_config` から引く（無ければ `default`）。`players_info` を渡したときだけ `katrain.players_info` を置く。`_ai_vs_human(ai="B")` は `{ai: AI, 相手: HUMAN}` の players_info。

- [ ] **Step 1: 失敗するテストを書く**（パッチスクリプト `<scratchpad>/patch_open_t3_test.py`）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

T = "tests/test_ai_veil.py"
H1_OLD = r'''        player="B",
        **game_attrs,
    ):
        size = size or self.SIZE
        logs = []
        katrain_ns = types.SimpleNamespace(log=lambda msg, *a, **k: logs.append(str(msg)))
'''
H1_NEW = r'''        player="B",
        placements=(),
        ai_config=None,
        players_info=None,
        **game_attrs,
    ):
        size = size or self.SIZE
        logs = []
        katrain_ns = types.SimpleNamespace(
            log=lambda msg, *a, **k: logs.append(str(msg)),
            # config("ai/<戦略キー>") だけを返す（序盤の研究外しで任せる難解＋の設定の節。無い節は default＝None）
            config=lambda setting, default=None: (ai_config or {}).get(setting.split("/", 1)[-1], default),
        )
        if players_info is not None:
            katrain_ns.players_info = players_info
'''
H2_OLD = r'''        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(size, size), **game_attrs)
'''
H2_NEW = r'''        game_attrs.setdefault("root", types.SimpleNamespace(placements=list(placements)))  # 序盤の窓の番号に足す置き石
        game = types.SimpleNamespace(katrain=katrain_ns, current_node=node, board_size=(size, size), **game_attrs)
'''
NEW_OLD = r'''MANUAL_PARITY_PAGE = Path('''
NEW_NEW = r'''def _ai_vs_human(ai="B"):
    """players_info: ai が AI・相手が人間（難解の ponder が起動する条件）。"""
    from katrain.core.constants import PLAYER_AI, PLAYER_HUMAN

    human = "W" if ai == "B" else "B"
    return {ai: types.SimpleNamespace(player_type=PLAYER_AI), human: types.SimpleNamespace(player_type=PLAYER_HUMAN)}


class TestOpenDelegate(_Harness):
    """序盤の窓で任せる先（spec §15.3 手順5）: ponder を止めただけの難解＋の派生クラスと、それを作る `_veil_open_delegate`。"""

    @pytest.mark.parametrize("size", [9, 13, 19])
    def test_subclass_only_turns_the_ponder_off(self, size):
        cls = getattr(ai_module, f"VeilOpenEnigma{size}PlusStrategy")
        base = getattr(ai_module, f"Enigma{size}PlusStrategy")
        assert cls.__bases__ == (base,) and cls.__name__.endswith("Strategy")
        own = {k for k in vars(cls) if not k.startswith("__")} - {"_abc_impl"}  # _abc_impl は ABC が足す
        assert own == {"_ponder_applies"}
        assert (cls.KEY_PREFIX, cls.LABEL) == (f"enigma{size}plus", f"Enigma{size}Plus")
        assert cls.SETTING_DEFAULTS is base.SETTING_DEFAULTS
        assert cls not in STRATEGY_REGISTRY.values()

    def test_ponder_never_applies_even_against_a_human(self):
        s, _ = self._strategy(players_info=_ai_vs_human())
        assert ai_module.Enigma9PlusStrategy(s.game, {})._ponder_applies() is True  # 素の難解＋なら先読みする場面
        assert ai_module.VeilOpenEnigma9PlusStrategy(s.game, {})._ponder_applies() is False

    @pytest.mark.parametrize("harness,size", [(_Harness, 9), (_Harness13, 13), (_Harness19, 19)], ids=VEIL_IDS)
    def test_class_and_config_section_follow_the_board(self, harness, size):
        """(h) 9/13/19路で任せる先のクラスと設定の節（ai:enigma9plus など）が切り替わる。節が無ければ難解＋の既定値。"""
        key = f"ai:enigma{size}plus"
        base = getattr(ai_module, f"Enigma{size}PlusStrategy")
        section = {f"enigma{size}plus_max_loss": 1.25}
        s, _ = harness()._strategy(ai_config={key: section})
        delegate, src = s._veil_open_delegate()
        assert src == key == VEIL_OPEN_DELEGATES[size]
        assert type(delegate) is getattr(ai_module, f"VeilOpenEnigma{size}PlusStrategy") and isinstance(delegate, base)
        assert delegate.settings == section and delegate.settings is not section  # 写しを渡す（config を書き換えない）
        assert delegate._setting("max_loss") == 1.25
        s, _ = harness()._strategy()  # 節が無い（config が None を返す）
        delegate, _ = s._veil_open_delegate()
        assert delegate.settings == {}
        assert delegate._setting("max_loss") == base.SETTING_DEFAULTS["max_loss"]

    def test_delegate_reads_the_position_and_generation_the_veil_waited_for(self):
        """(k) 任せた戦略の cn と query_generations は韜晦のもの（作る間に game.current_node が動いても読まない）。"""
        s, _ = self._strategy()
        s.query_generations = {12345: 7}
        moved = types.SimpleNamespace(**vars(s.cn))
        s.game.current_node = moved
        delegate, _ = s._veil_open_delegate()
        assert delegate.cn is s.cn and delegate.cn is not moved
        assert delegate.query_generations is s.query_generations


MANUAL_PARITY_PAGE = Path('''
patch(T, [(H1_OLD, H1_NEW, 1), (H2_OLD, H2_NEW, 1), (NEW_OLD, NEW_NEW, 1)])
```

貼った後に `python -m black --check --diff -l 120 -t py312 tests/test_ai_veil.py` で、足した行に差分が無いことを確かめる（Global Constraints 1）。

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q -k TestOpenDelegate`
Expected: FAIL（`AttributeError: module 'katrain.core.ai' has no attribute 'VeilOpenEnigma9PlusStrategy'`・`'Veil9Strategy' object has no attribute '_veil_open_delegate'`）。あわせて `python -m pytest tests/test_ai_veil.py -q -k "not TestOpenDelegate"` がすべて PASS（ハーネスの拡張は既存のテストを変えない）。出力を report に写す。

- [ ] **Step 3: 実装する**（パッチスクリプト `<scratchpad>/patch_open_t3.py`）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

AI = "katrain/core/ai.py"
CLS_OLD = r'''    return json.dumps({k: clean(v) for k, v in fields.items()}, ensure_ascii=True, sort_keys=True)


@register_strategy(AI_VEIL_9)
'''
CLS_NEW = r'''    return json.dumps({k: clean(v) for k, v in fields.items()}, ensure_ascii=True, sort_keys=True)


# ===== 一致率ひかえめ（韜晦）の序盤の研究外し（spec §15）: 窓の手番を任せる難解＋ =====
# 難解＋から ponder（着手後の先読み）を止めただけの派生クラス。@register_strategy は付けない（戦略の一覧に出さない）。
# KEY_PREFIX・LABEL・SETTING_DEFAULTS は難解＋のまま＝ユーザー設定の難解＋のキーと sticky フラグ（`_enigma9plus_endgame`
# など）の名前を保つ。クラス名は Strategy で終わる（ハーネスのログの正規表現 `^\[\w+Strategy\] ` が難解＋の Pool / Score /
# Deviate / Gamble / Overdraft の行を拾う）。ponder を止める理由は spec §3.1（監視対局で自ノードのフル解析が後回しになり、
# 相手の手がレポートで 200v の最善手と比べられる＝相手の一致率の基準がぶれる）。止めても手の選び方は変わらない。


class VeilOpenEnigma9PlusStrategy(Enigma9PlusStrategy):
    """韜晦9路の序盤の窓で手を任せる難解＋9路（ponder を起動しない）。"""

    def _ponder_applies(self):
        return False


class VeilOpenEnigma13PlusStrategy(Enigma13PlusStrategy):
    """韜晦13路の序盤の窓で手を任せる難解＋13路（ponder を起動しない）。"""

    def _ponder_applies(self):
        return False


class VeilOpenEnigma19PlusStrategy(Enigma19PlusStrategy):
    """韜晦19路の序盤の窓で手を任せる難解＋19路（ponder を起動しない）。"""

    def _ponder_applies(self):
        return False


# 盤サイズ → 任せる先のクラス（戦略キーは VEIL_OPEN_DELEGATES）
_VEIL_OPEN_CLASSES = {
    9: VeilOpenEnigma9PlusStrategy,
    13: VeilOpenEnigma13PlusStrategy,
    19: VeilOpenEnigma19PlusStrategy,
}


@register_strategy(AI_VEIL_9)
'''
DEL_OLD = r'''    def _generate_move(self) -> Tuple[Move, str]:
        # ---- S0 ラッパー'''
DEL_NEW = r'''    def _veil_open_delegate(self):
        """序盤の窓で手を任せる先（spec §15.3 手順5）を作って (戦略, 戦略キー) を返す。

        同じ盤サイズの難解＋の派生クラス（ponder を止めただけ）を、ユーザー設定の難解＋の節（`config("ai/<戦略キー>")` の
        写し。節が無ければ {}＝難解＋の既定値）で作る。作った直後に cn と query_generations を韜晦のものにする（韜晦が
        待った局面と世代をそのまま使う＝作る間に局面が動いても別の局面を読まない）。テストはこのメソッドをスタブに差し替える。
        """
        key = VEIL_OPEN_DELEGATES[self.BOARD_LEN]
        delegate = _VEIL_OPEN_CLASSES[self.BOARD_LEN](self.game, dict(self.game.katrain.config(f"ai/{key}") or {}))
        delegate.cn = self.cn
        delegate.query_generations = self.query_generations
        return delegate, key

    def _generate_move(self) -> Tuple[Move, str]:
        # ---- S0 ラッパー'''
patch(AI, [(CLS_OLD, CLS_NEW, 1), (DEL_OLD, DEL_NEW, 1)])
```

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_ai_veil.py tests/test_ai_enigma_plus.py tests/test_ai_enigma9.py tests/test_ai_mimic13.py -q`
Expected: すべて PASS（`TestOpenDelegate` の 8 件を含む。難解・擬態のテストは無変更で通る）。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 序盤の窓で手を任せる難解＋の派生クラス（ponder なし）と作る処理を追加" -m "spec §15.3 手順5。ユーザー設定の難解＋の節をそのまま渡し、cn と query_generations は韜晦のものにする。テストハーネスに置き石・config・players_info を足す。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: S4b（序盤の研究外し）を判定フローに組み込む（TDD）

**Files:**
- Modify: `katrain/core/ai.py`（`Veil9Strategy`: `_veil_open_index_or_none` と `_veil_open`〈`_veil_open_delegate` の後・`_generate_move` の前〉・`_generate_move`〈5419〉で `_veil_open_at` を戻す・`_veil_error`〈5432-5445〉に `open_index`・`_veil_move` の S4〈5487-5497〉と S5〈5499〉の間に S4b・クラスの docstring〈4927-4953〉）
- Test: `tests/test_ai_veil.py`（`MANUAL_PARITY_PAGE = Path(` の直前＝`TestOpenDelegate` の後）

**Interfaces:**
- Consumes: Task 1 の `veil_open_index` / `veil_open_window` / `veil_open_ok`。Task 2 の `open_moves`。Task 3 の `_veil_open_delegate()`。既存の `VEIL_TARGET_FLOOR`（4421）・`_veil_state()`（4984）・`_veil_finish(result, info, tier, kind, **fields)`（5004）・`_best_move(reason)`（2971 付近・継承）・`_log`・`OUTPUT_ERROR`。
- Produces: `Veil9Strategy._veil_open(self, player, sign, best_gtp, cand_gtps, p_match, info) -> None | (result, tier, kind, fields)` と、共有インターフェース節の記録（`open` / `open_index` / `open_src` / `open_in_cands` / `open_secs` / `open_thoughts` / `lead` / `root_wr`・tier / kind `opening`・why `opening` / `opening_best`・`_veil_state()["opening"]`）。インスタンス属性 `self._veil_open_at`（窓の中なら index・それ以外 None。`_veil_error` が読む）と、`Veil9Strategy._veil_open_index_or_none(self) -> int | None`（`_veil_open_at` がまだ None＝S4b より前の例外のとき `_veil_error` が窓の中かを判定する。`open_moves` 0 なら root に触れず None）。
- ログの行: `Opening gate: index=… < open_moves=… but … -> normal flow`・`Opening: index=… < open_moves=… -> delegating to <key> (<クラス名>)`・`Opening: <key> played <gtp> (…)`・ERROR `Opening: <key> returned <repr> (not a move on the board) -> best move`。

- [ ] **Step 1: 失敗するテストを書く**（パッチスクリプト `<scratchpad>/patch_open_t4_test.py`。`_NEAR_FREE`・`_end_cands`・`_END_HP`・`_boom`・`_hist`・`_Harness13` は既存のモジュールの名前）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

T = "tests/test_ai_veil.py"
OLD = r'''MANUAL_PARITY_PAGE = Path('''
NEW = r'''class _RootSpy:
    """root の属性を読んだら記録する（open_moves 0 の S4b が root に触れないことを確かめる）。"""

    def __init__(self):
        self.touched = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AttributeError(name)


class _StubEnigma:
    """序盤の窓で任せる難解＋のスタブ（`_veil_open_delegate` の戻り値）。打つ前に board_watch_probe_warm を立てる
    （難解が立てたままにする形）。gtp が None なら (None, 説明) を返し、error があればそれを送出する。"""

    def __init__(self, gtp, thoughts, error, game, player):
        self.gtp, self.thoughts, self.error, self.game, self.player = gtp, thoughts, error, game, player
        self.calls = 0

    def generate_move(self):
        self.calls += 1
        self.game.board_watch_probe_warm = True
        if self.error is not None:
            raise self.error
        move = None if self.gtp is None else Move.from_gtp(self.gtp, player=self.player)
        return move, self.thoughts


def _no_delegate():
    pytest.fail("open_moves 0 と窓の外では任せる先を作らない")


class _OpenFlow:
    """序盤の研究外し（spec §15.3）の通しテストの共通部（_Harness 系と組む）。窓は WINDOW 手・任せる先のキーは SRC。
    窓の手番は depth を明示する（_Harness の既定 depth 12 は 9路の窓 12 の外）。"""

    WINDOW, SRC = 12, "ai:enigma9plus"

    def _open(self, *, gtp="D4", thoughts="stub enigma thoughts", error=None, depth=0, settings=None, **kw):
        settings = {f"{self.CLS.KEY_PREFIX}_open_moves": self.WINDOW, **(settings or {})}
        s, logs = self._strategy(depth=depth, settings=settings, **kw)
        stub = _StubEnigma(gtp, thoughts, error, s.game, s.cn.next_player)
        s._veil_open_delegate = lambda: (stub, self.SRC)
        return s, logs, stub

    @staticmethod
    def _decision(logs):
        decisions = [m for m in logs if "Decision: {" in m]
        assert len(decisions) == 1
        return json.loads(decisions[0].split("Decision: ", 1)[1])

    @staticmethod
    def _tkwo(info):
        return (info["tier"], info["kind"], info.get("why"), info.get("open"))


class TestOpening(_OpenFlow, _Harness):
    """S4b 序盤の研究外し（spec §15.3・§15.5 の通しテスト）。9路・窓 12・既定は黒番・最善手 E5・難解＋のスタブは D4。"""

    def test_off_never_touches_the_root_and_adds_nothing(self):
        """(a) open_moves 0（既定）: 窓の手数（depth 0）でも S4b は何もしない＝root に触れず、任せる先を作らず、記録も
        足さない。同じ場面の depth 0 と depth 12 で Decision の中身（depth と secs 以外）・クエリ列・着手が同じ。"""
        runs = []
        for depth in (0, 12):
            spy = _RootSpy()
            s, logs = self._strategy(depth=depth, root=spy, **_NEAR_FREE)
            s._veil_open_delegate = _no_delegate
            move, _ = s.generate_move()
            record = self._decision(logs)
            assert spy.touched == []
            assert not any(k.startswith("open") for k in record)
            assert "opening" not in s.game._veil_state["veil9"]
            same = {k: v for k, v in record.items() if k not in ("depth", "secs")}
            runs.append((same, s.queries, s.probe_calls, move.gtp()))
        assert runs[0] == runs[1]

    def test_window_turn_plays_the_enigma_plus_move(self):
        """(b) 窓の中は難解＋の手をそのまま返す: tier / kind opening・ledger・Decision のキー・_veil_state["opening"]。"""
        s, logs, stub = self._open(thoughts="x" * 300)
        move, thoughts = s.generate_move()
        info = s.last_decision_info
        assert move.gtp() == "D4" and stub.calls == 1
        assert thoughts.startswith("[Veil9→ai:enigma9plus opening] xxx")
        assert self._tkwo(info) == ("opening", "opening", "opening", "played")
        opened = (info["open_index"], info["open_src"], info["open_in_cands"])
        assert opened == (0, "ai:enigma9plus", True)
        assert info["open_thoughts"] == "x" * 200 and info["open_secs"] >= 0.0
        assert info["lead"] == pytest.approx(10.0) and info["root_wr"] == pytest.approx(0.95)
        record = self._decision(logs)
        for key in ("open", "open_index", "open_src", "open_in_cands", "open_secs", "open_thoughts", "lead", "root_wr"):
            assert key in record, key
        assert s.queries == [] and s.probe_calls == [] and s.ponders == [] and info["queries"] == 0
        state = s.game._veil_state["veil9"]
        assert state["opening"] == 1 and state["ledger"] == [(0, "E5", "D4", "opening")]
        assert any(m.startswith("[Veil9Strategy] Rate: ") for m in logs)
        assert any("Opening: index=0 < open_moves=12 -> delegating to ai:enigma9plus" in m for m in logs)
        s.generate_move()
        assert s.game._veil_state["veil9"]["opening"] == 2

    def test_enigma_plus_playing_the_best_move_is_kind_best(self):
        s, _, _ = self._open(gtp="E5")
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        assert self._tkwo(info) == ("opening", "best", "opening_best", "played")
        assert "opening" not in s.game._veil_state["veil9"]
        assert s.game._veil_state["veil9"]["ledger"] == [(0, "E5", "E5", "best")]

    def test_white_lead_and_winrate_are_from_whites_view(self):
        s, _, _ = self._open(player="W", lead=3.0, wr=0.7)
        move, _ = s.generate_move()
        info = s.last_decision_info
        assert move.gtp() == "D4" and move.player == "W"
        assert info["lead"] == pytest.approx(3.0) and info["root_wr"] == pytest.approx(0.7)

    def test_missing_lead_still_hands_the_turn_over(self):
        """S5 は lead が無ければ最善手だが、窓の中は lead が None でも任せる（spec §15.3 手順4）。"""
        s, _, stub = self._open(lead=None, wr=None)
        assert s.generate_move()[0].gtp() == "D4" and stub.calls == 1
        info = s.last_decision_info
        assert info["lead"] is None and info["root_wr"] is None and info["kind"] == "opening"

    def test_outside_the_window_is_the_normal_flow(self):
        """(c) 窓の外（depth 12＝13 手目）は通常の流れそのまま: open_moves 0 と同じ記録（secs 以外）・open のキーなし。"""
        runs = []
        for open_moves in (0, 12):
            s, logs = self._strategy(settings={"veil9_open_moves": open_moves}, **_NEAR_FREE)
            s._veil_open_delegate = _no_delegate
            move, _ = s.generate_move()
            record = self._decision(logs)
            assert not any(k.startswith("open") for k in record)
            runs.append(({k: v for k, v in record.items() if k != "secs"}, s.queries, s.probe_calls, move.gtp()))
        assert runs[0] == runs[1]

    def test_gate_after_an_opponent_pass(self):
        """(d) 相手の直前パスは任せない（open gate）＝S7 の終局処理（EXITS の opp_pass と同じ結末）。"""
        s, logs, stub = self._open(cands=_end_cands(), hp=_END_HP, last_move=Move(None, player="W"))
        s.generate_move()
        info = s.last_decision_info
        assert stub.calls == 0 and "open_src" not in info
        assert self._tkwo(info) == ("terminal", "pass", "opp_pass", "gate") and info["open_index"] == 0
        assert any("Opening gate: index=0 < open_moves=12 but the opponent passed" in m for m in logs)

    @pytest.mark.parametrize("mine,n", [(0, 6), (2, 19)])  # p_match 1/7・3/20 = 0.15（境界も任せない）
    def test_gate_at_or_below_the_rate_floor(self, mine, n):
        """(d) p_match <= VEIL_TARGET_FLOOR（0.15）は任せない（15% 未満へ無駄に外さない）。"""
        s, _, stub = self._open(cands=[_Harness.CANDS[0], _Harness.CANDS[-1]], hist=_hist("B", mine, n))
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        assert stub.calls == 0 and info["open_index"] == 0
        assert self._tkwo(info) == ("i", "best", "no_pool", "gate")

    def test_just_above_the_rate_floor_is_handed_over(self):
        s, _, stub = self._open(hist=_hist("B", 0, 5))  # p_match 1/6
        assert s.generate_move()[0].gtp() == "D4" and stub.calls == 1

    @pytest.mark.parametrize("gtp", [None, "pass"])
    def test_no_move_from_enigma_plus_plays_the_best_move(self, gtp):
        """(e) 手が None / pass なら ERROR ログ＋最善手（open invariant）。"""
        s, logs, _ = self._open(gtp=gtp)
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        assert self._tkwo(info) == ("opening", "best", "invariant", "invariant")
        assert info["open_src"] == "ai:enigma9plus" and info["open_index"] == 0
        assert any(f"Opening: ai:enigma9plus returned {gtp!r} (not a move on the board)" in m for m in logs)
        assert "opening" not in s.game._veil_state["veil9"]
        assert s.game._veil_state["veil9"]["ledger"] == [(0, "E5", "E5", "best")]

    def test_a_move_outside_the_candidates_is_played(self):
        """(e) 通常解析の候補に無い手（C3）もそのまま打つ（open_in_cands 偽）。"""
        s, _, _ = self._open(gtp="C3")
        assert s.generate_move()[0].gtp() == "C3"
        info = s.last_decision_info
        assert info["kind"] == "opening" and info["open_in_cands"] is False

    def test_an_error_in_enigma_plus_plays_the_best_move(self):
        """(f)(j) 難解＋の例外は S0 のフェイルセーフ（最善手）で、記録に open_index。例外でも probe_warm は False に戻る。"""
        s, _, _ = self._open(error=RuntimeError("boom"))
        assert s.generate_move()[0].gtp() == "E5"
        info = s.last_decision_info
        assert (info["tier"], info["kind"], info["why"]) == ("failsafe", "best", "exception")
        assert info["open_index"] == 0 and "open" not in info
        assert info["error"] == "RuntimeError('boom')"
        assert s.game.board_watch_probe_warm is False
        assert s.game._veil_state["veil9"]["ledger"] == [(0, "E5", "E5", "best")]

    def test_an_error_after_the_gate_keeps_the_open_index(self, monkeypatch):
        monkeypatch.setattr(ai_module, "veil_allowance", _boom)
        s, _, stub = self._open(hist=_hist("B", 0, 6))
        s.generate_move()
        info = s.last_decision_info
        assert stub.calls == 0 and info["why"] == "exception" and info["open_index"] == 0

    def test_an_error_outside_the_window_has_no_open_index(self, monkeypatch):
        monkeypatch.setattr(ai_module, "veil_allowance", _boom)
        s, _, _ = self._open(depth=12)
        s.generate_move()
        assert s.last_decision_info["why"] == "exception" and "open_index" not in s.last_decision_info

    def test_an_error_before_s4b_in_the_window_keeps_the_open_index(self, monkeypatch):
        """(f) S4b より前の例外（S4 の集計）でも、窓の中の手番なら open_index を残す（spec §15.3 手順8）。"""
        monkeypatch.setattr(ai_module, "veil_tally", _boom)
        s, _, stub = self._open()
        s.generate_move()
        info = s.last_decision_info
        assert stub.calls == 0 and info["why"] == "exception" and info["open_index"] == 0

    def test_discarded_analysis_in_enigma_plus_is_not_swallowed(self):
        s, _, _ = self._open(error=AnalysisDiscardedException("new game"))
        with pytest.raises(AnalysisDiscardedException):
            s.generate_move()
        assert s.game.board_watch_probe_warm is False

    def test_probe_warm_is_reset_after_enigma_plus(self):
        """(j) 難解＋が立てた board_watch_probe_warm を、戻った後に False に戻す。"""
        s, _, stub = self._open()
        s.generate_move()
        assert stub.calls == 1 and s.game.board_watch_probe_warm is False

    def test_root_placements_shift_the_window(self):
        """(i) index = depth ＋ root の置き石の数（board_watch が相手の初手を置き石として取り込んだ局）。"""
        stone = Move.from_gtp("E5", player="B")
        s, _, stub = self._open(depth=11)
        s.generate_move()
        assert stub.calls == 1 and s.last_decision_info["open_index"] == 11
        s, logs, stub = self._open(depth=11, placements=(stone,))  # index 12 → 窓の外
        s.generate_move()
        assert stub.calls == 0 and not any(k.startswith("open") for k in self._decision(logs))
        stones = (stone, Move.from_gtp("D4", player="W"), Move.from_gtp("C3", player="B"))
        s, _, stub = self._open(depth=0, placements=stones)
        s.generate_move()
        assert stub.calls == 1 and s.last_decision_info["open_index"] == 3

    def test_the_real_delegate_never_starts_a_ponder(self, monkeypatch):
        """(g) 任せた難解＋が着手の直前に `_start_ponder` を呼んでも、ponder を止めた派生クラスなのでスレッドは起動せず
        `_enigma_ponder_owner` も None のまま（players_info は {自分: AI, 相手: HUMAN}。同じ場面で素の難解＋なら起動する）。
        本物の難解＋の選択はエンジンが要るので、`Enigma9Strategy._generate_move` を「_start_ponder を呼んで D4」に差し替える。"""
        started = []

        class _Thread:
            def __init__(self, *a, **k):
                pass

            def start(self):
                started.append(True)

        probe = {"hp": {"humanPolicy": [0.1] * 82}}

        def fake_enigma(strategy):
            strategy._start_ponder("D4", probe, strategy.cn.next_player)
            return Move.from_gtp("D4", player=strategy.cn.next_player), "fake enigma"

        monkeypatch.setattr(ai_module.threading, "Thread", _Thread)
        monkeypatch.setattr(ai_module.Enigma9Strategy, "_generate_move", fake_enigma)
        s, _ = self._strategy(
            depth=0,
            settings={"veil9_open_moves": 12},
            players_info=_ai_vs_human(),
            ai_config={"ai:enigma9plus": {}},
            _enigma_ponder_owner=None,
        )
        assert s.generate_move()[0].gtp() == "D4"
        assert s.last_decision_info["open"] == "played"
        assert started == [] and s.game._enigma_ponder_owner is None
        ai_module.Enigma9PlusStrategy(s.game, {})._start_ponder("D4", probe, "B")
        assert started == [True] and s.game._enigma_ponder_owner == "B"


class TestOpening13(_OpenFlow, _Harness13):
    WINDOW, SRC = 30, "ai:enigma13plus"

    def test_window_is_30_moves_on_13x13(self):
        s, _, stub = self._open(depth=29)
        assert s.generate_move()[0].gtp() == "D4" and stub.calls == 1
        info = s.last_decision_info
        assert (info["open_src"], info["open_index"]) == ("ai:enigma13plus", 29)
        assert s.game._veil_state["veil13"]["ledger"] == [(29, "G7", "D4", "opening")]
        s, _, stub = self._open(depth=30)
        s.generate_move()
        assert stub.calls == 0 and "open_index" not in s.last_decision_info


MANUAL_PARITY_PAGE = Path('''
patch(T, [(OLD, NEW, 1)])
```

貼った後に `python -m black --check --diff -l 120 -t py312 tests/test_ai_veil.py` で、足した行に差分が無いことを確かめる。

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_ai_veil.py -q -k "TestOpening"`
Expected: `test_off_never_touches_the_root_and_adds_nothing`・`test_outside_the_window_is_the_normal_flow`・`test_an_error_outside_the_window_has_no_open_index` は PASS（今の挙動の固定）、ほかは FAIL（D4 ではなく通常の流れの手・`open` のキーが無い〈KeyError〉・`stub.calls == 0`）。出力を report に写す。

- [ ] **Step 3: 実装する**（パッチスクリプト `<scratchpad>/patch_open_t4.py`）

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

AI = "katrain/core/ai.py"

# 1. _veil_open（_veil_open_delegate の後・_generate_move の前）
OPEN_OLD = r'''    def _generate_move(self) -> Tuple[Move, str]:
        # ---- S0 ラッパー'''
OPEN_NEW = r'''    def _veil_open_index_or_none(self):
        """序盤の窓の中なら index、OFF・窓の外・判定できないときは None（`_veil_error` が S4b より前の例外の手番で使う。
        spec §15.3 手順8）。open_moves 0 なら root に触れない。記録のための判定なので例外は出さない。"""
        try:
            open_moves = int(self._setting("open_moves") or 0)
            if open_moves <= 0:
                return None
            index = veil_open_index(self.cn.depth, len(self.game.root.placements))
            return index if veil_open_window(index, open_moves) else None
        except Exception:  # noqa: BLE001 記録のための判定で着手と記録を止めない
            return None

    def _veil_open(self, player, sign, best_gtp, cand_gtps, p_match, info):
        """S4b 序盤の研究外し（spec §15.3）。窓の中で関門を通れば、手を同じ盤サイズの難解＋に任せる。任せた手番だけ
        (result, tier, kind, fields) を返し、それ以外は None（呼び出し側が S5 以降の通常の流れへ進む）。

        open_moves 0 なら何もしない（root に触れない・info に何も足さない＝今とビット同一）。窓の外も何も足さない。
        窓の中で関門（相手の直前パス・p_match <= VEIL_TARGET_FLOOR）に止まった手番は open = "gate" と open_index だけ
        足して None。任せた手番は tier opening・kind opening（best と違う手）/ best で、open・open_index・open_src・
        open_in_cands・open_secs・open_thoughts と lead・root_wr（打つ側視点・None もありうる＝None でも任せる）を残す。
        手が None / pass なら ERROR ログ＋最善手（tier opening・kind best・why invariant・open = "invariant"）。通常解析の
        候補に無い手もそのまま打つ（難解と同じ）。
        難解＋の例外は S0 に任せる（`_veil_error` が open_index を残す）。戻った後は例外でも board_watch_probe_warm を
        False に戻す。窓の中では韜晦の他の層（失着・forced・即決・罠・終局帯の入れ替え）は動かない。"""
        open_moves = int(self._setting("open_moves") or 0)
        if open_moves <= 0:
            return None
        cn = self.cn
        index = veil_open_index(cn.depth, len(self.game.root.placements))
        if not veil_open_window(index, open_moves):
            return None
        self._veil_open_at = index
        info["open_index"] = index
        opp_passed = cn.move is not None and cn.move.is_pass
        if opp_passed or p_match <= VEIL_TARGET_FLOOR:
            info["open"] = "gate"
            reason = "the opponent passed" if opp_passed else f"p_match {p_match:.3f} <= {VEIL_TARGET_FLOOR:.2f}"
            self._log(f"Opening gate: index={index} < open_moves={open_moves} but {reason} -> normal flow")
            return None
        # 窓のリードの記録（S5 と同じ計算・クエリ 0 本。None でも任せる）
        root = cn.analysis.get("root") or {}
        root_lead, root_wr = root.get("scoreLead"), root.get("winrate")
        info["lead"] = None if root_lead is None else root_lead * sign
        info["root_wr"] = None if root_wr is None else (root_wr if player == "B" else 1.0 - root_wr)
        delegate, src = self._veil_open_delegate()
        info["open_src"] = src
        self._log(f"Opening: index={index} < open_moves={open_moves} -> delegating to {src} ({type(delegate).__name__})")
        started = time.time()
        try:
            move, thoughts = delegate.generate_move()
        finally:
            self.game.board_watch_probe_warm = False  # 難解＋が立てたままだと監視の先読みが Probe の温めを続ける
        info["open_secs"] = time.time() - started
        info["open_thoughts"] = str(thoughts or "")[:200]
        chosen = None if move is None else move.gtp()
        if not veil_open_ok(chosen):
            info["open"] = "invariant"
            self.game.katrain.log(
                f"[{type(self).__name__}] Opening: {src} returned {chosen!r} (not a move on the board) -> best move",
                OUTPUT_ERROR,
            )
            return (
                self._best_move(f"{self.LABEL}: the opening delegate returned no move, playing best move."),
                "opening", "best", {"why": "invariant"},
            )
        info["open"] = "played"
        info["open_in_cands"] = chosen in cand_gtps
        kind = "best" if chosen == best_gtp else "opening"
        if kind == "opening":
            state = self._veil_state()
            state["opening"] = state.get("opening", 0) + 1  # 打ったときだけ作る（OFF と窓の外の状態は今と同じ）
        what = "the best move" if kind == "best" else f"instead of {best_gtp}"
        self._log(
            f"Opening: {src} played {chosen} ({what}, in candidates: {info['open_in_cands']}, "
            f"{info['open_secs']:.1f}s)"
        )
        return (
            (move, f"[{self.LABEL}→{src} opening] {thoughts}"),
            "opening", kind, {"why": "opening" if kind == "opening" else "opening_best"},
        )

    def _generate_move(self) -> Tuple[Move, str]:
        # ---- S0 ラッパー'''

# 2. _generate_move: 窓の番号を手番ごとに戻す
S0_OLD = r'''        # ---- S0 ラッパー: 解析の破棄は上へ、それ以外の例外は最善手（ほかの出口と同じく Decision 行と ledger も残す）----
        t0 = time.time()
        try:
'''
S0_NEW = r'''        # ---- S0 ラッパー: 解析の破棄は上へ、それ以外の例外は最善手（ほかの出口と同じく Decision 行と ledger も残す）----
        t0 = time.time()
        self._veil_open_at = None  # S4b が窓の中の手番で番号を置く（例外の手番の記録 `_veil_error` が読む）
        try:
'''

# 3. _veil_error: 窓の中の例外の手番に open_index
ERR_DOC_OLD = r'''        why exception と depth / player / best / chosen / error）。記録に失敗しても最善手は打つ（ERROR ログを足す）。"""
'''
ERR_DOC_NEW = r'''        why exception と depth / player / best / chosen / error。序盤の窓の中の手番なら open_index も＝S4b が置いた
        `_veil_open_at`、まだ無ければ `_veil_open_index_or_none()`）。記録に失敗しても最善手は打つ（ERROR ログを足す）。"""
'''
ERR_OLD = r'''            info = {"depth": cn.depth, "player": cn.next_player, "best": cands[0]["move"] if cands else None, "t0": t0}
            return self._veil_finish(result, info, "failsafe", "best", why="exception", error=repr(error))
'''
ERR_NEW = r'''            info = {"depth": cn.depth, "player": cn.next_player, "best": cands[0]["move"] if cands else None, "t0": t0}
            open_at = getattr(self, "_veil_open_at", None)
            if open_at is None:  # S4b より前の例外（S1 の解析待ち・S4 の集計）でも窓の中かを記録する（spec §15.3 手順8）
                open_at = self._veil_open_index_or_none()
            if open_at is not None:
                info["open_index"] = open_at
            return self._veil_finish(result, info, "failsafe", "best", why="exception", error=repr(error))
'''

# 4. _veil_move: S4 と S5 の間に S4b
S4B_OLD = r'''            f"p_match={p_match:.3f} target={target:.2f} u={u:.2f}"
        )

        # ---- S5 リード（打つ側視点）----
'''
S4B_NEW = r'''            f"p_match={p_match:.3f} target={target:.2f} u={u:.2f}"
        )

        # ---- S4b 序盤の研究外し（spec §15.3。open_moves 0 なら何もしない＝root に触れず、記録も足さない）----
        opening = self._veil_open(player, sign, best_gtp, cand_gtps, p_match, info)
        if opening is not None:
            result, tier, kind, fields = opening
            return finish(result, tier, kind, **fields)

        # ---- S5 リード（打つ側視点）----
'''

# 5. クラスの docstring
DOC1_OLD = r'''    記録だけ、ON（2）は打つ（u > 0 のときだけ）。

    難解（Enigma9Strategy）からは'''
DOC1_NEW = r'''    記録だけ、ON（2）は打つ（u > 0 のときだけ）。
    序盤の研究外し（open_moves・spec §15・既定 OFF）は S4b（S4 の直後）で、index = cn.depth ＋ root の置き石の数 <
    open_moves の手番を、同じ盤サイズの難解＋（ponder を止めた派生クラス・ユーザー設定の難解＋の節のまま）に任せる
    （相手の直前パスと p_match <= VEIL_TARGET_FLOOR の手番は任せない）。窓の中は要件1・5・7の代わりに難解＋の挙動。

    難解（Enigma9Strategy）からは'''
DOC2_OLD = r'''    打ったときだけ作る））。
    設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
'''
DOC2_NEW = r'''    打ったときだけ作る）・opening（序盤の窓で難解＋が最善手と違う手を打った数・打ったときだけ作る））。
    設計: docs/superpowers/specs/2026-09-23-veil-strategy-design.md
'''
DOC3_OLD = r'''ヨセは委譲しない・ponder は起動しない。全分岐のフェイルセーフは最善手。'''
DOC3_NEW = r'''ヨセは委譲しない・ponder は起動しない（序盤の窓で任せる難解＋も ponder を止めた派生クラス）。全分岐のフェイルセーフは最善手。'''

patch(
    AI,
    [
        (OPEN_OLD, OPEN_NEW, 1),
        (S0_OLD, S0_NEW, 1),
        (ERR_DOC_OLD, ERR_DOC_NEW, 1),
        (ERR_OLD, ERR_NEW, 1),
        (S4B_OLD, S4B_NEW, 1),
        (DOC1_OLD, DOC1_NEW, 1),
        (DOC2_OLD, DOC2_NEW, 1),
        (DOC3_OLD, DOC3_NEW, 1),
    ],
)
```

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py tests/test_ai_mimic13.py tests/test_ai_enigma9.py tests/test_ai_enigma_plus.py tests/test_ai_enigma_opening.py tests/test_ai_enigma_gamble.py tests/test_ai_enigma_overdraft.py -q`
Expected: すべて PASS。既存の韜晦のテスト（`TestEveryExit`・`TestForced`・`TestBlunder` などすべて `open_moves` 0）が1件も変わらずに通る＝OFF の挙動が今と同じ。

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_veil.py
git commit -m "feat(veil): 序盤の研究外し（S4b・既定 OFF）を判定フローに組み込む" -m "spec §15.3。窓の中の手番を同じ盤サイズの難解＋（ponder なし・ユーザー設定のまま）に任せ、Decision に open・open_index・open_src などを残す。相手の直前パスと一致率 15% 以下は任せない。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: ハーネスの韜晦の要約（spec §15.4）

**Files:**
- Modify: `katrain_debug/selfplay_stats.py`（`VEIL_TERMINAL_KINDS`〈463〉の後に `_veil_unpaid`・`_opening_metrics`。`_decision_metrics`〈466-538〉の docstring・`vloss_by_kind`〈491〉・`curse_by_kind`〈501〉・out の末尾〈505〉・`nonfree_below_reserve`〈509-512〉）。black 整形済み＝Edit ツールでよい。
- Test: `tests/test_selfplay_stats.py`（`TestGameSummary` の `test_nonfree_below_reserve_ignores_the_terminal_band`〈433-446〉の後）

**Interfaces:**
- Consumes: Task 4 の記録（`decision` の `tier` / `kind` / `open` / `open_index` / `open_in_cands` / `why`）。既存の `_row(depth, is_ai, match, loss, **kw)`・`_reports(own, opp)`・`META`（tests/test_selfplay_stats.py 321-345）・`S.selfplay_game_summary(meta, reports, rows, target, reserve=None, ledger=None, wall_s=None)`。
- Produces: games.jsonl の `veil` に
  - `nonfree_below_reserve`: tier `opening` を数えない（`_veil_unpaid(d)` が真の手＝free・tier terminal / opening・kind pass / swap / finish を除く）。
  - `opening`: `{"turns", "opening", "report_loss", "ge2", "ge6", "not_in_cands", "gate", "invariant", "errors"}`。窓の記録（`open` か `open_index`）が1つも無ければ None。
  - `vloss_by_kind["opening"]` / `curse_by_kind["opening"]`: kind `opening` の記録がどれも数値の vloss を持たなければ None。ほかの kind（best・pass・swap・finish など vloss を持たない kind も）は今と同じ値＝`open_moves` 0 のアームの要約は変わらない。

- [ ] **Step 1: 失敗するテストを書く**（`tests/test_selfplay_stats.py` の `test_nonfree_below_reserve_ignores_the_terminal_band` の最後の行 `        assert veil["nonfree_below_reserve"] == 1  # 数えるのは lead 4.0 の paid だけ` の後に、空行1つを挟んで足す）

```python
    def test_opening_window_turns_are_summarised_apart(self):
        """序盤の研究外し（韜晦 spec §15.4）: 窓の手（tier opening）は lead < reserve でも nonfree_below_reserve に
        入れず、要約の opening に出す。vloss を持たない kind（opening）の vloss_by_kind・curse_by_kind は None。"""

        def dec(kind, chosen, open_, index, tier="opening", **kw):
            d = {"tier": tier, "kind": kind, "best": "C3", "chosen": chosen, "open": open_, "open_index": index}
            return {**d, **kw}

        exception = {"tier": "failsafe", "kind": "best", "best": "C3", "chosen": "C3", "why": "exception"}
        paid = {"tier": "iii", "kind": "paid", "best": "C3", "chosen": "D4", "vloss": 1.0, "lead": 4.0}
        rows = [
            _row(1, True, False, 2.5, decision=dec("opening", "D4", "played", 0, lead=0.5, open_in_cands=True)),
            _row(3, True, True, 0.0, decision=dec("best", "C3", "played", 2, lead=0.4, open_in_cands=True)),
            _row(5, True, False, 7.0, move="J9", decision=dec("opening", "J9", "played", 4, open_in_cands=False)),
            _row(7, True, True, 0.0, decision=dec("best", "C3", "invariant", 6, why="invariant")),
            _row(9, True, True, 0.0, decision=dec("best", "C3", "gate", 8, tier="i", why="no_pool", lead=0.3)),
            _row(11, True, True, 0.0, decision={**exception, "open_index": 10}),
            _row(13, True, False, 1.0, decision=paid),
        ]
        veil = S.selfplay_game_summary(META, _reports(0.25, 0.2), rows, target=0.30, reserve=5.0)["veil"]
        assert veil["nonfree_below_reserve"] == 1  # lead 4.0 の paid だけ（窓の手は lead 0.5 でも数えない）
        assert veil["opening"] == {
            "turns": 4,
            "opening": 2,
            "report_loss": pytest.approx(9.5),
            "ge2": 2,
            "ge6": 1,
            "not_in_cands": 1,
            "gate": 1,
            "invariant": 1,
            "errors": 1,
        }
        assert veil["vloss_by_kind"]["opening"] is None and veil["curse_by_kind"]["opening"] is None
        assert veil["report_loss_by_kind"]["opening"] == pytest.approx(9.5)
        assert veil["vloss_by_kind"]["best"] == pytest.approx(0.0)  # opening 以外の kind は今と同じ値
        assert veil["vloss_by_kind"]["paid"] == pytest.approx(1.0)
        assert veil["curse_by_kind"]["paid"] == pytest.approx(0.0)
        assert veil["paid_vloss_sum"] == pytest.approx(1.0)

    def test_opening_block_is_none_without_window_records(self):
        paid = {"tier": "iii", "kind": "paid", "best": "C3", "chosen": "D4", "vloss": 1.0, "lead": 9.0}
        rows = [_row(1, True, False, 1.0, decision=paid)]
        veil = S.selfplay_game_summary(META, _reports(0.25, 0.2), rows, target=0.30, reserve=5.0)["veil"]
        assert veil["opening"] is None
        assert veil["vloss_by_kind"] == {"paid": pytest.approx(1.0)}
```

- [ ] **Step 2: RED を確かめる**

Run: `python -m pytest tests/test_selfplay_stats.py -q -k "opening"`
Expected: FAIL（`nonfree_below_reserve` が 2〈lead 0.5 の窓の手も数える〉・`KeyError: 'opening'`）。出力を report に写す。

- [ ] **Step 3: 実装する**（Edit ツール・`katrain_debug/selfplay_stats.py`）

(1) `VEIL_TERMINAL_KINDS = ("pass", "swap", "finish")` の行の後（`def _decision_metrics` の前）に:

```python
def _veil_unpaid(d):
    """支払う外しでない手（free・終局帯の手・序盤の研究外しの窓の手＝reserve を見ない設計の手。韜晦 spec §15.4）。"""
    return d.get("kind") == "free" or d.get("tier") in ("terminal", "opening") or d.get("kind") in VEIL_TERMINAL_KINDS


def _opening_metrics(decs):
    """序盤の研究外し（韜晦 spec §15.4）の窓の手番の要約。窓の記録（open / open_index）が1つも無ければ None。

    turns = 難解＋に任せた手番（open が played か invariant）・opening = そのうち best と違う手を打った手番（kind
    opening）・report_loss = 任せて打った手（open played）のレポートの損失の合計・ge2 / ge6 = その手のうち損失 2目 /
    6目以上の数・not_in_cands = 通常解析の候補に無い手を打った数（open_in_cands が偽）・gate = 関門で任せなかった手番・
    invariant = 任せた手が None / pass で最善手にした手番・errors = 窓の中の例外の手番（why exception）。
    """
    opened = [r for r in decs if "open" in r["decision"] or "open_index" in r["decision"]]
    if not opened:
        return None
    played = [r for r in opened if r["decision"].get("open") == "played"]
    losses = [r["loss"] for r in played if r["loss"] is not None]
    return {
        "turns": sum(1 for r in opened if r["decision"].get("open") in ("played", "invariant")),
        "opening": sum(1 for r in played if r["decision"].get("kind") == "opening"),
        "report_loss": sum(losses),
        "ge2": sum(1 for x in losses if x >= 2.0),
        "ge6": sum(1 for x in losses if x >= 6.0),
        "not_in_cands": sum(1 for r in played if r["decision"].get("open_in_cands") is False),
        "gate": sum(1 for r in opened if r["decision"].get("open") == "gate"),
        "invariant": sum(1 for r in opened if r["decision"].get("open") == "invariant"),
        "errors": sum(1 for r in opened if r["decision"].get("why") == "exception"),
    }
```

(2) `_decision_metrics` の docstring の2行

```
    nonfree_below_reserve = lead < reserve で打った free でない外しの数（安全の警報）。終局帯の手（tier terminal か
    kind pass / swap / finish）は数えない。
```

を次に置き換える:

```
    nonfree_below_reserve = lead < reserve で打った free でない外しの数（安全の警報）。終局帯の手（tier terminal か
    kind pass / swap / finish）と序盤の研究外しの窓の手（tier opening）は数えない。窓の手は opening（`_opening_metrics`）。
    vloss を持たない kind opening の vloss_by_kind・curse_by_kind は 0 ではなく None（ほかの kind は vloss が無くても 0）。
```

(3) `    vloss_by_kind = {k: sum(vl(d) for d in deviated if str(d.get("kind")) == k) for k in sorted(kinds)}` を:

```python
    # vloss を持たない kind（序盤の研究外しの opening）は 0 ではなく None（韜晦 spec §15.4。ほかの kind は今と同じ値）
    with_vloss = {str(d.get("kind")) for d in infos if _num(d.get("vloss"))}
    vloss_by_kind = {
        k: None if k == "opening" and k not in with_vloss else sum(vl(d) for d in deviated if str(d.get("kind")) == k)
        for k in sorted(kinds)
    }
```

(4) `        "curse_by_kind": {k: report_loss_by_kind[k] - vloss_by_kind[k] for k in sorted(kinds)},` を:

```python
        "curse_by_kind": {
            k: None if vloss_by_kind[k] is None else report_loss_by_kind[k] - vloss_by_kind[k] for k in sorted(kinds)
        },
```

(5) out の dict の最後の `        "ledger_mismatch": None,` の後に `        "opening": _opening_metrics(decs),` を足す。

(6) `nonfree_below_reserve` の計算

```python
        out["nonfree_below_reserve"] = sum(
            1
            for d in below
            if d.get("kind") != "free" and d.get("tier") != "terminal" and d.get("kind") not in VEIL_TERMINAL_KINDS
        )
```

を次に置き換える:

```python
        out["nonfree_below_reserve"] = sum(1 for d in below if not _veil_unpaid(d))
```

- [ ] **Step 4: GREEN を確かめる**

Run: `python -m pytest tests/test_selfplay_stats.py tests/test_selfplay_run.py tests/test_selfplay_runner.py tests/test_selfplay_cli.py tests/test_selfplay_hooks.py tests/test_selfplay_opponent.py -q`
Expected: すべて PASS（既存の `test_decision_metrics_only_for_strategies_with_decision_info`・`test_nonfree_below_reserve_ignores_the_terminal_band` も無変更で通る＝opening の無い局の `vloss_by_kind` / `curse_by_kind` は今と同じ）。
続けて `python -m black --check -l 120 -t py312 katrain_debug/selfplay_stats.py tests/test_selfplay_stats.py`（期待: `2 files would be left unchanged.`）と `file katrain_debug/selfplay_stats.py tests/test_selfplay_stats.py`（期待: どちらも `with CRLF line terminators`）。

- [ ] **Step 5: コミット**

```bash
git add katrain_debug/selfplay_stats.py tests/test_selfplay_stats.py
git commit -m "feat(selfplay): 韜晦の要約で序盤の研究外しの窓の手を別に数える" -m "韜晦 spec §15.4。tier opening は nonfree_below_reserve に入れず要約 opening に出す。vloss を持たない kind opening の vloss_by_kind・curse_by_kind は None。" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: 文書（開発者向けルール・CLAUDE.md・マニュアルの本文・spec の状態・INDEX・計画の状態）

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（韜晦の節〈777-845〉）・`.claude/rules/ai-strategies.md`（30 行）・`CLAUDE.md`（15 行）
- Modify: `docs/manual/src/06d_ai_parity.html`（本文の箇条〈116〉の後）→ `python tools/build_manual.py`
- Modify: `docs/superpowers/specs/2026-09-23-veil-strategy-design.md`（5 行の状態・§15 の見出し〈647〉）・`docs/superpowers/specs/INDEX.md`（65 行・151 行・155 行）・この計画（Task 1〜5 の状態。Task 6 の状態は Task 7 Step 3 でコントローラが足す）
- Test: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q`（マニュアルの表の整合テストが通ること）

**Interfaces:**
- Consumes: Task 1〜5 の名前（`VEIL_OPEN_DELEGATES`・`VeilOpenEnigma{9,13,19}PlusStrategy`・`open` / `open_index` / `open_src` / `open_in_cands` / `open_secs` / `open_thoughts`・tier / kind `opening`・why `opening` / `opening_best`・`_veil_state` の `opening`・要約 `opening`）。
- Produces: なし（文書だけ）。

- [ ] **Step 1: パッチスクリプト `<scratchpad>/patch_open_t6.py`**

```python
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

# ---- .claude/rules/ai-parameters.md ----
P = ".claude/rules/ai-parameters.md"
patch(
    P,
    [
        (
            r'''forced（ON で打った数・打ったときだけ作る））、ログタグは `[Veil13Strategy]` 等。ponder と HumanStyle 委譲は使わない。''',
            r'''forced（ON で打った数・打ったときだけ作る）・opening（序盤の窓で難解＋が最善手と違う手を打った数・打ったときだけ作る））、ログタグは `[Veil13Strategy]` 等。ponder と HumanStyle 委譲は使わない（序盤の研究外しで任せた難解＋13/19路の中の序盤委譲を除く）。''',
            1,
        ),
        (
            r'''| `veil*_forced_max_loss` | 1手の損の上限（検証済み・目。ヨセは yose_max_loss） | 9路 3〜8・13路 6〜15・19路 8〜20 | 5 / **10** / 15 |
''',
            r'''| `veil*_forced_max_loss` | 1手の損の上限（検証済み・目。ヨセは yose_max_loss） | 9路 3〜8・13路 6〜15・19路 8〜20 | 5 / **10** / 15 |
| `veil*_open_moves` | 序盤の研究外し（spec §15）: S4b（S4 の直後・S5 の前）で、index = cn.depth ＋ root の置き石の数 < open_moves の手番を、同じ盤サイズの難解＋（`VEIL_OPEN_DELEGATES`・ponder を止めた派生クラス `VeilOpenEnigma{9,13,19}PlusStrategy`）にユーザー設定の難解＋の節（`config("ai/ai:enigma*plus")`）のまま任せる。関門: 相手の直前パスでない・p_match > 0.15。**ON のときだけ窓の中は要件1・5・7の代わりに難解＋の挙動**（窓の中は失着・forced・即決・罠・終局帯の入れ替えも動かない）。任せた手が None / pass なら ERROR＋最善手、候補外の手はそのまま打つ | 9路 OFF/6〜20・13路 OFF/12〜40・19路 OFF/20〜60 | OFF / **OFF** / OFF |
''',
            1,
        ),
        (
            r'''`VEIL_FORCED_PROBES=4`, ''',
            r'''`VEIL_FORCED_PROBES=4`, `VEIL_OPEN_DELEGATES={9: ai:enigma9plus, 13: ai:enigma13plus, 19: ai:enigma19plus}`, ''',
            1,
        ),
        (
            r'''tier i/ii/iii/terminal/blunder/forced/failsafe・kind best/free/paid/trap/decided/swap/finish/pass/blunder/forced・''',
            r'''tier i/ii/iii/terminal/blunder/forced/opening/failsafe・kind best/free/paid/trap/decided/swap/finish/pass/blunder/forced/opening・''',
            1,
        ),
        (
            r'''/ opp_pass / terminal / terminal_finish_rejected。''',
            r'''/ opp_pass / terminal / terminal_finish_rejected / opening / opening_best。''',
            1,
        ),
        (
            r'''`forced_gtp` `forced_cost` `forced_vloss` `forced_hp` `forced_wr` `forced_lead_after`）。''',
            r'''`forced_gtp` `forced_cost` `forced_vloss` `forced_hp` `forced_wr` `forced_lead_after`。序盤の研究外しの窓の手番はフィールド `open`＝gate / invariant / played と `open_index`、任せた手番は `open_src` `open_in_cands` `open_secs` `open_thoughts` と `lead` `root_wr`。窓の中の例外の手番は `open_index` だけ）。''',
            1,
        ),
        (
            r'''
**S13 の修正（2026-09-25）**''',
            r'''
**序盤の研究外し（spec §15・既定 OFF）**: 2026-09-26 のユーザーの決定（9路は序盤を定跡どおりに打つと高段の BOT に終局近くまで最善手で応じられかねないので、序盤は難解と同じく研究外しの手を打つ。難解は対 BOT で 100 戦近くほぼ全勝の実績）で足した層。窓の中は難解＋のユーザー設定の挙動（9路の 2026-09-26 の設定で通常の外しの損の上限 1.8目・勝率の下限 0.30、消費モードで 8目、捨て身の罠で 12目まで）。13路の窓の最初の手は難解＋13路の `opening_humanstyle_moves` の間 HumanStyle 9段の手。想定の値は 9路 12・13路 30（効果は spec §16 で測る）。ハーネスの要約は tier opening を `nonfree_below_reserve` に数えず、窓の手を `opening`（turns・opening・report_loss・ge2・ge6・not_in_cands・gate・invariant・errors）に出す。
**S13 の修正（2026-09-25）**''',
            1,
        ),
    ],
)

# ---- .claude/rules/ai-strategies.md ----
patch(
    ".claude/rules/ai-strategies.md",
    [
        (
            r'''ponder と HumanStyle 委譲は使わない。一致率は終局レポートと同一定義''',
            r'''ponder と HumanStyle 委譲は使わない（序盤の研究外しで任せた難解＋の中の委譲を除く）。一致率は終局レポートと同一定義''',
            1,
        ),
        (
            r'''（ON のときだけ要件1を『20局に1局ほどの負けは許す』に緩める）。
''',
            r'''（ON のときだけ要件1を『20局に1局ほどの負けは許す』に緩める）。序盤の研究外し（`veil*_open_moves`・spec §15・2026-09-26・既定 OFF）は、打つ手の番号（両者の通算）がこの値以下の手番を、同じ盤サイズの難解＋（ponder を止めた派生クラス `VeilOpenEnigma*PlusStrategy`）にユーザー設定の難解＋の節のまま任せる（ON のときだけ窓の中は要件1・5・7の代わりに難解＋の挙動。相手の直前パスと一致率 15% 以下の手番は任せない）。効果の計測は spec §16。
''',
            1,
        ),
    ],
)

# ---- CLAUDE.md ----
patch(
    "CLAUDE.md",
    [
        (
            r'''一致率ひかえめ（旧名 韜晦・9・13・19路＝勝ち優先で自分の一致率を絶対目標まで下げる・`Veil9Strategy`）''',
            r'''一致率ひかえめ（旧名 韜晦・9・13・19路＝勝ち優先で自分の一致率を絶対目標まで下げる・序盤の窓を難解＋に任せる研究外しの層〈既定 OFF〉つき・`Veil9Strategy`）''',
            1,
        ),
    ],
)

# ---- マニュアルの本文 ----
patch(
    "docs/manual/src/06d_ai_parity.html",
    [
        (
            r'''この層の条件を満たせば打ちます。</li>
''',
            r'''この層の条件を満たせば打ちます。</li>
    <li><b>序盤の研究外し</b>（<code>veil*_open_moves</code>・既定 OFF）は、打つ手の番号（両者の通算）が <code>veil*_open_moves</code> 以下の手番を、同じ盤サイズの難解＋に難解＋の設定のまま任せます（相手に定跡どおりに打たせない手。9路 12 なら各色 6 手）。窓の中は難解＋と同じ挙動で、この戦略の勝ちの安全条件・一致率の目標・自然さの床は使わず、難解＋の損の上限と勝率の下限に従います。相手が直前にパスした手番と、一致率が 15% 以下の手番は任せません。窓の後の手番はふつうに戻ります。13路・19路の難解＋が序盤を HumanStyle 9段で打つ手数の間は 9段の手になります。窓の中も着手後の先読みはしないので、難解＋を単独で使うより着手が遅くなることがあります。</li>
''',
            1,
        ),
    ],
)

# ---- spec と INDEX の状態 ----
SPEC = "docs/superpowers/specs/2026-09-23-veil-strategy-design.md"
patch(
    SPEC,
    [
        (
            r'''序盤の研究外し（§15・2026-09-26・📝 設計済み・実装待ち）''',
            r'''序盤の研究外し（§15・2026-09-26・実装済み〈計画 `2026-09-26-veil-opening.md`〉）''',
            1,
        ),
        (
            r'''## 15. 序盤の研究外し（`<prefix>_open_moves`・既定 OFF）— 2026-09-26 追記・📝 設計済み・実装待ち''',
            r'''## 15. 序盤の研究外し（`<prefix>_open_moves`・既定 OFF）— 2026-09-26 追記・実装済み（2026-09-26）''',
            1,
        ),
    ],
)
patch(
    "docs/superpowers/specs/INDEX.md",
    [
        (
            r'''§15 序盤の研究外し（2026-09-26・📝 設計済み・実装待ち・既定 OFF・''',
            r'''§15 序盤の研究外し（2026-09-26・実装済み・既定 OFF・''',
            1,
        ),
        (
            r'''（韜晦の spec `2026-09-23-veil-strategy-design.md` の §13 失着オプション。13路の既定を loose にする変更と決着局面の即決の検証も含む）。''',
            r'''（韜晦の spec `2026-09-23-veil-strategy-design.md` の §13 失着オプション。13路の既定を loose にする変更と決着局面の即決の検証も含む）。`2026-09-25-veil-forced.md`（同 §14 最善手しか無い手番の外し）と `2026-09-26-veil-opening.md`（同 §15 序盤の研究外し）も同じ spec の追加の計画。''',
            1,
        ),
    ],
)
```

- [ ] **Step 2: INDEX の計画の本数**（パッチスクリプト `<scratchpad>/patch_open_t6_count.py`。`docs/superpowers/specs/INDEX.md` の 151 行の `54本。`〈ファイルに1つだけ〉を、`docs/superpowers/plans` の `.md` の数に直す）

```python
import os
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

n = len([p for p in os.listdir("docs/superpowers/plans") if p.endswith(".md")])
patch("docs/superpowers/specs/INDEX.md", [("54本。", f"{n}本。", 1)])
print(n)
```

Run: `python <scratchpad>/patch_open_t6_count.py`（worktree のルートで）
Expected: `57`（ブランチ先頭の 55 本＋この計画＋Plan B の計画 `2026-09-26-selfplay-9x9.md`。どちらもディスク上にある）。

- [ ] **Step 3: マニュアルを作り直す**: `python tools/build_manual.py`。

- [ ] **Step 4: この計画の状態**（パッチスクリプト `<scratchpad>/patch_open_t6_status.py`。Task 1〜5 の見出しの下に、前の計画〈`2026-09-25-veil-forced.md`〉と同じ形の ``状態: 完了（`<短いハッシュ>`）。`` の行を足す。ハッシュは件名で引いたそのタスクのコミット〈レビューの修正のコミットは含めない〉。Task 6 のコミットはまだ無いので、Task 6 の行は Task 7 Step 3 でコントローラが足す）

```python
import subprocess
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

PLAN = "docs/superpowers/plans/2026-09-26-veil-opening.md"
TASKS = [  # (見出しの行, そのタスクのコミットの件名)
    ("## Task 1: 序盤の研究外しの純関数と任せる先の表（TDD）", "feat(veil): 序盤の研究外しの窓・確認の純関数と任せる先の表を追加"),
    ("## Task 2: 設定 `open_moves`（既定値・登録・GUI の説明・マニュアルの表）", "feat(veil): 序盤の研究外しの設定 open_moves（既定 OFF）を登録する"),
    ("## Task 3: 任せる先の派生クラスと `_veil_open_delegate`（テストハーネスの拡張を含む）", "feat(veil): 序盤の窓で手を任せる難解＋の派生クラス（ponder なし）と作る処理を追加"),
    ("## Task 4: S4b（序盤の研究外し）を判定フローに組み込む（TDD）", "feat(veil): 序盤の研究外し（S4b・既定 OFF）を判定フローに組み込む"),
    ("## Task 5: ハーネスの韜晦の要約（spec §15.4）", "feat(selfplay): 韜晦の要約で序盤の研究外しの窓の手を別に数える"),
]
log = subprocess.run(["git", "log", "--format=%h%x09%s", "76105598..HEAD"], capture_output=True, check=True).stdout
latest = {}
for line in log.decode("utf-8").splitlines():  # 新しい順＝同じ件名が2つあれば新しい方
    h, _, subject = line.partition("\t")
    latest.setdefault(subject, h)
edits = []
for heading, subject in TASKS:
    if subject not in latest:
        sys.exit(f"commit not found: {subject}")
    edits.append((heading + "\n", f"{heading}\n\n状態: 完了（`{latest[subject]}`）。\n", 1))
patch(PLAN, edits)
print({s: latest[s] for _, s in TASKS})
```

Run: `python <scratchpad>/patch_open_t6_status.py`（worktree のルートで）
Expected: 5 件の件名とハッシュが出る（`commit not found` で止まったら、そのタスクのコミットの件名を `git log --oneline 76105598..HEAD` で確かめる）。old は「見出し＋改行」なので、スクリプトの中の見出しの文字列〈後ろが `"`〉には当たらない。

- [ ] **Step 5: 確かめてコミット**

Run: `python -m pytest tests/test_ai_veil.py tests/test_ai_help_text.py -q`
Expected: PASS。

```bash
git add .claude/rules CLAUDE.md docs
git commit -m "docs(veil): 序盤の研究外しを開発者向けルール・マニュアル・spec の状態に反映" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7（コントローラ）: 全体のテスト・ブランチのレビュー・Task 6 の状態・報告

KataGo・KaTrain・ハーネスは使わない。ユーザー設定（`C:\Users\iwaki\.katrain\config.json`）は読みも書きもしない（Global Constraints 3）。

- [ ] **Step 1: 全体のテスト**: worktree のルートで `python -m pytest -q -p no:cacheprovider tests --ignore=tests/test_ai.py`。期待: 2118 件すべて PASS（ブランチ先頭 `76105598` の 2070 件＋この計画の 48 件＝Task 1 13・Task 2 3・Task 3 8・Task 4 22・Task 5 2）。
- [ ] **Step 2: ブランチのレビュー**: `git log --oneline 76105598..HEAD` の Task 1〜6 のコミットを、superpowers:requesting-code-review で spec §15 と照らしてレビューする（特に: OFF と窓の外で記録が今と同じ・`_veil_error` の `open_index`〈S4b より前の例外でも窓の中なら付く・OFF では root に触れない〉・任せた手が None / pass の手番も tier `opening`・例外でも `board_watch_probe_warm` が戻る・任せる先の設定がユーザー設定の写し・Enigma*/Mimic のコードが無変更〈`git diff 76105598..HEAD -- katrain/core/ai.py` で Enigma のクラスの行に変更が無い〉）。指摘を直したらそのタスクの focused テストと Step 1 を流し直す。
- [ ] **Step 3: Task 6 の状態**（パッチスクリプト `<scratchpad>/patch_open_t7_status.py`。Task 6 の見出しの下に Task 6 のコミットのハッシュを足してコミットする）

```python
import subprocess
import sys

sys.path.insert(0, r"<scratchpad の実パス>")
from crlf_patch import patch

PLAN = "docs/superpowers/plans/2026-09-26-veil-opening.md"
HEADING = "## Task 6: 文書（開発者向けルール・CLAUDE.md・マニュアルの本文・spec の状態・INDEX・計画の状態）"
SUBJECT = "docs(veil): 序盤の研究外しを開発者向けルール・マニュアル・spec の状態に反映"
log = subprocess.run(["git", "log", "--format=%h%x09%s", "76105598..HEAD"], capture_output=True, check=True).stdout
hashes = [h for h, _, s in (line.partition("\t") for line in log.decode("utf-8").splitlines()) if s == SUBJECT]
if not hashes:
    sys.exit(f"commit not found: {SUBJECT}")
patch(PLAN, [(HEADING + "\n", f"{HEADING}\n\n状態: 完了（`{hashes[0]}`）。\n", 1)])
print(hashes[0])
```

Run: `python <scratchpad>/patch_open_t7_status.py`（worktree のルートで）→ Task 6 のハッシュが出る。続けて:

```bash
git add docs/superpowers/plans/2026-09-26-veil-opening.md
git commit -m "docs(veil): 序盤の研究外しの計画に Task 6 の状態を記す" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: 報告**: 結果（Step 1 の件数・Step 2 のレビューの結論）をユーザーに報告し、あわせて「GUI の設定画面に `veilN_open_moves` のスライダーを出すには、ユーザー設定の `ai:veil9` / `ai:veil13` / `ai:veil19` に `"veilN_open_moves": 0`（OFF のまま）が要る（`katrain/gui/popups.py` 491 行と 497 行＝ユーザー設定にあるキーしか出さない）。これは Plan A の範囲外なので、この計画では編集しない」と伝える。編集するかどうか・いつ・どう足すかは Plan A の外で決める。
- [ ] **Step 5: 次へ**: master にはまだマージしない。同じブランチで Plan B（spec §16）に進む。

---

## spec のあいまいさと、この計画での決め方

1. **None / pass の手番の tier・kind**: spec §15.3 手順6 は「ERROR ログ＋最善手（`open = "invariant"`）」だけで tier を書いていない → 手順7（記録: tier `opening`）と Plan B との共有インターフェース（任せた手番は tier `opening`・`open` played / invariant）に合わせて tier `opening`・kind `best`・why `invariant` にし、`open` `invariant` と `open_index` `open_src` `open_secs` `open_thoughts` `lead` `root_wr` を残す（ほかの不変条件違反の出口の tier `failsafe` とは違う＝Plan B は窓の手番を `decision_tier == "opening"` で数えられる）。
2. **「vloss を持たない kind」（§15.4）**: spec が名指しする kind `opening` だけ、その記録がどれも数値の `vloss` を持たなければ `vloss_by_kind` と `curse_by_kind` を None にする。ほかの kind（vloss を持たない `best` や終局帯の `pass` / `swap` / `finish` も）は今と同じ値＝`open_moves` 0 のアームの要約は変わらない（終局帯の swap / finish の curse はレポートの損失〈勝者の呪いの目安〉として残る）。
3. **§15.4 の「任せた手番の数」**: `open` が played か invariant の手番（難解＋を呼んだ手番）。要約には spec の5項目に `gate`・`invariant`・`errors` を足す。窓の記録が1つも無い局（OFF のアーム）は `opening` が None。
4. **`_veil_error` の `open_index`（§15.3 手順8）**: 窓の中の手番の例外ならどこで出ても足す（関門で止めて通常の流れに進んだ手番・S4b より前の S1〜S4 の例外を含む）。手番ごとに `_generate_move` で `self._veil_open_at = None` に戻し、S4b が窓の中で番号を置く。まだ None なら `_veil_error` が `_veil_open_index_or_none()` で判定し直す（`open_moves` 0 なら root に触れない・判定の例外は None）。
5. **任せた手番の `queries`**: 韜晦自身のクエリ数（0）のまま。難解＋の中のクエリは数えず、所要時間は `open_secs` で見る。
6. **関門の p_match の境界**: `veil_urgency` と同じく `p_match <= VEIL_TARGET_FLOOR` で任せない（ちょうど 0.15 も任せない）。
7. **(g) ponder のテスト**: 本物の難解＋の選択はエンジンが要るので、`Enigma9Strategy._generate_move` を「`_start_ponder` を呼んで D4 を返す」に差し替え、本物の `_veil_open_delegate` が作った派生クラスでスレッドが起動しないこと（同じ場面の素の難解＋では起動すること）を確かめる。
8. **スライダーの候補値の形**: `_ENIGMA_GAMBLE_UNTIL_MOVE` と同じ `(n, "n")` のタプルで、0 は `(0, "OFF")`（マニュアルの既定欄は `OFF`）。
9. **説明文**: `tests/test_ai_help_text.py` の `test_referenced_sibling_keys_exist_in_the_same_strategy` が説明文中のキー名を同じ戦略の節で探すので、`aiopt:veil*_open_moves` には `enigma*plus_…` のキー名を書かない（難解＋の設定は言葉で書く）。
10. **ユーザー設定**: 前の計画（forced の Task 5 Step 8）は GUI がキーを読めるように OFF の値を足したが、Plan B との共有インターフェースが Plan A の範囲を「パッケージの `katrain/config.json` だけ・ユーザー設定は決して触らない」と定めるので、この計画ではどのタスクでも触らない。GUI のスライダーに要る `"veilN_open_moves": 0` は、Task 7 Step 4 でコントローラが結果と一緒にユーザーに伝え、編集は Plan A の外で決める。

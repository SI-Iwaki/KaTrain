# 難解 13/19路 局所性オプション Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `ai:enigma13` / `ai:enigma19` に、own_rare（自手の意外さ）を「相手の直前手／KataGo 最善手」の近傍で減衰させ、net の同点帯では最もアンカーに近い手を採るオプション（既定 OFF＝現行とビット同一）を追加し、13路実戦の復元 SGF で効果と破損を測る。

**Architecture:** `katrain/core/ai.py` の難解戦略は純関数群（`enigma9_*`）＋ `Enigma9Strategy._generate_move`（13/19 路はクラス属性差し替えのサブクラスで共有）。純関数を3つ足し（`enigma9_locality` / `enigma9_anchors` / `enigma9_choose_local`）、`enigma9_net_score` に `locality` 引数を足し、`_generate_move` のスコア行と選択1箇所に配線する。設定は `SETTING_DEFAULTS` → `constants.AI_OPTION_VALUES` / `AI_OPTION_ORDER` → 両 `config.json` → i18n `.po` の既存経路。

**Tech Stack:** Python 3.12 / pytest（KataGo 不要の純関数テスト）/ `katrain_debug --batch`（KataGo 起動・約10分/run）

**Spec:** `docs/superpowers/specs/2026-08-25-enigma-locality-design.md`

## Global Constraints

- OFF（`locality_stddev` ≤ 0 または `locality_slack` ≤ 0）は**採用判断・解析条件ともビット同一**（spec §4.3）。クエリ本数・visits・条件は一切変えない（spec §4.4）。
- 近さ: `prox = max_a exp(-|m-a|^2 / (2σ^2))`、ユークリッド距離、アンカー無し／σ≤0 で 1.0（spec §4.1）。
- 局所化 net: `E + w_reply·reply_rare + w_own·prox·own_rare − cost_weight·max(0, loss)`（spec §4.2）。
- 帯タイブレーク: 帯 `net ≥ top.net − slack` の中で prox 最大（同点は net 大 → loss 小）、**pick 自身が `best.net + margin` 以上**のときだけ外す（spec §4.3）。
- 設定キー: `enigma13_locality_stddev`（候補 0/2/2.5/3/4/5・既定 0）/ `enigma13_locality_slack`（0/0.2/0.3/0.5/1.0・既定 0.3）/ `enigma19_locality_stddev`（0/3/4/5/6/7・既定 0）/ `enigma19_locality_slack`（同・既定 0.3）。9路には GUI・config を出さないが `Enigma9Strategy.SETTING_DEFAULTS` にも 0.0 / 0.3 を置く（spec §5）。
- コミットメッセージは日本語・Conventional Commits。`black` を既存ファイル全体に掛けない。
- **ユーザー `C:\Users\iwaki\.katrain\config.json` はサブエージェントに委任せずメインセッションで直接 Edit**、編集前に KaTrain が起動していないことを確認（起動中は終了時に上書きされる）。
- `.claude/rules/*.md` の Edit が拒否されたらサブエージェント経由で編集・コミット。
- ログ・batch 出力は Grep で抽出（全読みしない）。

---

## File Structure

| ファイル | 責務 | 変更 |
|---|---|---|
| `katrain/core/ai.py` | 純関数 `enigma9_locality` / `enigma9_anchors` / `enigma9_choose_local`、定数 `ENIGMA9_LOCALITY_STDDEV` / `ENIGMA9_LOCALITY_SLACK`、`enigma9_net_score(locality=)`、`Enigma9Strategy._generate_move` 配線、`SETTING_DEFAULTS` ×3 | Modify |
| `tests/test_ai_enigma9.py` | 純関数テスト | Modify |
| `katrain/core/constants.py` | `AI_OPTION_VALUES` / `AI_OPTION_ORDER` に4キー | Modify |
| `katrain/config.json` / `C:\Users\iwaki\.katrain\config.json` | `ai:enigma13` / `ai:enigma19` に4キー | Modify |
| `katrain/i18n/locales/{jp,en}/LC_MESSAGES/katrain.po` → `.mo` | 短ラベル4本＋`aihelp:enigma13/19` 追記 | Modify |
| `docs/superpowers/specs/calibration-data/enigma9/restore_sgf_from_log.py` | 実戦ログ→SGF 復元 | Create |
| `docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf` | 復元 SGF | Create |
| `docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py` | batch JSON → 距離分布・E 分布の集計 | Create |
| `docs/superpowers/specs/calibration-data/enigma9/enigma-locality-results-20260825.md` | 実測結果 | Create |
| `.claude/rules/ai-parameters.md` / `.claude/rules/ai-strategies.md` / spec 追記 | ドキュメント | Modify |

---

### Task 1: 近さ・アンカーの純関数と `enigma9_net_score(locality=)`

**Files:**
- Modify: `katrain/core/ai.py`（`ENIGMA9_JIGO_TARGET = -1.0` の直後に定数、`enigma9_rarity` の直後に純関数、`enigma9_net_score` に引数）
- Test: `tests/test_ai_enigma9.py`

**Interfaces:**
- Produces:
  - `ENIGMA9_LOCALITY_STDDEV: float = 0.0`, `ENIGMA9_LOCALITY_SLACK: float = 0.3`
  - `enigma9_locality(coords, anchors, stddev) -> float`（coords `(x, y)` or None、anchors `list[(x, y)]`）
  - `enigma9_anchors(last_move_coords, best_gtp) -> list[tuple[int, int]]`
  - `enigma9_net_score(loss, e_punish, reply_findability, own_hp, w_reply=..., w_own=..., cost_weight=1.0, locality=1.0) -> float`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ai_enigma9.py` の import に `ENIGMA9_LOCALITY_SLACK, ENIGMA9_LOCALITY_STDDEV, enigma9_anchors, enigma9_locality` を追加し、`class TestChoose` の直前に追加:

```python
class TestLocality:
    """own_rare の局所化（2026-08-25・spec enigma-locality §4.1〜4.2）。"""

    def test_zero_stddev_is_one_everywhere(self):
        assert enigma9_locality((0, 0), [(10, 10)], 0.0) == 1.0
        assert enigma9_locality((0, 0), [(10, 10)], -1.0) == 1.0

    def test_no_anchors_is_one(self):
        assert enigma9_locality((3, 3), [], 3.0) == 1.0

    def test_none_coords_is_one(self):
        assert enigma9_locality(None, [(3, 3)], 3.0) == 1.0

    def test_on_anchor_is_one_and_decays_with_distance(self):
        assert enigma9_locality((3, 3), [(3, 3)], 3.0) == pytest.approx(1.0)
        # d=3, σ=3 → exp(-0.5) ≒ 0.607 / d=6 → exp(-2) ≒ 0.135（spec §4.1 の目安）
        assert enigma9_locality((6, 3), [(3, 3)], 3.0) == pytest.approx(math.exp(-0.5))
        assert enigma9_locality((9, 3), [(3, 3)], 3.0) == pytest.approx(math.exp(-2.0))

    def test_two_anchors_take_max_not_mean(self):
        # 盤の反対側にある2点の平均は幻影中心（CLAUDE.md）。max なら片方に近ければ 1.0
        assert enigma9_locality((0, 0), [(0, 0), (12, 12)], 3.0) == pytest.approx(1.0)
        assert enigma9_locality((6, 6), [(0, 0), (12, 12)], 3.0) == pytest.approx(math.exp(-0.5 * 72 / 9))

    def test_anchors_from_last_move_and_best(self):
        # 相手の直前手 (x=2, y=3) と最善手 K10（13路: x=9, y=9）
        assert enigma9_anchors((2, 3), "K10") == [(2, 3), (9, 9)]

    def test_anchors_skip_missing_last_move_and_pass(self):
        assert enigma9_anchors(None, "K10") == [(9, 9)]
        assert enigma9_anchors((2, 3), "pass") == [(2, 3)]
        assert enigma9_anchors(None, "pass") == []

    def test_net_score_locality_scales_only_own_rarity(self):
        base = enigma9_net_score(0.2, 1.0, 0.05, 0.0)  # own_hp 0 → own_rare 1.0
        half = enigma9_net_score(0.2, 1.0, 0.05, 0.0, locality=0.5)
        assert base - half == pytest.approx(0.5 * ENIGMA9_W_OWN_RARE)
        # locality=1.0（既定）は従来式とビット同一
        assert enigma9_net_score(0.2, 1.0, 0.05, 0.0, locality=1.0) == base

    def test_defaults_are_off(self):
        assert ENIGMA9_LOCALITY_STDDEV == 0.0
        assert ENIGMA9_LOCALITY_SLACK == 0.3
```

ファイル先頭の `import json` の上に `import math` を追加。

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_enigma9.py::TestLocality -v`
Expected: FAIL（ImportError: cannot import name 'enigma9_locality'）

- [ ] **Step 3: 実装**

`katrain/core/ai.py` の `ENIGMA9_JIGO_TARGET = -1.0` の直後:

```python
# 局所性オプション（13/19路・spec 2026-08-25-enigma-locality-design.md）。own_rare（自手の
# 意外さ）を「相手の直前手／KataGo 最善手」の近傍でだけ満額買い、net の同点帯では最も
# アンカーに近い手を採る。stddev 0 = OFF（採用判断・解析条件とも従来とビット同一）
ENIGMA9_LOCALITY_STDDEV = 0.0      # 近さの σ（盤座標・ユークリッド）。0 で無効
ENIGMA9_LOCALITY_SLACK = 0.3       # 同点帯の幅（目相当）。stddev > 0 のときだけ効く
```

`enigma9_rarity` の直後:

```python
def enigma9_locality(coords, anchors, stddev):
    """候補手のアンカー近傍度 0〜1 ＝ max_a exp(-|m-a|^2 / (2σ^2))。

    アンカーは「相手の直前手」と「KataGo 最善手」の2点 max（Hunt の Focus と同形。平均は
    盤の反対側の2点で幻影中心になるので取らない）。coords が None（pass）・アンカー無し・
    σ<=0 は 1.0＝局所性なし（OFF と同値）。
    """
    if coords is None or not anchors or stddev is None or stddev <= 0:
        return 1.0
    x, y = coords
    var = float(stddev) ** 2
    best = 0.0
    for ax, ay in anchors:
        d2 = (x - ax) ** 2 + (y - ay) ** 2
        best = max(best, math.exp(-0.5 * d2 / var))
    return best


def enigma9_anchors(last_move_coords, best_gtp):
    """局所性のアンカー座標列。相手の直前手（None/pass は省く）＋ KataGo 最善手（pass は省く）。"""
    anchors = []
    if last_move_coords is not None:
        anchors.append(tuple(last_move_coords))
    if best_gtp and best_gtp != "pass":
        try:
            coords = Move.from_gtp(best_gtp).coords
        except Exception:
            coords = None
        if coords is not None:
            anchors.append(tuple(coords))
    return anchors
```

`enigma9_net_score` を差し替え:

```python
def enigma9_net_score(loss, e_punish, reply_findability, own_hp,
                      w_reply=ENIGMA9_W_REPLY_RARE, w_own=ENIGMA9_W_OWN_RARE,
                      cost_weight=1.0, locality=1.0):
    """難解さの正味スコア（目相当）＝ E + 応手の見つけにくさ + 近さ×自手の意外さ − 損失×重み。

    cost_weight は勝勢時の損失割引（`enigma9_spending_plan`）。通常は 1.0。
    locality は own_rare の局所化係数（`enigma9_locality`）。OFF なら 1.0＝従来式。
    """
    return (
        e_punish
        + w_reply * enigma9_rarity(reply_findability)
        + w_own * locality * enigma9_rarity(own_hp)
        - cost_weight * max(0.0, loss)
    )
```

`ai.py` 先頭で `math` が import 済みか確認（`grep -n "^import math" katrain/core/ai.py`）。無ければ追加。

- [ ] **Step 4: テスト通過を確認**

Run: `pytest tests/test_ai_enigma9.py -v`
Expected: 全 PASS（既存 71 件＋新規 9 件）

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_enigma9.py
git commit -m "feat(enigma): 局所性の純関数（近さ・アンカー）と net の own_rare 局所化引数を追加（既定 OFF）"
```

---

### Task 2: 同点帯タイブレーク `enigma9_choose_local`

**Files:**
- Modify: `katrain/core/ai.py`（`enigma9_choose` の直後）
- Test: `tests/test_ai_enigma9.py`

**Interfaces:**
- Consumes: `enigma9_choose(scored, best_gtp, margin)`（既存）
- Produces: `enigma9_choose_local(scored, best_gtp, margin, slack, stddev) -> tuple[dict | None, list[dict]]`（pick と帯。OFF 経路は `(enigma9_choose(...), [])`）。scored の各 dict は `gtp` / `net` / `loss` / `prox`（無ければ 1.0）を持つ。

- [ ] **Step 1: 失敗するテストを書く**

import に `enigma9_choose_local` を追加し、`class TestChoose` の直後に追加:

```python
class TestChooseLocal:
    """同点帯タイブレーク（2026-08-25・spec enigma-locality §4.3）。"""

    def entry(self, gtp, net, prox=1.0, loss=0.5):
        return {"gtp": gtp, "net": net, "loss": loss, "prox": prox}

    def test_off_paths_delegate_to_legacy_choose(self):
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 1.5, prox=0.1), self.entry("D4", 1.4, prox=1.0)]
        for slack, stddev in [(0.0, 3.0), (0.3, 0.0), (0.0, 0.0), (-1.0, 3.0)]:
            pick, band = enigma9_choose_local(scored, "E5", 0.0, slack, stddev)
            assert pick == enigma9_choose(scored, "E5", 0.0)
            assert pick["gtp"] == "C3" and band == []

    def test_band_prefers_nearest(self):
        # C3 が net 最大だが遠い。D4 は 0.1 劣るだけで近い → 帯 0.3 内なら D4
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 1.5, prox=0.1), self.entry("D4", 1.4, prox=1.0)]
        pick, band = enigma9_choose_local(scored, "E5", 0.0, 0.3, 3.0)
        assert pick["gtp"] == "D4"
        assert sorted(c["gtp"] for c in band) == ["C3", "D4"]

    def test_clearly_better_far_trap_survives(self):
        # 帯の外（0.5 差 > slack 0.3）なら遠い罠が残る
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 2.0, prox=0.1), self.entry("D4", 1.4, prox=1.0)]
        pick, band = enigma9_choose_local(scored, "E5", 0.0, 0.3, 3.0)
        assert pick["gtp"] == "C3" and [c["gtp"] for c in band] == ["C3"]

    def test_pick_itself_must_beat_best_plus_margin(self):
        # 帯の最大 net（C3 1.5）では代理しない: 近い D4 の net 1.1 が best 1.0 + margin 0.2 に届かなければ None
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 1.5, prox=0.1), self.entry("D4", 1.1, prox=1.0)]
        pick, _ = enigma9_choose_local(scored, "E5", 0.2, 0.5, 3.0)
        assert pick is None

    def test_prox_tie_breaks_by_net_then_loss(self):
        scored = [self.entry("E5", 1.0, loss=0.0), self.entry("C3", 1.5, prox=0.5, loss=0.4),
                  self.entry("D4", 1.5, prox=0.5, loss=0.2), self.entry("F6", 1.3, prox=0.5)]
        pick, _ = enigma9_choose_local(scored, "E5", 0.0, 0.3, 3.0)
        assert pick["gtp"] == "D4"

    def test_missing_prox_counts_as_one(self):
        scored = [self.entry("E5", 1.0, loss=0.0), {"gtp": "C3", "net": 1.5, "loss": 0.5}, self.entry("D4", 1.4, prox=0.3)]
        pick, _ = enigma9_choose_local(scored, "E5", 0.0, 0.3, 3.0)
        assert pick["gtp"] == "C3"

    def test_fail_safes(self):
        assert enigma9_choose_local([self.entry("C3", 5.0)], "E5", 0.0, 0.3, 3.0) == (None, [])
        assert enigma9_choose_local([self.entry("E5", 1.0)], "E5", 0.0, 0.3, 3.0) == (None, [])
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_enigma9.py::TestChooseLocal -v`
Expected: FAIL（ImportError）

- [ ] **Step 3: 実装**

`enigma9_choose` の直後:

```python
def enigma9_choose_local(scored, best_gtp, margin, slack, stddev):
    """同点帯タイブレーク付きの選択（局所性オプション）。返り値 (pick or None, band)。

    挑戦者の net 最大 top から slack 以内の帯を作り、帯の中で prox（`enigma9_locality`）最大
    ＝最もアンカーに近い手を pick する（同点は net 大 → loss 小）。**pick 自身の net が
    最善手 + margin 以上のときだけ外す**（帯の最大 net で代理しない＝打つ手そのものが
    最善手に勝っていること）。slack <= 0 または stddev <= 0 は従来の `enigma9_choose` を
    そのまま返す＝OFF は採用判断がビット同一（net が完全同値の挑戦者があっても prox で
    並べ替えない）。
    """
    if slack is None or slack <= 0 or stddev is None or stddev <= 0:
        return enigma9_choose(scored, best_gtp, margin), []
    best_entry = next((c for c in scored if c["gtp"] == best_gtp), None)
    if best_entry is None:
        return None, []
    challengers = [c for c in scored if c["gtp"] != best_gtp]
    if not challengers:
        return None, []
    top = max(challengers, key=lambda c: (c["net"], -c["loss"]))
    band = [c for c in challengers if c["net"] >= top["net"] - slack]
    pick = max(band, key=lambda c: (c.get("prox", 1.0), c["net"], -c["loss"]))
    if pick["net"] >= best_entry["net"] + margin:
        return pick, band
    return None, band
```

- [ ] **Step 4: テスト通過を確認**

Run: `pytest tests/test_ai_enigma9.py -v`
Expected: 全 PASS

- [ ] **Step 5: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_enigma9.py
git commit -m "feat(enigma): 同点帯タイブレーク enigma9_choose_local を追加（slack/stddev 0 で従来 choose に委譲）"
```

---

### Task 3: `_generate_move` への配線と `SETTING_DEFAULTS`

**Files:**
- Modify: `katrain/core/ai.py`（`Enigma9Strategy.SETTING_DEFAULTS` / `Enigma13Strategy.SETTING_DEFAULTS` / `Enigma19Strategy.SETTING_DEFAULTS`、`_generate_move` の `w_own = enigma9_own_rarity_weight(in_yose)` 直後・スコアループ・`chosen = enigma9_choose(...)`）
- Test: `tests/test_ai_enigma9.py`

**Interfaces:**
- Consumes: Task 1 / Task 2 の純関数
- Produces: 設定キー `<prefix>_locality_stddev` / `<prefix>_locality_slack`（`self._setting("locality_stddev")` で解決）、ログ行 `Locality:` / `Band:`、`Score` 行の `prox=`

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_ai_enigma9.py` の既存 `SETTING_DEFAULTS` を検査するクラス（`grep -n "SETTING_DEFAULTS" tests/test_ai_enigma9.py` で探す。無ければ `TestChooseLocal` の直後に新設）に追加:

```python
class TestLocalitySettings:
    def test_all_enigma_classes_default_locality_off(self):
        for cls in (Enigma9Strategy, Enigma13Strategy, Enigma19Strategy):
            assert cls.SETTING_DEFAULTS["locality_stddev"] == 0.0
            assert cls.SETTING_DEFAULTS["locality_slack"] == 0.3
```

- [ ] **Step 2: 失敗を確認**

Run: `pytest tests/test_ai_enigma9.py::TestLocalitySettings -v`
Expected: FAIL（KeyError: 'locality_stddev'）

- [ ] **Step 3: `SETTING_DEFAULTS` に追加**

3クラスとも `"aim_jigo": False,` の直後に:

```python
        "locality_stddev": 0.0,   # 局所性 σ（0=OFF）。9路は GUI/config に出さない＝常に OFF
        "locality_slack": 0.3,    # 同点帯の幅（目相当）
```

- [ ] **Step 4: `_generate_move` に配線**

`w_own = enigma9_own_rarity_weight(in_yose)` の直後に追加:

```python
        # ---- 局所性オプション（13/19路・既定 OFF）----
        # own_rare を「相手の直前手／KataGo 最善手」の近傍で減衰させ、net の同点帯では最も
        # 近い手を採る。σ<=0 なら prox は全候補 1.0・選択は従来 choose＝ビット同一
        loc_stddev = float(self._setting("locality_stddev") or 0.0)
        loc_slack = float(self._setting("locality_slack") or 0.0)
        last_coords = self.cn.move.coords if (self.cn.move and not self.cn.move.is_pass) else None
        anchors = enigma9_anchors(last_coords, best_gtp) if loc_stddev > 0 else []
        if loc_stddev > 0:
            anchor_txt = ", ".join(
                f"{'last' if i == 0 and last_coords is not None else 'best'}({Move(a, player=player).gtp()})"
                for i, a in enumerate(anchors)
            )
            self._log(f"Locality: anchors=[{anchor_txt}] stddev={loc_stddev:.1f} slack={loc_slack:.2f}")
```

（`Move.is_pass` は `sgf_parser.py:68` の property。`math` は `ai.py:4` で import 済み）

スコアループ内、`own_hp = own_hp_of(c["gtp"])` の直後:

```python
            prox = enigma9_locality(Move.from_gtp(c["gtp"]).coords, anchors, loc_stddev)
```

`net = enigma9_net_score(...)` の呼び出しに `locality=prox` を追加し、`scored.append({... "net": net})` に `"prox": prox` を追加、Score ログの `own_hp={own_hp:.3f} (w_own={w_own:.1f})` の直後に ` prox={prox:.2f}` を追加。

`chosen = enigma9_choose(scored, best_gtp, margin)` を差し替え:

```python
        chosen, band = enigma9_choose_local(scored, best_gtp, margin, loc_slack, loc_stddev)
        if band:
            self._log(
                f"Band: {len(band)} within slack {loc_slack:.2f} of top net -> "
                f"nearest {chosen['gtp'] if chosen else 'none'}"
                + (f" (prox {chosen['prox']:.2f}, net {chosen['net']:.2f})" if chosen else "")
            )
```

`Deviate:` ログの `find_hp={chosen['find']:.3f}` の直後に `, prox={chosen.get('prox', 1.0):.2f}` を追加。

- [ ] **Step 5: テストと OFF の同一性確認**

Run: `pytest tests/test_ai_enigma9.py -v` → 全 PASS。
Run: `pytest tests --ignore=tests/test_ai.py -q` → 全 PASS（既存 941 前後）。
Run（KataGo 起動・約30秒。OFF で従来どおり動くことの煙テスト）:
```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma9/enigma9-vs-human-20260810-white.sgf --move 21 --strategy enigma9 --output text 2>&1 | grep -a "Deviate\|Best move wins\|prox=" | head -5
```
Expected: `Score` 行に `prox=1.00` が並び、`Locality:` 行は出ない（9路は σ=0）。着手は従来（spec 追記1 の F3）。

- [ ] **Step 6: コミット**

```bash
git add katrain/core/ai.py tests/test_ai_enigma9.py
git commit -m "feat(enigma): 難解 13/19路に局所性オプションを配線（own_rare 局所化＋同点帯タイブレーク・既定 OFF）"
```

---

### Task 4: 設定の露出（constants / config.json ×2 / i18n）

**Files:**
- Modify: `katrain/core/constants.py`（`AI_OPTION_VALUES` の `"enigma13_unsettled_max"` / `"enigma19_unsettled_max"` 行の直後、`AI_OPTION_ORDER` の同キー直後）
- Modify: `katrain/config.json`（`"ai:enigma13"` / `"ai:enigma19"`）
- Modify: `C:\Users\iwaki\.katrain\config.json`（**メインセッションで直接 Edit**）
- Modify: `katrain/i18n/locales/jp/LC_MESSAGES/katrain.po`, `katrain/i18n/locales/en/LC_MESSAGES/katrain.po`

- [ ] **Step 1: 検証スクリプト（失敗確認）**

```bash
python - <<'EOF'
import json, io
from katrain.core.constants import AI_OPTION_VALUES, AI_OPTION_ORDER
keys = ["enigma13_locality_stddev", "enigma13_locality_slack", "enigma19_locality_stddev", "enigma19_locality_slack"]
pkg = json.load(io.open("katrain/config.json", encoding="utf-8"))["ai"]
usr = json.load(io.open(r"C:/Users/iwaki/.katrain/config.json", encoding="utf-8"))["ai"]
for k in keys:
    sec = "ai:enigma13" if "13" in k else "ai:enigma19"
    assert k in AI_OPTION_VALUES and k in AI_OPTION_ORDER, k
    assert k in pkg[sec] and k in usr[sec], (k, sec)
print("ok")
EOF
```
Expected: AssertionError（未追加）

- [ ] **Step 2: `constants.py`**

`AI_OPTION_VALUES` の `"enigma13_unsettled_max": [8, 12, 16, 20, 24],` の直後:

```python
    # 局所性（spec 2026-08-25-enigma-locality-design.md）: own_rare を相手の直前手／KataGo
    # 最善手の近傍で減衰させ、net の同点帯では最も近い手を採る。0 = OFF（従来とビット同一）
    "enigma13_locality_stddev": [(0.0, "OFF"), (2.0, "2.0"), (2.5, "2.5"), (3.0, "3.0"), (4.0, "4.0"), (5.0, "5.0")],
    "enigma13_locality_slack": [0.0, 0.2, 0.3, 0.5, 1.0],
```

`"enigma19_unsettled_max": [24, 30, 36, 42, 48],` の直後:

```python
    "enigma19_locality_stddev": [(0.0, "OFF"), (3.0, "3.0"), (4.0, "4.0"), (5.0, "5.0"), (6.0, "6.0"), (7.0, "7.0")],
    "enigma19_locality_slack": [0.0, 0.2, 0.3, 0.5, 1.0],
```

`AI_OPTION_ORDER` の `"enigma13_unsettled_max": 7,` の直後に `"enigma13_locality_stddev": 8,` `"enigma13_locality_slack": 9,`、`"enigma19_unsettled_max": 7,` の直後に `"enigma19_locality_stddev": 8,` `"enigma19_locality_slack": 9,`。

- [ ] **Step 3: パッケージ `katrain/config.json`**

`"enigma13_unsettled_max": 16` を `"enigma13_unsettled_max": 16,\n            "enigma13_locality_stddev": 0.0,\n            "enigma13_locality_slack": 0.3` に、`"enigma19_unsettled_max": 36` を同様に `enigma19_` で置換（末尾カンマの有無に注意＝JSON として `python -c "import json;json.load(open('katrain/config.json'))"` が通ること）。

- [ ] **Step 4: ユーザー `C:\Users\iwaki\.katrain\config.json`（メインセッション）**

先に `tasklist | grep -a -i "python\|katrain"` で KaTrain が起動していないことを確認。`"enigma13_unsettled_max": 16` / `"enigma19_unsettled_max": 36` の行に同じ2キーを追加（値は 0.0 / 0.3）。`python -c "import json;json.load(open(r'C:/Users/iwaki/.katrain/config.json'))"` で検証。

- [ ] **Step 5: i18n**

`katrain/i18n/locales/jp/LC_MESSAGES/katrain.po` の `msgid "enigma13_unsettled_max"` ブロックの直後（空行の後）:

```
msgid "enigma13_locality_stddev"
msgstr "[13路] 局所性（意外さの有効半径・OFF=従来）"

msgid "enigma13_locality_slack"
msgstr "[13路] 局所性の同点帯（目）"
```

`msgid "enigma19_unsettled_max"` ブロックの直後に `[19路]` で同2本。

`msgid "aihelp:enigma13"` の msgstr 末尾 `13路以外の盤では常に最善手を打つだけになるので、他の戦略を使ってください。"` の**直前**に挿入:

```
enigma13_locality_stddev: 局所性（OFF=従来）。ON にすると「自手の意外さ」ボーナスを相手の直前手と KataGo 最善手の近傍でだけ満額買い、遠いほど減衰させ（σ=この値の正規分布）、さらに難解さが同点帯（enigma13_locality_slack 目以内）で並ぶ候補の中では最も近い手を選びます＝別の隅へ飛び飛びに打って手抜きに見える癖を抑えつつ、明確に優る遠くの罠はそのまま打ちます。
```

`msgid "aihelp:enigma19"` も同様（`grep -n 'msgid "aihelp:enigma19"' -A1` で末尾文を確認し、その直前に `enigma19_` に読み替えた同文を挿入）。

`katrain/i18n/locales/en/LC_MESSAGES/katrain.po`: `msgid "enigma13_unsettled_max"` ブロック直後に

```
msgid "enigma13_locality_stddev"
msgstr "[13x13] Locality stddev (OFF = classic)"

msgid "enigma13_locality_slack"
msgstr "[13x13] Locality tie band (pts)"
```

（`enigma19_` は `[19x19]`）。`aihelp:enigma13` の末尾 `On other board sizes it simply plays the best move."` の直前に:

```
enigma13_locality_stddev: locality (OFF = classic behaviour). When on, the own-move surprise bonus is paid in full only near the opponent's last move and KataGo's best move and decays with distance (Gaussian with this stddev), and among candidates whose difficulty ties within enigma13_locality_slack points the nearest one is chosen - this curbs the habit of hopping to another corner every move (which looks like serial tenuki) while still playing a distant trap that is clearly better. 
```

`aihelp:enigma19` も同様に `enigma19_`。

- [ ] **Step 6: `.mo` コンパイルと検証**

```bash
python tools/compile_mo.py
```
Step 1 の検証スクリプトを再実行 → `ok`。`pytest tests/test_ai_options_grid.py -q`（存在すれば）→ PASS。

- [ ] **Step 7: コミット**

```bash
git add katrain/core/constants.py katrain/config.json katrain/i18n
git commit -m "feat(enigma): 局所性オプションの設定を GUI に露出（constants / config.json / i18n）"
```

---

### Task 5: 13路実戦の SGF 復元と距離指標スクリプト

**Files:**
- Create: `docs/superpowers/specs/calibration-data/enigma9/restore_sgf_from_log.py`
- Create: `docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf`
- Create: `docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py`

**Interfaces:**
- Produces: `python restore_sgf_from_log.py <log> <out.sgf>`（priority 1011＝実ノード解析クエリの最長 `moves` を採り、W 列が `Playing move` 列と一致することを assert）、`python locality_jump_metrics.py <batch.json> <sgf> [--player W]`（外した手ごとの「相手の直前手」「KataGo 最善手」からのチェビシェフ距離分布・外し率・point_loss 合計を ASCII で出力）

- [ ] **Step 1: 復元スクリプト**

```python
"""実戦ログ（debug_level 1）のクエリ JSON から SGF を復元する。

priority 1011（実ノードの通常解析）のクエリだけを見る＝ponder（-39）は温める応手を
末尾に足した仮想局面なので混ぜてはいけない。復元した W 列が `Playing move` の列と
一致することを assert して、AI の手番（depth の偶奇）を取り違えないようにする。
用法: python restore_sgf_from_log.py <log> <out.sgf> [--ai W|B]
"""
import json
import re
import sys

REAL_PRIORITY = 1011
COLS = "ABCDEFGHJKLMNOPQRST"
SGF = "abcdefghijklmnopqrs"


def main():
    log, out = sys.argv[1], sys.argv[2]
    ai = sys.argv[sys.argv.index("--ai") + 1] if "--ai" in sys.argv else "W"
    txt = open(log, encoding="utf-8", errors="replace").read()
    best = None
    for m in re.finditer(r"Sending query QUERY:\d+: (\{.*\})", txt):
        try:
            q = json.loads(m.group(1))
        except Exception:
            continue
        if q.get("priority") != REAL_PRIORITY:
            continue
        if best is None or len(q["moves"]) > len(best["moves"]):
            best = q
    assert best is not None, "no real-node query found (debug_level 1 required)"
    plays = re.findall(r"Playing move (\S+) and creating game node", txt)
    ai_moves = [g for c, g in best["moves"] if c == ai]
    n = min(len(plays), len(ai_moves))
    assert ai_moves[:n] == plays[:n], f"AI colour mismatch: {ai_moves[:5]} vs {plays[:5]}"
    size = best["boardXSize"]

    def sgf_coord(gtp):
        if gtp == "pass":
            return ""
        return SGF[COLS.index(gtp[0])] + SGF[size - int(gtp[1:])]

    nodes = "".join(f";{c}[{sgf_coord(g)}]" for c, g in best["moves"])
    pb, pw = ("human", "enigma") if ai == "W" else ("enigma", "human")
    sgf = f"(;GM[1]FF[4]SZ[{size}]KM[{best['komi']}]RU[{best['rules']}]PB[{pb}]PW[{pw}]{nodes})"
    open(out, "w", encoding="utf-8").write(sgf)
    print(f"{len(best['moves'])} moves, size {size}, komi {best['komi']}, AI={ai} -> {out}")


if __name__ == "__main__":
    main()
```

Run:
```bash
cd docs/superpowers/specs/calibration-data/enigma9
python restore_sgf_from_log.py "C:/Users/iwaki/.katrain/logs/game_20260823_051702.log" enigma13-vs-human-20260823-white.sgf
```
Expected: `100 moves, size 13, komi 7.0, AI=W -> ...`（実測: priority 1011 の最長は 100 手・W 列は `Playing move` 50 手と一致）

- [ ] **Step 2: 距離指標スクリプト**

```python
"""katrain_debug --batch --output json の出力から「飛び飛び」指標を出す。

外した手（selected != ai_top）ごとに、相手の直前手（SGF の move_num-1）と KataGo 最善手
（ai_top）からのチェビシェフ距離を取り、分布・外し率・point_loss 合計を ASCII で出す。
用法: python locality_jump_metrics.py <batch.json> <sgf> [--player W]
"""
import json
import re
import sys
from collections import Counter

COLS = "ABCDEFGHJKLMNOPQRST"
SGF = "abcdefghijklmnopqrs"


def gtp_xy(g):
    return COLS.index(g[0]), int(g[1:])


def sgf_moves(path):
    txt = open(path, encoding="utf-8").read()
    size = int(re.search(r"SZ\[(\d+)\]", txt).group(1))
    out = []
    for c, v in re.findall(r";([BW])\[([a-s]{0,2})\]", txt):
        out.append(None if not v else (COLS[SGF.index(v[0])] + str(size - SGF.index(v[1]))))
    return out


def cheb(a, b):
    (x1, y1), (x2, y2) = gtp_xy(a), gtp_xy(b)
    return max(abs(x1 - x2), abs(y1 - y2))


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    moves = sgf_moves(sys.argv[2])
    player = sys.argv[sys.argv.index("--player") + 1] if "--player" in sys.argv else None
    rows = [m for m in data["moves"] if (player is None or m["player"] == player)]
    dev = [m for m in rows if not m["match_top"] and m["selected"] != "pass" and m["ai_top"] != "pass"]
    d_last, d_best = Counter(), Counter()
    for m in dev:
        prev = moves[m["move_num"] - 2] if m["move_num"] >= 2 else None  # move_num は1始まり
        if prev:
            d_last[cheb(m["selected"], prev)] += 1
        d_best[cheb(m["selected"], m["ai_top"])] += 1
    loss = sum((m["point_loss"] or 0.0) for m in rows)
    print(f"moves={len(rows)} deviations={len(dev)} ({len(dev) / max(1, len(rows)):.0%}) total_loss={loss:.2f}")
    print("cheb(selected, opp_last):", dict(sorted(d_last.items())), " >=4:", sum(v for k, v in d_last.items() if k >= 4))
    print("cheb(selected, ai_top):  ", dict(sorted(d_best.items())), " >=4:", sum(v for k, v in d_best.items() if k >= 4))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 動作確認（既存 batch JSON が無いので煙テストのみ）**

```bash
python docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py --help 2>&1 | head -2
python -c "import ast,sys;ast.parse(open('docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py').read());print('syntax ok')"
```

- [ ] **Step 4: コミット**

```bash
git add docs/superpowers/specs/calibration-data/enigma9/restore_sgf_from_log.py docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py
git commit -m "test(enigma): 13路実戦ログの SGF 復元と飛び飛び指標の集計スクリプトを追加"
```

---

### Task 6: 13路バッチ A/B（OFF / σ3 / σ4 ×3run）と 19路の方向確認

**Files:**
- Create: `docs/superpowers/specs/calibration-data/enigma9/enigma-locality-results-20260825.md`
- Output（コミットしない）: scratchpad `enigma13_<arm>_run<n>.json`

**Interfaces:**
- Consumes: Task 4 の設定キー（`--settings enigma13_locality_stddev=3.0 enigma13_locality_slack=0.3`）、Task 5 の SGF とスクリプト

- [ ] **Step 1: 両アームが本当に違う設定で走ることを確認（CLAUDE.md「A/B を設計したら…」）**

```bash
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf --move 2 --strategy enigma13 --settings enigma13_aim_jigo=true enigma13_target_score=1.5 enigma13_locality_stddev=3.0 enigma13_locality_slack=0.3 --output text 2>&1 | grep -a "Initializing\|Locality:\|Band:\|Deviate\|Best move wins" | head
python -m katrain_debug --sgf docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf --move 2 --strategy enigma13 --settings enigma13_aim_jigo=true enigma13_target_score=1.5 --output text 2>&1 | grep -a "Initializing\|Locality:\|prox=" | head -4
```
Expected: 1本目は `Initializing … 'enigma13_locality_stddev': 3.0` と `Locality: anchors=[last(K10), best(D4)] …` が出る。2本目は `Locality:` が出ず `prox=1.00`。（move 2 = 白の初手＝ログでは K3 に外した手番。ON なら K3 の net が 0.94 → 約 0.12 に落ちるはず）

- [ ] **Step 2: バッチ実行（バックグラウンド・約10分/run × 9）**

scratchpad に出す。3 arm × 3 run を順に（並列にすると GPU を取り合って時間比較が壊れる）:

```bash
S="C:/Users/iwaki/AppData/Local/Temp/claude/C--Users-iwaki-Documents-katrain-1-17-1-1-katrain-1-17-1-1/8f3f6427-de25-493a-bf9e-bef8f484743b/scratchpad"
SGF=docs/superpowers/specs/calibration-data/enigma9/enigma13-vs-human-20260823-white.sgf
BASE="enigma13_aim_jigo=true enigma13_target_score=1.5"
for run in 1 2 3; do
  for arm in off s3 s4; do
    case $arm in off) EXTRA="";; s3) EXTRA="enigma13_locality_stddev=3.0 enigma13_locality_slack=0.3";; s4) EXTRA="enigma13_locality_stddev=4.0 enigma13_locality_slack=0.3";; esac
    PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf $SGF --strategy enigma13 --batch --player W --settings $BASE $EXTRA --output json > "$S/enigma13_${arm}_run${run}.json" 2> "$S/enigma13_${arm}_run${run}.err"
  done
done
```
（`run_in_background` で起動し、完了通知を待つ。途中で `grep -a -c '"move_num"' $S/enigma13_*_run*.json` で進捗確認）

- [ ] **Step 3: 集計**

```bash
for f in "$S"/enigma13_*_run*.json; do echo "== $f"; python docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py "$f" $SGF --player W; python -c "import json,sys;d=json.load(open(sys.argv[1]));s=d['stats']['overall'];print({k:round(v,3) for k,v in s.items() if k in ('ai_top_move','ai_top5_move','mean_ptloss')})" "$f"; done
```

外した手の E 分布は batch JSON に無いので、`--move N` の個別実行で「OFF では遠い罠だった手番」を 3 手番選び（Step 2 のログの `Deviate … E=` が 2 以上の手番＝復元 SGF の move 番号は ログの Deviate 行の順序 × 2）、ON でその手が帯に残るか `Band:` 行で確認する。

- [ ] **Step 4: 19路の方向確認（OFF / σ5 × 1run）**

```bash
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --strategy enigma19 --batch --player W --move-range 1-120 --output json > "$S/enigma19_off.json" 2> "$S/enigma19_off.err"
PYTHONIOENCODING=utf-8 python -m katrain_debug --sgf tests/data/ogs.sgf --strategy enigma19 --batch --player W --move-range 1-120 --settings enigma19_locality_stddev=5.0 enigma19_locality_slack=0.3 --output json > "$S/enigma19_s5.json" 2> "$S/enigma19_s5.err"
python docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py "$S/enigma19_off.json" tests/data/ogs.sgf --player W
python docs/superpowers/specs/calibration-data/enigma9/locality_jump_metrics.py "$S/enigma19_s5.json" tests/data/ogs.sgf --player W
```
（`tests/data/ogs.sgf` は SZ[19]・113手）

- [ ] **Step 5: 結果 md**

`enigma-locality-results-20260825.md` に、arm × run の表（外し率 / `ai_top_move` / `mean_ptloss` / 距離≥4 の本数（対 直前手・対 最善手）/ total_loss）、3run 平均、Step 3 の遠い罠3手番の帯残存、19路の方向、を書く。判定は spec §7「採用判断」＝距離分布の改善と (c) 損失 (d) E≥1 の罠残存を並べる。**run 間ノイズ（ai_top_move ±0.03 / mean_ptloss ±0.05）より小さい差は差と読まない。**

- [ ] **Step 6: コミット**

```bash
git add docs/superpowers/specs/calibration-data/enigma9/enigma-locality-results-20260825.md
git commit -m "docs(enigma): 局所性オプションの 13路 A/B 実測（OFF/σ3/σ4 ×3run）と 19路の方向確認"
```

---

### Task 7: ドキュメント（rules / spec 追記）

**Files:**
- Modify: `.claude/rules/ai-parameters.md`（`enigma13_unsettled_max` 行・`enigma19_unsettled_max` 行の直後）
- Modify: `.claude/rules/ai-strategies.md`（`**13路の実戦校正は未実施**）。` と `**19路の実戦校正は未実施**）。` の直後）
- Modify: `docs/superpowers/specs/2026-08-25-enigma-locality-design.md`（末尾に「## 9. 実測（2026-08-25）」）
- Modify: `docs/superpowers/specs/INDEX.md`（🟡 → 🟢）

- [ ] **Step 1: `ai-parameters.md`**

Enigma13 の表の `enigma13_unsettled_max` 行の直後に:

```
| `enigma13_locality_stddev` | **局所性（2026-08-25・spec `2026-08-25-enigma-locality-design.md`）**。own_rare（自手の意外さ）を「相手の直前手／KataGo 最善手」の2アンカー max Gaussian（σ=この値）で減衰させ、net の同点帯では最もアンカーに近い手を採る。0=OFF＝採用判断・解析条件とも従来とビット同一。実測 13路: <Task 6 の要約（OFF→σ3 の距離≥4 本数と損失）> | OFF/2/2.5/3/4/5 | **0（OFF）**・推奨 <Task 6 で決めた値> |
| `enigma13_locality_slack` | 同点帯の幅（目相当）。stddev>0 のときだけ効く。帯の中で prox 最大の手を pick し、**pick 自身が最善 net + margin 以上**のときだけ外す | 0/0.2/0.3/0.5/1.0 | 0.3 |
```

Enigma19 の表にも `enigma19_` で同2行（候補 OFF/3/4/5/6/7、実測は「19路は方向確認のみ・未校正」）。

- [ ] **Step 2: `ai-strategies.md`**

`**13路の実戦校正は未実施**）。` の直後に1文:

```
13/19路には**局所性オプション** `enigma{13,19}_locality_stddev` / `_locality_slack`（2026-08-25・既定 OFF・spec `2026-08-25-enigma-locality-design.md`）がある＝13/19路では外した手の 69% が最善手からチェビシェフ距離 4 以上で、序盤は E≈0 のまま own_rare だけで別の隅へ飛ぶ（追記6 のヨセと同じ「own_rare が順位を決める」構造の序盤版）ため、own_rare を相手の直前手／KataGo 最善手の近傍で減衰させ、net の同点帯では最も近い手を採る。明確に優る遠い罠は帯の外なので残る。
```

- [ ] **Step 3: spec 追記と INDEX**

spec 末尾に `## 9. 実測（2026-08-25）` として Task 6 の結果 md の要約（表1つ＋判定）と、`## 3` の保留項目（第3アンカー）の要否を書く。INDEX の 🟡 行を 🟢 に変え「実装済み・13路実測あり・19路未校正」に。

- [ ] **Step 4: 検証とコミット**

```bash
pytest tests --ignore=tests/test_ai.py -q
git add .claude/rules/ai-parameters.md .claude/rules/ai-strategies.md docs/superpowers/specs/2026-08-25-enigma-locality-design.md docs/superpowers/specs/INDEX.md
git commit -m "docs(enigma): 局所性オプションのパラメータ表・戦略概要・spec 実測節を更新"
```
（`.claude/rules/` の Edit が拒否されたらサブエージェント経由）

---

## Self-Review

- **Spec coverage**: §4.1 近さ → Task 1 / §4.2 局所化 net → Task 1+3 / §4.3 帯タイブレーク → Task 2+3 / §4.4 不変（クエリ本数）→ Task 3 は座標計算のみ追加 / §4.5 ログ → Task 3 / §5 設定 → Task 3（SETTING_DEFAULTS）+ Task 4 / §6 ファイル → Task 4・5・7 / §7 検証 1〜4 → Task 1・2・3（単体・回帰）、Task 5・6（13路 A/B・19路）/ §8 却下案 → 実装なし（spec 記録のみ）。
- **Placeholder scan**: Task 7 の `<Task 6 の要約>` / `<Task 6 で決めた値>` は実測後に埋める値（実行時に確定する数値であって未設計ではない）。それ以外に TBD 無し。
- **Type consistency**: `enigma9_locality(coords, anchors, stddev)` / `enigma9_anchors(last_move_coords, best_gtp)` / `enigma9_choose_local(scored, best_gtp, margin, slack, stddev) -> (pick, band)` / `enigma9_net_score(..., locality=1.0)` / 設定 suffix `locality_stddev` `locality_slack` は Task 1〜4・6 で一貫。

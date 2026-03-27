---
description: KaTrain設定構造・起動時リセット・JsonStoreの落とし穴（base_katrain.py編集時に参照）
paths:
  - "katrain/core/base_katrain.py"
---

# base_katrain.py 実装ガイド

## config.json の構造と JsonStore のアクセス方法

KaTrain の設定は Kivy の `JsonStore` で管理される。**重要な落とし穴**がある。

### JsonStore のトップレベルキー構造

`dict(self._config_store)` はトップレベルキーのみを取得する：

```
engine, contribute, general, timer, game, trainer, ai, ui_state, dist_models
```

`ai:human` はトップレベルキーでは**ない**。`ai` キーの値（dict）の中にネストされている：

```python
# NG: self._config["ai:human"]  → KeyError / None
# OK: self._config["ai"]["ai:human"]
```

### config.json のネスト構造（ai セクション）

```json
{
  "ai": {
    "black": { ... },
    "white": { ... },
    "ai:human": { "human_kyu_rank": ..., "policy_temperature": ... },
    "ai:pro":   { "pro_year": ... },
    "ai:p:rank": { "kyu_rank": ... }
  }
}
```

### 設定値の読み書きパターン

```python
# 読み取り
value = self._config["ai"]["ai:human"]["policy_temperature"]

# 書き込み（ファイルにも即時反映される）
self._config["ai"]["ai:human"]["policy_temperature"] = 1.0
self._config_store.put("ai", **self._config["ai"])
```

`self._config_store.put("ai", ...)` を呼ぶと `C:\Users\iwaki\.katrain\config.json` に即時書き込まれる。

## 起動時リセットのパターン

「セッション中のみ有効で起動時に初期値に戻したい設定」は `_load_config` の末尾に追加する：

```python
# _load_config の末尾（self._config = dict(self._config_store) の直後）
if "ai" in self._config and "ai:human" in self._config["ai"]:
    if "policy_temperature" in self._config["ai"]["ai:human"]:
        self._config["ai"]["ai:human"]["policy_temperature"] = 1.0
        self._config_store.put("ai", **self._config["ai"])
```

### なぜ `_load_config` の末尾か

- `_load_config` の後に `save_config()` が呼ばれる箇所があるが、`self._config` を修正しておけば上書きされない
- GUI 初期化前に値が確定するため、スライダー等のウィジェットが正しい値で描画される

## デバッグ方法（設定値が反映されない場合）

コードを変更してもGUIの値が変わらない場合、以下を確認する：

```python
# 対話型で構造を確認
from kivy.storage.jsonstore import JsonStore
store = JsonStore('C:/Users/iwaki/.katrain/config.json')
d = dict(store)
print(list(d.keys()))                          # トップレベルキー一覧
print(d.get('ai', {}).keys())                  # ai サブキー一覧
print(d['ai']['ai:human']['policy_temperature']) # 値確認
```

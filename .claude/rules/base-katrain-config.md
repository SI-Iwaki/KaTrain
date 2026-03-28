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
    "ai:human": { "human_kyu_rank": ..., "first_impression_deviation": ... },
    "ai:pro":   { "pro_year": ... },
    "ai:p:rank": { "kyu_rank": ... }
  }
}
```

### 設定値の読み書きパターン

```python
# 読み取り
value = self._config["ai"]["ai:human"]["first_impression_deviation"]

# 書き込み（ファイルにも即時反映される）
self._config["ai"]["ai:human"]["first_impression_deviation"] = False
self._config_store.put("ai", **self._config["ai"])
```

`self._config_store.put("ai", ...)` を呼ぶと `C:\Users\iwaki\.katrain\config.json` に即時書き込まれる。

## 起動時リセットのパターン

現在、起動時リセット対象の設定はない。将来「セッション中のみ有効で起動時に初期値に戻したい設定」が必要な場合は `_load_config` の末尾に追加する。

`first_impression_deviation` 等のように、ユーザーが明示的にON/OFFを選ぶ設定は起動時リセットしない。

## デバッグ方法（設定値が反映されない場合）

コードを変更してもGUIの値が変わらない場合、以下を確認する：

```python
# 対話型で構造を確認
from kivy.storage.jsonstore import JsonStore
store = JsonStore('C:/Users/iwaki/.katrain/config.json')
d = dict(store)
print(list(d.keys()))                          # トップレベルキー一覧
print(d.get('ai', {}).keys())                  # ai サブキー一覧
print(d['ai']['ai:human']['first_impression_deviation']) # 値確認
```

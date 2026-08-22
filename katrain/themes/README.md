# 同梱テーマ

`katrain/gui/theme_manager.py` が読む盤面テーマ。1テーマ = 1ディレクトリで、
中に `theme*.json`（`Theme` クラスの属性上書き）と、差し替える画像を置く。

画像は Kivy の `resource_find` が名前で解決するので、`katrain/img/` と同名のファイル
（`board.png` / `B_stone.png` / `W_stone.png` / `topmove.png` 等）を置けば差し替わる。
別名にしたい場合は json 側で `"BOARD_TEXTURE": "kaya.png"` のように指定する。

ユーザーが追加するテーマは `~/.katrain/themes/<名前>/` に同じ構成で置くと一覧に出る。

## 出典

上流 https://github.com/sanderland/katrain の `themes/` から取り込んだもの。

| ディレクトリ | 作者 | 備考 |
|---|---|---|
| `koast/` | reddit.com/user/-koast- | 盤・石の別デザイン |
| `lizzie/` | Eric W（画像は [Lizzie](https://github.com/featurecat/lizzie/) by featurecat and contributors 由来） | Lizzie 風。不確実な手のヒントを点で出さずに隠す |
| `milos/` | Milos | kaya 盤・地合いをシェード表示・マーク無し |

各ディレクトリの `README.md` も原文のまま残してある。

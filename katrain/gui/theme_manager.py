"""盤面テーマ（盤・碁石のデザイン）の一覧と切り替え。

テーマ = 1ディレクトリで、中の `theme*.json` が `Theme` クラスの属性を上書きし、
同梱画像と同名のファイル（`board.png` 等）がそのまま画像を差し替える。
探索は Kivy の `resource_find` 任せで、選択中のテーマのディレクトリを検索パスの
末尾に置く（`resource_find` は `reversed(resource_paths)` を走るので後勝ち）。

適用順は デフォルト → `~/.katrain/theme*.json`（従来からのベタ置き）→ 選択テーマ。
つまり GUI で明示的に選んだテーマが最優先で、画像の探索順もこれに揃えてある。

起動時に一度きりだった適用と違い、設定から何度でも切り替わるので、テーマが書いた
属性を覚えておいて次の適用の前にデフォルトへ戻す（`_applied_keys`）。
"""

import copy
import glob
import json
import os
from typing import Dict, List, Optional, Tuple

from kivy.cache import Cache
from kivy.resources import resource_add_path, resource_find, resource_paths, resource_remove_path

from katrain.core.constants import DATA_FOLDER
from katrain.core.utils import find_package_resource
from katrain.gui.theme import Theme

THEME_DEFAULT = "default"

# テーマを1つも適用していない状態の Theme。巻き戻しの基準になるので import 時に取る。
_DEFAULTS: Dict[str, object] = {k: copy.deepcopy(getattr(Theme, k)) for k in dir(Theme) if k.isupper()}

_applied_keys: List[str] = []
_applied_path: Optional[str] = None
_applied_theme: str = THEME_DEFAULT


def bundled_themes_dir() -> str:
    return find_package_resource("katrain/themes")


def user_data_dir() -> str:
    return os.path.abspath(os.path.expanduser(DATA_FOLDER))


def user_themes_dir() -> str:
    return os.path.join(user_data_dir(), "themes")


def theme_json_files(directory: Optional[str]) -> List[str]:
    """テーマディレクトリの `theme*.json`。同一ディレクトリ内は名前順で後勝ち。"""
    if not directory or not os.path.isdir(directory):
        return []
    return sorted(glob.glob(os.path.join(directory, "theme*.json")))


def theme_dir(name: str) -> Optional[str]:
    """テーマ名からディレクトリを引く。同名ならユーザー側が同梱を隠す。"""
    if not name or name == THEME_DEFAULT:
        return None
    for root in (user_themes_dir(), bundled_themes_dir()):
        candidate = os.path.join(root, name)
        if os.path.isdir(candidate):
            return candidate
    return None


def list_themes() -> List[Tuple[str, str]]:
    """`[(テーマ名, 表示ラベル)]`。default が先頭で、以降は名前順。"""
    names = []
    for root in (bundled_themes_dir(), user_themes_dir()):
        if not os.path.isdir(root):
            continue
        for entry in sorted(os.listdir(root)):
            if entry != THEME_DEFAULT and entry not in names and theme_json_files(os.path.join(root, entry)):
                names.append(entry)
    return [(THEME_DEFAULT, THEME_DEFAULT)] + [(name, name) for name in sorted(names)]


def startup_theme_name() -> str:
    """GUI が立ち上がる前に、選択中のテーマ名だけを config から読む。

    テーマは kv の評価より先に適用しないと間に合わないので、`KaTrainBase` の
    設定読み込み（マイグレーション込み）を待てない。読めなければ default。
    """
    for path in (os.path.join(user_data_dir(), "config.json"), find_package_resource("katrain/config.json")):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f).get("general", {}).get("board_theme") or THEME_DEFAULT
        except Exception:  # noqa: E722 - 設定が壊れていてもテーマで落とさない
            continue
    return THEME_DEFAULT


def current_theme() -> str:
    return _applied_theme


def _restore_defaults():
    global _applied_keys
    for key in _applied_keys:
        if key in _DEFAULTS:
            setattr(Theme, key, copy.deepcopy(_DEFAULTS[key]))
    _applied_keys = []


def _apply_json_files(paths: List[str], log) -> None:
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                overrides = json.load(f)
        except Exception as e:  # noqa: E722 - 壊れたテーマでアプリを落とさない
            log(f"テーマファイル {path} を読めませんでした: {e}")
            continue
        for key, value in overrides.items():
            setattr(Theme, key, value)
            if key not in _applied_keys:
                _applied_keys.append(key)
            log(f"[{os.path.basename(path)}] テーマ上書き {key} = {value}")


def _swap_resource_path(new_path: Optional[str]) -> None:
    global _applied_path
    if _applied_path and _applied_path in resource_paths:
        resource_remove_path(_applied_path)
    _applied_path = new_path
    if new_path:
        resource_add_path(new_path)
    # resource_find は結果を60秒キャッシュするので、探索パスを触ったら必ず捨てる
    Cache.remove("kv.resourcefind")


def _clear_texture_cache() -> None:
    try:
        from katrain.gui.kivyutils import clear_texture_cache
    except Exception:  # noqa: E722 - GUI 未初期化（テスト等）では何もしない
        return
    clear_texture_cache()


def apply_theme(name: str, log=print) -> str:
    """テーマを適用し、実際に適用した名前を返す。未知の名前は default に落とす。"""
    global _applied_theme

    name = name or THEME_DEFAULT
    directory = theme_dir(name)
    if name != THEME_DEFAULT and directory is None:
        log(f"テーマ {name!r} が見つかりません。デフォルトを使います。")
        name = THEME_DEFAULT

    _restore_defaults()
    _swap_resource_path(directory)
    _apply_json_files(theme_json_files(user_data_dir()), log)
    _apply_json_files(theme_json_files(directory), log)

    # フォントは実体パスで持つ約束（__main__ の起動時解決と同じ）。テーマがフォントを差し替えた
    # 場合も、default へ巻き戻して素のファイル名に戻った場合も、ここで解決し直す。
    # 解決済みの絶対パスに対しては no-op なので無条件でよい。
    Theme.DEFAULT_FONT = resource_find(Theme.DEFAULT_FONT) or Theme.DEFAULT_FONT

    _clear_texture_cache()
    _applied_theme = name
    return name

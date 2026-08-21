"""古い詰碁ログを月別 zip へ畳む（Kivy 非依存）。

詰碁ログは回答帳に記録した問題のぶんが `.keep` で保護されて自動削除されないので、
放っておくと単調増加する（実測 2026-08-21: 11日で 599本・130MB＝年 4GB ペース）。
どのログも詰碁モードの改善に使うため**捨てられない**ので、一定日数を過ぎたものを
`logs/archive/<prefix>_YYYYMM.zip` へ畳んで容量とファイル数だけ抑える。

`.keep` マーカー（中身は `<回答帳キー>\n<メモ>` で `tsumego_answers.json` と join する
材料）も一緒に畳む。zip に入ったことを確かめてからでないと元は消さない。

アーカイブ済みログの横断検索は `tools/grep_tsumego_logs.py`。
"""

import datetime
import glob
import os
import re
import zipfile

# アーカイブ先（logs/ の下のサブフォルダ）
ARCHIVE_DIR_NAME = "archive"
# これより古いログを畳む
ARCHIVE_AFTER_DAYS = 30
# 保護マーカーの接尾辞（`base_katrain.KaTrainBase.KEEP_MARKER_SUFFIX` と同じ）
KEEP_MARKER_SUFFIX = ".keep"
# 対象の種別。対局ログは10本で回る設計なので畳まない（消えたものを蘇らせない）
LOG_PREFIX = "tsumego"


def _timestamp_from_name(name):
    """`<prefix>_YYYYMMDD_HHMMSS[_N].log` から日時を読む。読めなければ None。"""
    parts = os.path.basename(name).split("_")
    if len(parts) >= 3:
        try:
            return datetime.datetime.strptime(f"{parts[1]}_{parts[2][:6]}", "%Y%m%d_%H%M%S")
        except ValueError:
            pass
    return None


def _log_time(path):
    """ログの日時。名前から読めない場合だけ mtime に落とす。"""
    return _timestamp_from_name(path) or datetime.datetime.fromtimestamp(os.path.getmtime(path))


def archive_zip_name(log_name, when=None):
    """そのログが入る月別 zip の名前（`tsumego_202608.zip`）。"""
    stamp = _timestamp_from_name(log_name) or when
    if stamp is None:
        raise ValueError(f"日時が決められない: {log_name}")
    prefix = os.path.basename(log_name).split("_")[0]
    return f"{prefix}_{stamp:%Y%m}.zip"


def logs_to_archive(log_dir, now=None, days=ARCHIVE_AFTER_DAYS, prefix=LOG_PREFIX):
    """畳む対象のログのパス一覧（古い順）。"""
    if not os.path.isdir(log_dir):
        return []
    cutoff = (now or datetime.datetime.now()) - datetime.timedelta(days=days)
    return [p for p in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log"))) if _log_time(p) < cutoff]


def _members(path):
    """ログ本体と、あれば保護マーカー。"""
    marker = path + KEEP_MARKER_SUFFIX
    return [path] + ([marker] if os.path.exists(marker) else [])


def _is_stored(zip_path, member):
    """`member` が zip に同じ大きさで入っているか（消してよいかの判定）。"""
    try:
        with zipfile.ZipFile(zip_path) as z:
            return z.getinfo(os.path.basename(member)).file_size == os.path.getsize(member)
    except (KeyError, OSError, zipfile.BadZipFile):
        return False


def archive_logs(log_dir, paths, logger=None):
    """指定したログを月別 zip へ移す。畳めた本数を返す。"""
    archive_dir = os.path.join(log_dir, ARCHIVE_DIR_NAME)
    archived = 0
    for path in paths:
        if not os.path.exists(path):
            continue
        members = _members(path)
        try:
            os.makedirs(archive_dir, exist_ok=True)
            zip_path = os.path.join(archive_dir, archive_zip_name(path, when=_log_time(path)))
            with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as z:
                stored = set(z.namelist())
                for member in members:
                    name = os.path.basename(member)
                    # 既に入っている＝書き込み後・削除前に落ちた回の再実行。二重化しない
                    if name not in stored:
                        z.write(member, arcname=name)
        except Exception as e:
            if logger:
                logger(f"ログのアーカイブに失敗（{e}）: {path}")
            continue
        # 例外が出なくても、実際に入ったことを確かめてからでないと消さない
        if not all(_is_stored(zip_path, member) for member in members):
            if logger:
                logger(f"ログのアーカイブを確認できないので元を残す: {path}")
            continue
        for member in members:
            try:
                os.remove(member)
            except OSError:
                pass
        archived += 1
    return archived


def archive_old_logs(log_dir, now=None, days=ARCHIVE_AFTER_DAYS, prefix=LOG_PREFIX, logger=None):
    """`days` より古いログを月別 zip へ畳む。畳めた本数を返す。"""
    return archive_logs(log_dir, logs_to_archive(log_dir, now=now, days=days, prefix=prefix), logger=logger)


def _archive_zips(log_dir, prefix=LOG_PREFIX):
    return sorted(glob.glob(os.path.join(log_dir, ARCHIVE_DIR_NAME, f"{prefix}_*.zip")))


def _iter_sources(log_dir, prefix=LOG_PREFIX):
    """`(表示名, ログ名, 本文)` を古い順に返す（アーカイブ済み → 手元の平文）。

    `.keep` マーカーは検索対象にしない（回答帳キーは本体にも入っているので重複するだけ）。
    """
    for zip_path in _archive_zips(log_dir, prefix):
        with zipfile.ZipFile(zip_path) as z:
            for name in sorted(n for n in z.namelist() if n.endswith(".log")):
                label = f"{ARCHIVE_DIR_NAME}/{os.path.basename(zip_path)}:{name}"
                yield label, name, z.read(name).decode("utf-8", "replace")
    for path in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log"))):
        name = os.path.basename(path)
        with open(path, encoding="utf-8", errors="replace") as f:
            yield name, name, f.read()


def search_logs(log_dir, pattern, prefix=LOG_PREFIX, ignore_case=False, name_filter=None):
    """平文ログとアーカイブ zip を横断して正規表現検索し `(表示名, 行番号, 行)` を返す。"""
    regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    hits = []
    for label, name, text in _iter_sources(log_dir, prefix):
        if name_filter and name_filter not in name:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                hits.append((label, lineno, line))
    return hits


def extract_logs(log_dir, name_filter, out_dir, prefix=LOG_PREFIX):
    """アーカイブ zip から名前が一致するログ（と `.keep`）を平文で取り出す。書いたパスを返す。"""
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for zip_path in _archive_zips(log_dir, prefix):
        with zipfile.ZipFile(zip_path) as z:
            for name in sorted(z.namelist()):
                if name_filter and name_filter not in name:
                    continue
                target = os.path.join(out_dir, os.path.basename(name))
                with open(target, "wb") as f:
                    f.write(z.read(name))
                written.append(target)
    return written

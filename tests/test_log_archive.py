"""古い詰碁ログの月別 zip アーカイブ（`katrain.core.log_archive`）。

詰碁ログは回答帳に記録した問題のぶんが `.keep` で保護され自動削除されないので、
放っておくと単調増加する（実測 2026-08-21: 11日で 599本・130MB）。一定日数を過ぎた
ものを `logs/archive/tsumego_YYYYMM.zip` へ畳んで容量とファイル数を抑える。

「残しておきたい」が要件なので**捨てない**こと、`.keep`（中身は回答帳キー＋メモで
`tsumego_answers.json` と join する材料）を一緒に畳むこと、zip への書き込みが
失敗したら元を消さないことが、この機構の壊れてはいけない性質。
"""

import datetime
import os
import zipfile

import pytest

from katrain.core import log_archive as la

NOW = datetime.datetime(2026, 9, 15, 12, 0, 0)


def write_log(log_dir, name, body="body", keep=False):
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    if keep:
        with open(path + la.KEEP_MARKER_SUFFIX, "w", encoding="utf-8") as f:
            f.write("deadbeef\nanswer_book 3手\n")
    return path


def zip_path(log_dir, name):
    return os.path.join(log_dir, la.ARCHIVE_DIR_NAME, name)


def entries(path):
    with zipfile.ZipFile(path) as z:
        return sorted(z.namelist())


def test_archive_zip_name_groups_by_month():
    assert la.archive_zip_name("tsumego_20260810_102038.log") == "tsumego_202608.zip"
    assert la.archive_zip_name("tsumego_20260901_000000_2.log") == "tsumego_202609.zip"


def test_only_logs_older_than_threshold_are_selected(tmp_path):
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260810_102038.log")  # 36日前
    write_log(log_dir, "tsumego_20260910_102038.log")  # 5日前
    selected = [os.path.basename(p) for p in la.logs_to_archive(log_dir, now=NOW, days=30)]
    assert selected == ["tsumego_20260810_102038.log"]


def test_game_logs_are_not_selected(tmp_path):
    """対局ログは10本で回る設計。消えたものを蘇らせない。"""
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "game_20260810_102038.log")
    assert la.logs_to_archive(log_dir, now=NOW, days=30) == []


def test_keep_marker_is_not_selected_as_a_log(tmp_path):
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260810_102038.log", keep=True)
    selected = la.logs_to_archive(log_dir, now=NOW, days=30)
    assert [os.path.basename(p) for p in selected] == ["tsumego_20260810_102038.log"]


def test_archive_moves_log_and_keep_marker_into_monthly_zip(tmp_path):
    log_dir = str(tmp_path / "logs")
    log = write_log(log_dir, "tsumego_20260810_102038.log", body="回答帳キー abc123", keep=True)
    assert la.archive_logs(log_dir, [log]) == 1
    z = zip_path(log_dir, "tsumego_202608.zip")
    assert entries(z) == ["tsumego_20260810_102038.log", "tsumego_20260810_102038.log.keep"]
    with zipfile.ZipFile(z) as zf:
        assert zf.read("tsumego_20260810_102038.log").decode("utf-8") == "回答帳キー abc123"
        assert zf.read("tsumego_20260810_102038.log.keep").decode("utf-8").startswith("deadbeef")
    assert not os.path.exists(log), "zip に入れたら元は消す"
    assert not os.path.exists(log + la.KEEP_MARKER_SUFFIX)


def test_archive_appends_to_existing_zip(tmp_path):
    log_dir = str(tmp_path / "logs")
    la.archive_logs(log_dir, [write_log(log_dir, "tsumego_20260810_102038.log")])
    la.archive_logs(log_dir, [write_log(log_dir, "tsumego_20260811_102038.log")])
    assert entries(zip_path(log_dir, "tsumego_202608.zip")) == [
        "tsumego_20260810_102038.log",
        "tsumego_20260811_102038.log",
    ]


def test_different_months_go_to_different_zips(tmp_path):
    log_dir = str(tmp_path / "logs")
    la.archive_logs(
        log_dir,
        [
            write_log(log_dir, "tsumego_20260810_102038.log"),
            write_log(log_dir, "tsumego_20260901_102038.log"),
        ],
    )
    assert os.path.exists(zip_path(log_dir, "tsumego_202608.zip"))
    assert os.path.exists(zip_path(log_dir, "tsumego_202609.zip"))


def test_already_archived_log_is_removed_without_duplicate_entry(tmp_path):
    """書き込み後・削除前に落ちた場合の再実行。zip を二重化せず元だけ片付ける。"""
    log_dir = str(tmp_path / "logs")
    la.archive_logs(log_dir, [write_log(log_dir, "tsumego_20260810_102038.log", body="same body")])
    again = write_log(log_dir, "tsumego_20260810_102038.log", body="same body")
    assert la.archive_logs(log_dir, [again]) == 1
    assert entries(zip_path(log_dir, "tsumego_202608.zip")) == ["tsumego_20260810_102038.log"]
    assert not os.path.exists(again)


def test_source_is_kept_when_zip_write_fails(tmp_path, monkeypatch):
    """1本が書けなくても、その元は消さずに残す（消えたら復元できない）。"""
    log_dir = str(tmp_path / "logs")
    ok = write_log(log_dir, "tsumego_20260810_102038.log")
    bad = write_log(log_dir, "tsumego_20260811_102038.log")

    real_write = zipfile.ZipFile.write

    def flaky_write(self, filename, arcname=None, **kwargs):
        if os.path.basename(filename).startswith("tsumego_20260811"):
            raise OSError("disk full")
        return real_write(self, filename, arcname=arcname, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "write", flaky_write)
    assert la.archive_logs(log_dir, [ok, bad]) == 1
    assert not os.path.exists(ok)
    assert os.path.exists(bad), "書けなかったログを消している"


def test_archive_old_logs_leaves_recent_ones_alone(tmp_path):
    log_dir = str(tmp_path / "logs")
    recent = write_log(log_dir, "tsumego_20260910_102038.log", keep=True)
    old = write_log(log_dir, "tsumego_20260810_102038.log", keep=True)
    assert la.archive_old_logs(log_dir, now=NOW, days=30) == 1
    assert os.path.exists(recent) and os.path.exists(recent + la.KEEP_MARKER_SUFFIX)
    assert not os.path.exists(old)
    assert entries(zip_path(log_dir, "tsumego_202608.zip")) == [
        "tsumego_20260810_102038.log",
        "tsumego_20260810_102038.log.keep",
    ]


def test_archive_old_logs_on_missing_directory(tmp_path):
    assert la.archive_old_logs(str(tmp_path / "nope"), now=NOW, days=30) == 0


def test_unparsable_name_falls_back_to_mtime(tmp_path):
    """名前から日時が読めないものは mtime で判断し、その月の zip へ入れる。"""
    log_dir = str(tmp_path / "logs")
    path = write_log(log_dir, "tsumego_broken.log")
    old = datetime.datetime(2026, 7, 4, 9, 0, 0).timestamp()
    os.utime(path, (old, old))
    assert la.archive_old_logs(log_dir, now=NOW, days=30) == 1
    assert entries(zip_path(log_dir, "tsumego_202607.zip")) == ["tsumego_broken.log"]


def test_source_is_kept_when_entry_did_not_land(tmp_path, monkeypatch):
    """例外なく書けたように見えても、zip に入っていなければ元は消さない。

    圧縮の失敗が黙って落ちた場合まで含めて「畳んだ証拠を確かめてから消す」こと。
    ログは捨てられない前提なので、消す側の条件は例外の有無ではなく実在で決める。
    """
    log_dir = str(tmp_path / "logs")
    path = write_log(log_dir, "tsumego_20260810_102038.log")
    monkeypatch.setattr(zipfile.ZipFile, "write", lambda self, filename, arcname=None, **kw: None)
    assert la.archive_logs(log_dir, [path]) == 0
    assert os.path.exists(path), "zip に入っていないログを消している"


def test_source_is_kept_when_stored_size_differs(tmp_path, monkeypatch):
    """同名で入っていても中身の大きさが違えば別物なので元を消さない。"""
    log_dir = str(tmp_path / "logs")
    la.archive_logs(log_dir, [write_log(log_dir, "tsumego_20260810_102038.log", body="short")])
    longer = write_log(log_dir, "tsumego_20260810_102038.log", body="much longer body")
    assert la.archive_logs(log_dir, [longer]) == 0
    assert os.path.exists(longer)


def test_search_finds_matches_in_plain_logs(tmp_path):
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260910_102038.log", body="line1\n回答帳キー abc123\nline3\n")
    hits = la.search_logs(log_dir, "回答帳キー")
    assert hits == [("tsumego_20260910_102038.log", 2, "回答帳キー abc123")]


def test_search_finds_matches_inside_archive_zips(tmp_path):
    """畳んだあとも同じパターンで引けること（これが無いと圧縮＝検索性の喪失になる）。"""
    log_dir = str(tmp_path / "logs")
    la.archive_logs(log_dir, [write_log(log_dir, "tsumego_20260810_102038.log", body="a\n回答帳キー zzz\n")])
    hits = la.search_logs(log_dir, "回答帳キー")
    assert hits == [("archive/tsumego_202608.zip:tsumego_20260810_102038.log", 2, "回答帳キー zzz")]


def test_search_covers_plain_and_archived_in_one_pass(tmp_path):
    log_dir = str(tmp_path / "logs")
    la.archive_logs(log_dir, [write_log(log_dir, "tsumego_20260810_102038.log", body="hit old\n")])
    write_log(log_dir, "tsumego_20260910_102038.log", body="hit new\n")
    assert [h[0] for h in la.search_logs(log_dir, "^hit")] == [
        "archive/tsumego_202608.zip:tsumego_20260810_102038.log",
        "tsumego_20260910_102038.log",
    ]


def test_search_takes_a_regular_expression(tmp_path):
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260910_102038.log", body="Selected: D4\nSelected move\n")
    assert [h[2] for h in la.search_logs(log_dir, r"Selected: [A-Z]\d")] == ["Selected: D4"]


def test_search_can_ignore_case(tmp_path):
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260910_102038.log", body="FAILED\n")
    assert la.search_logs(log_dir, "failed") == []
    assert len(la.search_logs(log_dir, "failed", ignore_case=True)) == 1


def test_search_can_filter_by_log_name(tmp_path):
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260910_102038.log", body="hit\n")
    write_log(log_dir, "tsumego_20260911_102038.log", body="hit\n")
    assert [h[0] for h in la.search_logs(log_dir, "hit", name_filter="20260911")] == ["tsumego_20260911_102038.log"]


def test_search_skips_keep_markers(tmp_path):
    """マーカーは回答帳キーの重複ヒットになるだけなので検索対象にしない（本体にも入っている）。"""
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260910_102038.log", body="deadbeef\n", keep=True)
    assert [h[0] for h in la.search_logs(log_dir, "deadbeef")] == ["tsumego_20260910_102038.log"]


def test_extract_log_restores_plain_file_from_zip(tmp_path):
    log_dir = str(tmp_path / "logs")
    la.archive_logs(log_dir, [write_log(log_dir, "tsumego_20260810_102038.log", body="本文", keep=True)])
    out = str(tmp_path / "out")
    restored = la.extract_logs(log_dir, "20260810", out_dir=out)
    assert [os.path.basename(p) for p in restored] == [
        "tsumego_20260810_102038.log",
        "tsumego_20260810_102038.log.keep",
    ]
    assert open(os.path.join(out, "tsumego_20260810_102038.log"), encoding="utf-8").read() == "本文"

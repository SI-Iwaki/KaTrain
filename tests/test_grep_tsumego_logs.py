"""アーカイブ横断検索の CLI（`tools/grep_tsumego_logs.py`）。

圧縮したログは Grep ツールで直接引けないので、この入口が検索性そのもの。
配線（引数・出力形式・文字コード）が壊れていないことを実プロセスで見る。
"""

import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "tools", "grep_tsumego_logs.py")


def run(*args):
    proc = subprocess.run([sys.executable, SCRIPT, *args], cwd=ROOT, capture_output=True, timeout=120)
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def write_log(log_dir, name, body):
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    return path


def test_cli_prints_matches_from_plain_and_archived_logs(tmp_path):
    log_dir = str(tmp_path / "logs")
    archive = os.path.join(log_dir, "archive")
    os.makedirs(archive, exist_ok=True)
    with zipfile.ZipFile(os.path.join(archive, "tsumego_202608.zip"), "w") as z:
        z.writestr("tsumego_20260810_102038.log", "x\n回答帳キー old123\n")
    write_log(log_dir, "tsumego_20260910_102038.log", "回答帳キー new456\n")

    code, out = run("--log-dir", log_dir, "回答帳キー")
    assert code == 0, out
    assert "archive/tsumego_202608.zip:tsumego_20260810_102038.log:2:回答帳キー old123" in out
    assert "tsumego_20260910_102038.log:1:回答帳キー new456" in out


def test_cli_reports_no_match_with_nonzero_status(tmp_path):
    """grep と同じで、ヒット0は終了コード1（スクリプトから使えるように）。"""
    log_dir = str(tmp_path / "logs")
    write_log(log_dir, "tsumego_20260910_102038.log", "nothing here\n")
    code, _ = run("--log-dir", log_dir, "存在しない語")
    assert code == 1


def test_cli_can_archive_now(tmp_path):
    """自動側の基準（30日）を待たずに手で畳めること。"""
    log_dir = str(tmp_path / "logs")
    old = write_log(log_dir, "tsumego_20200101_000000.log", "古い問題\n")
    code, out = run("--log-dir", log_dir, "--archive-now", "--days", "1")
    assert code == 0, out
    assert not os.path.exists(old)
    with zipfile.ZipFile(os.path.join(log_dir, "archive", "tsumego_202001.zip")) as z:
        assert z.namelist() == ["tsumego_20200101_000000.log"]


def test_cli_can_extract_an_archived_log(tmp_path):
    log_dir = str(tmp_path / "logs")
    archive = os.path.join(log_dir, "archive")
    os.makedirs(archive, exist_ok=True)
    with zipfile.ZipFile(os.path.join(archive, "tsumego_202608.zip"), "w") as z:
        z.writestr("tsumego_20260810_102038.log", "本文\n")
    out_dir = str(tmp_path / "out")
    code, out = run("--log-dir", log_dir, "--extract", "20260810", "--out-dir", out_dir)
    assert code == 0, out
    restored = os.path.join(out_dir, "tsumego_20260810_102038.log")
    assert open(restored, encoding="utf-8").read() == "本文\n"

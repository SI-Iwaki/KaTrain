"""ログファイルの種別ごとの挙動（対局ログ / 詰碁ログ）。Kivy の GUI 起動は不要。

詰碁ログは「1問1ファイル・日時入りの名前・古いものから自動削除」で、対局ログの
「MIN_MOVES 手未満は無効試合として削除」規則を**適用しない**（詰碁は数手で終わるので、
その規則のままだと次の問題をキャプチャした瞬間に直前の問題のログが消える）。
"""

import os

from katrain.core import base_katrain as bk


def make_app(tmp_path, monkeypatch, debug_level=0):
    monkeypatch.setattr(bk, "DATA_FOLDER", str(tmp_path))
    app = object.__new__(bk.KaTrainBase)  # __init__（設定読み込み）を通さない
    app._game_log_file = None
    app._game_log_path = None
    app._game_log_keep = False
    app.debug_level = debug_level
    app.game = None
    return app


def logs(tmp_path, prefix):
    folder = os.path.join(str(tmp_path), "logs")
    if not os.path.isdir(folder):
        return []
    return sorted(f for f in os.listdir(folder) if f.startswith(f"{prefix}_") and f.endswith(".log"))


def test_tsumego_log_is_created_at_any_debug_level(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, debug_level=0)
    app.start_game_log(kind="tsumego")
    assert len(logs(tmp_path, "tsumego")) == 1, "詰碁ログは debug_level 0 でも作る（報告に添付できるように）"
    assert os.path.basename(app._game_log_path).startswith("tsumego_2")  # 日付から始まる名前


def test_game_log_still_needs_debug_level(tmp_path, monkeypatch):
    app = make_app(tmp_path, monkeypatch, debug_level=0)
    app.start_game_log()
    assert logs(tmp_path, "game") == [], "対局ログの条件は従来どおり"


def test_short_tsumego_log_survives_next_capture(tmp_path, monkeypatch):
    """詰碁は数手で終わる。次の問題を開いても直前の問題のログが残ること。"""
    app = make_app(tmp_path, monkeypatch, debug_level=1)
    app.start_game_log(kind="tsumego")
    first = app._game_log_path
    app.log("problem 1")
    app.start_game_log(kind="tsumego")  # 次の問題をキャプチャ
    assert os.path.exists(first), "短いという理由で直前の詰碁ログが消えている"
    assert len(logs(tmp_path, "tsumego")) == 2
    assert app._game_log_path != first, "同じ秒でも別ファイルになること"
    assert open(first, encoding="utf-8").read().strip() == "problem 1"


def test_short_game_log_is_still_dropped(tmp_path, monkeypatch):
    """対局ログの「短い対局は無効試合」規則は変えない。

    削除された直後は同じ秒なら同名で開き直されるので、パスの有無ではなく
    「直前の対局の中身が残っていないこと」で見る。
    """
    app = make_app(tmp_path, monkeypatch, debug_level=1)
    app.start_game_log()
    app.log("game 1")
    app.start_game_log()
    remaining = logs(tmp_path, "game")
    assert len(remaining) == 1
    body = open(os.path.join(str(tmp_path), "logs", remaining[0]), encoding="utf-8").read()
    assert "game 1" not in body


def test_old_tsumego_logs_are_deleted(tmp_path, monkeypatch):
    """古いものから自動削除され、上限（LOG_KINDS）を超えて溜まらないこと。"""
    app = make_app(tmp_path, monkeypatch, debug_level=1)
    keep = bk.KaTrainBase.LOG_KINDS["tsumego"][1]
    for _ in range(keep + 5):
        app.start_game_log(kind="tsumego")
    assert len(logs(tmp_path, "tsumego")) <= keep


def test_tsumego_logs_do_not_evict_game_logs(tmp_path, monkeypatch):
    """種別ごとに独立して回すこと（詰碁ログが対局ログを押し出さない）。"""
    app = make_app(tmp_path, monkeypatch, debug_level=1)
    app.start_game_log()
    app.game = type("G", (), {"current_node": type("N", (), {"depth": 999})()})()  # 有効試合扱い
    for _ in range(bk.KaTrainBase.LOG_KINDS["tsumego"][1] + 3):
        app.start_game_log(kind="tsumego")
    assert len(logs(tmp_path, "game")) == 1


def test_kept_tsumego_log_survives_rotation(tmp_path, monkeypatch):
    """回答帳に保存した問題のログは上限を超えても消えないこと（再出題の検証コーパス）。"""
    app = make_app(tmp_path, monkeypatch, debug_level=1)
    app.start_game_log(kind="tsumego")
    app.log("回答帳に記録した問題")
    kept = app.keep_current_log(key="deadbeef", note="answer_book 3手")
    assert kept == app._game_log_path
    for _ in range(bk.KaTrainBase.LOG_KINDS["tsumego"][1] + 5):
        app.start_game_log(kind="tsumego")
    assert os.path.exists(kept), "保護したログが自動削除されている"
    assert "回答帳に記録した問題" in open(kept, encoding="utf-8").read()
    assert open(kept + bk.KaTrainBase.KEEP_MARKER_SUFFIX, encoding="utf-8").read().startswith("deadbeef")


def test_kept_logs_do_not_consume_rotation_slots(tmp_path, monkeypatch):
    """保護済みは本数に数えない＝溜めても直近の通常ログを押し出さないこと。"""
    app = make_app(tmp_path, monkeypatch, debug_level=1)
    limit = bk.KaTrainBase.LOG_KINDS["tsumego"][1]
    for _ in range(5):
        app.start_game_log(kind="tsumego")
        app.keep_current_log(key="k")
    for _ in range(limit):
        app.start_game_log(kind="tsumego")
    unprotected = [
        f
        for f in logs(tmp_path, "tsumego")
        if not os.path.exists(os.path.join(str(tmp_path), "logs", f + bk.KaTrainBase.KEEP_MARKER_SUFFIX))
    ]
    assert len(unprotected) == limit, "保護したぶんだけ通常ログの枠が削られている"
    assert len(logs(tmp_path, "tsumego")) == limit + 5


def test_keep_current_log_without_open_log(tmp_path, monkeypatch):
    """ログが開いていない（debug_level 0 の対局等）ときは何もせず None を返すこと。"""
    app = make_app(tmp_path, monkeypatch, debug_level=0)
    app.start_game_log()
    assert app.keep_current_log(key="k") is None


def test_new_game_closes_tsumego_log_even_at_debug_level_0(tmp_path, monkeypatch):
    """詰碁ログは debug_level 0 でも開くので、その後の対局開始で必ず閉じること。

    閉じ忘れると（対局ログを作らない debug_level 0 で）次の対局の行が直前の
    詰碁ログに流れ込み、1問1ファイルという前提が壊れる。
    """
    app = make_app(tmp_path, monkeypatch, debug_level=0)
    app.start_game_log(kind="tsumego")
    path = app._game_log_path
    app.log("problem 1")
    app.start_game_log()  # 通常の対局を開始（debug_level 0 なので対局ログは作らない）
    assert app._game_log_file is None
    app.log("game 1 move")
    body = open(path, encoding="utf-8").read()
    assert "problem 1" in body and "game 1 move" not in body


def old_log(tmp_path, name="tsumego_20200101_000000.log", body="古い問題", keep=True):
    """アーカイブ対象になる十分に古いログを置く。"""
    folder = os.path.join(str(tmp_path), "logs")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(body)
    if keep:
        with open(path + bk.KaTrainBase.KEEP_MARKER_SUFFIX, "w", encoding="utf-8") as f:
            f.write("deadbeef\n")
    return path


def test_start_game_log_archives_old_tsumego_logs(tmp_path, monkeypatch):
    """保護されていても十分に古い詰碁ログは月別 zip へ畳まれること（捨てはしない）。"""
    import zipfile

    old = old_log(tmp_path)
    app = make_app(tmp_path, monkeypatch, debug_level=0)
    app.start_game_log(kind="tsumego")
    current = app._game_log_path
    app._log_archive_thread.join(timeout=30)
    assert not os.path.exists(old), "古いログがアーカイブされていない"
    archive = os.path.join(str(tmp_path), "logs", "archive", "tsumego_202001.zip")
    with zipfile.ZipFile(archive) as z:
        assert sorted(z.namelist()) == ["tsumego_20200101_000000.log", "tsumego_20200101_000000.log.keep"]
        assert z.read("tsumego_20200101_000000.log").decode("utf-8") == "古い問題"
    assert os.path.exists(current), "いま開いているログを畳んでいる"


def test_archiving_runs_once_per_session(tmp_path, monkeypatch):
    """毎問スキャンし直さない（1セッション1回）。"""
    app = make_app(tmp_path, monkeypatch, debug_level=0)
    app.start_game_log(kind="tsumego")
    first = app._log_archive_thread
    assert first is not None
    first.join(timeout=30)
    app.start_game_log(kind="tsumego")
    assert app._log_archive_thread is first, "2問目でもアーカイブスレッドを起こしている"

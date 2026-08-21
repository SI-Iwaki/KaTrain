import os
import shutil
import sys
import threading

from kivy import Config
from kivy.storage.jsonstore import JsonStore

from katrain.core.ai import ai_rank_estimation
from katrain.core.constants import (
    PLAYER_HUMAN,
    PLAYER_AI,
    PLAYING_NORMAL,
    PLAYING_TEACHING,
    OUTPUT_INFO,
    OUTPUT_ERROR,
    OUTPUT_DEBUG,
    AI_DEFAULT,
    CONFIG_MIN_VERSION,
    DATA_FOLDER,
)
from katrain.core.utils import find_package_resource


class Player:
    def __init__(self, player="B", player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL, periods_used=0):
        self.player = player
        self.sgf_rank = None
        self.calculated_rank = None
        self.name = ""
        self.update(player_type, player_subtype)
        self.periods_used = periods_used

    def update(self, player_type=PLAYER_HUMAN, player_subtype=PLAYING_NORMAL):
        self.player_type = player_type
        self.player_subtype = player_subtype

    @property
    def ai(self):
        return self.player_type == PLAYER_AI

    @property
    def human(self):
        return self.player_type == PLAYER_HUMAN

    @property
    def being_taught(self):
        return self.player_type == PLAYER_HUMAN and self.player_subtype == PLAYING_TEACHING

    @property
    def strategy(self):
        return self.player_subtype if self.ai else AI_DEFAULT

    def __str__(self):
        return f"{self.player_type} ({self.player_subtype})"


def parse_version(s):
    parts = [int(p) for p in s.split(".")]
    while len(parts) < 3:
        parts.append(0)
    return parts


class KaTrainBase:
    USER_CONFIG_FILE = os.path.expanduser(os.path.join(DATA_FOLDER, "config.json"))
    PACKAGE_CONFIG_FILE = "katrain/config.json"

    """Settings, logging, and players functionality, so other classes like bots who need a katrain instance can be used without a GUI"""

    def __init__(self, force_package_config=False, debug_level=None, **kwargs):
        self.debug_level = debug_level or 0
        self.game = None
        self._game_log_file = None
        self._game_log_path = None
        self._game_log_keep = False  # True なら手数が短くても消さない（詰碁ログ）

        self.logger = lambda message, level=OUTPUT_INFO: self.log(message, level)
        self.config_file = self._load_config(force_package_config=force_package_config)
        self.debug_level = self.config("general/debug_level", OUTPUT_INFO) if debug_level is None else debug_level

        Config.set("kivy", "log_level", "warning")
        if self.debug_level >= OUTPUT_DEBUG:
            Config.set("kivy", "log_enable", 1)
            Config.set("kivy", "log_level", "debug")
        #        if self.debug_level >= OUTPUT_EXTRA_DEBUG:
        #            Config.set("kivy", "log_level", "trace")
        self.players_info = {"B": Player("B"), "W": Player("W")}
        self.reset_players()

    def log(self, message, level=OUTPUT_INFO):
        if level == OUTPUT_ERROR:
            print(f"ERROR: {message}")
        elif self.debug_level >= level:
            print(message)
        if self._game_log_file and (level == OUTPUT_ERROR or self.debug_level >= level):
            try:
                self._game_log_file.write(f"{message}\n")
                self._game_log_file.flush()
            except Exception:
                pass

    # ログの種別ごとの (ファイル名の接頭辞, 残す本数)。詰碁は1問1ファイルなので本数を多めに取る
    LOG_KINDS = {"game": ("game", 10), "tsumego": ("tsumego", 30)}
    # 保護マーカーの接尾辞（`tsumego_<日時>.log.keep`）。これが隣にあるログは本数に数えず、
    # 自動削除もしない。回答帳に保存した問題のログを恒久保存するために使う（回答帳には誤答した
    # 問題だけでなく、解析に時間がかかったので次から即答させたい問題も入る＝**正解した問題も
    # 含む**。正解／誤答の別は後から回答帳の手順と突き合わせて決めるので、ここでは区別せず
    # 全部残す。中身は `<回答帳キー>\n<メモ>` で entry と join できる）。
    # ログ本体を open したまま改名/移動すると Windows で失敗するので、別ファイルで印を付ける
    KEEP_MARKER_SUFFIX = ".keep"

    # 古い詰碁ログの月別 zip 化は1セッション1回・別スレッド（初回は数百MBを畳むので、
    # 同期で走らせると次の問題のキャプチャを待たせる）
    _log_archive_thread = None

    def _maybe_archive_logs(self, log_dir):
        """`ARCHIVE_AFTER_DAYS` より古い詰碁ログを `logs/archive/` の月別 zip へ畳む。

        回答帳に記録した問題のログは `.keep` で保護されて自動削除の対象外なので、
        そのままだと単調増加する（実測 2026-08-21: 11日で 599本・130MB）。どのログも
        詰碁モードの改善に使うため捨てず、容量とファイル数だけ抑える。
        """
        if self._log_archive_thread is not None:
            return self._log_archive_thread
        from katrain.core.log_archive import archive_old_logs

        def worker():
            try:
                count = archive_old_logs(log_dir, logger=lambda m: self.log(m, OUTPUT_INFO))
                if count:
                    self.log(f"古い詰碁ログ {count} 本を logs/archive へ畳みました", OUTPUT_INFO)
            except Exception as e:
                self.log(f"ログのアーカイブに失敗（{e}）", OUTPUT_INFO)

        self._log_archive_thread = threading.Thread(target=worker, daemon=True)
        self._log_archive_thread.start()
        return self._log_archive_thread

    def keep_current_log(self, key="", note=""):
        """いま開いているログを自動削除の対象から外す。保護したパスを返す（できなければ None）。

        ログが開いている間しか呼べない（`start_game_log` が次を開くとパスは失われる）。
        """
        path = self._game_log_path
        if not path:
            return None
        try:
            with open(path + self.KEEP_MARKER_SUFFIX, "w", encoding="utf-8") as f:
                f.write(f"{key}\n{note}\n")
        except Exception as e:
            self.log(f"ログの保護に失敗（{e}）: {path}", OUTPUT_INFO)
            return None
        return path

    def start_game_log(self, kind="game"):
        """新しいログファイルを開く。kind="tsumego" は詰碁1問ぶんのログ。

        詰碁ログが対局ログと別種なのは2点の違いがあるため:
        - **短さで削除しない**: 詰碁は数手で終わるので、対局用の「MIN_MOVES 手未満は無効試合」
          規則をそのまま適用すると、次の問題をキャプチャした瞬間に直前の問題のログが消える
        - **debug_level に関係なく残す**: 不具合報告にそのまま添付できるように（内容の詳しさは
          従来どおり debug_level に従う＝0 なら INFO 行のみ、1 ならエンジンのクエリまで入る）
        """
        MIN_MOVES = 20
        prefix, max_logs = self.LOG_KINDS.get(kind, self.LOG_KINDS["game"])
        is_tsumego = kind == "tsumego"
        # 直前のファイルは debug_level に関係なく必ず閉じる（詰碁ログは debug_level 0 でも
        # 開くので、閉じる処理を下の早期 return より後ろに置くと、次の対局のログが
        # 直前の詰碁ログに流れ込む）
        if self._game_log_file:
            try:
                self._game_log_file.close()
            except Exception:
                pass
            self._game_log_file = None
            # 直前の対局が MIN_MOVES 手未満なら無効試合として削除（詰碁ログは対象外）
            if self._game_log_path and not self._game_log_keep:
                try:
                    moves = self.game.current_node.depth if self.game else 0
                except Exception:
                    moves = 0
                if moves < MIN_MOVES:
                    try:
                        os.remove(self._game_log_path)
                    except Exception:
                        pass
            self._game_log_path = None
            self._game_log_keep = False
        if not is_tsumego and self.debug_level < 1:
            return

        from datetime import datetime
        import glob

        log_dir = os.path.join(os.path.expanduser(DATA_FOLDER), "logs")
        os.makedirs(log_dir, exist_ok=True)
        self._maybe_archive_logs(log_dir)

        # 種別ごとに独立して古い順に消す（詰碁ログが対局ログを押し出さない）。
        # 保護済み（.keep が隣にある）は本数からも外す＝保護したぶんだけ通常ログの枠が
        # 減るのを避ける（回答帳に溜めた誤答コーパスが最近のログを押し出さない）
        existing = [
            p
            for p in sorted(glob.glob(os.path.join(log_dir, f"{prefix}_*.log")))
            if not os.path.exists(p + self.KEEP_MARKER_SUFFIX)
        ]
        for old_file in existing[: max(0, len(existing) - max_logs + 1)]:
            try:
                os.remove(old_file)
            except Exception:
                pass

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = os.path.join(log_dir, f"{prefix}_{timestamp}.log")
        seq = 2  # 同じ秒に2回開いても直前のファイルを潰さない（連続キャプチャ）
        while os.path.exists(log_path):
            log_path = os.path.join(log_dir, f"{prefix}_{timestamp}_{seq}.log")
            seq += 1
        try:
            self._game_log_file = open(log_path, "w", encoding="utf-8")
            self._game_log_path = log_path
            self._game_log_keep = is_tsumego
            print(f"{'詰碁ログ' if is_tsumego else 'Game log'}: {log_path}")
        except Exception as e:
            print(f"Failed to open {kind} log: {e}")

    def _load_config(self, force_package_config):
        if len(sys.argv) > 1 and sys.argv[1].endswith("config.json"):
            config_file = os.path.abspath(sys.argv[1])
            self.log(f"Using command line config file {config_file}", OUTPUT_INFO)
        else:
            user_config_file = find_package_resource(self.USER_CONFIG_FILE)
            package_config_file = find_package_resource(self.PACKAGE_CONFIG_FILE)
            if force_package_config:
                config_file = package_config_file
            else:
                try:
                    if not os.path.exists(user_config_file):
                        self.log("User config does not exist, creating it", OUTPUT_DEBUG)
                        parent_dir = os.path.split(user_config_file)[0]
                        self.log(f"Creating parent directory if needed: {parent_dir}", OUTPUT_DEBUG)
                        os.makedirs(parent_dir, exist_ok=True)
                        
                        self.log(f"Copying package config {package_config_file} to user config {user_config_file}", OUTPUT_DEBUG)
                        shutil.copyfile(package_config_file, user_config_file)
                        config_file = user_config_file
                        self.log(f"Copied package config to local file {config_file}", OUTPUT_INFO)
                    else:  # user file exists
                        try:
                            version_str = JsonStore(user_config_file).get("general")["version"]
                            version = parse_version(version_str)
                            self.log(f"Parsed version: {version}", OUTPUT_DEBUG)
                        except Exception as e:  # noqa E722 broken file etc
                            self.log(f"Failed to read version from user config: {e}", OUTPUT_DEBUG)
                            version_str = "0.0.0"
                            version = [0, 0, 0]
                        min_version = parse_version(CONFIG_MIN_VERSION)
                        if version < min_version:
                            backup = f"{user_config_file}.{version_str}.backup"
                            shutil.copyfile(user_config_file, backup)
                            shutil.copyfile(package_config_file, user_config_file)
                            self.log(
                                f"Copied package config file to {user_config_file} as user file is outdated or broken ({version}<{min_version}). Old version stored as {backup}",
                                OUTPUT_INFO,
                            )
                        config_file = user_config_file
                        self.log(f"Using user config file {config_file}", OUTPUT_INFO)
                except Exception as e:
                    config_file = package_config_file
                    self.log(
                        f"Using package config file {config_file} (exception {e} occurred when finding or creating user config)",
                        OUTPUT_INFO,
                    )
        try:
            self._config_store = JsonStore(config_file, indent=4)
        except Exception as e:
            self.log(f"Failed to load config {config_file}: {e}", OUTPUT_ERROR)
            sys.exit(1)
        self._config = dict(self._config_store)
        return config_file

    def save_config(self, key=None):
        if key is None:
            for k, v in self._config.items():
                self._config_store.put(k, **v)
        else:
            self._config_store.put(key, **self._config[key])

    def config(self, setting, default=None):
        try:
            if "/" in setting:
                cat, key = setting.split("/")
                return self._config.get(cat, {}).get(key, default)
            else:
                return self._config.get(setting, default)
        except KeyError:
            self.log(f"Missing configuration option {setting}", OUTPUT_ERROR)

    def update_player(self, bw, **kwargs):
        self.players_info[bw].update(**kwargs)
        self.update_calculated_ranks()

    def update_calculated_ranks(self):
        for bw, player_info in self.players_info.items():
            if player_info.player_type == PLAYER_AI:
                settings = self.config(f"ai/{player_info.strategy}")
                player_info.calculated_rank = ai_rank_estimation(player_info.player_subtype, settings)
            else:
                player_info.calculated_rank = None

    def reset_players(self):
        self.update_player("B")
        self.update_player("W")
        for v in self.players_info.values():
            v.periods_used = 0

    @property
    def last_player_info(self) -> Player:
        return self.players_info[self.game.current_node.player]

    @property
    def next_player_info(self) -> Player:
        return self.players_info[self.game.current_node.next_player]

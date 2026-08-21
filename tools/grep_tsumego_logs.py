"""詰碁ログの横断検索（平文 + `logs/archive/` の月別 zip）。

古い詰碁ログは `katrain.core.log_archive` が月別 zip へ畳むので、Grep ツールや
`grep` では直接引けなくなる。その代わりがこのスクリプト。`.claude/rules/log-analysis.md`
の Grep パターンをそのまま渡せる。

    python tools/grep_tsumego_logs.py "回答帳キー"
    python tools/grep_tsumego_logs.py -i "failed|error"
    python tools/grep_tsumego_logs.py --name 20260810 "Selected:"
    python tools/grep_tsumego_logs.py --extract 20260810_102038   # 平文に取り出す
    python tools/grep_tsumego_logs.py --archive-now --days 7      # 手で畳む

出力は `<場所>:<行番号>:<行>`。ヒット0なら grep と同じく終了コード 1。
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from katrain.core.log_archive import ARCHIVE_AFTER_DAYS, LOG_PREFIX, archive_old_logs, extract_logs, search_logs

DEFAULT_LOG_DIR = os.path.join(os.path.expanduser("~"), ".katrain", "logs")


def main(argv=None):
    parser = argparse.ArgumentParser(description="詰碁ログを平文・アーカイブ横断で検索する")
    parser.add_argument("pattern", nargs="?", help="正規表現")
    parser.add_argument("--log-dir", default=DEFAULT_LOG_DIR, help=f"ログの場所（既定: {DEFAULT_LOG_DIR}）")
    parser.add_argument("--prefix", default=LOG_PREFIX, help="ログの種別（既定: tsumego）")
    parser.add_argument("-i", "--ignore-case", action="store_true", help="大文字小文字を区別しない")
    parser.add_argument("--name", help="ログ名にこの文字列を含むものだけ")
    parser.add_argument("--extract", metavar="NAME", help="名前が一致するログを zip から平文で取り出す")
    parser.add_argument("--out-dir", default=".", help="--extract の出力先（既定: カレント）")
    parser.add_argument("--archive-now", action="store_true", help="いま畳む（自動側の基準を待たない）")
    parser.add_argument("--days", type=int, default=ARCHIVE_AFTER_DAYS, help="--archive-now の対象日数")
    args = parser.parse_args(argv)

    # ログ本文には日本語が入るので、cp932 端末でも落とさない
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if args.archive_now:
        count = archive_old_logs(args.log_dir, days=args.days, prefix=args.prefix, logger=print)
        print(f"{count} 本を {os.path.join(args.log_dir, 'archive')} へ畳みました")
        return 0

    if args.extract:
        written = extract_logs(args.log_dir, args.extract, args.out_dir, prefix=args.prefix)
        for path in written:
            print(path)
        return 0 if written else 1

    if not args.pattern:
        parser.error("検索する正規表現を指定してください（または --extract / --archive-now）")

    hits = search_logs(
        args.log_dir,
        args.pattern,
        prefix=args.prefix,
        ignore_case=args.ignore_case,
        name_filter=args.name,
    )
    for source, lineno, line in hits:
        print(f"{source}:{lineno}:{line}")
    return 0 if hits else 1


if __name__ == "__main__":
    sys.exit(main())

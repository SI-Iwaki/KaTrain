"""AI設定画面の説明欄: 戦略の概要と「各項目」の一覧を組み立てる（Kivy のウィジェットには依存しない）。

画面の項目名は英語の設定キーのまま表示されるので、説明欄の各項目は
「■ 英語キー（日本語名）［既定 X］: 解説」と英語キーを先頭に出し、どのスライダーの解説か分かるようにする。
並びは設定画面と同じ `ai_option_display_order`＝順番のずれと書き漏れが構造的に起きない。

項目の訳文は `aiopt:` 名前空間に置き、1 行目を日本語名・2 行目以降を解説とする。引く順は
戦略別 `aiopt:<strategy>/<key>`（同じキーでも戦略で意味が違う場合）→ キー共通 `aiopt:<key>` →
難解系・韜晦系の共通文面 `aiopt:enigma*_<suffix>` / `aiopt:veil*_<suffix>`。難解系（enigma9/13/19 と＋版）は
同じ項目がキー接頭辞違いで 6 つずつ、韜晦系（veil9/13/19）は 3 つずつ並ぶので、共通文面の `{p}` を実際の
接頭辞（例 enigma13plus / veil13）へ置き換えて 1 本で書く。
一覧のあとに `aihelptips:<strategy>`（「こんなときは」等の調整の目安）があれば続ける。
項目の訳文が 1 つも無い言語（現状は日本語以外）では概要だけを返す＝従来どおりの表示。
"""

import re
from typing import Callable, Dict, List, Optional, Tuple

from kivy.utils import escape_markup

from katrain.core.constants import AI_KEY_PROPERTIES, AI_OPTION_ORDER, AI_OPTION_VALUES

Translate = Callable[[str], str]

# 項目名（英語キー）の強調色。暗い背景の説明欄で本文と見分けられる淡い黄
KEY_COLOR = "ffd27a"

_ENIGMA_FAMILY = re.compile(r"^(enigma(?:9|13|19)(?:plus)?)_(.+)$")
_VEIL_FAMILY = re.compile(r"^(veil(?:9|13|19))_(.+)$")
# （キーの正規表現, 共通文面の msgid 接頭辞）。共通文面の {p} は一致したキー接頭辞（例 enigma13plus / veil13）になる
_FAMILIES = ((_ENIGMA_FAMILY, "enigma*"), (_VEIL_FAMILY, "veil*"))
# 日本語の文字（全角記号・かな / CJK 統合漢字拡張A / CJK 統合漢字 / 全角英数・半角カナ）
_CJK_RANGES = ((0x3000, 0x30FF), (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xFF00, 0xFFEF))
_CJK = re.compile("[" + "".join(chr(lo) + "-" + chr(hi) for lo, hi in _CJK_RANGES) + "]")
_NBSP = chr(0xA0)

_FALLBACK_ITEM = "■ {key}（{name}）: {body}"


def _has_cjk(text: str) -> bool:
    return bool(_CJK.search(text))


def cjk_wrap_friendly(text: str) -> str:
    """日本語を含む文章を Kivy の Label で自然に折り返せるようにする。

    Kivy は半角スペースでしか改行できず、スペースの後ろの「語」が行に収まらないと語ごと次の行へ送る。
    日本語は長い 1 語に見えるので、スペースの位置で行が幅の途中で切れて不揃いになる（実測: 500px 幅で
    125px・96px の短い行ができた）。そこで、改行できる空白として残すのは「その前後が英語だけの語」の間
    （英文の単語区切り）に限り、ほかは改行しない空白（NBSP）にして、行末で文字単位に折り返させる。
    右隣の語は NBSP でつながった先まで含めて判定する（`net = E（9段…` の `=` の前で切ると、日本語の長い
    塊が次の行へ送られて同じことが起きる）。日本語を含まない文章（英語 UI）は変えない。
    """
    if not _has_cjk(text):
        return text
    tokens = text.split(" ")
    keep = [False] * (len(tokens) - 1)
    # word_cjk: 「tokens[j] から始まる語（次の改行できる空白・改行まで）」に日本語が入っているか。右から求める
    word_cjk = _has_cjk(tokens[-1].split("\n", 1)[0])
    for i in range(len(tokens) - 2, -1, -1):
        keep[i] = not _has_cjk(tokens[i].rsplit("\n", 1)[-1]) and not word_cjk
        first = tokens[i].split("\n", 1)[0]
        if "\n" in tokens[i] or keep[i]:
            word_cjk = _has_cjk(first)
        else:
            word_cjk = _has_cjk(first) or word_cjk
    out = [tokens[0]]
    for i, token in enumerate(tokens[1:]):
        out.append(" " if keep[i] else _NBSP)
        out.append(token)
    return "".join(out)


def ai_option_display_order(settings) -> List[str]:
    """設定画面の表示順（上から）。強さに直結する項目（AI_KEY_PROPERTIES）→ AI_OPTION_ORDER → キー名"""
    return sorted(settings, key=lambda k: (k not in AI_KEY_PROPERTIES, AI_OPTION_ORDER.get(k, 99), k))


def _translated(translate: Translate, msgid: str) -> Optional[str]:
    text = translate(msgid)
    return text if text and text != msgid else None


def ai_option_help_entry(strategy: str, key: str, translate: Translate) -> Optional[Tuple[str, str]]:
    """設定項目の（日本語名, 解説）。この言語に訳文が無ければ None"""
    candidates = [f"aiopt:{strategy}/{key}", f"aiopt:{key}"]
    family = None
    for pattern, wildcard in _FAMILIES:
        family = pattern.match(key)
        if family:
            candidates.append(f"aiopt:{wildcard}_{family.group(2)}")
            break
    for msgid in candidates:
        text = _translated(translate, msgid)
        if text is None:
            continue
        if family:
            text = text.replace("{p}", family.group(1))
        name, _, body = text.partition("\n")
        return name.strip(), body.strip()
    return None


def _same_value(a, b) -> bool:
    numbers = (int, float)
    if isinstance(a, numbers) and isinstance(b, numbers) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-9
    return a == b


def format_ai_option_value(key: str, value, translate: Translate) -> str:
    """設定値の表示（既定値の欄に使う）。スライダーにラベルがあればそのラベル（例 30%・OFF・9段）"""
    candidates = AI_OPTION_VALUES.get(key)
    if isinstance(value, bool) or candidates == "bool":
        return "ON" if value else "OFF"
    if isinstance(candidates, (list, tuple)) and candidates and isinstance(candidates[0], tuple):
        for candidate, label in candidates:
            if _same_value(candidate, value):
                return re.sub(r"\[(.*?)]", lambda m: translate(m[1]), label)
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def compose_ai_help(strategy: str, settings, translate: Translate, defaults: Optional[Dict] = None) -> str:
    """説明欄のテキスト（Kivy markup・折り返し調整済み）。概要のあとに、設定画面の表示順で各項目の解説を並べる。

    各項目は「見出し（英語キー・日本語名・既定値）」と「解説」の間の空白だけを改行できる空白として残す＝
    見出しは途中で切れず、長い解説は次の行から始まる（英語キーの直後で行が切れると、日本語名がどの
    スライダーのものか読み取りにくい）。訳文の書式 `ai option item` は `{body}` を最後に置くこと。
    """
    defaults = defaults or {}
    lines = []
    for key in ai_option_display_order(settings):
        entry = ai_option_help_entry(strategy, key, translate)
        if entry is None:
            continue
        name, body = entry
        fields = {"key": f"[b][color={KEY_COLOR}]{escape_markup(key)}[/color][/b]", "name": escape_markup(name)}
        if key in defaults:
            fields["default"] = escape_markup(format_ai_option_value(key, defaults[key], translate))
            template = _translated(translate, "ai option item")
        else:
            template = _translated(translate, "ai option item nodefault")
        head_template = (template or _FALLBACK_ITEM).partition("{body}")[0].rstrip()
        head = cjk_wrap_friendly(escape_markup(head_template).format(**fields))
        lines.append(head + " " + cjk_wrap_friendly(escape_markup(body)))
    text = cjk_wrap_friendly(escape_markup(translate(strategy.replace("ai:", "aihelp:"))))
    if lines:
        header = _translated(translate, "ai option help header") or ""
        text += "\n\n" + cjk_wrap_friendly(escape_markup(header)) + "\n" + "\n".join(lines)
    tips = _translated(translate, strategy.replace("ai:", "aihelptips:"))
    if tips:
        text += "\n\n" + cjk_wrap_friendly(escape_markup(tips))
    return text

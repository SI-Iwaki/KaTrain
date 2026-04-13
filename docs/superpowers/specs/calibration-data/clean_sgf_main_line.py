"""SGF の variation を全て落として、最長パス（actually-played main line）のみを残す前処理ツール。

KaTrain で保存された SGF は AI の代替手や user の探索が variation として保存されるため、
batch_eval の `node.children[0]` traversal が短い分岐に陥る。本ツールは最長パスを
辿ってその path 上の手だけを含む新 SGF を出力する。

使用:
    python clean_sgf_main_line.py <input.sgf> <output.sgf>
"""
import sys
from pathlib import Path

from katrain.core.game import KaTrainSGF
from katrain.core.sgf_parser import SGFNode


def longest_depth(node):
    """Return the depth of the longest path from this node to any leaf."""
    if not node.children:
        return 0
    return 1 + max(longest_depth(c) for c in node.children)


def collect_main_line_nodes(root):
    """Walk root -> leaf following the longest child at each branch.

    Returns a list of nodes (excluding root) representing the main line.
    """
    nodes = []
    node = root
    while node.children:
        node = max(node.children, key=longest_depth)
        nodes.append(node)
    return nodes


def serialize_node_props(node):
    """Serialize a single node's properties as SGF string (excluding semicolon)."""
    parts = []
    for key, values in node.properties.items():
        joined = "".join(f"[{SGFNode._escape_value(v)}]" for v in values)
        parts.append(f"{key}{joined}")
    return "".join(parts)


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.sgf> <output.sgf>", file=sys.stderr)
        sys.exit(1)
    input_path, output_path = Path(sys.argv[1]), Path(sys.argv[2])

    root = KaTrainSGF.parse_file(str(input_path))
    main_nodes = collect_main_line_nodes(root)

    parts = ["(;"]
    parts.append(serialize_node_props(root))
    for n in main_nodes:
        parts.append(";")
        parts.append(serialize_node_props(n))
    parts.append(")")

    output_path.write_text("".join(parts), encoding="utf-8")
    print(f"Wrote {len(main_nodes)} main-line moves to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()

"""Compile .po files to .mo files for KaTrain i18n."""
import struct
import sys
import os


def parse_string(line):
    """Extract content between quotes and unescape."""
    line = line.strip()
    if line.startswith('"') and line.endswith('"'):
        s = line[1:-1]
        # Order matters: \\\\ first, then other escapes
        s = s.replace("\\\\", "\x00BACKSLASH\x00")
        s = s.replace("\\n", "\n")
        s = s.replace("\\t", "\t")
        s = s.replace('\\"', '"')
        s = s.replace("\x00BACKSLASH\x00", "\\")
        return s
    return ""


def compile_po_to_mo(po_path, mo_path):
    with open(po_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    entries = []
    msgid_lines = []
    msgstr_lines = []
    state = None

    def flush():
        if msgid_lines is not None:
            mid = "".join(msgid_lines)
            mstr = "".join(msgstr_lines)
            entries.append((mid, mstr))

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped == "":
            continue

        if stripped.startswith("msgid "):
            if state is not None:
                flush()
            msgid_lines = []
            msgstr_lines = []
            state = "id"
            rest = stripped[6:].strip()
            msgid_lines.append(parse_string(rest))
        elif stripped.startswith("msgstr "):
            state = "str"
            rest = stripped[7:].strip()
            msgstr_lines.append(parse_string(rest))
        elif stripped.startswith('"'):
            if state == "id":
                msgid_lines.append(parse_string(stripped))
            elif state == "str":
                msgstr_lines.append(parse_string(stripped))

    flush()

    # Include metadata (empty msgid) and translated entries
    entries = [(k, v) for k, v in entries if v]
    entries.sort(key=lambda x: x[0].encode("utf-8"))

    n = len(entries)
    ids_data = [e[0].encode("utf-8") for e in entries]
    strs_data = [e[1].encode("utf-8") for e in entries]

    header_size = 28
    table_size = n * 8
    keystart = header_size + table_size * 2

    ids_offsets = []
    offset = 0
    for d in ids_data:
        ids_offsets.append((len(d), keystart + offset))
        offset += len(d) + 1

    valuestart = keystart + offset
    strs_offsets = []
    offset = 0
    for d in strs_data:
        strs_offsets.append((len(d), valuestart + offset))
        offset += len(d) + 1

    output = struct.pack(
        "Iiiiiii", 0x950412DE, 0, n, header_size, header_size + table_size, 0, 0
    )
    for length, off in ids_offsets:
        output += struct.pack("ii", length, off)
    for length, off in strs_offsets:
        output += struct.pack("ii", length, off)
    for d in ids_data:
        output += d + b"\x00"
    for d in strs_data:
        output += d + b"\x00"

    with open(mo_path, "wb") as f:
        f.write(output)
    print(f"OK: {mo_path} ({n} entries)")


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(__file__), "..", "katrain", "i18n", "locales")
    for lang in ["en", "jp"]:
        po = os.path.join(base, lang, "LC_MESSAGES", "katrain.po")
        mo = os.path.join(base, lang, "LC_MESSAGES", "katrain.mo")
        compile_po_to_mo(po, mo)

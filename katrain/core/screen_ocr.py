"""Windows 標準の文字認識（Windows.Media.Ocr・日本語）で画像の文字行を読む（Kivy 非依存・追加依存なし）。

PowerShell 5.1 の別プロセス（screen_ocr.ps1）に PNG を渡して行ごとの文字列を受け取る。
1 回 1〜2 秒かかるので GUI スレッドでは呼ばないこと。失敗はすべて None（例外は出さない）。
"""

import os
import subprocess
import sys
import tempfile
from typing import List, Optional

_SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_ocr.ps1")
_CREATE_NO_WINDOW = 0x08000000


def ocr_lines(img, scale: int = 3, timeout_sec: float = 8.0) -> Optional[List[str]]:
    """PIL 画像を scale 倍に拡大して読み、空行を除いた行のリストを返す。読めない環境・失敗は None"""
    if sys.platform != "win32":
        return None
    path = None
    try:
        from PIL import Image

        big = img.convert("RGB").resize((img.size[0] * scale, img.size[1] * scale), Image.LANCZOS)
        fd, path = tempfile.mkstemp(suffix=".png", prefix="katrain_ocr_")
        os.close(fd)
        big.save(path)
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", _SCRIPT, "-Path", path],
            capture_output=True,
            timeout=timeout_sec,
            creationflags=_CREATE_NO_WINDOW,
        )
        if proc.returncode != 0:
            return None
        text = proc.stdout.decode("utf-8", errors="replace")
        return [line.strip() for line in text.splitlines() if line.strip()]
    except Exception:
        return None
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

"""Khởi động VSub Studio.

    uv run python run.py                # mở http://127.0.0.1:8000
    uv run python run.py --port 8080    # đổi cổng
    uv run python run.py --no-browser   # không tự mở trình duyệt
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

# Console Windows mặc định là cp1252 -> chuyển sang UTF-8 để in được tiếng Việt
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description="VSub Studio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--reload", action="store_true", help="tự nạp lại khi sửa code")
    args = ap.parse_args()

    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"

    if not args.no_browser and not args.reload:
        def open_later() -> None:
            time.sleep(1.4)
            webbrowser.open(url)

        threading.Thread(target=open_later, daemon=True).start()

    print("\n" + "─" * 54)
    print("  🎬  VSub Studio")
    print(f"  →  {url}")
    print("  Nhấn Ctrl+C để dừng")
    print("─" * 54 + "\n")

    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="warning",
    )


if __name__ == "__main__":
    main()

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
    ap.add_argument("--invite", action="store_true", help="tạo mã mời đăng ký studio, dùng một lần trong 24 giờ")
    ap.add_argument("--make-admin", metavar="USERNAME", help="cấp quyền quản trị cho một tài khoản đã đăng ký")
    ap.add_argument("--ssl-certfile", help="chứng thư HTTPS cho điện thoại qua Wi-Fi")
    ap.add_argument("--ssl-keyfile", help="khóa riêng HTTPS")
    ap.add_argument("--reload", action="store_true", help="tự nạp lại khi sửa code")
    args = ap.parse_args()

    if args.make_admin:
        from backend.db import Member, get_db, init_db
        init_db()
        with get_db() as db:
            user = db.query(Member).filter_by(username=args.make_admin.strip().lower(), active=True).first()
            if not user:
                ap.error("Không tìm thấy tài khoản đang hoạt động. Hãy đăng ký trước.")
            user.role = "admin"
        print("Đã cấp quyền quản trị. Tải lại trang để mở Quản trị.")
        return
    if args.invite:
        from backend.api.auth import issue_invite
        from backend.db import init_db
        init_db()
        print("Mã mời (chỉ đưa cho thành viên được quyền vào studio):", issue_invite())
        return
    if bool(args.ssl_certfile) != bool(args.ssl_keyfile):
        ap.error("HTTPS cần cả --ssl-certfile và --ssl-keyfile")
    scheme = "https" if args.ssl_certfile else "http"
    url = f"{scheme}://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"

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
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
        log_level="warning",
    )


if __name__ == "__main__":
    main()

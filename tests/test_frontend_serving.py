"""Backend phục vụ giao diện tĩnh đúng cách, và ranh giới frontend/backend giữ được."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend.config import FRONTEND_DIR
from backend.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


# ------------------------------------------------------------- trang chủ


def test_trang_chu_nap_dung_thu_tu_js(client):
    html = client.get("/").text
    order = ["core", "boot", "films", "source", "setup", "ai", "progress", "editor", "dubbing", "export", "prefs", "main"]
    positions = [html.index(f"/js/{n}.js?v=") for n in order]
    assert positions == sorted(positions), "core phải nạp trước, main (boot()) phải nạp sau cùng"
    assert html.index("/config.js?v=") < positions[0], "config.js phải nạp trước core.js"
    assert "/css/style.css?v=" in html


def test_moi_file_js_tren_dia_deu_duoc_nap(client):
    """Tách file mà quên thêm thẻ script là mất chức năng im lặng."""
    html = client.get("/").text
    for p in (FRONTEND_DIR / "js").glob("*.js"):
        assert f"/js/{p.name}?v=" in html, f"{p.name} không được nạp trong index.html"


# ------------------------------------------------------- file tĩnh


@pytest.mark.parametrize("path,mime", [
    ("/js/core.js", "javascript"), ("/css/style.css", "css"), ("/config.js", "javascript"),
])
def test_phuc_vu_file_giao_dien(client, path, mime):
    r = client.get(path)
    assert r.status_code == 200 and mime in r.headers["content-type"]
    assert r.headers.get("cache-control") == "no-cache"


@pytest.mark.parametrize("path", ["/js/khong-co.js", "/css/khong-co.css", "/js/..%2Fconfig.py", "/js/."])
def test_khong_phuc_vu_file_la_hay_ngoai_thu_muc(client, path):
    assert client.get(path).status_code in (307, 404)


def test_js_khong_ghep_cung_dia_chi_backend():
    """Mọi đường dẫn /api/ phải đi qua api()/apiUrl()/API_BASE để giao diện chạy tách server được."""
    bad = []
    for p in sorted((FRONTEND_DIR / "js").glob("*.js")):
        for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            s = ln.strip()
            code = re.sub(r"(?<!:)//.*$", "", ln)  # bỏ chú thích cuối dòng, giữ https://
            if "/api/" in code and not any(k in code for k in ("api(", "apiUrl(", "API_BASE")) \
                    and not s.startswith(("/*", "*")):
                bad.append(f"{p.name}:{n}")
    assert not bad, bad


def test_o_model_ai_go_tu_do_duoc():
    """Endpoint OpenAI-compatible có model riêng (qwen3.8-flash...), danh sách cố định không đủ."""
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    line = next(ln for ln in html.splitlines() if 'id="aiModel"' in ln)
    assert "<input" in line and 'list="aiModelList"' in line, line
    assert 'id="aiModelList"' in html


def test_logic_ai_nam_rieng_trong_ai_js():
    """Mọi thứ về engine AI (key, model, endpoint, cache) gom một chỗ, không rải khắp nơi."""
    own = ("function fillEngines", "function syncAiBox", "function aiPayload",
           "function aiReady", "async function refreshCacheInfo")
    ai = (FRONTEND_DIR / "js" / "ai.js").read_text(encoding="utf-8")
    assert all(d in ai for d in own)
    for p in (FRONTEND_DIR / "js").glob("*.js"):
        if p.name == "ai.js":
            continue
        src = p.read_text(encoding="utf-8")
        assert not any(d in src for d in own), f"{p.name} còn định nghĩa hàm AI"
        assert "#apiKey" not in src, f"{p.name} đọc API key trực tiếp — phải qua aiPayload()"


def test_khong_dung_hop_thoai_goc_cua_trinh_duyet():
    """confirm()/alert()/prompt() bị trình duyệt nhúng nuốt: trả về false ngay, không hỏi.

    Từng gây lỗi "bấm xoá nhưng không xoá". Phải dùng askConfirm() trong core.js.
    """
    native = re.compile(r"(?<![\w.])(confirm|alert|prompt)\(")
    bad = [f"{p.name}:{n}" for p in (FRONTEND_DIR / "js").glob("*.js")
           for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
           if native.search(ln) and not ln.strip().startswith(("//", "*", "/*"))]
    assert not bad, bad
    assert "function askConfirm" in (FRONTEND_DIR / "js" / "core.js").read_text(encoding="utf-8")


# ------------------------------------------------------------- API


def test_tai_lieu_api_tu_sinh(client):
    assert client.get("/api/docs").status_code == 200
    spec = client.get("/api/openapi.json").json()
    tags = {t for path in spec["paths"].values() for op in path.values() for t in op.get("tags", [])}
    assert {"system", "tts", "media", "jobs", "films", "projects"} <= tags


def test_moi_endpoint_deu_duoi_api(client):
    spec = client.get("/api/openapi.json").json()
    assert all(p.startswith("/api/") for p in spec["paths"]), "backend chỉ nói chuyện qua /api/"


def test_cors_tat_mac_dinh():
    assert not any("CORS" in m.cls.__name__ for m in app.user_middleware)


def test_cors_bat_khi_dat_bien_moi_truong():
    code = (
        "import os; os.environ['VSUB_CORS_ORIGINS']='http://127.0.0.1:5500';"
        "from backend.main import app;"
        "print(any('CORS' in m.cls.__name__ for m in app.user_middleware))"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip() == "True"

"""Đường gọi OpenAI-compatible chạy thật, trên một máy chủ giả lập ở localhost.

Không cần key, không ra mạng. Kiểm: dịch theo lô, rút gọn câu (HP-5), kiểm tra
kết nối, model sai / key sai báo đúng lỗi, endpoint chậm bị cắt sau
VSUB_AI_TIMEOUT thay vì treo job.
"""

from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("openai")

from backend.core import budget, translate  # noqa: E402
from backend.core.subtitles import Cue  # noqa: E402
from backend.main import app  # noqa: E402

GOOD_KEY = "fake-key"


class _FakeOpenAI(BaseHTTPRequestHandler):
    """Giả lập /v1/chat/completions: dịch = thêm tiền tố [vi], rút gọn = giữ 2 từ đầu."""

    calls: list[dict] = []

    def log_message(self, *args):  # im lặng
        pass

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        model = body.get("model", "")
        auth = self.headers.get("Authorization", "")
        _FakeOpenAI.calls.append({"path": self.path, "model": model, "auth": auth})

        if self.path != "/v1/chat/completions":
            return self._send(404, {"error": {"message": "no such route"}})
        if auth != f"Bearer {GOOD_KEY}":
            return self._send(401, {"error": {"message": "Incorrect API key provided",
                                              "type": "invalid_request_error", "code": "invalid_api_key"}})
        if model == "missing-model":
            return self._send(404, {"error": {"code": "model_not_found", "type": "api_error",
                                              "message": f"The model '{model}' does not exist"}})
        if model == "slow-model":
            time.sleep(4)

        user = next(m["content"] for m in body["messages"] if m["role"] == "user")
        out = []
        for line in user.splitlines():
            if "|" not in line:
                continue
            parts = line.split("|")
            if len(parts) == 3:      # n|âm tiết|câu  -> yêu cầu rút gọn
                out.append(f"{parts[0]}|{' '.join(parts[2].split()[:2])}")
            else:                    # n|câu          -> dịch
                out.append(f"{parts[0]}|[vi] {parts[-1]}")
        content = "\n".join(out) if out else "OK"
        self._send(200, {
            "id": "chatcmpl-fake", "object": "chat.completion", "created": 0, "model": model,
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        })

    def _send(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture(scope="module")
def fake_openai():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAI)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    # có dấu / cuối như người dùng hay dán — code phải tự bỏ
    yield f"http://127.0.0.1:{srv.server_address[1]}/v1/"
    srv.shutdown()


@pytest.fixture(autouse=True)
def cache_rieng(workdir, monkeypatch):
    """Không đụng vào cache dịch thật của người dùng."""
    monkeypatch.setattr(translate, "_CACHE_FILE", workdir / "cache.json")


def c(start, end, text):
    return Cue(start=start, end=end, text=text)


# ------------------------------------------------------------------ dịch


def test_dich_qua_endpoint_tuy_chinh_voi_model_tuy_y(fake_openai):
    cues = [c(0, 2, "第一句。"), c(3, 5, "第二句。")]
    logs: list[str] = []
    translate.translate_cues(
        cues, source="zh", target="vi", engine="openai",
        api_key=GOOD_KEY, model="qwen3.8-flash", base_url=fake_openai, on_log=logs.append,
    )
    assert [x.text2 for x in cues] == ["[vi] 第一句。", "[vi] 第二句。"]
    last = _FakeOpenAI.calls[-1]
    assert last["model"] == "qwen3.8-flash", "tên model gõ tay phải đi nguyên vẹn tới endpoint"
    assert last["path"] == "/v1/chat/completions", "dấu / cuối base_url không được thành //"
    assert any("xong sau" in ln for ln in logs), "log phải ghi thời gian từng lô để biết đang chờ API"


def test_key_sai_bao_401_de_hieu(fake_openai):
    cues = [c(0, 2, "你好。")]
    with pytest.raises(translate.TranslateError) as err:
        translate.translate_cues(cues, "zh", "vi", engine="openai",
                                 api_key="wrong", model="m", base_url=fake_openai)
    assert "401" in str(err.value) or "Key sai" in str(err.value)


# ------------------------------------------------------------ rút gọn HP-5


def test_rut_gon_cau_vuot_khung_qua_endpoint(fake_openai):
    """Câu 8 từ trong khung 0,8 s chắc chắn vượt; mock cắt còn 2 từ -> hết vượt.

    Cần một cue ngay sau để khung không được cộng thêm 2 s "khoảng trống cuối".
    """
    cues = [c(0, 0.8, "一二三四五六七八。"), c(0.85, 2.0, "下一句。")]
    cues[0].text2 = "một hai ba bốn năm sáu bảy tám"
    logs: list[str] = []
    tighten = translate.make_tightener("openai", api_key=GOOD_KEY, model="m", base_url=fake_openai, on_log=logs.append)
    stats = budget.run_loop(cues, tighten, on_log=logs.append)
    assert stats["over_before"] == 1
    assert cues[0].text2 == "một hai"
    assert stats["tightened"] == 1 and stats["over_after"] == 0
    assert any("Rút gọn" in ln and "câu" in ln for ln in logs)


# ------------------------------------------------------- kiểm tra kết nối


def test_kiem_tra_ket_noi_ok(fake_openai):
    r = translate.check_connection("openai", api_key=GOOD_KEY, model="m", base_url=fake_openai)
    assert r["ok"] is True and r["reply"] == "OK" and r["latency_ms"] >= 0


def test_kiem_tra_ket_noi_model_khong_ton_tai(fake_openai):
    r = translate.check_connection("openai", api_key=GOOD_KEY, model="missing-model", base_url=fake_openai)
    assert r["ok"] is False and "Model" in r["error"]


def test_kiem_tra_ket_noi_key_sai(fake_openai):
    r = translate.check_connection("openai", api_key="wrong", model="m", base_url=fake_openai)
    assert r["ok"] is False and ("401" in r["error"] or "Key" in r["error"])


def test_endpoint_cham_bi_cat_theo_timeout(fake_openai):
    """Endpoint 4 s, timeout 1 s: phải báo lỗi trong vài giây chứ không chờ 600 s như SDK mặc định."""
    t0 = time.monotonic()
    r = translate.check_connection("openai", api_key=GOOD_KEY, model="slow-model", base_url=fake_openai, timeout=1)
    assert r["ok"] is False and "1s" in r["error"]
    assert time.monotonic() - t0 < 3.5


def test_api_check_tra_loi_qua_http(fake_openai):
    with TestClient(app) as client:
        r = client.post("/api/ai/check", json={"engine": "openai", "api_key": GOOD_KEY,
                                                "ai_model": "m", "ai_base_url": fake_openai})
        assert r.status_code == 200 and r.json()["ok"] is True
        assert GOOD_KEY not in r.text, "không được trả key ngược lại"
        bad = client.post("/api/ai/check", json={"engine": "google"})
        assert bad.status_code == 400


def test_timeout_doc_tu_bien_moi_truong(monkeypatch):
    monkeypatch.setenv("VSUB_AI_TIMEOUT", "45")
    assert translate.ai_timeout() == 45
    monkeypatch.setenv("VSUB_AI_TIMEOUT", "rác")
    assert translate.ai_timeout() == 120

"""Kiểm thử riêng tư: không thư viện nào được "gọi về nhà" mà người dùng không biết.

Kết quả rà soát thực tế (9/2026): pyannote.audio 4.x mặc định gửi thời lượng
audio + số nhân vật về otel.pyannote.ai. Mấy test này khoá lại chuyện tắt nó,
và khoá luôn hợp đồng gọi hàm với pyannote 4.x — chỗ chưa từng chạy thật vì
thiếu token, nên chỉ có test mới bắt được.
"""

from __future__ import annotations

import os
import subprocess
import sys
import types

import pytest


# ------------------------------------------------ biến môi trường chặn telemetry


@pytest.mark.parametrize(
    "name,expected",
    [
        ("PYANNOTE_METRICS_ENABLED", "false"),
        ("HF_HUB_DISABLE_TELEMETRY", "1"),
        ("GRADIO_ANALYTICS_ENABLED", "False"),
        ("DO_NOT_TRACK", "1"),
    ],
)
def test_import_config_tat_telemetry(name, expected):
    """Kiểm trong tiến trình sạch, vì biến đã được đặt sẵn ở tiến trình pytest."""
    code = f"import os; from app import config; print(os.environ.get({name!r}, ''))"
    env = {k: v for k, v in os.environ.items() if k != name}
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert out.returncode == 0, out.stderr[-400:]
    assert out.stdout.strip() == expected


def test_nguoi_dung_co_y_bat_thi_khong_bi_ghi_de():
    """setdefault chứ không phải gán đè — ai muốn bật telemetry thì vẫn bật được."""
    code = "import os; from app import config; print(os.environ['PYANNOTE_METRICS_ENABLED'])"
    env = dict(os.environ, PYANNOTE_METRICS_ENABLED="true")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60)
    assert out.stdout.strip() == "true"


# ---------------------------------------------- hợp đồng gọi pyannote 4.x


class PipelineGia:
    """Đóng vai `pyannote.audio.Pipeline`, ghi lại from_pretrained được gọi thế nào."""

    calls: list[dict] = []

    @classmethod
    def from_pretrained(cls, model_id, **kwargs):
        cls.calls.append({"model_id": model_id, **kwargs})
        return cls()

    def to(self, device):
        return self


@pytest.fixture
def pyannote_gia(monkeypatch):
    """Cắm module pyannote giả vào sys.modules; xoá cache pipeline của diarize."""
    from app import diarize

    pkg = types.ModuleType("pyannote")
    audio = types.ModuleType("pyannote.audio")
    audio.Pipeline = PipelineGia
    pkg.audio = audio
    monkeypatch.setitem(sys.modules, "pyannote", pkg)
    monkeypatch.setitem(sys.modules, "pyannote.audio", audio)
    monkeypatch.setattr(diarize, "_pipeline", None)
    monkeypatch.setattr(diarize, "_pipeline_key", None)
    PipelineGia.calls.clear()
    return diarize


def test_goi_from_pretrained_bang_token_khong_phai_use_auth_token(pyannote_gia):
    """pyannote 4.x không có `use_auth_token` và không có **kwargs -> TypeError.

    Lỗi này nằm ở đường chạy chưa từng được chạy thật (thiếu token HF), nên
    không có test là nó chỉ lộ ra lúc người dùng bấm chạy lần đầu.
    """
    pyannote_gia._load(token="hf_thu_nghiem")

    assert len(PipelineGia.calls) == 1
    call = PipelineGia.calls[0]
    assert call["token"] == "hf_thu_nghiem"
    assert "use_auth_token" not in call


def test_khong_co_token_thi_truyen_none(pyannote_gia, monkeypatch):
    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    pyannote_gia._load()
    assert PipelineGia.calls[0]["token"] is None


def test_nap_pipeline_dat_bien_tat_telemetry_truoc(pyannote_gia, monkeypatch):
    monkeypatch.delenv("PYANNOTE_METRICS_ENABLED", raising=False)
    pyannote_gia._load(token="x")
    assert os.environ.get("PYANNOTE_METRICS_ENABLED") == "false"


def test_pipeline_duoc_cache_khong_nap_lai(pyannote_gia):
    pyannote_gia._load(token="x")
    pyannote_gia._load(token="x")
    assert len(PipelineGia.calls) == 1


def test_from_pretrained_tra_none_thi_bao_ro_ly_do(pyannote_gia, monkeypatch):
    """pyannote trả None (không raise) khi chưa chấp nhận điều khoản — phải dịch ra lời người."""
    from app.diarize import DiarizeError

    monkeypatch.setattr(PipelineGia, "from_pretrained", classmethod(lambda cls, m, **k: None))
    with pytest.raises(DiarizeError, match="chấp nhận điều khoản"):
        pyannote_gia._load(token="x")


# ------------------------------------------------- không có tài nguyên ngoài


def test_giao_dien_khong_tai_tai_nguyen_tu_ben_ngoai():
    """Không script/style/font/ảnh từ CDN — mở trang là không có request nào ra ngoài."""
    from app.config import WEB_DIR
    import re

    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")

    for src in re.findall(r'<(?:script|link|img|iframe)[^>]+(?:src|href)="([^"]+)"', html):
        assert not src.startswith(("http://", "https://", "//")), f"tài nguyên ngoài: {src}"
    assert not re.search(r"fetch\(\s*['\"]https?://", js), "fetch tới máy chủ ngoài"
    assert not re.search(r"url\(\s*['\"]?https?://", css), "CSS tải tài nguyên ngoài"
    assert "sendBeacon" not in js and "XMLHttpRequest" not in js


def test_khong_ghi_bi_mat_xuong_localStorage():
    from app.config import WEB_DIR

    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    # Khối saveJobRecovery phải xoá cả hai khoá bí mật trước khi lưu
    block = js[js.index("function saveJobRecovery") : js.index("function clearJobRecovery")]
    assert "delete safe.api_key" in block
    assert "delete safe.hf_token" in block

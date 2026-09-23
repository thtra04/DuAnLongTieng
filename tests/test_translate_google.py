"""Engine Google: đường gtx gộp nhiều dòng, giãn nhịp, và báo lỗi rõ khi bị chặn."""

from __future__ import annotations

import pytest

from backend.core import translate
from backend.core.subtitles import Cue


@pytest.fixture(autouse=True)
def _khong_ngu(monkeypatch):
    monkeypatch.setattr(translate.time, "sleep", lambda s: None)


def _echo_call(payload: str, src: str, tgt: str) -> str:
    """Google giả: dịch mỗi dòng thành 'vi:<dòng>' và giữ nguyên xuống dòng."""
    return "\n".join(f"vi:{line}" for line in payload.split("\n"))


def test_gtx_gop_nhieu_dong_mot_lo():
    calls: list[str] = []

    def call(payload, src, tgt):
        calls.append(payload)
        return _echo_call(payload, src, tgt)

    out = translate._translate_gtx(["你好", "再见", "谢谢"], "zh-CN", "vi", call=call)

    assert out == ["vi:你好", "vi:再见", "vi:谢谢"]
    assert calls == ["你好\n再见\n谢谢"]  # một lượt gọi cho cả lô


def test_gtx_dong_trong_giu_trong_va_xuong_dong_trong_cau_bi_go():
    out = translate._translate_gtx(["a\nb", "", "c"], "zh-CN", "vi", call=_echo_call)
    assert out == ["vi:a b", "", "vi:c"]


def test_gtx_lo_tach_sai_thi_dich_tung_dong():
    calls: list[str] = []

    def call(payload, src, tgt):
        calls.append(payload)
        if "\n" in payload:
            return "gộp hết vào một dòng"  # Google gộp dòng -> số phần không khớp
        return f"vi:{payload}"

    out = translate._translate_gtx(["một", "hai"], "zh-CN", "vi", call=call)

    assert out == ["vi:một", "vi:hai"]
    assert calls == ["một\nhai", "một", "hai"]


def test_gtx_bi_chan_thi_lui_roi_thu_lai(monkeypatch):
    monkeypatch.setattr(translate, "_BLOCK_BACKOFF", (1.0, 2.0))
    n = {"k": 0}
    logs: list[str] = []

    def call(payload, src, tgt):
        n["k"] += 1
        if n["k"] < 3:
            raise RuntimeError("Server Error: You made too many requests to the server")
        return _echo_call(payload, src, tgt)

    out = translate._translate_gtx(["x"], "zh-CN", "vi", on_log=logs.append, call=call)

    assert out == ["vi:x"]
    assert n["k"] == 3
    assert any("tạm chặn" in m for m in logs)


def test_gtx_chan_mai_thi_bao_loi_ro_thay_vi_tra_rong(monkeypatch):
    monkeypatch.setattr(translate, "_BLOCK_BACKOFF", (1.0,))

    def call(payload, src, tgt):
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    with pytest.raises(translate.TranslateError, match="chặn máy này"):
        translate._translate_gtx(["x"], "zh-CN", "vi", call=call)


def test_gtx_loi_khac_thi_nem_len_de_roi_ve_duong_cu():
    def call(payload, src, tgt):
        raise OSError("mất mạng")

    with pytest.raises(OSError):
        translate._translate_gtx(["x"], "zh-CN", "vi", call=call)


def test_gtx_chia_lo_theo_so_dong_va_do_dai(monkeypatch):
    monkeypatch.setattr(translate, "_GTX_MAX_LINES", 2)
    monkeypatch.setattr(translate, "_GTX_MAX_CHARS", 8)
    assert translate._gtx_batches(["a", "b", "c"]) == [[0, 1], [2]]
    assert translate._gtx_batches(["aaaaaaa", "bbb"]) == [[0], [1]]
    assert translate._gtx_batches([]) == []


def test_engine_google_di_duong_gtx_truoc(monkeypatch):
    monkeypatch.setattr(translate, "_gtx_call", _echo_call)
    cues = [Cue(0, 1, "你好。"), Cue(1, 2, "再见。")]

    translate.translate_cues(cues, source="zh", target="vi", engine="google")

    assert [c.text2 for c in cues] == ["vi:你好。", "vi:再见。"]


def test_engine_google_roi_ve_deep_translator_khi_gtx_hong(monkeypatch):
    def hong(payload, src, tgt):
        raise OSError("endpoint đổi")

    monkeypatch.setattr(translate, "_gtx_call", hong)

    class _FakeGoogle:
        def __init__(self, source, target):
            pass

        def translate(self, text):
            return text.replace("你好", "xin chào")

    import deep_translator

    monkeypatch.setattr(deep_translator, "GoogleTranslator", _FakeGoogle)
    logs: list[str] = []
    out = translate._translate_deep(["你好"], "zh", "vi", "google", on_log=logs.append)

    assert out == ["xin chào"]
    assert any("gtx" in m for m in logs)


def test_dich_tung_dong_bi_chan_lien_tuc_thi_bao_loi(monkeypatch):
    monkeypatch.setattr(translate, "_BLOCK_BACKOFF", (1.0,))

    class _Blocked:
        def translate(self, text):
            raise RuntimeError("too many requests")

    with pytest.raises(translate.TranslateError, match="chặn máy này"):
        translate._translate_one(_Blocked(), "你好")


def test_dich_tung_dong_loi_khac_thi_bo_qua_dong_do():
    class _Broken:
        def translate(self, text):
            raise RuntimeError("lỗi lạ")

    logs: list[str] = []
    assert translate._translate_one(_Broken(), "你好", on_log=logs.append) == ""
    assert any("Bỏ qua" in m for m in logs)

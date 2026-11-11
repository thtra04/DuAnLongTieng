"""Dịch theo ngữ cảnh: bộ thuật ngữ cho engine miễn phí, ngữ cảnh quanh mỗi lô AI,
bảng vai, ghi chú đọc lướt, và bộ nhớ dịch học từ câu người dùng sửa tay."""

from __future__ import annotations

import pytest

from backend.core import translate
from backend.core.subtitles import Cue
from backend.store import memory


@pytest.fixture(autouse=True)
def cach_ly(workdir, monkeypatch, tmp_db):
    monkeypatch.setattr(translate, "_CACHE_FILE", workdir / "cache.json")
    monkeypatch.setattr(memory, "_ready", False)


def c(start, end, text, speaker="", text2=""):
    return Cue(start=start, end=end, text=text, speaker=speaker, text2=text2)


# ---------------------------------------------------------------- thuật ngữ


def test_doc_bo_thuat_ngu_nhieu_kieu_viet():
    pairs = translate.parse_glossary("郎君 = lang quân\n霍女 / 霍娘 -> Hoắc nương\n# ghi chú\nbro: ông bạn\nhỏng")
    assert ("郎君", "lang quân") in pairs
    assert ("霍女", "Hoắc nương") in pairs and ("霍娘", "Hoắc nương") in pairs
    assert ("bro", "ông bạn") in pairs
    assert len(pairs) == 4


def test_muc_dai_thay_truoc_muc_ngan():
    pairs = translate.parse_glossary("朱 = Chu\n朱大生 = Chu Đại Sinh")
    out, used = translate.apply_glossary(["朱大生来了"], pairs)
    assert "Chu Đại Sinh" in out[0] and used == 1
    assert "大生" not in out[0]


def test_tu_latinh_chi_thay_khi_dung_tron_tu():
    out, used = translate.apply_glossary(["Bro, my brother is here"], translate.parse_glossary("bro = ông bạn"))
    assert out[0] == "ông bạn, my brother is here"
    assert used == 1


def test_google_nhan_cau_da_cai_thuat_ngu(monkeypatch):
    sent = {}

    def gia(texts, source, target, engine, on_progress=None, on_log=None):
        sent["texts"] = list(texts)
        return ["x"] * len(texts)

    monkeypatch.setattr(translate, "_translate_deep", gia)
    cues = [c(0, 2, "郎君你回来了")]
    translate.translate_cues(cues, "zh", "vi", engine="google", glossary="郎君 = lang quân")
    assert "lang quân" in sent["texts"][0] and "郎君" not in sent["texts"][0]


# ------------------------------------------------------------- ngữ cảnh AI


def _fake_ai(monkeypatch, briefs=None):
    """Thay lớp gọi API: ghi lại system + payload, dịch = thêm tiền tố [vi]."""
    seen = {"payloads": [], "systems": [], "brief_calls": 0}

    class _Msg:
        def __init__(self, content):
            self.message = type("M", (), {"content": content})

    class _Completions:
        def create(self, model, messages):
            system = messages[0]["content"]
            user = messages[1]["content"]
            seen["systems"].append(system)
            seen["payloads"].append(user)
            out = []
            for line in user.splitlines():
                head, sep, rest = line.partition("|")
                if sep and head.strip().isdigit():
                    out.append(f"{head}|[vi] {rest}")
            return type("R", (), {"choices": [_Msg("\n".join(out))]})

    client = type("C", (), {"chat": type("Ch", (), {"completions": _Completions()})})
    monkeypatch.setattr(translate, "_openai_client", lambda *a, **k: client)

    def chat(engine, system, user, api_key, model, base_url, on_log=None):
        seen["brief_calls"] += 1
        return briefs or ""

    monkeypatch.setattr(translate, "_chat", chat)
    return seen


def test_lo_sau_mang_theo_cau_da_dich_va_cau_ke_tiep(monkeypatch):
    seen = _fake_ai(monkeypatch)
    cues = [c(i * 3, i * 3 + 2, f"Sentence number {i}.") for i in range(90)]
    translate.translate_cues(cues, "en", "vi", engine="openai", api_key="k", auto_context=False)
    assert len(seen["payloads"]) == 3
    first, second = seen["payloads"][0], seen["payloads"][1]
    assert "[ĐÃ DỊCH TRƯỚC ĐÓ]" not in first and "[CÂU KẾ TIẾP]" in first
    assert "[ĐÃ DỊCH TRƯỚC ĐÓ]" in second and "→ [vi] Sentence number 39." in second
    assert "- Sentence number 80." in second, "phải cho model thấy vài câu sắp tới"
    assert all(x.text2 == f"[vi] {x.text}" for x in cues), "ngữ cảnh không được lẫn vào bản dịch"


def test_kich_ban_ngan_gui_dang_cu_khong_them_muc(monkeypatch):
    seen = _fake_ai(monkeypatch)
    cues = [c(0, 2, "Hello."), c(3, 5, "Bye.")]
    translate.translate_cues(cues, "en", "vi", engine="openai", api_key="k")
    assert seen["payloads"] == ["1|Hello.\n2|Bye."]
    assert seen["brief_calls"] == 0, "kịch bản ngắn không cần đọc lướt"


def test_bang_vai_vao_loi_nhac_va_ten_vai_khong_lot_vao_ban_dich(monkeypatch):
    seen = _fake_ai(monkeypatch)
    cues = [c(0, 2, "你回来了。", "S1"), c(3, 5, "嗯。", "S2")]
    cast = [{"id": "S1", "name": "Nữ 1", "gender": "F", "age": "A"},
            {"id": "S2", "name": "", "gender": "M", "age": "E"}]
    translate.translate_cues(cues, "zh", "vi", engine="openai", api_key="k", cast=cast)
    assert "1|(Nữ 1) 你回来了。" in seen["payloads"][0]
    assert "2|(S2) 嗯。" in seen["payloads"][0]
    system = seen["systems"][0]
    assert "Nữ 1: nữ, người lớn" in system and "S2: nam, cao tuổi" in system
    assert "Xưng hô tiếng Việt" in system and "Hán-Việt" in system
    # máy chủ giả chép cả "(Nữ 1)" vào bản dịch — phải được gỡ
    assert translate._strip_speaker_tag("(Nữ 1) Chàng về rồi.", "Nữ 1") == "Chàng về rồi."
    assert cues[0].text2 == "[vi] (Nữ 1) 你回来了。"  # tiền tố [vi] đứng trước nên không gỡ nhầm


def test_ghi_chu_doc_luot_di_kem_moi_lo(monkeypatch):
    brief = "1. Phim cổ trang. 3. Chu Đại Sinh (nam), Hoắc nương (nữ). 4. Vợ gọi chồng là lang quân."
    seen = _fake_ai(monkeypatch, briefs=brief)
    cues = [c(i * 3, i * 3 + 2, f"Line {i}.") for i in range(50)]
    logs: list[str] = []
    translate.translate_cues(cues, "en", "vi", engine="openai", api_key="k", on_log=logs.append)
    assert seen["brief_calls"] == 1
    assert all(brief in s for s in seen["systems"]) and len(seen["systems"]) == 2
    assert any("Đọc lướt" in ln for ln in logs)


def test_doc_luot_loi_thi_van_dich(monkeypatch):
    seen = _fake_ai(monkeypatch)

    def hong(*a, **k):
        raise translate.TranslateError("endpoint sập")

    monkeypatch.setattr(translate, "_chat", hong)
    cues = [c(i * 3, i * 3 + 2, f"Line {i}.") for i in range(20)]
    translate.translate_cues(cues, "en", "vi", engine="openai", api_key="k")
    assert cues[5].text2 == "[vi] Line 5."
    assert "Ghi chú đọc lướt" not in seen["systems"][0]


def test_doi_bang_vai_thi_khong_dung_nham_cache(monkeypatch):
    seen = _fake_ai(monkeypatch)
    for gender in ("F", "M"):
        cues = [c(0, 2, "你好。", "S1")]
        translate.translate_cues(cues, "zh", "vi", engine="openai", api_key="k",
                                 cast=[{"id": "S1", "name": f"Vai {gender}", "gender": gender}])
    assert len(seen["payloads"]) == 2


# ------------------------------------------------------------ bộ nhớ dịch


def test_hoc_tu_cau_nguoi_dung_sua_va_dung_lai(monkeypatch):
    old = [c(0, 2, "郎君你回来了", text2="Lang Jun, anh đã về").to_dict(),
           c(3, 5, "奴家等了你很久", text2="Gia đình nô lệ đợi bạn").to_dict()]
    new = [dict(old[0], text2="Lang quân, chàng về rồi"), dict(old[1])]
    assert memory.learn_from_edit(old, new, "zh", "vi", "job1") == 1
    assert memory.stats()["pairs"] == 1

    monkeypatch.setattr(translate, "_translate_deep", lambda texts, *a, **k: ["máy dịch"] * len(texts))
    logs: list[str] = []
    cues = [c(0, 2, "郎君你回来了。"), c(3, 5, "别的话")]
    translate.translate_cues(cues, "zh", "vi", engine="google", on_log=logs.append)
    assert cues[0].text2 == "Lang quân, chàng về rồi", "câu đã sửa tay phải thắng máy dịch (khác dấu câu cuối vẫn khớp)"
    assert cues[1].text2 == "máy dịch"
    assert any("Bộ nhớ dịch" in ln for ln in logs)
    assert memory.stats()["reused"] == 1


def test_khong_hoc_khi_dong_bi_tach_gop_hoac_sua_chu_goc():
    old = [c(0, 2, "a", text2="x").to_dict(), c(3, 5, "b", text2="y").to_dict()]
    assert memory.learn_from_edit(old, old[:1], "en", "vi") == 0
    assert memory.learn_from_edit(old, [dict(old[0], text="A!", text2="z"), old[1]], "en", "vi") == 0
    assert memory.learn_from_edit(old, [dict(x) for x in old], "en", "vi") == 0, "không sửa gì thì không học"


def test_cau_gan_giong_thanh_mau_cho_ai_va_tat_duoc(monkeypatch):
    memory.learn([("郎君你今天回来得真早", "Hôm nay chàng về sớm thật")], "zh", "vi")
    seen = _fake_ai(monkeypatch)
    cues = [c(0, 2, "郎君你今天回来得真晚。")]
    translate.translate_cues(cues, "zh", "vi", engine="openai", api_key="k")
    assert "Hôm nay chàng về sớm thật" in seen["systems"][0]
    translate.translate_cues([c(0, 2, "郎君你今天回来得真晚。")], "zh", "vi", engine="openai", api_key="k",
                             use_memory=False)
    assert "Hôm nay chàng về sớm thật" not in seen["systems"][-1]


def test_ngon_ngu_dich_khac_thi_khong_dung_lai(monkeypatch):
    memory.learn([("Hello.", "Xin chào.")], "en", "vi")
    exact, examples = memory.lookup(["Hello."], "en", "th")
    assert exact == {} and examples == []


def test_xuat_corpus_jsonl(workdir):
    memory.learn([("Hello.", "Xin chào."), ("Bye.", "Tạm biệt.")], "en", "vi")
    out = workdir / "tm.jsonl"
    assert memory.export_jsonl(out, "vi") == 2
    first = out.read_text(encoding="utf-8").splitlines()[0]
    assert '"src": "Hello."' in first and '"tgt": "Xin chào."' in first


# ------------------------------------------------- corpus huấn luyện (HP-6)


def test_dung_corpus_tu_bo_nho_va_du_an_ai_loai_tap_kiem_thu(workdir):
    import importlib.util
    import json
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "build_corpus", Path(__file__).resolve().parent.parent / "training" / "build_corpus.py")
    bc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bc)

    def job(name, engine, cues):
        d = workdir / "jobs" / name
        d.mkdir(parents=True)
        (d / "state.json").write_text(json.dumps(
            {"cfg": {"engine": engine}, "source_lang": "zh", "target_lang": "vi", "cues": cues},
            ensure_ascii=False), encoding="utf-8")

    job("a", "openai", [c(0, 2, "你好。", text2="Xin chào.").to_dict(), c(3, 5, "在测试集里。", text2="Trong tập test.").to_dict()])
    job("b", "google", [c(0, 2, "谷歌翻译。", text2="Google dịch.").to_dict()])
    memory.learn([("你好。", "Chào chàng.")], "zh", "vi")

    corpus, stats = bc.merge([bc.from_memory(), bc.from_jobs(workdir / "jobs")], holdout={"在测试集里"})
    assert [(r["src"], r["tgt"], r["origin"]) for r in corpus] == [("你好。", "Chào chàng.", "user")], \
        "bản người dùng sửa thắng bản AI; Google và câu thuộc tập kiểm thử không được vào"
    assert stats["holdout"] == 1 and stats["duplicate"] == 1

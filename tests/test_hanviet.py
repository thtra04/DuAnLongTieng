"""Âm Hán Việt cho bản dịch Trung → Việt: tra âm, tìm cụm, sửa phiên âm sót, tự học thuật ngữ.

Câu thử lấy từ bộ gold thật (data/_bench/gold): Google dịch 郎君 thành "Lang Jun",
霍 thành "Huo", 春风楼 thành "tháp Chunfeng".
"""

from __future__ import annotations

import pytest

from backend.core import hanviet
from backend.core.subtitles import Cue


@pytest.fixture
def so_tay(monkeypatch, workdir):
    """Bộ thuật ngữ tự học trống, riêng cho từng test."""
    monkeypatch.setattr(hanviet, "LEARNED_PATH", workdir / "hanviet_learned.json")
    return workdir / "hanviet_learned.json"


def test_am_han_viet_tung_chu_va_chu_nhieu_am():
    assert hanviet.reading("郎君") == "lang quân"
    assert hanviet.reading("朱大生") == "chu đại sinh"
    assert hanviet.reading("刘") == "lưu", "chữ giản thể mượn âm chữ phồn thể 劉"
    assert hanviet.reading("长", ["chang"]) == "trường" and hanviet.reading("长", ["zhang"]) == "trưởng"
    assert hanviet.reading("我们x") is None


def test_so_am_tiet_khong_phan_biet_kieu_bo_dau():
    assert hanviet.canon("thuỷ") == hanviet.canon("thủy")
    assert hanviet.canon("Hoà") == hanviet.canon("hòa")
    assert hanviet.contains("Thiếp thấy Lang Quân mới giống", "lang quân")
    assert not hanviet.contains("lang thang quân", "lang quân")


def test_tim_cum_han_viet_trong_ban_dich_da_duyet():
    pairs = hanviet.harvest("我看郎君倒像个歹人", "Thiếp thấy lang quân mới giống kẻ xấu")
    assert pairs == [("郎君", "lang quân")]
    # một chữ chỉ nhận khi là tên riêng viết hoa giữa câu
    assert hanviet.harvest("我姓霍", "Thiếp họ Hoắc") == [("霍", "Hoắc")]
    assert hanviet.harvest("他是王", "Hắn là vương") == []


def test_cum_dau_cau_viet_thuong_tru_khi_la_ten_rieng():
    assert hanviet.harvest("郎君怕什么", "Lang quân sợ gì chứ?") == [("郎君", "lang quân")]
    seen = hanviet.harvest_many([("我姓霍", "Thiếp họ Hoắc"), ("霍儿", "Hoắc nhi")])
    assert seen[("霍儿", "Hoắc nhi")] == 1, "霍 đã biết là tên riêng nên 'Hoắc nhi' đầu câu giữ chữ hoa"


@pytest.mark.parametrize("zh, google, fixed", [
    ("我姓霍", "Họ của tôi là Huo", "Họ của tôi là Hoắc"),
    ("郎君好大的威风", "Lang Jun hoành tráng quá", "Lang Quân hoành tráng quá"),
    ("来人去春风楼", "Hãy đến và đi đến tháp Chunfeng", "Hãy đến và đi đến tháp Xuân Phong"),
    ("是朱郎说的锦衣玉食", "Đó là đồ ăn ngon mà Zhu Lang đã nói", "Đó là đồ ăn ngon mà Chu Lang đã nói"),
])
def test_sua_phien_am_pinyin_sot_lai(zh, google, fixed):
    assert hanviet.fix_pinyin(zh, google)[0] == fixed


def test_khong_dung_tu_tieng_viet_trung_mat_chu_pinyin():
    # "an", "Ba", "Lang" là từ tiếng Việt; câu gốc có 安 / 爸 / 郎 cũng không được đổi
    assert hanviet.fix_pinyin("平安就好", "Bình an là được")[1] == []
    assert hanviet.fix_pinyin("爸爸你来了", "Ba ơi, ba tới rồi")[1] == []
    assert hanviet.fix_pinyin("郎在哪", "Anh Lang ở đâu")[1] == []
    # phiên âm không khớp chữ nào trong câu gốc thì để nguyên
    assert hanviet.fix_pinyin("你好", "Gặp Zhang ở đâu")[1] == []


def test_sua_phien_am_theo_cach_viet_da_hoc():
    out, _ = hanviet.fix_pinyin("到了郎君这里", "Đến chỗ của Lang Jun", {"郎君": "lang quân"})
    assert out == "Đến chỗ của lang quân"


def test_hoc_thuat_ngu_va_uu_tien_nguoi_sua_tay(so_tay):
    assert hanviet.learn([("郎君", "Lang Quân")], "AI") == 1
    assert hanviet.learned_pairs(["郎君来了"]) == [], "học từ AI phải gặp từ hai lần mới tự áp"
    hanviet.learn([("郎君", "lang quân")], "sửa tay")
    hanviet.learn([("郎君", "Lang Quân")], "AI")  # AI không đè được người sửa tay
    assert hanviet.load()["郎君"]["vi"] == "lang quân"
    assert hanviet.learned_pairs(["郎君来了", "无关"]) == [("郎君", "lang quân")]
    assert hanviet.learned_pairs(["你好"]) == [], "chỉ trả cụm có mặt trong kịch bản"


def test_mot_chu_thuong_khong_tu_ap(so_tay):
    hanviet.learn([("他", "hắn"), ("霍", "Hoắc")], "thuật ngữ")
    assert hanviet.learned_pairs(["他姓霍"]) == [("霍", "Hoắc")]


def test_hoc_tu_cho_nguoi_dung_sua(so_tay):
    got = hanviet.corrections("郎君好大的威风", "Lang Jun hoành tráng quá", "Lang quân oai phong thật")
    assert got == [("郎君", "lang quân")]
    # cụm có sẵn ở bản máy dịch thì không phải chỗ người dùng sửa
    assert hanviet.corrections("老爷保重", "Lão gia bảo trọng nhé", "Lão gia bảo trọng") == []


def test_dich_google_cai_cum_da_hoc_va_sua_phien_am(so_tay, monkeypatch):
    from backend.core import translate

    hanviet.learn([("郎君", "lang quân")], "sửa tay")
    sent = []

    def fake_deep(texts, source, target, engine, on_progress=None, on_log=None):
        sent.extend(texts)
        return ["Lang quân hoành tráng quá" if "lang quân" in t else "Họ của tôi là Huo" for t in texts]

    monkeypatch.setattr(translate, "_translate_deep", fake_deep)
    monkeypatch.setattr(translate, "engine_available", lambda e: (True, ""))
    cues = [Cue(0, 2, "郎君好大的威风", ""), Cue(3, 5, "我姓霍。", "")]
    logs = []
    translate.translate_cues(cues, "zh", "vi", engine="google", on_log=logs.append, use_memory=False)
    assert any("lang quân" in s for s in sent), "cụm đã học phải được cài vào câu gốc"
    assert cues[1].text2 == "Họ của tôi là Hoắc."
    assert any("âm Hán Việt" in ln for ln in logs)


def test_tat_bang_bien_moi_truong(monkeypatch):
    assert hanviet.enabled("zh", "vi") and not hanviet.enabled("en", "vi") and not hanviet.enabled("zh", "en")
    monkeypatch.setenv("VSUB_HANVIET", "0")
    assert not hanviet.enabled("zh", "vi")


def test_xuat_ban_sua_tay_thi_nho_cum_han_viet(so_tay, tmp_db):
    from backend.store import memory

    old = [{"start": 0, "end": 2, "text": "郎君好大的威风", "text2": "Lang Jun hoành tráng quá"}]
    new = [{"start": 0, "end": 2, "text": "郎君好大的威风", "text2": "Lang quân oai phong thật"}]
    memory.learn_from_edit(old, new, "zh", "vi", "job1")
    assert hanviet.load()["郎君"]["vi"] == "lang quân"
    assert hanviet.load()["郎君"]["origin"] == "sửa tay"


def test_generate_from_script_without_confusing_family_names_and_nouns(so_tay):
    from backend.core.zh_terms import Lexicon
    texts = ["我叫歐陽明。", "在下司马青", "我姓单", "这张单据", "这位单医生", "重庆", "粗茶淡飯",
             "我叫他回来", "在下雨", "老爷车", "王朝", "在下周"]
    lex = Lexicon(texts)
    terms = {r["zh"]: (r["kind"], r["vi"]) for r in lex.suggest(texts)}
    assert terms["歐陽明"] == ("person", "Âu Dương Minh")
    assert lex.direct(texts[1]) == "Tại hạ là Tư Mã Thanh"
    assert terms["单医生"] == ("person", "bác sĩ Thiện")
    assert lex.prepare("这张单据") == ("这张单据", {})
    assert terms["重庆"] == ("place", "Trùng Khánh") and terms["粗茶淡飯"][0] == "idiom"
    assert "老爷" not in terms and not any(lex.direct(t) for t in (texts[7], texts[8], texts[-1]))
    assert not so_tay.exists()


def test_correlatives_keep_quantity_polarity_and_unmatched_clauses(so_tay):
    from backend.core.zh_terms import Lexicon
    lex = Lexicon([])
    assert lex.direct("有些事知道的越少越安心") == "Có những chuyện, càng biết ít càng yên lòng"
    assert lex.direct("了解得越多越不安。") == "Càng hiểu nhiều càng bất an."
    assert lex.direct("不是知道得越少越安心") == ""


def test_name_slots_preserve_reordering_retry_and_project_override(so_tay, monkeypatch):
    from backend.core import translate
    calls = []
    def mt(batch, *args):
        calls.append(list(batch))
        return (["Je suis QZ7012 à QZ7011", "marque perdue"] if len(batch) == 2
                else ["Tôi đến Trùng Khánh."])
    monkeypatch.setattr(translate, "_translate_nllb", mt)
    monkeypatch.setattr(translate, "engine_available", lambda e: (True, ""))
    cues = [Cue(1, 2, "我叫欧阳青"), Cue(2, 3, "在重庆见到欧阳青"), Cue(3, 4, "我们去重庆"),
            Cue(4, 5, "锦衣玉食？")]
    translate.translate_cues(cues, "zh", "vi", "nllb", glossary="欧阳青 = Âu Dương Khanh", use_memory=False)
    assert [c.text2 for c in cues] == ["Tôi tên là Âu Dương Khanh", "Je suis Âu Dương Khanh à Trùng Khánh",
                                        "Tôi đến Trùng Khánh.", "Ăn ngon mặc đẹp?"]
    assert len(calls) == 2 and len(calls[-1]) == 1 and "QZ" not in calls[-1][0]

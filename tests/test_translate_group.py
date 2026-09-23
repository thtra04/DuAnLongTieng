"""Kiểm thử phần gom câu, chia lại bản dịch và đọc kết quả AI trả về.

Đây là chỗ quyết định bản dịch có rơi đúng cue hay không. Sai ở đây thì phụ đề
vẫn hiện đủ chữ, không có lỗi nào bung ra — chỉ là chữ lệch khỏi lời thoại.
"""

from __future__ import annotations

from backend.core.subtitles import Cue
from backend.core.translate import (
    _ai_batches,
    _length_units,
    _parse_numbered,
    engine_available,
    group_cues,
    split_proportional,
)


def c(start, end, text):
    return Cue(start=start, end=end, text=text)


# ------------------------------------------------------------ gom câu


def test_gom_cac_manh_cua_mot_cau():
    cues = [c(0, 1, "Hôm nay"), c(1, 2, "trời rất"), c(2, 3, "đẹp.")]
    assert group_cues(cues) == [[0, 1, 2]]


def test_tach_khi_gap_dau_ket_cau():
    cues = [c(0, 1, "Xong rồi."), c(1, 2, "Bắt đầu lại.")]
    assert group_cues(cues) == [[0], [1]]


def test_tach_khi_im_lang_qua_lau():
    cues = [c(0, 1, "Một"), c(5, 6, "Hai")]
    assert group_cues(cues) == [[0], [1]]


def test_khong_gom_qua_sau_cue():
    cues = [c(i, i + 0.5, "chữ") for i in range(10)]
    assert all(len(g) <= 6 for g in group_cues(cues))


def test_khong_gom_qua_gioi_han_ky_tu():
    cues = [c(i, i + 0.5, "x" * 100) for i in range(5)]
    for g in group_cues(cues):
        assert sum(len(cues[i].text) for i in g) <= 240 + 100


def test_dau_ket_cau_sau_ngoac_kep_van_tinh():
    cues = [c(0, 1, 'Anh ta nói "xong rồi."'), c(1, 2, "Tiếp theo")]
    assert group_cues(cues)[0] == [0]


def test_moi_cue_deu_thuoc_dung_mot_nhom():
    cues = [c(i, i + 0.5, f"chữ {i}") for i in range(15)]
    flat = [i for g in group_cues(cues) for i in g]
    assert flat == list(range(15)), "không được bỏ sót hay lặp cue nào"


def test_danh_sach_rong():
    assert group_cues([]) == []


# ------------------------------------------------- chia lại bản dịch


def test_chia_theo_ti_le_do_dai():
    parts = split_proportional("một hai ba bốn năm sáu", [1, 1])
    assert len(parts) == 2
    assert all(p.strip() for p in parts)


def test_chia_khong_lam_mat_chu():
    goc = "một hai ba bốn năm sáu bảy tám"
    parts = split_proportional(goc, [1, 1, 1])
    assert "".join(parts).replace(" ", "") == goc.replace(" ", "")


def test_chia_khong_chem_giua_tu():
    parts = split_proportional("alpha bravo charlie delta echo", [1, 1])
    for p in parts:
        for word in p.split():
            assert word in "alpha bravo charlie delta echo".split()


def test_chia_mot_phan_tra_nguyen_van():
    assert split_proportional("nguyên câu", [1]) == ["nguyên câu"]


def test_chia_chuoi_rong():
    assert split_proportional("", [1, 1, 1]) == ["", "", ""]


def test_chia_khong_can_phan_nao():
    assert split_proportional("gì đó", []) == []


def test_trong_so_lech_cho_phan_dai_hon():
    parts = split_proportional("a" * 10 + " " + "b" * 90, [1, 9])
    assert len(parts[1]) > len(parts[0])


def test_chu_han_cat_o_dau_cung_duoc():
    parts = split_proportional("你好世界再見朋友", [1, 1])
    assert len(parts) == 2 and all(parts)


# -------------------------------------------- đọc kết quả AI trả về


def test_doc_dang_so_gach_dung():
    raw = "1|Xin chào\n2|Tạm biệt"
    assert _parse_numbered(raw, 0, 2) == ["Xin chào", "Tạm biệt"]


def test_gan_theo_so_dong_chu_khong_theo_thu_tu():
    """Model đảo thứ tự thì bản dịch vẫn phải vào đúng cue."""
    raw = "2|Hai\n1|Một\n3|Ba"
    assert _parse_numbered(raw, 0, 3) == ["Một", "Hai", "Ba"]


def test_dong_bi_bo_sot_de_rong():
    assert _parse_numbered("1|Một\n3|Ba", 0, 3) == ["Một", "", "Ba"]


def test_bo_qua_loi_dan_thua_cua_model():
    raw = "Đây là bản dịch của bạn:\n\n1|Một\n2|Hai\n\nHy vọng giúp được bạn!"
    assert _parse_numbered(raw, 0, 2) == ["Một", "Hai"]


def test_chap_nhan_nhieu_kieu_dau_phan_cach():
    assert _parse_numbered("1. Một", 0, 1) == ["Một"]
    assert _parse_numbered("1) Một", 0, 1) == ["Một"]
    assert _parse_numbered("1: Một", 0, 1) == ["Một"]
    assert _parse_numbered("1｜Một", 0, 1) == ["Một"]


def test_so_dong_ngoai_pham_vi_bi_bo_qua():
    assert _parse_numbered("1|Một\n99|Lạc", 0, 2) == ["Một", ""]


def test_offset_lo_khi_batch_khong_bat_dau_tu_1():
    assert _parse_numbered("41|Bốn mốt\n42|Bốn hai", 40, 2) == ["Bốn mốt", "Bốn hai"]


def test_ket_qua_rong():
    assert _parse_numbered("", 0, 3) == ["", "", ""]
    assert _parse_numbered(None, 0, 2) == ["", ""]


# ------------------------------------------------------ chia lô gửi AI


def test_chia_lo_khong_bo_sot_dong():
    texts = ["câu " * 20] * 50
    flat = [i for b in _ai_batches(texts) for i in b]
    assert flat == list(range(50))


def test_lo_khong_qua_dai():
    texts = ["x" * 500] * 30
    for batch in _ai_batches(texts, max_chars=2600):
        assert sum(len(texts[i]) for i in batch) <= 2600 + 500


def test_lo_khong_qua_nhieu_dong():
    texts = ["x"] * 200
    assert all(len(b) <= 40 for b in _ai_batches(texts, max_lines=40))


def test_danh_sach_rong_khong_sinh_lo_nao():
    assert list(_ai_batches([])) == []


# ------------------------------------------------------ đếm đơn vị đọc


def test_dem_tu_cho_chu_latin():
    assert _length_units("một hai ba") == 3


def test_dem_ky_tu_cho_chu_han():
    assert _length_units("你好世界") == 4


def test_chuoi_rong_van_tinh_la_mot():
    assert _length_units("") == 1


# -------------------------------------------------------- engine


def test_engine_hop_le_bao_dung_trang_thai():
    ok, why = engine_available("google")
    assert isinstance(ok, bool)
    if not ok:
        assert why


def test_engine_la_bi_tu_choi():
    ok, why = engine_available("gpt-9000")
    assert not ok and "không hợp lệ" in why


def test_goi_y_cai_khong_dua_lenh_uv_sync_tran():
    """`uv sync --extra ai` chạy trần sẽ gỡ các nhóm khác đã cài (torch, VieNeu, pyannote).

    Câu gợi ý phải bảo người dùng THÊM --extra vào lệnh đang dùng.
    """
    from backend.core.translate import _ENGINE_NEEDS

    for engine, (_mods, how) in _ENGINE_NEEDS.items():
        if "uv sync" in how:
            assert "thêm --extra" in how, f"{engine}: {how}"


# ------------------------------- chữ Hán: không gộp qua ranh giới đoạn Whisper


def _cue_seg(text, start, end, seg):
    return Cue(start, end, text, words=[{"word": text, "start": start, "end": end, "seg": seg}])


def test_chu_han_khac_doan_whisper_thi_moi_cue_mot_nhom():
    cues = [_cue_seg("在下朱大生", 0, 1, 0), _cue_seg("最会疼人", 1, 2, 1), _cue_seg("管教你锦衣玉食", 2, 3, 2)]
    assert group_cues(cues) == [[0], [1], [2]]


def test_chu_han_cung_doan_bi_tach_vi_dai_thi_van_gom():
    cues = [_cue_seg("在下朱大生", 0, 1, 0), _cue_seg("最会疼人", 1, 2, 0)]
    assert group_cues(cues) == [[0, 1]]


def test_chu_han_co_dau_ket_cau_van_tach_nhu_cu():
    cues = [_cue_seg("在下朱大生。", 0, 1, 0), _cue_seg("最会疼人", 1, 2, 0)]
    assert group_cues(cues) == [[0], [1]]


def test_chu_latin_khac_doan_van_gom_thanh_cau():
    cues = [_cue_seg("I think that", 0, 1, 0), _cue_seg("he is right.", 1, 2, 1)]
    assert group_cues(cues) == [[0, 1]]


def test_cue_khong_co_words_thi_khong_doi_hanh_vi():
    cues = [Cue(0, 1, "在下朱大生"), Cue(1, 2, "最会疼人")]
    assert group_cues(cues) == [[0, 1]]

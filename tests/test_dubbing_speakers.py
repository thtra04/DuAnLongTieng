"""Kiểm thử phần lồng tiếng đa nhân vật — không gọi TTS, chỉ kiểm logic chia đơn vị đọc."""

from __future__ import annotations

from app.dubbing import _clean_neighbours, _split_by_speaker, speaker_ids, speech_units
from app.subtitles import Cue


def c(start: float, end: float, text: str, speaker: str = "", text2: str = "") -> Cue:
    return Cue(start=start, end=end, text=text, text2=text2, speaker=speaker)


# ------------------------------------------------------ chia theo người nói


def test_chia_khi_doi_nguoi_noi():
    cues = [c(0, 1, "a", "S1"), c(1, 2, "b", "S1"), c(2, 3, "c", "S2")]
    assert _split_by_speaker(cues, [0, 1, 2]) == [[0, 1], [2]]


def test_khong_chia_khi_cung_mot_nguoi():
    cues = [c(0, 1, "a", "S1"), c(1, 2, "b", "S1")]
    assert _split_by_speaker(cues, [0, 1]) == [[0, 1]]


def test_doi_qua_lai_thi_chia_thanh_tung_luot():
    cues = [c(0, 1, "a", "S1"), c(1, 2, "b", "S2"), c(2, 3, "c", "S1")]
    assert _split_by_speaker(cues, [0, 1, 2]) == [[0], [1], [2]]


def test_cue_chua_gan_nhan_khong_dinh_vao_luot_nguoi_khac():
    cues = [c(0, 1, "a", "S1"), c(1, 2, "b", ""), c(2, 3, "c", "S1")]
    assert _split_by_speaker(cues, [0, 1, 2]) == [[0], [1], [2]]


def test_khong_gan_nhan_gi_ca_thi_giu_nguyen_mot_khoi():
    """Video một người nói / chưa bật diarization -> hành vi y như trước."""
    cues = [c(0, 1, "a"), c(1, 2, "b"), c(2, 3, "c")]
    assert _split_by_speaker(cues, [0, 1, 2]) == [[0, 1, 2]]


# ------------------------------------------------------------ speech_units


def test_don_vi_doc_khong_tron_hai_nhan_vat():
    """Hai nhân vật đối đáp nhanh, cùng một câu -> vẫn phải tách hai lần đọc."""
    cues = [
        c(0.0, 1.0, "Anh đi đâu", "S1", text2="Anh đi đâu"),
        c(1.0, 2.0, "đấy?", "S2", text2="đấy?"),
    ]
    units = speech_units(cues, use_translation=True)
    assert len(units) == 2, "gộp hai nhân vật vào một lần đọc là mất ý nghĩa tách vai"
    assert units[0]["speaker"] == "S1"
    assert units[1]["speaker"] == "S2"


def test_don_vi_doc_van_gop_khi_cung_mot_nguoi():
    cues = [
        c(0.0, 1.0, "Hôm nay", "S1", text2="Hôm nay"),
        c(1.0, 2.0, "trời đẹp.", "S1", text2="trời đẹp."),
    ]
    units = speech_units(cues, use_translation=True)
    assert len(units) == 1
    assert units[0]["cues"] == [0, 1]
    assert units[0]["speaker"] == "S1"


def test_moi_don_vi_deu_co_khoa_speaker():
    cues = [c(0, 1, "xin chào", "S1", text2="xin chào")]
    units = speech_units(cues, use_translation=True)
    assert "speaker" in units[0]


def test_khong_co_nhan_thi_speaker_rong():
    cues = [c(0, 1, "xin chào", text2="xin chào")]
    units = speech_units(cues, use_translation=True)
    assert units[0]["speaker"] == ""


# ----------------------------------------------------------- danh sách vai


def test_sap_nhan_vat_theo_thoi_gian_noi():
    cues = [c(0, 1, "a", "S2"), c(1, 9, "b", "S1"), c(9, 10, "c", "S2")]
    assert speaker_ids(cues) == ["S1", "S2"]


def test_bo_qua_cue_chua_gan_nhan():
    cues = [c(0, 5, "a", ""), c(5, 6, "b", "S1")]
    assert speaker_ids(cues) == ["S1"]


def test_khong_co_nhan_vat_nao():
    assert speaker_ids([c(0, 1, "a")]) == []


# --------------------------------------------------- chọn mẫu giọng sạch


def test_cue_sat_luot_nguoi_khac_bi_loai_khoi_mau():
    cues = [c(0.0, 2.0, "a", "S2"), c(2.1, 8.0, "b", "S1")]
    index = {id(x): i for i, x in enumerate(cues)}
    assert not _clean_neighbours(cues, index, cues[1]), "cách 0.1s thì dễ dính đuôi giọng S2"


def test_cue_cach_xa_luot_nguoi_khac_thi_nhan():
    cues = [c(0.0, 2.0, "a", "S2"), c(5.0, 11.0, "b", "S1")]
    index = {id(x): i for i, x in enumerate(cues)}
    assert _clean_neighbours(cues, index, cues[1])


def test_hang_xom_cung_nguoi_noi_thi_khong_sao():
    cues = [c(0.0, 2.0, "a", "S1"), c(2.05, 8.0, "b", "S1")]
    index = {id(x): i for i, x in enumerate(cues)}
    assert _clean_neighbours(cues, index, cues[1])

"""HP-5 — vòng lặp đóng về ngân sách thời gian.

Trước đây: dịch một lần, rồi lúc lồng tiếng câu nào dài quá khung thì **nén âm
thanh** bằng atempo — giọng gấp và máy móc (đo thật: 48/69 câu phải nén).

Bây giờ: sau khi dịch, **dự đoán** thời lượng đọc của từng câu (HP-3), so với
ngân sách thời gian của khung thoại, và câu nào vượt thì **dịch lại ngắn hơn**
(tối đa hai lượt). Chỉ khi vẫn vượt mới để atempo xử lý như phương án cuối.

Cách "siết" tuỳ engine dịch, nên được tiêm vào dưới dạng `Tightener`:
với Claude/OpenAI là nhắc lại kèm giới hạn âm tiết; với NLLB đẳng thời (HP-4)
là đổi token ngân sách; với Google/NLLB thường (cấu hình C0, không API key) là
bộ luật rút gọn tiếng Việt `shorten.py`. Không có cách siết thì chỉ đo và báo.

Ngân sách của một nhóm cue tính **đúng như lúc lồng tiếng**
(`dubbing.build_dub_track`): khung thoại + khoảng lặng phía sau + một chút vào
sớm — nếu tính khác đi thì câu "vừa" theo vòng lặp vẫn "tràn" theo TTS.
"""

from __future__ import annotations

import re
from typing import Callable

from . import duration
from .subtitles import Cue
from .translate import _join_fragments, split_proportional

# Đồng bộ với dubbing.MAX_LEAD_IN và khoảng chừa 0.02s trong build_dub_track
LEAD_IN = 0.15
GAP_MARGIN = 0.02
# Vượt ít hơn ngần này (tỉ lệ) thì coi như vừa — TTS có sai số, đừng dịch lại vô ích
TOLERANCE = 0.05

Tightener = Callable[[list[dict]], list]  # mỗi phần tử: str (cả câu) hoặc list[str] (từng cue)


def window_seconds(cues: list[Cue], idx: list[int]) -> float:
    """Ngân sách thời gian cho nhóm cue `idx` (giây)."""
    start, end = cues[idx[0]].start, cues[idx[-1]].end
    nxt, prev = idx[-1] + 1, idx[0] - 1
    gap_after = (cues[nxt].start - end) if nxt < len(cues) else 2.0
    gap_before = (start - cues[prev].end) if prev >= 0 else start
    lead_in = max(0.0, min(LEAD_IN, gap_before - GAP_MARGIN))
    return max(0.0, end - start) + max(0.0, gap_after - GAP_MARGIN) + lead_in


def reading_units(cues: list[Cue]) -> list[list[int]]:
    """Các nhóm cue mà bước lồng tiếng sẽ đọc thành **một lần TTS**.

    Trước đây vòng lặp đo theo nhóm dịch (`group_cues`), còn lồng tiếng lại đọc
    theo `dubbing.speech_units` — nhóm dịch chẻ thêm mỗi khi đổi người nói và khi
    quá dài. Đo thật trên video bilibili 16 phút: 70 nhóm dịch nhưng 186 đơn vị
    đọc, nên vòng lặp thấy 8 câu vượt trong khi TTS phải tăng tốc 78 câu. Đo đúng
    đơn vị TTS sẽ đọc thì con số hai bên mới khớp nhau.
    """
    from .dubbing import speech_units

    return [u["cues"] for u in speech_units(cues, use_translation=True)]


def assess(cues: list[Cue], model: duration.DurationModel | None = None) -> list[dict]:
    """Đánh giá từng đơn vị đọc: ngân sách, thời lượng dự đoán, vượt bao nhiêu.

    Đơn vị lấy đúng như lúc lồng tiếng (`reading_units`); bản dịch của cả đơn vị
    được nối lại để dự đoán, rồi khi rút gọn thì chia lại vào từng cue.
    """
    model = model or duration.default_model()
    out: list[dict] = []
    for g in reading_units(cues):
        text = _join_fragments([(cues[i].text2 or "").strip() for i in g])
        if not text.strip():
            continue
        budget = window_seconds(cues, g)
        predicted = model.predict(text)
        over = predicted - budget
        out.append(
            {
                "cues": g,
                "text": text,
                "budget": round(budget, 3),
                "predicted": round(predicted, 3),
                "over": round(over, 3),
                "ratio": round(predicted / budget, 3) if budget > 0 else float("inf"),
                "syllables": duration.syllables(text),
            }
        )
    return out


def over_budget(items: list[dict], tolerance: float = TOLERANCE) -> list[dict]:
    return [it for it in items if it["budget"] > 0 and it["ratio"] > 1.0 + tolerance]


def target_syllables(item: dict, safety: float = 0.92) -> int:
    """Số âm tiết tối đa để câu vừa ngân sách, có chừa sai số dự đoán."""
    if item["predicted"] <= 0:
        return item["syllables"]
    want = int(item["syllables"] * item["budget"] / item["predicted"] * safety)
    return max(1, min(item["syllables"] - 1, want))


def _write_back(cues: list[Cue], item: dict, new_text) -> None:
    """Ghi câu đã rút gọn vào các cue của đơn vị.

    Bộ siết có thể trả **danh sách từng mảnh** (bộ luật rút gọn từng cue một, giữ
    nguyên ranh giới cue) hoặc **một chuỗi** (AI viết lại cả câu) — chuỗi thì chia
    lại theo tỉ lệ ký tự như lúc dịch. Chia lại theo tỉ lệ có thể đẩy một từ cuối
    cue này sang đầu cue sau, nên bộ nào giữ được mảnh thì nên trả mảnh.
    """
    g = item["cues"]
    if isinstance(new_text, (list, tuple)):
        if len(new_text) == len(g) and any((p or "").strip() for p in new_text):
            for i, part in zip(g, new_text):
                cues[i].text2 = (part or "").strip()
            return
        new_text = _join_fragments([(p or "").strip() for p in new_text])
    new_text = (new_text or "").strip()
    if not new_text:
        return
    if len(g) == 1:
        cues[g[0]].text2 = new_text
        return
    weights = [max(1, len(cues[i].text.strip())) for i in g]
    for i, part in zip(g, split_proportional(new_text, weights)):
        cues[i].text2 = part


def run_loop(
    cues: list[Cue],
    tightener: Tightener | None,
    model: duration.DurationModel | None = None,
    max_passes: int = 2,
    tolerance: float = TOLERANCE,
    on_log: Callable[[str], None] | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> dict:
    """Chạy vòng lặp ngân sách. Sửa `cues[i].text2` tại chỗ. Trả về thống kê.

    Thống kê là thứ chương thực nghiệm cần: bao nhiêu câu vượt trước/sau, mấy
    lượt, và danh sách câu vẫn vượt để người dùng rút gọn tay ở bước 4.
    """
    model = model or duration.default_model()
    items = assess(cues, model)
    before = over_budget(items, tolerance)
    stats = {
        "groups": len(items),
        "over_before": len(before),
        "over_after": len(before),
        "passes": 0,
        "tightened": 0,
        "model_trained": model.trained,
        "unresolved": [],
    }
    if on_log:
        on_log(
            f"Ngân sách thời gian: {len(before)}/{len(items)} câu dự đoán vượt khung"
            + ("" if model.trained else " (ước lượng thô, chưa có mô hình HP-3)")
            + "."
        )
    if not before:
        return stats
    if tightener is None:
        if on_log:
            on_log("  Engine dịch này chưa có cách rút gọn có kiểm soát — để atempo xử lý.")
        stats["unresolved"] = [_brief(it) for it in before]
        return stats

    pending = before
    for n in range(1, max_passes + 1):
        stats["passes"] = n
        requests = [
            {
                **it,
                "target_syllables": target_syllables(it),
                "pieces": [(cues[i].text2 or "").strip() for i in it["cues"]],
                # câu gốc: bộ siết kiểu dịch lại (NLLB đẳng thời, HP-4) cần nó
                "source": _join_fragments([(cues[i].text or "").strip() for i in it["cues"]]),
            }
            for it in pending
        ]
        if on_log:
            on_log(f"  Lượt {n}/{max_passes}: gửi {len(requests)} câu vượt khung đi rút gọn.")
        try:
            shorter = tightener(requests)
        except Exception as exc:
            if on_log:
                on_log(f"  Lượt rút gọn {n} lỗi, dừng: {exc}")
            break
        changed = 0
        for it, new_text in zip(requests, shorter):
            if isinstance(new_text, (list, tuple)):
                if [p.strip() for p in new_text] != it["pieces"]:
                    _write_back(cues, it, new_text)
                    changed += 1
                continue
            new_text = (new_text or "").strip()
            if new_text and new_text != it["text"]:
                _write_back(cues, it, new_text)
                changed += 1
        stats["tightened"] += changed
        items = assess(cues, model)
        pending = over_budget(items, tolerance)
        if on_log:
            on_log(f"  Lượt {n}: rút gọn {changed} câu, còn {len(pending)} câu vượt.")
        if on_progress:
            on_progress(n / max_passes)
        if not pending or changed == 0:
            break

    stats["over_after"] = len(pending)
    stats["unresolved"] = [_brief(it) for it in pending]
    return stats


# ------------------------------------------------- dịch gọn từng dòng (bước 4)
CPS_MAX = 22          # ký tự/giây — trùng ngưỡng tô vàng "cps" ở bảng phụ đề
LENGTH_RATIO = 1.25   # bản dịch dài quá 125 % bản gốc thì bảng phụ đề gắn nhãn "Dài"
_CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")


def length_units(text: str) -> int:
    """Đơn vị độ dài như bảng phụ đề đếm: chữ với tiếng Trung/Nhật, từ với ngôn ngữ còn lại."""
    text = text or ""
    if _CJK.search(text):
        return max(1, len(re.sub(r"\s+", "", text)))
    return max(1, len(text.split()))


def line_target(cue: Cue, model: duration.DurationModel | None = None) -> int | None:
    """Số âm tiết tối đa để dòng này hết bị gắn cờ, hoặc None nếu dòng không dài.

    Ba cờ, lấy mức chặt nhất: dài quá 125 % bản gốc ("Dài"), quá 22 ký tự/giây ("cps"),
    và giọng đọc dự đoán không kịp khung giờ của dòng.
    """
    text = (cue.text2 or "").strip()
    if not text:
        return None
    model = model or duration.default_model()
    syl = duration.syllables(text)
    span = max(0.3, cue.end - cue.start)
    caps: list[int] = []
    if (cue.text or "").strip():
        allowed = length_units(cue.text) * LENGTH_RATIO
        units = length_units(text)
        if units > allowed:
            caps.append(int(syl * allowed / units))
    if len(text) / span > CPS_MAX:
        caps.append(int(syl * CPS_MAX * span / len(text)))
    predicted = model.predict(text)
    if predicted > span * (1.0 + TOLERANCE):
        caps.append(int(syl * span / predicted * 0.92))
    if not caps:
        return None
    return max(1, min(syl - 1, *caps))


def fit_lines(
    cues: list[Cue],
    indices: list[int] | None,
    tightener: Tightener,
    model: duration.DurationModel | None = None,
) -> dict:
    """Dịch gọn lại các dòng bị gắn cờ dài. `indices` rỗng = mọi dòng đang dài.

    Mỗi dòng là một yêu cầu riêng (không gộp đơn vị đọc) để chữ không chạy sang dòng
    bên cạnh. Bản mới chỉ được nhận khi thật sự ngắn hơn bản cũ. Không sửa `cues`;
    trả về danh sách thay đổi để bên gọi tự áp và hoàn tác được.
    """
    model = model or duration.default_model()
    pool = range(len(cues)) if not indices else [i for i in indices if 0 <= i < len(cues)]
    requests = []
    for i in pool:
        target = line_target(cues[i], model)
        if target is None:
            continue
        text = (cues[i].text2 or "").strip()
        requests.append({"cues": [i], "text": text, "pieces": [text], "target_syllables": target,
                         "syllables": duration.syllables(text), "source": (cues[i].text or "").strip()})
    changes: list[dict] = []
    if requests:
        for r, new in zip(requests, tightener(requests)):
            if isinstance(new, (list, tuple)):
                new = _join_fragments([(p or "").strip() for p in new])
            new = " ".join((new or "").split())
            if new and new != r["text"] and duration.syllables(new) < r["syllables"]:
                changes.append({"i": r["cues"][0], "text2": new, "target": r["target_syllables"],
                                "fits": duration.syllables(new) <= r["target_syllables"]})
    return {"asked": len(requests), "changes": changes}


def _brief(item: dict) -> dict:
    g = item["cues"]
    return {
        "lines": f"{g[0] + 1}" if len(g) == 1 else f"{g[0] + 1}–{g[-1] + 1}",
        "over_s": item["over"],
        "budget_s": item["budget"],
        "predicted_s": item["predicted"],
        "text": item["text"][:60],
    }

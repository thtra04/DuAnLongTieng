"""HP-5 — vòng lặp đóng về ngân sách thời gian.

Trước đây: dịch một lần, rồi lúc lồng tiếng câu nào dài quá khung thì **nén âm
thanh** bằng atempo — giọng gấp và máy móc (đo thật: 48/69 câu phải nén).

Bây giờ: sau khi dịch, **dự đoán** thời lượng đọc của từng câu (HP-3), so với
ngân sách thời gian của khung thoại, và câu nào vượt thì **dịch lại ngắn hơn**
(tối đa hai lượt). Chỉ khi vẫn vượt mới để atempo xử lý như phương án cuối.

Cách "siết" tuỳ engine dịch, nên được tiêm vào dưới dạng `Tightener`:
với Claude/OpenAI là nhắc lại kèm giới hạn âm tiết; với NLLB đẳng thời (HP-4)
là đổi token ngân sách. Không có cách siết thì vòng lặp chỉ đo và báo.

Ngân sách của một nhóm cue tính **đúng như lúc lồng tiếng**
(`dubbing.build_dub_track`): khung thoại + khoảng lặng phía sau + một chút vào
sớm — nếu tính khác đi thì câu "vừa" theo vòng lặp vẫn "tràn" theo TTS.
"""

from __future__ import annotations

from typing import Callable

from . import duration
from .subtitles import Cue
from .translate import _join_fragments, group_cues, split_proportional

# Đồng bộ với dubbing.MAX_LEAD_IN và khoảng chừa 0.02s trong build_dub_track
LEAD_IN = 0.15
GAP_MARGIN = 0.02
# Vượt ít hơn ngần này (tỉ lệ) thì coi như vừa — TTS có sai số, đừng dịch lại vô ích
TOLERANCE = 0.05

Tightener = Callable[[list[dict]], list[str]]


def window_seconds(cues: list[Cue], idx: list[int]) -> float:
    """Ngân sách thời gian cho nhóm cue `idx` (giây)."""
    start, end = cues[idx[0]].start, cues[idx[-1]].end
    nxt, prev = idx[-1] + 1, idx[0] - 1
    gap_after = (cues[nxt].start - end) if nxt < len(cues) else 2.0
    gap_before = (start - cues[prev].end) if prev >= 0 else start
    lead_in = max(0.0, min(LEAD_IN, gap_before - GAP_MARGIN))
    return max(0.0, end - start) + max(0.0, gap_after - GAP_MARGIN) + lead_in


def assess(cues: list[Cue], model: duration.DurationModel | None = None) -> list[dict]:
    """Đánh giá từng nhóm câu: ngân sách, thời lượng dự đoán, vượt bao nhiêu.

    Nhóm câu lấy theo cùng quy tắc với khâu dịch (`group_cues`) — vì bản dịch
    được dịch theo nhóm rồi chia lại, nên siết cũng phải siết theo nhóm.
    """
    model = model or duration.default_model()
    out: list[dict] = []
    for g in group_cues(cues):
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


def _write_back(cues: list[Cue], item: dict, new_text: str) -> None:
    g = item["cues"]
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
        requests = [{**it, "target_syllables": target_syllables(it)} for it in pending]
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


def _brief(item: dict) -> dict:
    g = item["cues"]
    return {
        "lines": f"{g[0] + 1}" if len(g) == 1 else f"{g[0] + 1}–{g[-1] + 1}",
        "over_s": item["over"],
        "budget_s": item["budget"],
        "predicted_s": item["predicted"],
        "text": item["text"][:60],
    }

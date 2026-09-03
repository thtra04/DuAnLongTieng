"""Khung đo tự động — cài đặt Bảng 5.2 của đề cương.

Mọi thay đổi kỹ thuật đều phải kèm số đo trước/sau trên cùng một tập kiểm thử
cố định. Module này là chỗ tính và gom các số đo đó, để bảng kết quả trong
báo cáo sinh ra từ dữ liệu thật chứ không chép tay.

Bốn nhóm chỉ số (theo đề cương):

* **Đẳng thời** — tỉ lệ câu phải nén, hệ số nén lớn nhất, tổng thời gian tràn.
  Lấy từ thống kê của `dubbing.build_dub_track`.
* **Nhân vật** — độ chính xác gán nhãn so với nhãn người gán tay.
* **Chất lượng dịch** — BLEU (sacreBLEU, tuỳ chọn); COMET để bên ngoài vì nặng.
* **Hiệu năng** — hệ số thời gian thực = thời gian xử lý / thời lượng video.

Năm cấu hình đối chứng C0…C4 khai báo ở `CONFIGS` để mọi lần chạy đều ghi rõ
mình thuộc cấu hình nào — bảng so sánh chỉ có nghĩa khi cột nào ra cột đó.
"""

from __future__ import annotations

import csv
import io
import itertools
import json
import time
from pathlib import Path

from .subtitles import Cue

# ------------------------------------------------------- cấu hình đối chứng

CONFIGS: dict[str, dict] = {
    "C0": {
        "label": "Một giọng · Google Translate · nén tốc độ khi tràn",
        "diarize": False, "engine": "google", "isochronic": False, "budget_loop": False,
        "note": "Đường cơ sở — hệ thống nền trước đề tài.",
    },
    "C1": {
        "label": "Một giọng · mô hình ngôn ngữ lớn có nhắc giữ độ dài",
        "diarize": False, "engine": "claude", "isochronic": False, "budget_loop": False,
        "note": "Đối chứng: điều khiển độ dài bằng câu nhắc có đủ không.",
    },
    "C2": {
        "label": "Đa giọng · Google Translate",
        "diarize": True, "engine": "google", "isochronic": False, "budget_loop": False,
        "note": "Tách riêng đóng góp của HP-1 và HP-2.",
    },
    "C3": {
        "label": "Đa giọng · dịch đẳng thời · không vòng lặp",
        "diarize": True, "engine": "nllb", "isochronic": True, "budget_loop": False,
        "note": "Tách riêng đóng góp của HP-4.",
    },
    "C4": {
        "label": "Hệ thống đầy đủ — đa giọng · dịch đẳng thời · vòng lặp ngân sách",
        "diarize": True, "engine": "nllb", "isochronic": True, "budget_loop": True,
        "note": "Cấu hình đề xuất.",
    },
}

# Trường nào của `dubbing.build_dub_track` stats được dùng, và tên chuẩn trong báo cáo
ISOCHRONY_FIELDS = ("compress_ratio", "max_factor", "overflow_count", "overflow_s")


def config_of(cfg: dict) -> str:
    """Suy cấu hình C0…C4 gần nhất từ cấu hình chạy thật, để gắn nhãn tự động.

    Người dùng có thể ghi đè bằng `cfg["eval_config"]`. Suy luận chỉ dựa trên ba
    công tắc quyết định bảng so sánh: có tách nhân vật không, dịch có ràng buộc
    đẳng thời không, có vòng lặp ngân sách không.
    """
    explicit = str(cfg.get("eval_config") or "").strip().upper()
    if explicit in CONFIGS:
        return explicit
    diarize = bool(cfg.get("diarize"))
    iso = bool(cfg.get("isochronic"))
    loop = bool(cfg.get("budget_loop"))
    if iso and loop:
        return "C4"
    if iso:
        return "C3"
    if diarize:
        return "C2"
    if str(cfg.get("engine", "")) in ("claude", "openai"):
        return "C1"
    return "C0"


# --------------------------------------------------------------- đẳng thời


def isochrony_metrics(stats: dict) -> dict:
    """Ba chỉ số đẳng thời từ thống kê của `build_dub_track`.

    `count` là số câu đọc thành công; tỉ lệ tính trên đó chứ không trên số cue,
    vì cue bị bỏ (không có bản dịch) không được đọc nên cũng chẳng nén gì.
    """
    count = int(stats.get("count") or 0)
    sped = int(stats.get("sped_up") or 0)
    return {
        "units": count,
        "compress_count": sped,
        "compress_ratio": round(sped / count, 4) if count else 0.0,
        "max_factor": round(float(stats.get("max_factor") or 1.0), 4),
        "overflow_count": int(stats.get("overflow") or 0),
        "overflow_s": round(float(stats.get("overflow_s") or 0.0), 3),
        "failed": int(stats.get("failed") or 0),
        "skipped": int(stats.get("skipped") or 0),
    }


def realtime_factor(elapsed_s: float, duration_s: float) -> float | None:
    """Hệ số thời gian thực: 1.0 nghĩa là xử lý mất đúng bằng thời lượng video."""
    if not duration_s or duration_s <= 0 or elapsed_s is None:
        return None
    return round(float(elapsed_s) / float(duration_s), 3)


# ---------------------------------------------------------------- nhân vật


def export_for_labeling(cues: list[Cue]) -> list[dict]:
    """Bảng để người gán nhãn tay: mỗi dòng một cue, cột `gold` để trống.

    Xuất kèm nhãn máy đoán để người gán chỉ sửa chỗ sai thay vì gõ lại từ đầu —
    nhưng cột `gold` vẫn để trống, tránh người gán lười mà giữ nguyên nhãn máy.
    """
    return [
        {
            "index": i,
            "start": round(c.start, 2),
            "end": round(c.end, 2),
            "text": c.text,
            "predicted": c.speaker or "",
            "gold": "",
        }
        for i, c in enumerate(cues)
    ]


def import_labels(rows: list[dict]) -> dict[int, str]:
    """Đọc lại bảng đã gán: {chỉ số cue: nhãn}. Bỏ qua dòng để trống."""
    out: dict[int, str] = {}
    for row in rows:
        try:
            idx = int(row.get("index"))
        except (TypeError, ValueError):
            continue
        gold = str(row.get("gold") or "").strip()
        if gold:
            out[idx] = gold
    return out


def speaker_accuracy(cues: list[Cue], gold: dict[int, str]) -> dict:
    """Độ chính xác gán nhãn nhân vật so với nhãn người gán tay.

    Nhãn máy (S1, S2…) và nhãn người (A, B, "Hoàng đế"…) là hai bảng tên khác
    nhau, nên phải tìm **ánh xạ tốt nhất** giữa hai bảng rồi mới đếm đúng/sai —
    không thì máy gán hoàn hảo mà chỉ đặt tên khác cũng bị chấm 0 điểm. Số nhân
    vật nhỏ nên duyệt hết mọi hoán vị (≤ 8 nhân vật); nhiều hơn thì ghép tham
    lam theo ô lớn nhất của ma trận nhầm lẫn.

    Chỉ chấm những cue có nhãn người; cue máy để trống tính là sai.
    """
    pairs = [((cues[i].speaker or "").strip(), g) for i, g in gold.items() if 0 <= i < len(cues)]
    n = len(pairs)
    if n == 0:
        return {"n": 0, "correct": 0, "accuracy": None, "mapping": {}, "gold_speakers": 0, "pred_speakers": 0}

    preds = sorted({p for p, _ in pairs if p})
    golds = sorted({g for _, g in pairs})
    confusion: dict[tuple[str, str], int] = {}
    for p, g in pairs:
        confusion[(p, g)] = confusion.get((p, g), 0) + 1

    def score(mapping: dict[str, str]) -> int:
        return sum(cnt for (p, g), cnt in confusion.items() if mapping.get(p) == g)

    best: dict[str, str] = {}
    best_score = -1
    if len(preds) <= 8 and len(golds) <= 8:
        # mỗi nhãn máy ghép với tối đa một nhãn người, và ngược lại
        slots = golds + [None] * max(0, len(preds) - len(golds))
        for perm in itertools.permutations(slots, len(preds)):
            mapping = {p: g for p, g in zip(preds, perm) if g is not None}
            s = score(mapping)
            if s > best_score:
                best, best_score = mapping, s
    else:
        used_g: set[str] = set()
        for (p, g), _ in sorted(confusion.items(), key=lambda kv: -kv[1]):
            if p and p not in best and g not in used_g:
                best[p] = g
                used_g.add(g)
        best_score = score(best)

    return {
        "n": n,
        "correct": best_score,
        "accuracy": round(best_score / n, 4),
        "mapping": best,
        "gold_speakers": len(golds),
        "pred_speakers": len(preds),
    }


# ----------------------------------------------------------- chất lượng dịch


def bleu(hypotheses: list[str], references: list[str]) -> float | None:
    """BLEU bằng sacreBLEU. Trả None nếu chưa cài — chỉ số này là tuỳ chọn."""
    if not hypotheses or len(hypotheses) != len(references):
        return None
    try:
        import sacrebleu
    except ImportError:
        return None
    return round(float(sacrebleu.corpus_bleu(hypotheses, [references]).score), 2)


# ------------------------------------------------------- ghi & gom kết quả


def build_record(
    *,
    job_id: str,
    cfg: dict,
    dub_stats: dict | None = None,
    duration_s: float = 0.0,
    elapsed_s: float | None = None,
    speaker: dict | None = None,
    extra: dict | None = None,
) -> dict:
    """Một bản ghi kết quả cho một lần chạy — thứ được ghi vào `eval.json`."""
    rec = {
        "job": job_id,
        "config": config_of(cfg),
        "engine": cfg.get("engine", ""),
        "diarize": bool(cfg.get("diarize")),
        "source_lang": cfg.get("source_lang") or "",
        "duration_s": round(float(duration_s or 0.0), 2),
        "rtf": realtime_factor(elapsed_s, duration_s) if elapsed_s is not None else None,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if dub_stats:
        rec.update(isochrony_metrics(dub_stats))
    if speaker:
        rec["speaker_accuracy"] = speaker.get("accuracy")
        rec["speaker_n"] = speaker.get("n")
    if extra:
        rec.update(extra)
    return rec


def write_record(path: Path, record: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, indent=1))
    return path


def collect(job_dir: Path) -> list[dict]:
    """Gom mọi `eval.json` trong thư mục job — mỗi lần xuất là một bản ghi."""
    out: list[dict] = []
    if not job_dir.is_dir():
        return out
    for path in sorted(job_dir.glob("*/eval.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out.append(data)
    return out


def _mean(values: list[float]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(sum(vals) / len(vals), 4) if vals else None


def aggregate(records: list[dict]) -> list[dict]:
    """Gom theo cấu hình: trung bình từng chỉ số, kèm số lần chạy.

    Trả về theo thứ tự C0…C4 rồi tới cấu hình lạ (nếu có), để bảng lúc nào cũng
    đọc từ đường cơ sở tới hệ thống đầy đủ.
    """
    by: dict[str, list[dict]] = {}
    for r in records:
        by.setdefault(str(r.get("config") or "?"), []).append(r)
    order = [c for c in CONFIGS if c in by] + sorted(c for c in by if c not in CONFIGS)
    rows: list[dict] = []
    for name in order:
        group = by[name]
        row = {"config": name, "label": CONFIGS.get(name, {}).get("label", ""), "runs": len(group)}
        for field in (*ISOCHRONY_FIELDS, "rtf", "speaker_accuracy", "bleu", "comet"):
            row[field] = _mean([g.get(field) for g in group])
        rows.append(row)
    return rows


_COLUMNS = [
    ("config", "Cấu hình"),
    ("runs", "Số lần chạy"),
    ("compress_ratio", "Tỉ lệ câu phải nén"),
    ("max_factor", "Hệ số nén lớn nhất"),
    ("overflow_s", "Tổng thời gian tràn (s)"),
    ("bleu", "BLEU"),
    ("comet", "COMET"),
    ("speaker_accuracy", "Độ chính xác nhân vật"),
    ("rtf", "Hệ số thời gian thực"),
]


def _fmt(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    return str(value)


def to_markdown(rows: list[dict]) -> str:
    """Bảng Markdown dán thẳng vào báo cáo — đúng cột của Bảng 5.2."""
    head = "| " + " | ".join(title for _, title in _COLUMNS) + " |"
    sep = "|" + "|".join("---" for _ in _COLUMNS) + "|"
    body = ["| " + " | ".join(_fmt(r.get(k)) for k, _ in _COLUMNS) + " |" for r in rows]
    return "\n".join([head, sep, *body])


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([title for _, title in _COLUMNS])
    for r in rows:
        writer.writerow([_fmt(r.get(k)) for k, _ in _COLUMNS])
    return buf.getvalue()

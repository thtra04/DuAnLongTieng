"""HP-3 — dự đoán thời lượng đọc của một câu tiếng Việt.

Trả lời câu hỏi "câu này TTS sẽ đọc hết trong bao nhiêu giây?" mà không phải
gọi TTS. Đây là mắt xích để dịch máy biết ngân sách thời gian của từng câu, và
là thứ thay cho phép đếm từ thô sơ (`translate._length_units`) hiện nay.

Theo đúng lộ trình trong đề cương: khởi đầu bằng **hồi quy tuyến tính trên đặc
trưng thủ công** (số âm tiết, dấu câu, giọng, phong cách) làm mốc; chưa đạt thì
mới nâng lên PhoBERT gắn đầu hồi quy. Mô hình chỉ phụ thuộc tiếng Việt — phía
ngôn ngữ đích — nên dùng chung cho mọi ngôn ngữ nguồn.

Dữ liệu huấn luyện tự sinh bằng `scripts/gen_duration_data.py`: chạy TTS trên
hàng chục nghìn câu và đo trực tiếp độ dài sóng âm, không cần gán nhãn tay.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

from ..config import MODEL_DIR

MODEL_PATH = MODEL_DIR / "duration_vi.json"

# Tiếng Việt viết rời từng âm tiết, nên số token cách nhau bằng khoảng trắng
# chính là số âm tiết — đặc trưng mạnh nhất. Chữ Hán/Kana thì mỗi ký tự ~ một âm.
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿가-힯]")
_WORD = re.compile(r"[0-9A-Za-zÀ-ỹ]+")
_DIGITS = re.compile(r"\d+")

# Tốc độ đọc điển hình của giọng tổng hợp tiếng Việt, dùng cho ước lượng thô khi
# chưa có mô hình. Đo tay trên VieNeu-TTS: ~4,3 âm tiết/giây cộng ~0,3 giây đệm.
HEURISTIC_SYL_PER_S = 4.3
HEURISTIC_PAD_S = 0.3

FEATURE_NAMES = (
    "bias", "syllables", "chars", "commas", "stops", "questions", "exclaims",
    "digit_groups", "long_words", "cjk_chars",
)


def syllables(text: str) -> int:
    """Số âm tiết. Chữ CJK đếm theo ký tự; còn lại đếm theo cụm chữ/số."""
    text = text or ""
    cjk = len(_CJK.findall(text))
    latin = len(_WORD.findall(_CJK.sub(" ", text)))
    return cjk + latin


def features(text: str) -> list[float]:
    """Vector đặc trưng thủ công cho một câu. Phần tử đầu là hệ số chặn."""
    text = (text or "").strip()
    words = _WORD.findall(_CJK.sub(" ", text))
    return [
        1.0,
        float(syllables(text)),
        float(len(text)),
        float(text.count(",") + text.count(";")),
        float(text.count(".") + text.count("…")),
        float(text.count("?")),
        float(text.count("!")),
        float(len(_DIGITS.findall(text))),
        float(sum(1 for w in words if len(w) >= 7)),  # từ mượn / tên riêng dài
        float(len(_CJK.findall(text))),
    ]


def heuristic_seconds(text: str) -> float:
    """Ước lượng thô khi chưa có mô hình — mốc để đo mô hình cải thiện bao nhiêu."""
    n = syllables(text)
    return 0.0 if n == 0 else n / HEURISTIC_SYL_PER_S + HEURISTIC_PAD_S


class DurationModel:
    """Hồi quy tuyến tính (ridge) từ đặc trưng thủ công sang số giây.

    Kèm **hệ số tốc độ theo giọng** (`meta["voice_factors"]`): mỗi giọng TTS đọc
    nhanh chậm khác nhau tới ~15 %. Đo trên 3.674 câu, 5 phần kiểm tra chéo: không
    biết giọng MAE 246 ms, nhân hệ số giọng 173 ms (thử mô hình phi tuyến cùng đặc
    trưng thì không hơn: 252 ms — chỗ nghẽn là giọng, không phải dạng mô hình).
    Giọng chưa có hệ số (giọng nhân bản, giọng mới) thì hệ số 1.
    """

    def __init__(self, weights: list[float] | None = None, meta: dict | None = None):
        self.weights = list(weights) if weights else []
        self.meta = dict(meta or {})

    # ----------------------------------------------------------- huấn luyện
    @classmethod
    def fit(
        cls, texts: list[str], seconds: list[float], ridge: float = 1e-2,
        voices: list[str] | None = None,
    ) -> "DurationModel":
        """Bình phương tối thiểu có điều hoà. Cần numpy; dữ liệu nhỏ vẫn chạy được.

        `voices` (giọng đọc từng mẫu) thì học thêm hệ số tốc độ của mỗi giọng: trung
        vị của tỉ lệ số giây thật / số giây dự đoán chung, trên các mẫu của giọng đó.
        """
        if len(texts) != len(seconds) or not texts:
            raise ValueError("Cần cùng số câu và số giây, và ít nhất một mẫu.")
        import numpy as np

        X = np.array([features(t) for t in texts], dtype=np.float64)
        y = np.array(seconds, dtype=np.float64)
        k = X.shape[1]
        reg = ridge * np.eye(k)
        reg[0, 0] = 0.0  # không điều hoà hệ số chặn
        w = np.linalg.solve(X.T @ X + reg, X.T @ y)
        model = cls(w.tolist(), {"n": len(texts), "ridge": ridge, "features": list(FEATURE_NAMES)})
        if voices:
            if len(voices) != len(texts):
                raise ValueError("Cần đúng một giọng cho mỗi câu.")
            base = model.predict_many(texts)
            ratios: dict[str, list[float]] = {}
            for v, s, p in zip(voices, seconds, base):
                if v and p > 0:
                    ratios.setdefault(str(v), []).append(float(s) / p)
            model.meta["voice_factors"] = {
                v: round(float(np.median(r)), 4) for v, r in ratios.items() if len(r) >= 20
            }
        model.meta["train_mae"] = model.mae(texts, seconds, voices)
        return model

    def voice_factor(self, voice: str = "") -> float:
        return float((self.meta.get("voice_factors") or {}).get(str(voice or ""), 1.0))

    # ------------------------------------------------------------ dự đoán
    def predict(self, text: str, voice: str = "") -> float:
        """Số giây TTS sẽ đọc `text`. Biết `voice` thì chính xác hơn (hệ số tốc độ giọng)."""
        if not self.weights:
            return heuristic_seconds(text)
        x = features(text)
        value = sum(w * f for w, f in zip(self.weights, x))
        # Câu rỗng thì 0 giây; câu có chữ thì ít nhất cũng phải mất một tí
        if syllables(text) == 0:
            return 0.0
        return max(0.15, float(value)) * self.voice_factor(voice)

    def predict_many(self, texts: list[str], voices: list[str] | None = None) -> list[float]:
        voices = voices or [""] * len(texts)
        return [self.predict(t, v) for t, v in zip(texts, voices)]

    def mae(self, texts: list[str], seconds: list[float], voices: list[str] | None = None) -> float:
        if not texts:
            return 0.0
        pred = self.predict_many(texts, voices)
        return sum(abs(p - float(s)) for p, s in zip(pred, seconds)) / len(texts)

    # ------------------------------------------------------------ lưu/nạp
    def save(self, path: Path | str = MODEL_PATH) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"weights": self.weights, "meta": self.meta, "features": list(FEATURE_NAMES)}
        with path.open("w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False, indent=1))
        return path

    @classmethod
    def load(cls, path: Path | str = MODEL_PATH) -> "DurationModel":
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        if list(data.get("features") or []) != list(FEATURE_NAMES):
            raise ValueError("Mô hình được huấn luyện với bộ đặc trưng khác — huấn luyện lại.")
        return cls(data.get("weights") or [], data.get("meta") or {})

    @property
    def trained(self) -> bool:
        return bool(self.weights)


_default: DurationModel | None = None


def default_model() -> DurationModel:
    """Mô hình dùng chung: nạp từ đĩa nếu đã huấn luyện, không thì ước lượng thô."""
    global _default
    if _default is None:
        try:
            _default = DurationModel.load(MODEL_PATH)
        except (OSError, ValueError):
            _default = DurationModel()
    return _default


def reset_default() -> None:
    global _default
    _default = None


# ---------------------------------------------------------- đánh giá mô hình


def evaluate(
    model: DurationModel, texts: list[str], seconds: list[float], voices: list[str] | None = None,
) -> dict:
    """MAE của mô hình và của ước lượng thô trên cùng tập — để báo cáo cải thiện."""
    n = len(texts)
    if n == 0:
        return {"n": 0, "mae_ms": None, "heuristic_mae_ms": None, "improvement": None}
    model_mae = model.mae(texts, seconds, voices)
    pred = model.predict_many(texts, voices)
    heur_mae = sum(abs(heuristic_seconds(t) - float(s)) for t, s in zip(texts, seconds)) / n
    return {
        "n": n,
        "mae_ms": round(model_mae * 1000, 1),
        "heuristic_mae_ms": round(heur_mae * 1000, 1),
        "improvement": round(1 - model_mae / heur_mae, 4) if heur_mae > 0 else None,
        "rmse_ms": round(
            math.sqrt(sum((p - float(s)) ** 2 for p, s in zip(pred, seconds)) / n) * 1000, 1
        ),
    }

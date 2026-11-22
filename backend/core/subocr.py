"""Đọc phụ đề nung sẵn trong hình (OCR) → dòng phụ đề có mốc giờ, thay cho bước nghe.

Phim tải về thường đã có phụ đề tiếng gốc (hoặc tiếng Anh) nung vào hình. Chữ đó do người làm
phim gõ nên đúng hơn hẳn chữ máy nghe được, nhất là khi nhân vật nói giọng địa phương, nói
nhanh, hay nhạc nền lớn: trên clip 《奥德赛》 (đo 22/11/2026) Whisper chỉ đúng 44–48 % số
câu với mọi cỡ model, trong khi bản dịch từ chữ trên hình đạt gấp hơn hai lần bản dịch từ chữ
nghe được.

Cách làm, ba bước:
  1. **Tìm dải phụ đề** (`find_band`): lấy khung hình rải đều cả phim, dùng lại bộ đánh dấu
     "nét chữ phụ đề" của `hardsub` rồi chọn dải hàng ngang hay có nét chữ **và** nét đổi khác
     giữa hai khung liền nhau (chữ đổi theo câu thoại; cảnh nền, logo thì đứng yên).
  2. **Chia câu** (`scan`): cho ffmpeg nhả riêng dải đó ở `FPS` khung/giây. Hai khung liền
     nhau có nét chữ trùng nhau thì thuộc cùng một câu; nét đổi là sang câu mới. Mốc giờ của
     câu là lúc chữ hiện ra và lúc chữ tắt.
  3. **Đọc chữ** (`Reader`): mỗi câu đọc một khung ở giữa bằng mô hình nhận dạng dòng chữ
     PP-OCRv4 (ONNX, ~11 MB, chạy CPU bằng onnxruntime có sẵn của nhóm lồng tiếng — không cần
     thêm thư viện). Vì đã biết chữ nằm ở đâu nên không cần mô hình dò vùng chữ.

Giới hạn đã biết: mô hình đọc chữ Hán (giản thể, phồn thể thông dụng) và chữ Latin không dấu
— phụ đề Thái, Hàn, Nhật (kana), Việt có dấu chưa đọc được; phụ đề phải canh giữa, chữ sáng có
viền hoặc nền tối (kiểu phổ biến nhất).
"""

from __future__ import annotations

import subprocess
import unicodedata
from pathlib import Path
from typing import Callable

import numpy as np

from . import hardsub, media
from .subtitles import Cue

REPO, FILE = "SWHL/RapidOCR", "PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx"

FPS = 5.0                   # khung/giây khi chia câu: mốc giờ lệch tối đa ~0,1 s
VIEW_W = 960                # bề ngang quy đổi của cả khung: chữ phụ đề cao cỡ 25–40 px
SIDE = 0.12                 # nới dải sang hai bên: câu dài hơn những câu đã thấy lúc dò dải
BRIGHT, CONTRAST = 200, 120  # như hardsub: nét sáng, có viền tối sát bên
R = 3                       # bán kính cửa sổ ở bề ngang VIEW_W (hardsub dùng 2 px ở 480)
ZOOM = 2                    # ảnh đưa cho mô hình đọc lấy gấp đôi VIEW_W: chữ nhỏ (phụ đề Anh) vẫn rõ nét
MIN_PIX = 0.0015            # dải có ít nét hơn ngần này (tỉ lệ điểm) = không có chữ
SAME_IOU = 0.55             # nét hai khung liền nhau trùng hơn ngần này = cùng một câu
REC_H, REC_MAX_W = 48, 1600  # mô hình đọc dòng chữ cao 48 px
MIN_CONF = 0.72             # độ tin trung bình của các chữ; thấp hơn = nền nhiễu, không phải chữ
MIN_CHAR = 0.4              # từng chữ: dưới ngần này thì bỏ chữ đó
MIN_DUR = 0.3              # câu ngắn hơn ngần này (giây) = nháy hình, bỏ
JOIN_GAP = 0.45             # hai lần đọc giống nhau cách nhau ít hơn ngần này = một câu

BAND_ROW_HIT = 0.008        # hàng có >= 0,8 % điểm là nét chữ (chữ Latin mảnh thưa nét hơn chữ Hán)
BAND_FRAMES = 72            # số khung rải đều để tìm dải
BAND_MIN_SHARE = 0.10       # dải phải có chữ ở >= 10 % số khung…
BAND_MIN_CHANGE = 0.55      # …và trong các cặp khung liền nhau cùng có chữ, >= 55 % cặp đổi chữ


# ------------------------------------------------------------------ mô hình


def available() -> tuple[bool, str]:
    try:
        import onnxruntime  # noqa: F401
        import PIL  # noqa: F401
    except ImportError:
        return False, ("Thiếu thư viện đọc chữ (onnxruntime). Cài nhóm lồng tiếng: "
                       "uv sync --extra tts")
    return True, ""


def model_file(on_log: Callable[[str], None] | None = None) -> Path:
    """Đường dẫn mô hình trong data/models; lần đầu thì tải (~11 MB) từ Hugging Face."""
    from huggingface_hub import hf_hub_download

    from ..config import MODEL_DIR

    try:
        return Path(hf_hub_download(REPO, FILE, cache_dir=str(MODEL_DIR), local_files_only=True))
    except Exception:  # noqa: BLE001 — chưa có trong máy
        if on_log:
            on_log("Tải mô hình đọc chữ phụ đề (~11 MB, một lần)…")
        return Path(hf_hub_download(REPO, FILE, cache_dir=str(MODEL_DIR)))


class Reader:
    """Mô hình đọc MỘT dòng chữ đã cắt sát (CTC)."""

    def __init__(self, path: str | Path | None = None, on_log=None):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(str(path or model_file(on_log)), opts,
                                            providers=["CPUExecutionProvider"])
        self.input = self.session.get_inputs()[0].name
        chars = self.session.get_modelmeta().custom_metadata_map["character"].splitlines()
        self.chars = [""] + chars + [" "]          # 0 = ô trống của CTC, cuối = dấu cách

    @staticmethod
    def _prep(img: np.ndarray) -> np.ndarray:
        from PIL import Image

        h, w = img.shape[:2]
        nw = int(min(REC_MAX_W, max(REC_H, round(w * REC_H / max(1, h)))))
        im = Image.fromarray(img).resize((nw, REC_H), Image.BILINEAR)
        a = np.asarray(im, dtype=np.float32)[:, :, ::-1]       # mô hình học trên ảnh BGR
        return ((a / 255.0 - 0.5) / 0.5).transpose(2, 0, 1)

    def read(self, images: list[np.ndarray], batch: int = 12) -> list[tuple[str, float]]:
        """[(chữ, độ tin 0–1)] cho từng ảnh RGB (cao × rộng × 3)."""
        out: list[tuple[str, float]] = [("", 0.0)] * len(images)
        prepped = [(i, self._prep(im)) for i, im in enumerate(images) if im.size]
        prepped.sort(key=lambda p: p[1].shape[2])               # gom ảnh rộng gần nhau
        for s in range(0, len(prepped), batch):
            chunk = prepped[s:s + batch]
            wmax = max(a.shape[2] for _, a in chunk)
            x = np.zeros((len(chunk), 3, REC_H, wmax), np.float32)
            for k, (_, a) in enumerate(chunk):
                x[k, :, :, :a.shape[2]] = a
            prob = self.session.run(None, {self.input: x})[0]   # (ảnh, bước, lớp)
            ids, top = prob.argmax(axis=2), prob.max(axis=2)
            for k, (i, a) in enumerate(chunk):
                steps = max(1, int(np.ceil(prob.shape[1] * a.shape[2] / wmax)))  # bỏ phần đệm
                text, conf, prev = [], [], 0
                for t in range(steps):
                    c = int(ids[k, t])
                    # chữ đoán non tay (< MIN_CHAR) thường là mép nền lọt vào khung cắt, không phải chữ
                    if c and c != prev and top[k, t] >= MIN_CHAR:
                        text.append(self.chars[c]); conf.append(float(top[k, t]))
                    prev = c
                out[i] = ("".join(text).strip(), float(np.mean(conf)) if conf else 0.0)
        return out


# ------------------------------------------------------------------ nét chữ


def _slide(a: np.ndarray, r: int, op, fill) -> np.ndarray:
    """`op` trên cửa sổ vuông (2r+1)²; min/max/or/and tách được nên làm ngang rồi dọc."""
    out = a
    for axis in (0, 1):
        pad = [(0, 0), (0, 0)]
        pad[axis] = (r, r)
        p = np.pad(out, pad, mode="constant", constant_values=fill) if fill is not None \
            else np.pad(out, pad, mode="edge")
        n = out.shape[axis]
        acc = p.take(range(0, n), axis=axis).copy()
        for d in range(1, 2 * r + 1):
            op(acc, p.take(range(d, d + n), axis=axis), out=acc)
        out = acc
    return out


def stroke_mask(gray: np.ndarray) -> np.ndarray:
    """Điểm giống nét chữ phụ đề ở bề ngang VIEW_W: sáng, có viền tối sát bên, nét mảnh."""
    g = gray.astype(np.int16)
    bright = g >= BRIGHT
    lo = _slide(g, R, np.minimum, None)
    thick = _slide(_slide(bright, R, np.logical_and, False), R, np.logical_or, False)
    return bright & (g - lo >= CONTRAST) & ~thick


def _spans(on: np.ndarray, gap: int) -> list[tuple[int, int]]:
    """Các đoạn liền của mảng bool, nối những đoạn cách nhau <= gap."""
    idx = np.flatnonzero(on)
    if not idx.size:
        return []
    cut = np.flatnonzero(np.diff(idx) > gap + 1)
    starts = np.r_[idx[0], idx[cut + 1]]
    ends = np.r_[idx[cut], idx[-1]]
    return list(zip(starts.tolist(), ends.tolist()))


def text_lines(mask: np.ndarray, center: float) -> list[tuple[int, int, int, int]]:
    """Khung bao (y0, y1, x0, x1) của từng dòng chữ canh giữa trong dải; [] nếu không có.

    Phụ đề canh giữa nên chỉ lấy cụm nét chứa (hoặc sát) cột giữa khung; vật sáng có viền ở
    hai bên (áo giáp, mây hoạt hình) nằm cách xa hơn một quãng trống thì bị bỏ ra.
    """
    h, w = mask.shape
    cols = mask.sum(axis=0) > 0
    spans = _spans(cols, gap=max(12, int(0.9 * h)))
    if not spans:
        return []
    cx = int(center * w)
    spans.sort(key=lambda s: (0 if s[0] - h <= cx <= s[1] + h else 1,
                              -int(mask[:, s[0]:s[1] + 1].sum())))
    x0, x1 = spans[0]
    if not (x0 - h <= cx <= x1 + h):
        return []
    rows = mask[:, x0:x1 + 1].sum(axis=1)
    lines = [(a, b) for a, b in _spans(rows >= 2, gap=2) if b - a + 1 >= max(8, 0.18 * h)]
    out = []
    for a, b in lines:
        cc = np.flatnonzero(mask[a:b + 1, x0:x1 + 1].sum(axis=0) > 0)
        if cc.size:
            out.append((a, b, x0 + int(cc[0]), x0 + int(cc[-1])))
    return out


def _crop(rgb: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    y0, y1, x0, x1 = box
    py, px = max(3, (y1 - y0) // 6), max(6, (y1 - y0) // 3)
    return rgb[max(0, y0 - py):y1 + 1 + py, max(0, x0 - px):x1 + 1 + px]


# ------------------------------------------------------------------ tìm dải


def find_band(video: str | Path, info: dict | None = None, frames: int = BAND_FRAMES) -> dict:
    """Dò dải phụ đề khi chưa có mốc lời thoại: lấy khung rải đều cả phim.

    Khác `hardsub.find_band` (lấy khung đúng giữa từng câu thoại nên khung nào cũng có chữ):
    ở đây nhiều khung rơi vào lúc không ai nói, nên chỉ xét các cặp khung liền nhau mà hàng
    đó CÙNG có chữ — phụ đề thì phần lớn các cặp ấy đổi chữ, logo / cảnh nền thì không.
    """
    info = info or media.probe(video)
    if not info.get("width"):
        return {"found": False, "reason": "File không có hình."}
    size = (VIEW_W, max(2, int(round(info["height"] * VIEW_W / info["width"] / 2)) * 2))
    dur = float(info.get("duration") or 0.0)
    if dur <= 2:
        return {"found": False, "reason": "Video quá ngắn."}
    n = int(min(frames, max(12, dur / 1.5)))
    times = [dur * (0.04 + 0.92 * (i + 0.5) / n) for i in range(n)]
    grabbed = [f for f in (hardsub.grab_frame(video, t, size) for t in times) if f is not None]
    if len(grabbed) < 8:
        return {"found": False, "reason": "Không đọc được khung hình."}
    return band_from_frames(grabbed)


def band_from_frames(frames: list[np.ndarray]) -> dict:
    h, w = frames[0].shape
    masks = [stroke_mask(f) for f in frames]
    rows = np.stack([m.mean(axis=1) for m in masks])
    base = np.median(rows, axis=1, keepdims=True) + 0.002
    dense = (rows >= BAND_ROW_HIT) & (rows / base >= hardsub.ROW_REL)
    both = np.zeros(h); changed = np.zeros(h)
    for a in range(len(masks) - 1):
        inter = (masks[a] & _slide(masks[a + 1], 2, np.logical_or, False)).sum(axis=1)
        union = (masks[a] | masks[a + 1]).sum(axis=1)
        pair = dense[a] & dense[a + 1]
        both += pair
        changed += pair & (inter / np.maximum(union, 1) < hardsub.SAME_IOU)
    share = dense.mean(axis=0)
    ratio = changed / np.maximum(both, 1)
    # hàng "là phụ đề": hay có chữ, và khi có chữ ở hai khung liền nhau thì chữ thường đã đổi
    score = np.where((share >= BAND_MIN_SHARE) & (both >= 3), ratio, 0.0) * np.minimum(1.0, share / 0.25)
    score = np.convolve(score, np.ones(3) / 3, mode="same")
    best = float(score.max())
    if best < BAND_MIN_CHANGE * 0.6:
        return {"found": False, "score": round(best, 3), "frames": len(frames),
                "reason": "Không thấy phụ đề nung sẵn trong hình."}
    on = score >= best * 0.4
    peak = int(score.argmax())
    y0 = y1 = peak
    slack = max(2, int(0.02 * h))
    while y0 > 0 and (on[y0 - 1] or on[max(0, y0 - 1 - slack):y0 - 1].any()):
        y0 -= 1
    while y1 < h - 1 and (on[y1 + 1] or on[y1 + 2:min(h, y1 + 2 + slack)].any()):
        y1 += 1
    while not on[y0]:
        y0 += 1
    while not on[y1]:
        y1 -= 1
    band_h = (y1 - y0 + 1) / h
    if not (hardsub.MIN_BAND <= band_h <= hardsub.MAX_BAND):
        return {"found": False, "score": round(best, 3), "frames": len(frames),
                "reason": f"Dải chữ tìm được cao {band_h:.0%} khung — không giống phụ đề."}
    use = [m for m, d in zip(masks, dense) if d[y0:y1 + 1].any()]
    cols = np.stack([m[y0:y1 + 1].mean(axis=0) for m in use]).mean(axis=0)
    mass = np.cumsum(cols)
    x0 = int(np.searchsorted(mass, 0.02 * mass[-1])); x1 = int(np.searchsorted(mass, 0.98 * mass[-1]))
    center = float(np.searchsorted(mass, 0.5 * mass[-1])) / w
    if abs(center - 0.5) > hardsub.CENTER_TOL:
        return {"found": False, "score": round(best, 3), "frames": len(frames),
                "reason": "Dải chữ không canh giữa — có lẽ không phải phụ đề."}
    pad_y = max(0.012, 0.3 * band_h)
    half = max(0.15, abs(x0 / w - 0.5), abs((x1 + 1) / w - 0.5)) + 0.05
    return {"found": True, "score": round(best, 3), "frames": len(frames),
            "y0": round(max(0.0, y0 / h - pad_y), 4), "y1": round(min(1.0, (y1 + 1) / h + pad_y), 4),
            "x0": round(max(0.0, 0.5 - half), 4), "x1": round(min(1.0, 0.5 + half), 4)}


# ------------------------------------------------------------------ chia câu


def _geometry(band: dict, info: dict) -> tuple[str, int, int, float]:
    """(bộ lọc ffmpeg, rộng, cao, vị trí cột giữa khung trong dải 0–1)."""
    x0 = max(0.0, float(band["x0"]) - SIDE); x1 = min(1.0, float(band["x1"]) + SIDE)
    y0, y1 = float(band["y0"]), float(band["y1"])
    ratio = float(info["height"]) / float(info["width"])
    cw = max(16, int(round(VIEW_W * (x1 - x0) / 2)) * 2) * ZOOM
    ch = max(8, int(round(VIEW_W * ratio * (y1 - y0) / 2)) * 2) * ZOOM
    vf = (f"fps={FPS:g},crop=iw*{x1 - x0:.5f}:ih*{y1 - y0:.5f}:iw*{x0:.5f}:ih*{y0:.5f},"
          f"scale={cw}:{ch}:flags=bicubic")
    return vf, cw, ch, (0.5 - x0) / (x1 - x0)


def scan(video: str | Path, band: dict, info: dict, on_progress=None, cancel=None,
         start: float = 0.0, duration: float | None = None) -> list[dict]:
    """Chia dải phụ đề thành các "lượt chữ": [{start, end, image (RGB), lines}]."""
    vf, cw, ch, center = _geometry(band, info)
    cmd = [media.ffmpeg_exe(), "-hide_banner", "-loglevel", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video)]
    if duration:
        cmd += ["-t", f"{duration:.3f}"]
    cmd += ["-an", "-sn", "-vf", vf, "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    size = cw * ch * 3
    min_pix = max(40, int(MIN_PIX * cw * ch / ZOOM ** 2))
    total = max(1.0, float(duration or (info.get("duration") or 0.0) - start) * FPS)
    runs: list[dict] = []
    cur: dict | None = None
    prev_mask = None
    i = 0

    def close():
        nonlocal cur
        if cur:
            frames = cur.pop("frames")
            cur["image"], cur["lines"] = frames[len(frames) // 2]
            cur["end"] = start + (cur.pop("last") + 0.5) / FPS
            runs.append(cur)
        cur = None

    try:
        while True:
            raw = proc.stdout.read(size)
            if len(raw) < size:
                break
            rgb = np.frombuffer(raw, np.uint8).reshape(ch, cw, 3)
            # nét chữ dò ở bề ngang VIEW_W; kênh sáng nhất: chữ vàng cũng "sáng"
            mask = stroke_mask(rgb[::ZOOM, ::ZOOM].max(axis=2))
            lines = text_lines(mask, center) if mask.sum() >= min_pix else []
            if lines:
                keep = np.zeros_like(mask)
                for y0, y1, x0, x1 in lines:
                    keep[y0:y1 + 1, x0:x1 + 1] = True
                mask &= keep
            if not lines or mask.sum() < min_pix:
                close(); prev_mask = None
            else:
                same = False
                if cur is not None and prev_mask is not None:
                    union = (mask | prev_mask).sum()
                    same = union > 0 and (mask & prev_mask).sum() / union > SAME_IOU
                if not same:
                    close()
                    cur = {"start": start + max(0.0, i - 0.5) / FPS, "frames": []}
                cur["frames"].append((rgb.copy(), [tuple(v * ZOOM for v in b) for b in lines]))
                if len(cur["frames"]) > 64:          # chữ đứng rất lâu: giữ thưa lại cho nhẹ máy
                    cur["frames"] = cur["frames"][::2]
                cur["last"] = i
                prev_mask = mask
            i += 1
            if i % 50 == 0:
                if cancel:
                    cancel()
                if on_progress:
                    on_progress(min(0.95, i / total))
        close()
    finally:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()
    return runs


# ------------------------------------------------------------------ thành câu


def _similar(a: str, b: str) -> bool:
    """Hai lần đọc cùng một câu (lệch vài chữ do nền động)."""
    if a == b:
        return True
    if not a or not b or abs(len(a) - len(b)) > max(2, 0.25 * max(len(a), len(b))):
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        row = [i]
        for j, cb in enumerate(b, 1):
            row.append(min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = row
    return prev[-1] <= max(1, 0.2 * max(len(a), len(b)))


def _is_han(ch: str) -> bool:
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿"


def tidy(text: str) -> str:
    text = unicodedata.normalize("NFC", text).strip()
    return " ".join(text.split())


def script_lang(texts: list[str]) -> str | None:
    """Ngôn ngữ của chữ đọc được: 'zh' nếu phần lớn là chữ Hán, 'en' nếu là chữ Latin."""
    han = sum(_is_han(c) for t in texts for c in t)
    latin = sum(c.isascii() and c.isalpha() for t in texts for c in t)
    if han + latin == 0:
        return None
    return "zh" if han * 4 >= latin else "en"     # một chữ Hán ≈ một từ, một từ Latin ≈ 4–5 chữ cái


def to_cues(runs: list[dict], reader: Reader, duration: float = 0.0) -> tuple[list[Cue], dict]:
    crops, owner = [], []
    for k, r in enumerate(runs):
        for box in r["lines"]:
            crops.append(_crop(r["image"], box)); owner.append(k)
    read = reader.read(crops)
    items = []
    for k, r in enumerate(runs):
        parts = [read[j] for j in range(len(crops)) if owner[j] == k]
        # chấm từng dòng: vệt sáng phía trên/dưới chữ thành một "dòng" đọc ra rác, độ tin thấp
        parts = [(tidy(t), c) for t, c in parts if tidy(t) and c >= MIN_CONF]
        if not parts:
            continue
        text = " ".join(t for t, _ in parts)        # phụ đề hai dòng: nối bằng dấu cách
        conf = float(np.mean([c for _, c in parts]))
        items.append({"start": r["start"], "end": r["end"], "text": text, "conf": conf})
    stats = {"runs": len(runs), "read": len(items)}

    # một câu bị cắt vụn vì nền động / hiệu ứng chữ: nối các lần đọc giống nhau liền kề
    merged: list[dict] = []
    for it in items:
        last = merged[-1] if merged else None
        if last and it["start"] - last["end"] <= JOIN_GAP and _similar(last["text"], it["text"]):
            if it["conf"] * (it["end"] - it["start"]) > last["conf"] * (last["end"] - last["start"]):
                last["text"], last["conf"] = it["text"], it["conf"]
            last["end"] = it["end"]
        else:
            merged.append(dict(it))
    cues = []
    for m in merged:
        if m["end"] - m["start"] < MIN_DUR:
            continue
        end = min(m["end"], duration) if duration else m["end"]
        if end > m["start"]:
            cues.append(Cue(round(m["start"], 3), round(end, 3), m["text"]))
    for a, b in zip(cues, cues[1:]):
        a.end = min(a.end, b.start)
    stats.update(cues=len(cues))
    return cues, stats


def read_subtitles(video: str | Path, info: dict | None = None, band: dict | None = None,
                   on_progress=None, on_log=None, cancel=None) -> dict:
    """Trả về {cues, band, language, stats}. Không thấy phụ đề thì cues rỗng, band['found'] False."""
    info = info or media.probe(video)
    band = band if band and band.get("found") else find_band(video, info)
    if not band.get("found"):
        return {"cues": [], "band": band, "language": None, "stats": {}}
    if on_log:
        on_log(f"Dải phụ đề trong hình: {band['y0'] * 100:.0f}–{band['y1'] * 100:.0f} % chiều cao "
               f"(điểm {band.get('score', 0):.2f}). Đang đọc chữ từng câu…")
    reader = Reader(on_log=on_log)
    runs = scan(video, band, info, on_progress=on_progress, cancel=cancel)
    cues, stats = to_cues(runs, reader, float(info.get("duration") or 0.0))
    if on_progress:
        on_progress(1.0)
    return {"cues": cues, "band": band, "language": script_lang([c.text for c in cues]), "stats": stats}

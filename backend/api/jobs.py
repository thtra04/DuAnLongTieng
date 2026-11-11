"""/api/analyze, /api/jobs — chạy phân tích / xuất trong nền và theo dõi tiến độ."""

from __future__ import annotations

import json
import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..config import JOB_DIR, UPLOAD_DIR
from ..core import diarize, pipeline, translate
from ..core.jobs import create_job, get_job, run_in_thread
from ..store import films, memory
from .deps import find_source_video, needs_video, rebuild_state, safe_id

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post("/analyze")
async def analyze(payload: dict) -> dict:
    cfg = dict(payload or {})
    source_type = cfg.get("source_type", "file")

    if source_type == "file":
        media_id = safe_id(cfg.get("media_id"))
        cfg["media_id"] = media_id
        folder = UPLOAD_DIR / media_id if media_id else None
        files = [p for p in folder.glob("*") if p.is_file()] if folder and folder.is_dir() else []
        if not files:
            raise HTTPException(400, "Chưa chọn video (media_id không hợp lệ).")
        cfg["video_path"] = str(files[0])
    elif source_type == "url":
        if not (cfg.get("url") or "").strip():
            raise HTTPException(400, "Thiếu link video.")
        raw_part = cfg.get("part")
        if raw_part in (None, "", 0):
            cfg["part"] = None
        else:
            try:
                cfg["part"] = max(1, int(raw_part))
            except (TypeError, ValueError):
                raise HTTPException(400, "Số phần cần tải không hợp lệ.") from None
        # Tên bộ & tổng số tập do trình duyệt gửi kèm — chỉ để gom nhóm về sau,
        # nên cứ cắt gọn thay vì báo lỗi nếu gửi sai kiểu.
        cfg["series_name"] = str(cfg.get("series_name") or "").strip()[:160]
        try:
            cfg["series_total"] = max(0, int(cfg.get("series_total") or 0))
        except (TypeError, ValueError):
            cfg["series_total"] = 0
    else:
        raise HTTPException(400, "Nguồn video không hợp lệ.")

    mode = cfg.get("sub_mode", "auto")
    if mode == "text" and not (cfg.get("script_text") or "").strip():
        raise HTTPException(400, "Chưa dán văn bản kịch bản.")
    if mode == "srt" and not (cfg.get("subtitle_text") or "").strip():
        raise HTTPException(400, "Chưa nạp file phụ đề .srt/.vtt.")
    if cfg.get("translate") and not cfg.get("target_lang"):
        raise HTTPException(400, "Chưa chọn ngôn ngữ đích.")

    if cfg.get("translate"):
        ok, why = translate.engine_available(cfg.get("engine", "google"))
        if not ok:
            raise HTTPException(400, why)

    # Kiểm tra nhận diện người nói TRƯỚC khi chạy: bước này nằm sau khâu nghe
    # lời thoại, để lỗi ở đó thì người dùng đã chờ mất cả chục phút.
    if cfg.get("diarize"):
        ok, why = diarize.available(cfg.get("hf_token", ""))
        if not ok:
            raise HTTPException(400, why)
        for key in ("num_speakers", "max_speakers"):
            raw = cfg.get(key)
            if raw in (None, "", 0):
                cfg[key] = None
                continue
            try:
                cfg[key] = max(1, min(20, int(raw)))
            except (TypeError, ValueError):
                raise HTTPException(400, f"Số nhân vật không hợp lệ ({key}).") from None

    # Đang làm cho một tập cụ thể của một bộ phim? Kiểm tra trước khi chạy, để
    # không phải nghe cả video xong mới phát hiện bộ/tập không tồn tại.
    film_id = (cfg.get("film_id") or "").strip()
    episode_no = None
    if film_id:
        try:
            episode_no = int(cfg.get("episode_no"))
        except (TypeError, ValueError):
            raise HTTPException(400, "Thiếu số tập cần làm.") from None
        target_film = next((f for f in films.all_films() if f["id"] == film_id), None)
        if not target_film:
            raise HTTPException(404, "Bộ phim này không còn nữa.")
        if episode_no not in {int(e.get("no") or 0) for e in target_film.get("episodes") or []}:
            raise HTTPException(404, f"Bộ phim này không có tập {episode_no}.")

    job = create_job("analyze", pipeline.analyze_steps(cfg))
    job.log("Bắt đầu xử lý.")

    def target(j):
        pipeline.run_analyze(j, cfg)
        if film_id and episode_no is not None:
            try:
                films.bind(film_id, episode_no, j.id)
                j.log(f"Đã gắn kết quả vào tập {episode_no}.")
            except films.FilmError as exc:
                # Phụ đề vẫn xong, chỉ là không gắn được vào bộ -> nói rõ,
                # đừng làm cả job thành lỗi.
                j.log(f"Không gắn được vào tập {episode_no}: {exc}")

    run_in_thread(job, target)
    return {"job_id": job.id}


@router.post("/jobs/{job_id}/render")
async def render(job_id: str, payload: dict) -> dict:
    cfg = dict(payload or {})
    job_id = safe_id(job_id)
    cfg["source_job"] = job_id  # để bước lồng tiếng ghi giọng đã dùng vào đúng dự án
    state_path = JOB_DIR / job_id / "state.json" if job_id else None

    if state_path and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        # File video có thể đã bị xoá dù state.json còn.
        # Phải kiểm chuỗi rỗng riêng: Path("") ra "." mà "." thì luôn tồn tại.
        saved = state.get("video_path") or ""
        if not (saved and Path(saved).is_file()):
            found = find_source_video(job_id, cfg.get("media_id"))
            if found:
                state["video_path"] = str(found)
            elif needs_video(cfg):
                raise HTTPException(
                    410,
                    "File video gốc không còn trên máy chủ nên không nung / gắn track / "
                    "lồng tiếng được. Bỏ chọn các mục đó thì vẫn xuất được SRT · VTT · TXT, "
                    "hoặc quay lại bước 1 chọn lại video.",
                )
            else:
                state["video_path"] = ""  # chỉ xuất file chữ, không cần video
    else:
        if not cfg.get("cues"):
            raise HTTPException(
                410,
                "Phiên làm việc đã hết hạn trên máy chủ. Hãy chạy lại từ bước 1.",
            )
        state = rebuild_state(job_id, cfg)
        state_path = JOB_DIR / (job_id or "phien-moi") / "state.json"

    # Cho phép người dùng sửa phụ đề trước khi xuất
    machine_cues = state.get("cues") or []
    if cfg.get("cues"):
        state["cues"] = cfg["cues"]
    if cfg.get("source_lang") and not state.get("source_lang"):
        state["source_lang"] = cfg["source_lang"]
    if cfg.get("target_lang") and not state.get("target_lang"):
        state["target_lang"] = cfg["target_lang"]

    state_path.parent.mkdir(parents=True, exist_ok=True)
    pipeline.write_utf8(state_path, json.dumps(state, ensure_ascii=False, indent=1))

    if not state.get("cues"):
        raise HTTPException(400, "Không có dòng phụ đề nào để xuất.")
    if not any(cfg.get("outputs", {}).values()):
        raise HTTPException(400, "Chưa chọn định dạng nào để xuất.")

    # Câu nào khác bản máy dịch tức là người dùng đã sửa tay -> ghi vào bộ nhớ dịch để
    # lần sau gặp lại câu đó (hoặc câu gần giống) thì dịch theo cách họ đã chọn. Đặt sau
    # mọi bước kiểm tra: yêu cầu bị từ chối thì không học gì.
    learned = 0
    if cfg.get("cues") and cfg.get("learn", True):
        try:
            learned = memory.learn_from_edit(
                machine_cues, cfg["cues"],
                source_lang=state.get("source_lang") or "",
                target_lang=state.get("target_lang") or "",
                job_id=job_id,
            )
        except Exception:  # học hỏng không được chặn việc xuất
            learned = 0

    job = create_job("render", pipeline.render_steps(cfg))
    job.result = {"source_job": job_id}
    job.log("Bắt đầu xuất file.")
    if learned:
        job.log(f"Bộ nhớ dịch: ghi nhớ {learned} câu bạn đã sửa tay để lần sau dịch theo.")
    # File xuất ra nằm ở thư mục của job render này, không nằm cùng job phân
    # tích. Ghi lại mối liên hệ để mục "Dự án đã làm" còn tìm thấy chúng sau
    # khi khởi động lại tool (danh sách job trong RAM thì mất).
    pipeline.write_utf8(
        job.dir / "render.json",
        json.dumps({"source_job": job_id}, ensure_ascii=False),
    )

    def target(j):
        j.result = {}
        pipeline.run_render(j, state, cfg)

    run_in_thread(job, target)
    return {"job_id": job.id}


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job không tồn tại.")
    return job.to_dict()


@router.post("/jobs/{job_id}/cancel")
def job_cancel(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job không tồn tại.")
    job.cancel.set()
    job.log("Nhận lệnh huỷ…")
    return {"ok": True}


@router.get("/jobs/{job_id}/files/{name}")
def job_file(job_id: str, name: str, download: int = 1):
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job không tồn tại.")
    safe = Path(name).name
    path = job.dir / safe
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "File không tồn tại.")
    mime = mimetypes.guess_type(safe)[0] or "application/octet-stream"
    return FileResponse(path, media_type=mime, filename=safe if download else None)

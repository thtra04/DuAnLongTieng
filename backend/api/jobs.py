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


@router.post("/jobs/{job_id}/retranslate")
async def retranslate(job_id: str, payload: dict) -> dict:
    """Dịch lại phụ đề của dự án `job_id` với engine / thuật ngữ / bối cảnh mới, không chạy lại nhận dạng."""
    from ..store import characters

    cfg = dict(payload or {})
    job_id = safe_id(job_id)
    state_path = JOB_DIR / job_id / "state.json" if job_id else None
    if not state_path or not state_path.exists():
        raise HTTPException(410, "Dự án không còn trên máy chủ. Hãy chạy lại từ bước 1.")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if not (cfg.get("target_lang") or state.get("target_lang")):
        raise HTTPException(400, "Chưa chọn ngôn ngữ đích.")
    ok, why = translate.engine_available(cfg.get("engine", "google"))
    if not ok:
        raise HTTPException(400, why)
    if cfg.get("cues") is not None and not isinstance(cfg["cues"], list):
        raise HTTPException(400, "Danh sách phụ đề không hợp lệ.")

    # Bảng vai (tên, giới, nhóm tuổi) để engine AI chọn xưng hô theo người nói
    cast: list[dict] = []
    try:
        cast = [{"id": c["label"], "name": c.get("name") or "", "gender": c.get("gender") or "",
                 "age": c.get("age") or ""} for c in characters.list_for(job_id)]
    except Exception:
        cast = []
    if not cast:
        cast = [s for s in state.get("speakers") or [] if isinstance(s, dict)]

    # Chưa dòng nào có vai và người dùng bật tách giọng nam / nữ -> nhận vai trong lượt này
    lines = cfg["cues"] if cfg.get("cues") is not None else (state.get("cues") or [])
    has_roles = any(isinstance(c, dict) and (c.get("speaker") or "").strip() for c in lines)
    cfg["resplit"] = bool(cfg.get("gender_split")) and not has_roles

    job = create_job("retranslate", pipeline.retranslate_steps(cfg))
    job.log("Bắt đầu dịch lại.")
    run_in_thread(job, lambda j: pipeline.run_retranslate(j, state, state_path, cfg, cast))
    return {"job_id": job.id}


@router.post("/reading-budget")
def reading_budget(payload: dict) -> dict:
    """Dự đoán thời lượng đọc của từng câu lồng tiếng so với khung giờ của nó.

    Dòng thời gian ở bước 4 gọi mỗi khi người dùng sửa chữ hoặc kéo mốc giờ, để tô đỏ
    câu đọc không kịp TRƯỚC khi xuất. Dùng đúng hàm `budget.assess` mà bước xuất dùng.
    """
    from ..core import budget
    from ..core.subtitles import Cue

    raw = (payload or {}).get("cues") or []
    if not isinstance(raw, list) or len(raw) > 20000:
        raise HTTPException(400, "Danh sách phụ đề không hợp lệ.")
    cues = [Cue.from_dict(c) for c in raw if isinstance(c, dict)]
    items = [
        {"cues": it["cues"], "start": cues[it["cues"][0]].start, "predicted": it["predicted"],
         "budget": it["budget"], "over": max(0.0, it["over"])}
        for it in budget.assess(cues)
    ]
    return {"items": items, "tolerance": budget.TOLERANCE}


@router.post("/fit-lines")
def fit_lines(payload: dict) -> dict:
    """Dịch gọn lại những dòng phụ đề đang dài hơn khung giờ (nút "Dịch gọn" ở bước 4).

    Engine AI dịch lại từ câu gốc với giới hạn âm tiết; NLLB có adapter đẳng thời dịch lại
    với token ngân sách; engine còn lại rút gọn bản dịch tiếng Việt bằng luật. Không ghi gì
    xuống đĩa — trả về các dòng đổi để trình duyệt áp vào bảng và hoàn tác được.
    """
    from ..core import budget
    from ..core.subtitles import Cue

    cfg = dict(payload or {})
    raw = cfg.get("cues") or []
    if not isinstance(raw, list) or len(raw) > 20000:
        raise HTTPException(400, "Danh sách phụ đề không hợp lệ.")
    indices = cfg.get("indices") or []
    if not isinstance(indices, list) or not all(isinstance(i, int) for i in indices):
        raise HTTPException(400, "Danh sách dòng cần dịch gọn không hợp lệ.")
    engine = cfg.get("engine") or "google"
    ok, why = translate.engine_available(engine)
    if not ok:
        raise HTTPException(400, why)
    target = cfg.get("target_lang") or "vi"
    logs: list[str] = []
    tightener = translate.make_tightener(
        engine, api_key=cfg.get("api_key") or "", model=cfg.get("ai_model") or "",
        base_url=cfg.get("ai_base_url") or "", target=target, on_log=logs.append,
        source=cfg.get("source_lang") or "", with_source=True,
    )
    if tightener is None:
        raise HTTPException(400, "Engine này không dịch gọn được với ngôn ngữ đích đang chọn — hãy chọn engine AI ở bước 2.")
    cues = [Cue.from_dict(c) for c in raw if isinstance(c, dict)]
    try:
        out = budget.fit_lines(cues, indices, tightener)
    except Exception as exc:
        raise HTTPException(502, f"Dịch gọn không thành: {exc}") from exc
    method = "ai" if engine in ("claude", "openai") else (
        "nllb" if engine == "nllb" and translate.lora_available() and translate.lora_applies(cfg.get("source_lang"), target)
        else "rules")
    return {**out, "method": method}


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

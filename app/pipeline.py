"""Luồng xử lý: nguồn video -> phụ đề -> dịch -> xuất file."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import align, asr, dubbing, media, subtitles, translate
from .jobs import Job, Step
from .subtitles import Cue

SAFE_NAME = re.compile(r"[^\w\-. ]+", re.UNICODE)


def safe_stem(name: str, fallback: str = "video") -> str:
    stem = SAFE_NAME.sub("", Path(name).stem).strip()
    return (stem or fallback)[:60]


def write_utf8(path: Path, content: str) -> Path:
    """Ghi UTF-8 với xuống dòng LF (Path.write_text sẽ đổi thành CRLF trên Windows)."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        fh.write(content)
    return path


# ------------------------------------------------------------ bước phân tích


def analyze_steps(cfg: dict) -> list[Step]:
    steps: list[Step] = []
    if cfg.get("source_type") == "url":
        part = cfg.get("part")
        label = f"Tải phần {part} từ link" if part else "Tải video từ link"
        steps.append(Step("download", label, weight=2.0))
    steps.append(Step("probe", "Đọc thông tin video", weight=0.2))

    mode = cfg.get("sub_mode", "auto")
    if mode == "srt":
        steps.append(Step("subs", "Nạp file phụ đề", weight=0.3))
    else:
        steps.append(Step("audio", "Tách âm thanh", weight=0.6))
        steps.append(Step("asr", "Nghe & nhận dạng lời thoại", weight=6.0))
        if mode == "text":
            steps.append(Step("align", "Canh văn bản của bạn theo lời nói", weight=0.8))

    if cfg.get("translate"):
        steps.append(Step("translate", "Dịch phụ đề", weight=3.0))
    steps.append(Step("write", "Tạo file phụ đề", weight=0.3))
    return steps


def run_analyze(job: Job, cfg: dict) -> None:
    workdir = job.dir
    video_path = Path(cfg["video_path"]) if cfg.get("video_path") else None

    # 1. Tải từ URL nếu cần
    if cfg.get("source_type") == "url":
        part = cfg.get("part")
        job.start_step("download", cfg.get("url", "")[:70])
        job.log(f"Đang tải: {cfg.get('url')}" + (f"  (phần {part})" if part else ""))
        video_path = media.download_url(
            cfg["url"],
            workdir / "source",
            on_progress=lambda p: job.set_step_progress("download", p),
            on_log=job.log,
            part=part,
        )
        job.finish_step("download", video_path.name)
    job.check_cancel()

    if not video_path or not video_path.exists():
        raise RuntimeError("Không tìm thấy file video nguồn.")

    # 2. Probe
    job.start_step("probe")
    info = media.probe(video_path)
    job.finish_step("probe", f"{info['width']}x{info['height']} · {_hms(info['duration'])}")
    job.log(
        f"Video: {info['width']}x{info['height']}, {_hms(info['duration'])}, "
        f"{'có tiếng' if info['has_audio'] else 'KHÔNG có tiếng'}"
    )

    duration = info.get("duration", 0.0)
    detected_lang = cfg.get("source_lang") or None
    cues: list[Cue] = []
    mode = cfg.get("sub_mode", "auto")
    coverage_note = ""
    asr_result: dict = {}

    # 3. Lấy phụ đề
    if mode == "srt":
        job.start_step("subs")
        cues = subtitles.parse_subtitle(cfg.get("subtitle_text", ""))
        if not cues:
            raise RuntimeError("File phụ đề rỗng hoặc sai định dạng (cần .srt/.vtt).")
        job.finish_step("subs", f"{len(cues)} dòng")
        job.log(f"Đã nạp {len(cues)} dòng phụ đề.")
    else:
        if not info.get("has_audio"):
            raise RuntimeError("Video không có âm thanh nên không thể nhận dạng lời thoại.")

        job.start_step("audio")
        wav = media.extract_audio(
            video_path, workdir / "audio.wav",
            on_progress=lambda p: job.set_step_progress("audio", p),
        )
        job.finish_step("audio")
        job.check_cancel()

        job.start_step("asr", "Đang khởi động model…")
        result = asr.transcribe(
            wav,
            language=cfg.get("source_lang") or None,
            model_size=cfg.get("asr_model", "medium"),
            device=cfg.get("device", "auto"),
            duration=duration,
            vad=bool(cfg.get("vad", False)),
            initial_prompt=cfg.get("prompt", ""),
            auto_fix=bool(cfg.get("auto_fix", True)),
            on_progress=lambda p: job.set_step_progress("asr", p),
            on_log=job.log,
        )
        detected_lang = result.get("language") or detected_lang
        cov = result.get("coverage", 0.0)
        job.finish_step(
            "asr",
            f"Ngôn ngữ: {detected_lang or '?'} · phủ {cov * 100:.0f}% · {result['device'].upper()}",
        )
        job.log(f"Nhận dạng xong. Ngôn ngữ phát hiện: {detected_lang}")
        asr_result = result
        coverage_note = _coverage_warning(job, result, duration)
        job.check_cancel()

        if mode == "text":
            job.start_step("align")
            cues = align.align_text(
                cfg.get("script_text", ""), result["words"], duration,
                max_chars=cfg.get("max_chars", 84),
            )
            job.finish_step("align", f"{len(cues)} dòng")
            job.log(f"Đã canh {len(cues)} dòng theo văn bản bạn cung cấp.")
        else:
            cues = subtitles.cues_from_words(
                result["words"],
                max_chars=cfg.get("max_chars", 84),
                max_dur=cfg.get("max_dur", 6.0),
            )
            job.log(f"Tạo {len(cues)} dòng phụ đề từ lời thoại.")

    if not cues:
        raise RuntimeError("Không tạo được dòng phụ đề nào.")
    job.check_cancel()

    # 4. Dịch
    target = cfg.get("target_lang") or ""
    if cfg.get("translate") and target:
        job.start_step("translate", f"{len(cues)} dòng")
        translate.translate_cues(
            cues,
            source=detected_lang,
            target=target,
            engine=cfg.get("engine", "google"),
            api_key=cfg.get("api_key", ""),
            model=cfg.get("ai_model", ""),
            base_url=cfg.get("ai_base_url", ""),
            context_note=cfg.get("context_note", ""),
            translation_mode=cfg.get("translation_mode", "natural"),
            glossary=cfg.get("glossary", ""),
            on_progress=lambda p: job.set_step_progress("translate", p),
            on_log=job.log,
        )
        job.finish_step("translate")
        job.log("Dịch xong.")

    # Nới cue hiện quá nhanh so với tốc độ đọc (áp dụng cả khi không dịch)
    align.retime_translation(cues)
    job.check_cancel()

    # 5. Ghi file
    job.start_step("write")
    state = {
        "video_path": str(video_path),
        "video_name": video_path.name,
        "info": info,
        "source_lang": detected_lang,
        "target_lang": target if cfg.get("translate") else "",
        "cues": [c.to_dict() for c in cues],
        "cfg": {k: v for k, v in cfg.items() if k not in ("api_key", "script_text", "subtitle_text")},
    }
    write_utf8(workdir / "state.json", json.dumps(state, ensure_ascii=False, indent=1))
    job.finish_step("write")

    job.result = {
        "video_name": video_path.name,
        "duration": duration,
        "width": info["width"],
        "height": info["height"],
        "source_lang": detected_lang,
        "target_lang": state["target_lang"],
        "cue_count": len(cues),
        "cues": state["cues"],
        "has_libass": media.has_libass(),
        "coverage": asr_result.get("coverage", 1.0 if cues else 0.0),
        "coverage_note": coverage_note,
        "gaps": [g for g in asr_result.get("gaps", []) if g[1] - g[0] >= 15][:8],
        "asr_notes": asr_result.get("notes", []),
    }


# --------------------------------------------------------------- bước xuất


def render_steps(cfg: dict) -> list[Step]:
    steps = [Step("files", "Ghi file phụ đề", weight=0.3)]
    out = cfg.get("outputs", {})
    if out.get("burn"):
        steps.append(Step("burn", "Nung phụ đề vào video", weight=10.0))
    if out.get("soft"):
        steps.append(Step("soft", "Gắn phụ đề dạng track", weight=1.5))
    if out.get("dub"):
        if (cfg.get("dub") or {}).get("voice") == dubbing.CLONE_VOICE:
            steps.append(Step("ref", "Cắt mẫu giọng gốc", weight=0.4))
        steps.append(Step("tts", "Đọc bản dịch thành tiếng", weight=12.0))
        steps.append(Step("dubmux", "Ghép tiếng vào video", weight=2.0))
    return steps


def _warn_too_many_lines(job, cues, mode, src_lang, tgt_lang, max_chars, max_lines) -> None:
    """Đếm cue phải xuống quá `max_lines` dòng để giữ đúng `max_chars`."""
    over = []
    for i, cue in enumerate(cues):
        body = subtitles._display(cue, mode, src_lang, tgt_lang)
        rows = 0
        for para in body.split("\n"):
            if para.strip():
                rows += len(subtitles.wrap_text(para, max_chars, max_lines).split("\n"))
        if rows > max_lines:
            over.append((i + 1, rows))
    if not over:
        return
    worst = sorted(over, key=lambda x: -x[1])[:5]
    job.log(
        f"⚠ {len(over)}/{len(cues)} dòng phải xuống quá {max_lines} dòng để giữ đúng "
        f"{max_chars} ký tự/dòng (nhiều nhất {worst[0][1]} dòng, ở dòng "
        + ", ".join(str(n) for n, _ in worst) + ")."
    )
    job.log(
        f"   Muốn gọn hơn: nới **Số ký tự mỗi dòng** lên, hoặc rút gọn mấy dòng đó ở bước 4."
    )


def run_render(job: Job, state: dict, cfg: dict) -> None:
    workdir = job.dir
    cues = [Cue.from_dict(d) for d in state["cues"]]
    video_path = Path(state["video_path"])
    stem = safe_stem(state.get("video_name", "video"))
    src_lang = state.get("source_lang") or None
    tgt_lang = state.get("target_lang") or None
    mode = cfg.get("display", "main")  # main | second | both | both_rev
    style = cfg.get("style") or {}
    max_chars = int(cfg.get("line_chars", 42))
    max_lines = int(cfg.get("max_lines", 2))
    outputs = cfg.get("outputs", {})
    files: list[dict] = []

    offset = float(cfg.get("offset", 0.0) or 0.0)
    if offset:
        subtitles.shift_cues(cues, offset)
        job.log(f"Đã dịch chuyển toàn bộ phụ đề {offset:+.2f}s")

    job.start_step("files")

    def emit(name: str, content: str) -> Path:
        p = write_utf8(workdir / name, content)
        files.append({"name": name, "size": p.stat().st_size, "kind": p.suffix.lstrip(".")})
        return p

    lang_tag = tgt_lang if mode in ("second", "both_rev") else (src_lang or "sub")

    # `wrap_text` giữ đúng `max_chars` nên chữ dài sẽ tràn thành nhiều dòng hơn
    # `max_lines`. Nói cho người dùng biết thay vì lặng lẽ hiện 4-5 dòng.
    _warn_too_many_lines(job, cues, mode, src_lang, tgt_lang, max_chars, max_lines)

    if outputs.get("srt", True):
        emit(f"{stem}.{lang_tag}.srt",
             subtitles.to_srt(cues, mode, src_lang, tgt_lang, max_chars, max_lines))
    if outputs.get("vtt"):
        emit(f"{stem}.{lang_tag}.vtt",
             subtitles.to_vtt(cues, mode, src_lang, tgt_lang, max_chars, max_lines))
    if outputs.get("srt_both") and tgt_lang:
        emit(f"{stem}.song-ngu.srt",
             subtitles.to_srt(cues, "both", src_lang, tgt_lang, max_chars, max_lines))
    if outputs.get("txt"):
        body = "\n".join(
            (c.text2 if mode in ("second", "both_rev") and c.text2 else c.text) for c in cues
        )
        emit(f"{stem}.txt", body + "\n")

    ass_path = write_utf8(
        workdir / "burn.ass",
        subtitles.to_ass(
            cues, mode, src_lang, tgt_lang, style, max_chars, max_lines,
            play_res_x=state["info"].get("width") or 1920,
            play_res_y=state["info"].get("height") or 1080,
        ),
    )
    if outputs.get("ass"):
        files.append({"name": "burn.ass", "size": ass_path.stat().st_size, "kind": "ass"})

    job.finish_step("files", f"{len(files)} file")
    job.check_cancel()

    duration = state["info"].get("duration", 0.0)

    if outputs.get("burn"):
        if not media.has_libass():
            raise RuntimeError(
                "ffmpeg hiện tại không hỗ trợ nung phụ đề (thiếu libass). "
                "Chạy: uv run python -m app.setup_ffmpeg"
            )
        job.start_step("burn", "Đang encode…")
        out_name = f"{stem}.hardsub.mp4"
        job.log(f"Nung phụ đề vào video (~{_hms(duration)} nội dung)…")
        media.burn_subtitles(
            video_path, ass_path, workdir / out_name,
            on_progress=lambda p: job.set_step_progress("burn", p),
            crf=int(cfg.get("crf", 20)),
            preset=cfg.get("preset", "medium"),
        )
        p = workdir / out_name
        files.append({"name": out_name, "size": p.stat().st_size, "kind": "mp4"})
        job.finish_step("burn")
        job.check_cancel()

    if outputs.get("soft"):
        job.start_step("soft")
        srt_tmp = write_utf8(
            workdir / "_soft.srt",
            subtitles.to_srt(cues, mode, src_lang, tgt_lang, max_chars, max_lines),
        )
        out_name = f"{stem}.softsub.mp4"
        media.mux_soft_subs(
            video_path, srt_tmp, workdir / out_name,
            lang=(tgt_lang or src_lang or "und"),
            on_progress=lambda p: job.set_step_progress("soft", p),
        )
        p = workdir / out_name
        files.append({"name": out_name, "size": p.stat().st_size, "kind": "mp4"})
        srt_tmp.unlink(missing_ok=True)
        job.finish_step("soft")
        job.check_cancel()

    if outputs.get("dub"):
        _run_dub(job, cues, state, cfg, workdir, stem, files, duration)

    job.result = {"files": files}


def _run_dub(job, cues, state, cfg, workdir, stem, files, duration) -> None:
    """Đọc bản dịch thành tiếng rồi ghép vào video."""
    dcfg = cfg.get("dub") or {}
    voice = dcfg.get("voice", "")
    style = dcfg.get("style", "tu_nhien")
    ref_audio = ""

    ok, reason = dubbing.available()
    if not ok:
        raise RuntimeError(reason)

    has_translation = any(c.text2.strip() for c in cues)
    if not has_translation:
        # Đọc nguyên văn tiếng gốc bằng giọng Việt chỉ ra tiếng bịa. Chặn ngay
        # đây, đừng để chạy hết TTS mấy chục phút rồi mới lộ.
        src = (state.get("source_lang") or "").lower()
        if subtitles.is_cjk("".join(c.text for c in cues[:60])) or src.startswith(
            ("zh", "ja", "ko", "th", "ru", "ar", "hi")
        ):
            raise RuntimeError(
                "Phụ đề đang là tiếng nước ngoài mà chưa có bản dịch — đọc nguyên văn "
                "bằng giọng Việt sẽ ra tiếng vô nghĩa. Hãy bật Dịch phụ đề ở bước 2 "
                "(hoặc tự điền bản dịch ở bước 4) rồi lồng tiếng lại."
            )
        job.log("Không có bản dịch — sẽ đọc chính nội dung phụ đề gốc.")

    if voice == dubbing.CLONE_VOICE:
        clone_ok, clone_why = dubbing.clone_available()
        if not clone_ok:
            raise RuntimeError(clone_why)
        job.start_step("ref", "Đang cắt mẫu giọng…")
        ref_audio = str(
            dubbing.extract_reference(Path(state["video_path"]), cues, workdir / "voice_ref.wav")
        )
        job.finish_step("ref")
        job.log("Đã cắt mẫu giọng gốc để nhân bản.")
        job.check_cancel()

    job.start_step("tts", f"{len(cues)} dòng")
    job.log("Đang nạp model VieNeu-TTS (lần đầu có thể mất vài phút)…")
    dub_wav, stats = dubbing.build_dub_track(
        cues,
        total_duration=duration,
        workdir=workdir,
        voice="" if ref_audio else voice,
        ref_audio=ref_audio,
        style=style,
        use_translation=has_translation,
        max_speed=float(dcfg.get("max_speed", 1.5)),
        on_progress=lambda p: job.set_step_progress("tts", p),
        on_log=job.log,
    )
    detail = f"{stats['count']} câu"
    if stats["sped_up"]:
        detail += f" · {stats['sped_up']} câu tăng tốc (tối đa {stats['max_factor']:.2f}×)"
    if stats["failed"]:
        detail += f" · {stats['failed']} câu lỗi"
    job.finish_step("tts", detail)
    job.log("Đọc xong: " + detail)
    if stats.get("trimmed_ms"):
        job.log(
            f"Đã cắt {stats['trimmed_ms'] / max(1, stats['count']):.0f} ms lặng đầu/cuối "
            "mỗi câu để tiếng vào đúng mốc giờ."
        )
    if stats["overflow"]:
        # Tràn là nguyên nhân chính làm tiếng lồng lệch dần so với hình: câu này
        # còn đang đọc thì câu sau đã tới. Chỉ rõ dòng nào để rút gọn cho nhanh.
        job.log(
            f"⚠ {stats['overflow']} dòng vẫn dài hơn khung giờ dù đã tăng tốc "
            f"{stats['max_factor']:.2f}× — tràn tổng {stats['overflow_s']:.1f}s. "
            "Chỗ nào tràn thì tiếng bị đọc chồng sang câu sau, nghe như lệch dần."
        )
        for w in stats.get("worst", [])[:5]:
            job.log(
                f"   {w['line']}: tràn {w['over_s']:.1f}s "
                f"({w['chars']} ký tự trong khung {w['window_s']:.1f}s)"
            )
        job.log(
            "   Cách chữa: rút gọn đúng những dòng trên ở bước 4, hoặc nới "
            "**Tăng tốc tối đa** lên 1.8–2.0×."
        )
    job.check_cancel()

    # Nếu đã nung phụ đề thì lồng tiếng lên chính bản đó (vừa có chữ vừa có tiếng)
    hardsub = workdir / f"{stem}.hardsub.mp4"
    base_video = hardsub if hardsub.exists() else Path(state["video_path"])
    if base_video == hardsub:
        job.log("Lồng tiếng lên bản đã nung phụ đề.")

    job.start_step("dubmux")
    out_name = f"{stem}.longtieng.mp4"

    orig_vol = float(dcfg.get("original_volume", 0.45))
    dub_vol = float(dcfg.get("dub_volume", 1.0))
    keep = bool(dcfg.get("keep_original", True))
    duck = bool(dcfg.get("duck", True))
    voice_dbfs, duck_db = dubbing.wav_levels(dub_wav)[0], 0.0

    # Giọng TTS ra nhỏ hơn thoại gốc trong phim -> tự đo rồi kéo lên cho khỏi lép
    if dcfg.get("auto_level", True):
        dub_vol, orig_vol, duck_db = dubbing.balance(
            dub_wav, base_video, orig_vol,
            duration=duration, boost=dub_vol, duck=duck, keep_original=keep,
            tmpdir=workdir, on_log=job.log,
        )
    elif duck:
        # Tắt tự cân nhưng vẫn né: hụp một mức vừa phải, cố định
        duck_db = dubbing.VOICE_ABOVE_BG_DB - dubbing.VOICE_ABOVE_GAP_DB

    dubbing.mux_dub(
        base_video,
        dub_wav,
        workdir / out_name,
        original_volume=orig_vol,
        dub_volume=dub_vol,
        keep_original=keep,
        duck=duck,
        duck_db=duck_db,
        voice_dbfs=voice_dbfs,
        duration=duration,
        on_log=job.log,
        on_progress=lambda p: job.set_step_progress("dubmux", p),
    )
    p = workdir / out_name
    files.append({"name": out_name, "size": p.stat().st_size, "kind": "mp4"})
    if dcfg.get("keep_wav"):
        files.append({"name": dub_wav.name, "size": dub_wav.stat().st_size, "kind": "wav"})
    job.finish_step("dubmux")


def _coverage_warning(job, result: dict, duration: float) -> str:
    """Ghi log rõ ràng khi phụ đề không phủ hết video, trả về câu cảnh báo."""
    cov = result.get("coverage", 0.0)
    if not duration or cov >= 0.9:
        return ""

    last = cov * duration
    msg = (
        f"⚠ Phụ đề chỉ phủ tới giây {last:.0f}/{duration:.0f} ({cov * 100:.0f}%). "
        "Phần còn lại Whisper không nghe ra lời."
    )
    job.log(msg)

    gaps = [g for g in result.get("gaps", []) if g[1] - g[0] >= 15]
    if gaps:
        pretty = ", ".join(f"{int(a)}–{int(b)}s" for a, b in gaps[:6])
        job.log(f"  Các đoạn không có phụ đề: {pretty}")
    job.log(
        "  Nếu đó là đoạn CÓ lời: thử model lớn hơn (medium / large-v3), "
        "hoặc chọn đúng ngôn ngữ gốc thay vì để tự động."
    )
    return msg


def _hms(seconds: float) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

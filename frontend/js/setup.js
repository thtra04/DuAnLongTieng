/* frontend/js/setup.js — bước 2: cấu hình dịch & nhận dạng, gửi /api/analyze (phần AI ở ai.js).
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
/* --------------------------- bước 2: cấu hình --------------------------- */
$('#doTranslate').addEventListener('change', e => {
  const on = e.target.checked;
  $('#engineCard').classList.toggle('hide', !on);
  $('#tgtLang').disabled = !on;
  updateStepSummary();
});

function bindRange(id, outId, fmt = v => v) {
  const el = $(id), out = $(outId);
  const upd = () => { out.textContent = fmt(el.value); };
  el.addEventListener('input', upd); upd();
}
bindRange('#maxChars', '#maxCharsOut');
bindRange('#stSize', '#stSizeOut');
bindRange('#stOutline', '#stOutlineOut');
bindRange('#stMargin', '#stMarginOut');
bindRange('#stLineChars', '#stLineCharsOut');
bindRange('#crf', '#crfOut');

$('#startBtn').addEventListener('click', startAnalyze);

async function startAnalyze() {
  if (!aiReady()) return;
  const payload = {
    source_type: S.sourceType,
    media_id: S.mediaId,
    url: S.url,
    part: S.sourceType === 'url' ? S.part : null,
    // xong thì tự gắn kết quả vào đúng tập của bộ phim đang làm
    film_id: S.target?.filmId || '',
    episode_no: S.target?.no ?? null,
    series_name: S.sourceType === 'url' ? (S.linkInfo?.title || '') : '',
    series_total: S.sourceType === 'url' ? (S.linkInfo?.count || 0) : 0,
    sub_mode: S.subMode,
    script_text: $('#scriptText').value,
    subtitle_text: S.subtitleText,
    source_lang: $('#srcLang').value || null,
    target_lang: $('#tgtLang').value,
    translate: $('#doTranslate').checked,
    ...aiPayload(),   // engine, key, model, endpoint, phong cách, thuật ngữ, budget_loop — ai.js
    asr_model: $('#asrModel').value,
    device: $('#device').value,
    vad: $('#vad').checked,
    auto_fix: $('#autoFix').checked,
    prompt: $('#prompt').value.trim(),
    max_chars: +$('#maxChars').value,
    gender_split: $('#genderOn').checked,
    diarize: $('#diarizeOn').checked,
    num_speakers: +$('#numSpeakers').value || null,
    hf_token: $('#hfToken').value.trim(),
  };
  savePrefs();

  // Chạy mới thì thôi không còn dính vào dự án cũ đang mở
  S.projectId = null;
  S.videoSrc = '';

  $('#startBtn').disabled = true;
  try {
    const r = await api('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    S.jobId = r.job_id;
    saveJobRecovery(payload);
    updateStepSummary();
    unlock(3);
    goStep(3);
    $('#toEditor').classList.add('hide');
    $('#cancelBtn').disabled = false;
    pollJob();
  } catch (e) {
    toast(e.message, 'err', 8000);
  } finally {
    $('#startBtn').disabled = false;
  }
}


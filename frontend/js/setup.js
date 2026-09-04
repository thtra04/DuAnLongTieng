/* frontend/js/setup.js — bước 2: cấu hình dịch & nhận dạng, gửi /api/analyze.
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
  if ($('#doTranslate').checked && (S.engine === 'claude' || S.engine === 'openai')) {
    const hasEnvKey = S.engine === 'claude' ? S.sys.has_anthropic_key : S.sys.has_openai_key;
    if (!$('#apiKey').value.trim() && !hasEnvKey) {
      return toast('Hãy nhập API key hoặc đặt biến môi trường cho engine AI đã chọn.', 'warn', 7000);
    }
  }
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
    engine: S.engine,
    api_key: $('#apiKey').value.trim(),
    ai_model: $('#aiModel').value || '',
    ai_base_url: S.engine === 'openai' ? $('#aiBaseUrl').value.trim() : '',
    context_note: $('#contextNote').value.trim(),
    translation_mode: $('#translationMode').value,
    glossary: $('#glossary').value.trim(),
    asr_model: $('#asrModel').value,
    device: $('#device').value,
    vad: $('#vad').checked,
    auto_fix: $('#autoFix').checked,
    prompt: $('#prompt').value.trim(),
    max_chars: +$('#maxChars').value,
    diarize: $('#diarizeOn').checked,
    num_speakers: +$('#numSpeakers').value || null,
    hf_token: $('#hfToken').value.trim(),
    // HP-5: chỉ có nghĩa với engine AI — máy chủ tự bỏ qua với Google/MyMemory
    budget_loop: !!($('#budgetLoop') && $('#budgetLoop').checked),
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


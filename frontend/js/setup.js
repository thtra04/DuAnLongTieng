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
$('#retransBtn').addEventListener('click', startRetranslate);
$('#redoTransBtn').addEventListener('click', () => {
  unlock(2);
  $('#doTranslate').checked = true;
  $('#doTranslate').dispatchEvent(new Event('change'));
  goStep(2);
  $('#engineCard').scrollIntoView({ behavior: 'smooth', block: 'start' });
});

/* Dịch lại phụ đề của dự án đang mở: giữ lời gốc, mốc giờ, vai; chỉ viết lại bản dịch. */
async function startRetranslate() {
  if (!$('#doTranslate').checked) return toast('Bật "Dịch phụ đề" rồi chọn ngôn ngữ đích trước đã.', 'warn');
  if (!aiReady()) return;
  const had = S.cues.some(c => c.text2);
  if (had && !(await askConfirm('Dịch lại sẽ thay toàn bộ bản dịch hiện có, kể cả những dòng bạn đã sửa tay trong lần mở này. '
      + 'Những câu bạn đã sửa và từng xuất thì bộ nhớ dịch vẫn giữ và sẽ dùng lại.', { ok: 'Dịch lại', danger: false }))) return;
  const payload = {
    cues: S.cues.map(c => ({ start: c.start, end: c.end, text: c.text, text2: '', speaker: c.speaker || '' })),
    target_lang: $('#tgtLang').value,
    ...aiPayload(),
    // dự án chưa dòng nào có vai thì máy chủ nhận vai nam / nữ luôn trong lượt này
    gender_split: $('#genderOn').checked,
  };
  savePrefs();
  $('#retransBtn').disabled = true;
  try {
    const r = await api(`/api/jobs/${S.jobId}/retranslate`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    unlock(3);
    goStep(3);
    $('#toEditor').classList.add('hide');
    $('#cancelBtn').disabled = false;
    pollRetranslate(r.job_id);
  } catch (e) {
    toast(e.message, 'err', 9000);
  } finally {
    $('#retransBtn').disabled = false;
  }
}

function pollRetranslate(id) {
  clearInterval(S.poll);
  S.transJob = id;
  S.poll = setInterval(async () => {
    let j;
    try { j = await api(`/api/jobs/${id}`); }
    catch (e) { clearInterval(S.poll); toast('Mất kết nối job: ' + e.message, 'err'); return; }
    paintProgress(j, '#stepsList', '#logBox');
    if (j.status === 'done') {
      clearInterval(S.poll);
      S.transJob = null;
      $('#cancelBtn').disabled = true;
      $('#phaseText').textContent = 'hoàn tất';
      S.cues = (j.result.cues || []).map(c => ({ ...c }));
      S.analyzed = { ...(S.analyzed || {}), target_lang: j.result.target_lang, speakers: j.result.speakers || [] };
      await loadCharacters(S.jobId);   // lượt này có thể vừa nhận vai cho dự án chưa có vai
      S.display = 'second';
      $$('.tab[data-disp]').forEach(t => { t.disabled = false; t.classList.toggle('active', t.dataset.disp === 'second'); });
      updateStepSummary();
      $('#toEditor').classList.remove('hide');
      unlock(4);
      setupEditor();
      goStep(4);
      toast(`Đã dịch lại ${S.cues.length} dòng.`, 'ok', 4000);
    } else if (j.status === 'error' || j.status === 'cancelled') {
      clearInterval(S.poll);
      S.transJob = null;
      $('#cancelBtn').disabled = true;
      $('#phaseText').textContent = j.status === 'cancelled' ? 'đã huỷ' : 'lỗi';
      toast(j.error || 'Dịch lại thất bại — bản dịch cũ vẫn còn nguyên.', 'err', 12000);
    }
  }, 800);
}

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
    separate_first: $('#separateFirstOn').checked,
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


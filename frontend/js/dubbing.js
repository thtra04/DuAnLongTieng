/* frontend/js/dubbing.js — lồng tiếng: giọng đọc, nhân vật & giọng theo vai.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
/* ------------------------------ lồng tiếng ------------------------------ */
bindRange('#dubOrigVol', '#dubOrigVolOut', v => v + '%');
bindRange('#dubVol', '#dubVolOut', v => v + '%');
bindRange('#dubSpeed', '#dubSpeedOut', v => (v / 100).toFixed(2) + '×');

function initTts() {
  const t = S.sys.tts || {};
  $('#dubStyle').innerHTML = (t.styles || [])
    .map(s => `<option value="${s.id}">${s.label}</option>`).join('');
  if (!t.available) {
    $('#ttsBox').classList.add('hide');
    $('#ttsUnavailable').classList.remove('hide');
    $('#ttsReason').innerHTML =
      `Chưa bật được lồng tiếng — ${t.reason || 'thiếu VieNeu-TTS'}.<br>` +
      `Cài bằng: <code>uv sync --extra tts</code> rồi khởi động lại tool.`;
  }
}

$('#dubOn').addEventListener('change', async e => {
  const on = e.target.checked;
  $('#dubOpts').classList.toggle('hide', !on);
  $('#outDubWrap').classList.toggle('hide', !on);
  $('#outDubWavWrap').classList.toggle('hide', !on);
  const outDub = $('#outDub');
  outDub.checked = on;
  outDub.closest('.check').classList.toggle('on', on);
  if (on && !S.voicesLoaded) await loadVoices();
  if (on) renderSpeakerVoices();
});

async function loadVoices() {
  const sel = $('#dubVoice');
  sel.innerHTML = '<option value="">Đang tải model giọng… (lần đầu ~1 phút)</option>';
  try {
    const r = await api('/api/tts/voices');
    if (!r.available) throw new Error(r.reason);
    const clone = r.clone_id || '__clone__';
    // Thiếu thư viện thì khoá sẵn mục nhân bản, đừng để chọn rồi xuất mới lỗi
    const cloneOk = r.clone !== false;
    S.voices = r.voices || [];
    S.cloneOk = cloneOk;
    sel.innerHTML =
      r.voices.map(v => `<option value="${v.id}">${esc(v.label)}</option>`).join('') +
      `<option value="${clone}"${cloneOk ? '' : ' disabled'}>` +
      (cloneOk
        ? 'Nhân bản giọng người nói trong video'
        : 'Nhân bản giọng — chưa dùng được (cần uv sync --extra clone)') +
      '</option>';
    S.voicesLoaded = true;
    renderSpeakerVoices();
    toast(`Đã nạp ${r.voices.length} giọng đọc.`, 'ok', 2600);
    if (!cloneOk && r.clone_reason) {
      toast('Nhân bản giọng: ' + r.clone_reason, 'warn', 9000);
    }
  } catch (e) {
    sel.innerHTML = '<option value="">— không tải được —</option>';
    toast('Không lấy được danh sách giọng: ' + e.message, 'err', 9000);
  }
}

// Chế độ tiếng gốc: bỏ giọng (nền 100%), giữ và hạ nhỏ (nền 45%), hay thay hẳn.
$('#dubOrigMode').addEventListener('change', e => {
  const mode = e.target.value;
  $('#dubKeepOrig').checked = mode !== 'mute';
  $('#origVolWrap').style.opacity = mode === 'mute' ? '.4' : '1';
  $('#dubOrigVol').disabled = mode === 'mute';
  $('#duckWrap').style.opacity = mode === 'keep' ? '1' : '.4';
  $('#dubDuck').disabled = mode !== 'keep';
  const vol = $('#dubOrigVol');
  if (mode === 'voice_off' && +vol.value < 70) { vol.value = 100; vol.dispatchEvent(new Event('input')); }
  if (mode === 'keep' && +vol.value > 60) { vol.value = 45; vol.dispatchEvent(new Event('input')); }
});
$('#dubOrigMode').dispatchEvent(new Event('change'));

$('#dubTest').addEventListener('click', async () => {
  const btn = $('#dubTest'), msg = $('#dubTestMsg');
  const voice = $('#dubVoice').value;
  if (!voice) return toast('Chưa chọn giọng.', 'warn');
  if (voice === (S.sys.tts?.clone_id || '__clone__'))
    return toast('Giọng nhân bản chỉ tạo được lúc xuất video.', 'warn', 6000);

  // đọc thử chính dòng đang chọn, không có thì dùng câu mẫu
  const c = S.cues[S.activeCue] || S.cues[0];
  const text = (c && (c.text2 || c.text)) || 'Xin chào, đây là giọng đọc thử.';

  btn.disabled = true; msg.textContent = 'đang tạo…';
  try {
    const res = await fetch(apiUrl('/api/tts/preview'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 300), voice, style: $('#dubStyle').value }),
    });
    if (!res.ok) throw new Error((await res.json()).error || 'lỗi');
    const url = URL.createObjectURL(await res.blob());
    const a = $('#dubAudio');
    a.src = url; a.classList.remove('hide'); a.controls = true;
    $('#player').pause();
    await a.play();
    msg.textContent = '';
  } catch (e) {
    msg.textContent = '';
    toast('Nghe thử lỗi: ' + e.message, 'err', 8000);
  } finally {
    btn.disabled = false;
  }
});

/* --------------------------- nhân vật & giọng --------------------------- */

/* Nhãn nhân vật từ máy chủ là S1, S2… Người dùng đổi tên và chọn giọng được;
   hai thứ đó lưu ở máy chủ theo dự án (bảng characters/voices) nên mở lại dự án
   vẫn còn. Phụ đề vẫn dùng nhãn gốc. */
const SPK_SLOTS = 6;

/** Nạp tên vai & giọng đã lưu vào phiên làm việc (thay hẳn, không trộn với dự án trước). */
function applyCharacters(list) {
  S.speakerNames = {};
  S.speakerVoices = {};
  S.speakerAges = {};      // {nhãn: 'C' | 'A' | 'E'} — trẻ em đoán từ cao độ, còn lại người dùng chọn
  S.speakerGenders = {};   // {nhãn: 'M' | 'F'} — máy chủ đoán từ cao độ giọng, sửa được ở bảng vai
  (list || []).forEach(c => {
    if (c.name) S.speakerNames[c.label] = c.name;
    if (c.voice) S.speakerVoices[c.label] = c.voice;
    if (c.gender) S.speakerGenders[c.label] = c.gender;
    if (c.age) S.speakerAges[c.label] = c.age;
  });
}

async function loadCharacters(id) {
  if (!id) return applyCharacters([]);
  try {
    const r = await api(`/api/projects/${id}/characters`);
    applyCharacters(r.characters);
  } catch { applyCharacters([]); }
}

/* Gõ tên là lưu — gom lại 400 ms để không bắn một request mỗi phím. */
const _spkSaveTimers = {};
function saveCharacter(label, patch) {
  const id = S.projectId || S.jobId;
  if (!id) return;
  clearTimeout(_spkSaveTimers[label]);
  _spkSaveTimers[label] = setTimeout(() => {
    api(`/api/projects/${id}/characters/${encodeURIComponent(label)}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }).catch(() => {});
  }, 400);
}

function spkSlot(id) {
  const n = parseInt(String(id).replace(/\D/g, ''), 10);
  return (Number.isFinite(n) ? (n - 1) % SPK_SLOTS : 0) + 1;
}

function spkName(id) {
  const custom = (S.speakerNames || {})[id];
  if (custom) return custom;
  const n = parseInt(String(id).replace(/\D/g, ''), 10);
  return Number.isFinite(n) ? `Vai ${n}` : id;
}

function initDiarize() {
  const d = S.sys.diarize || {};
  const box = $('#diarizeOpts');
  const hint = $('#diarizeHint');

  // Có token trong biến môi trường rồi thì khỏi bắt nhập lại
  if (d.has_token) $('#hfTokenWrap').classList.add('hide');

  $('#diarizeOn').addEventListener('change', e => {
    box.classList.toggle('hide', !e.target.checked);
  });

  if (!d.available && !d.has_token) {
    hint.innerHTML =
      `${esc(d.reason || 'Chưa dùng được.')}<br>` +
      `Model: <code>${esc(d.model || '')}</code> — mở trang model trên Hugging Face, ` +
      `bấm chấp nhận điều khoản, rồi tạo token ở mục Access Tokens.`;
  } else {
    hint.textContent =
      'Chạy trên chính đường tiếng của video nên không phụ thuộc ngôn ngữ — '
      + 'phim Trung, Hàn, Nhật, Anh đều dùng được.';
  }
}

/** Bảng chọn giọng cho từng nhân vật, dựng lại mỗi khi có phụ đề mới. */
function renderSpeakerVoices() {
  const box = $('#spkBox'), list = $('#spkList');
  const speakers = speakersFromCues();

  if (!speakers.length) {
    box.classList.add('hide');
    list.innerHTML = '';
    return;
  }
  box.classList.remove('hide');
  $('#spkCount').textContent =
    `${speakers.length} nhân vật · ${speakers.reduce((n, s) => n + s.lines, 0)} dòng`;

  S.speakerVoices = S.speakerVoices || {};
  const voices = S.voices || [];
  const cloneId = S.sys.tts?.clone_id || '__clone__';

  // Mặc định: NHÂN BẢN chính giọng nhân vật trong phim khi máy làm được — đo trên
  // clip mẫu, giọng nhân bản giống giọng gốc hơn hẳn giọng có sẵn (độ giống 0,43/0,55
  // so với 0,41/0,37), đọc vẫn rõ (Whisper nghe đúng 15/17 câu). Không nhân bản được
  // thì lấy giọng có sẵn cùng giới tính, chưa vai nào dùng. (Chọn theo cao độ gần
  // giọng gốc đã thử và đo ra kém giống hơn — xem gender.pick_voice.)
  S.speakerGenders = S.speakerGenders || {};
  const taken = new Set(Object.values(S.speakerVoices));
  speakers.forEach((s, i) => {
    if (S.speakerVoices[s.id] || !voices.length) return;
    if (S.cloneOk) { S.speakerVoices[s.id] = cloneId; return; }
    const pick = closestVoice(voices, S.speakerGenders[s.id] || '', taken)
      || voices[i % voices.length];
    S.speakerVoices[s.id] = pick.id;
    taken.add(pick.id);
  });
  const GENDER_LABEL = { M: 'Nam', F: 'Nữ' };
  const AGE_LABEL = { C: 'Trẻ em', A: 'Người lớn', E: 'Cao tuổi' };

  list.innerHTML = speakers.map(s => `
    <div class="spkrow" data-spk="${esc(s.id)}">
      <span class="spk s${spkSlot(s.id)} big">${esc(s.id)}</span>
      <div class="spkmain">
        <div class="spkline">
          <input class="spkname" type="text" value="${esc(spkName(s.id))}"
                 data-spk="${esc(s.id)}" maxlength="40" aria-label="Tên nhân vật ${esc(s.id)}">
          <button type="button" class="spkgender g-${S.speakerGenders[s.id] || 'x'}" data-spk="${esc(s.id)}"
                  title="Giới tính giọng của vai này — bấm để đổi và chọn lại giọng cho hợp"
                  aria-label="Giới tính giọng của ${esc(s.id)}: ${GENDER_LABEL[S.speakerGenders[s.id]] || 'chưa rõ'}. Bấm để đổi"
                  >${GENDER_LABEL[S.speakerGenders[s.id]] || '?'}</button>
          <button type="button" class="spkage a-${S.speakerAges[s.id] || 'x'}" data-spk="${esc(s.id)}"
                  title="Nhóm tuổi của vai này — bấm để đổi (trẻ em tự đoán từ cao độ; người cao tuổi phải chọn tay)"
                  aria-label="Nhóm tuổi của ${esc(s.id)}: ${AGE_LABEL[S.speakerAges[s.id]] || 'chưa rõ'}. Bấm để đổi"
                  >${AGE_LABEL[S.speakerAges[s.id]] || 'Tuổi?'}</button>
          <span class="muted">${s.lines} dòng · ${Math.round(s.seconds)}s nói</span>
        </div>
        ${s.sample ? `<div class="spksample">“${esc(s.sample)}”</div>` : ''}
        <div class="spkline">
          <select class="spkvoice" data-spk="${esc(s.id)}" aria-label="Giọng cho ${esc(s.id)}">
            ${voices.map(v => `<option value="${esc(v.id)}"${S.speakerVoices[s.id] === v.id ? ' selected' : ''}>${esc(v.label)}</option>`).join('')}
            <option value="${esc(cloneId)}"${S.speakerVoices[s.id] === cloneId ? ' selected' : ''}
              ${S.cloneOk === false ? ' disabled' : ''}>
              Nhân bản chính giọng nhân vật này
            </option>
          </select>
          <button class="btn sm ghost spktest" data-spk="${esc(s.id)}" title="Nghe thử giọng này"
                  aria-label="Nghe thử giọng của ${esc(s.id)}">${icon('volume')}</button>
        </div>
      </div>
    </div>`).join('');

  $$('.spkvoice', list).forEach(sel => sel.addEventListener('change', () => {
    S.speakerVoices[sel.dataset.spk] = sel.value;
    saveCharacter(sel.dataset.spk, { voice: sel.value, style: $('#dubStyle').value });
  }));
  $$('.spkgender', list).forEach(btn => btn.addEventListener('click', () => {
    const id = btn.dataset.spk;
    const g = S.speakerGenders[id] === 'M' ? 'F' : 'M';
    S.speakerGenders[id] = g;
    // Đang nhân bản thì giữ nguyên (giọng nhân bản lấy từ chính vai đó, không phụ
    // thuộc giới tính); đang dùng giọng có sẵn thì đổi sang giọng có sẵn đúng giới mới
    if (S.speakerVoices[id] !== cloneId) {
      const taken = new Set(Object.entries(S.speakerVoices).filter(([k]) => k !== id).map(([, v]) => v));
      const pick = closestVoice(voices, g, taken);
      if (pick) S.speakerVoices[id] = pick.id;
    }
    renderSpeakerVoices();
    saveCharacter(id, { gender: g, voice: S.speakerVoices[id] || '', style: $('#dubStyle').value });
  }));
  $$('.spkage', list).forEach(btn => btn.addEventListener('click', () => {
    const id = btn.dataset.spk;
    const next = { A: 'E', E: 'C', C: 'A' }[S.speakerAges[id]] || 'A';
    S.speakerAges[id] = next;
    renderSpeakerVoices();
    saveCharacter(id, { age: next });
  }));
  $$('.spkname', list).forEach(inp => inp.addEventListener('input', () => {
    S.speakerNames = S.speakerNames || {};
    S.speakerNames[inp.dataset.spk] = inp.value.trim();
    saveCharacter(inp.dataset.spk, { name: inp.value.trim() });
    renderCues();
  }));
  $$('.spktest', list).forEach(btn => btn.addEventListener('click', () => {
    previewSpeaker(btn.dataset.spk, btn);
  }));
}

/** Danh sách nhân vật rút thẳng từ cue đang có trên màn hình.
    Lấy từ cue chứ không lấy từ `S.analyzed.speakers` để người dùng sửa nhãn ở
    bước 4 thì bảng giọng cập nhật theo ngay. */
function speakersFromCues() {
  const table = {};
  S.cues.forEach(c => {
    const id = (c.speaker || '').trim();
    if (!id) return;
    const item = table[id] || (table[id] = { id, lines: 0, seconds: 0, sample: '' });
    item.lines++;
    item.seconds += Math.max(0, c.end - c.start);
    if (!item.sample) item.sample = (c.text2 || c.text || '').trim().slice(0, 70);
  });
  return Object.values(table).sort((a, b) => b.seconds - a.seconds);
}

/** Giọng có sẵn cùng giới tính, ưu tiên giọng chưa vai nào dùng. */
function closestVoice(voices, gender, taken) {
  const same = gender ? voices.filter(v => v.gender === gender) : [];
  if (!same.length) return null;
  return same.find(v => !taken.has(v.id)) || same[0];
}

/** Mọi nhãn vai đã biết (kể cả vai tạm thời không còn dòng nào), để đổi vai cho một dòng. */
function knownSpeakerIds() {
  const ids = new Set([
    ...speakersFromCues().map(s => s.id),
    ...Object.keys(S.speakerGenders || {}),
    ...Object.keys(S.speakerNames || {}),
  ]);
  return [...ids].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}

/** {nhãn nhân vật: id giọng} gửi kèm lúc xuất file. */
function collectSpeakerVoices() {
  const out = {};
  speakersFromCues().forEach(s => {
    const v = (S.speakerVoices || {})[s.id];
    if (v) out[s.id] = v;
  });
  return out;
}

async function previewSpeaker(id, btn) {
  const voice = (S.speakerVoices || {})[id];
  const cloneId = S.sys.tts?.clone_id || '__clone__';
  if (!voice) return toast('Chưa chọn giọng cho nhân vật này.', 'warn');
  if (voice === cloneId) {
    return toast('Giọng nhân bản chỉ tạo được lúc xuất video — nó cần cắt mẫu từ chính video.', 'warn', 7000);
  }
  const line = S.cues.find(c => (c.speaker || '') === id && (c.text2 || c.text || '').trim());
  const text = line ? (line.text2 || line.text) : 'Xin chào, đây là giọng đọc thử.';

  btn.disabled = true;
  try {
    const res = await fetch(apiUrl('/api/tts/preview'), {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 300), voice, style: $('#dubStyle').value }),
    });
    if (!res.ok) throw new Error((await res.json()).error || 'lỗi');
    const a = $('#dubAudio');
    a.src = URL.createObjectURL(await res.blob());
    a.classList.remove('hide'); a.controls = true;
    $('#player').pause();
    await a.play();
  } catch (e) {
    toast(`Nghe thử ${spkName(id)} lỗi: ${e.message}`, 'err', 8000);
  } finally {
    btn.disabled = false;
  }
}


/* ------------------------- kịch bản lồng tiếng -------------------------- */
// Máy chủ ghép bản dịch thành từng câu đọc có dấu câu (/api/tts/script). Người dùng
// sửa ở đây; lúc xuất chỉ gửi những câu đã sửa, kèm chữ gốc (`base`) để máy chủ bỏ
// qua bản sửa đã cũ nếu sau đó phụ đề bị đổi.
S.dubScript = null;

function scriptSig() {
  return JSON.stringify([
    S.cues.map(c => [c.text, c.text2 || '', c.speaker || '']),
    $('#dubShorten').checked,
  ]);
}

async function buildScript() {
  const btn = $('#scriptBtn');
  if (!S.cues?.length) return toast('Chưa có phụ đề để dựng kịch bản.', 'warn');
  btn.disabled = true;
  $('#scriptMsg').textContent = 'Đang dựng…';
  try {
    const r = await api('/api/tts/script', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cues: S.cues,
        target_lang: S.analyzed?.target_lang || 'vi',
        shorten: $('#dubShorten').checked,
      }),
    });
    // giữ lại câu đã sửa nếu câu đó vẫn y như cũ
    const old = new Map((S.dubScript?.units || [])
      .filter(u => u.text !== u.base).map(u => [u.cues.join(','), u]));
    const units = r.units.map(u => {
      const prev = old.get(u.cues.join(','));
      return { ...u, base: u.text, text: prev && prev.base === u.text ? prev.text : u.text };
    });
    S.dubScript = { units, sig: scriptSig() };
    renderScript();
    $('#scriptMsg').textContent = '';
  } catch (e) {
    $('#scriptMsg').textContent = '';
    toast('Không dựng được kịch bản: ' + e.message, 'err', 7000);
  } finally {
    btn.disabled = false;
  }
}

function renderScript() {
  const sc = S.dubScript, box = $('#scriptList');
  if (!sc) { box.classList.add('hide'); return; }
  const edited = sc.units.filter(u => u.text !== u.base).length;
  $('#scriptCount').textContent = `${sc.units.length} câu đọc · ${S.cues.length} dòng phụ đề`
    + (edited ? ` · ${edited} câu đã sửa` : '');
  $('#scriptBtn').innerHTML = `${icon('refresh')} Dựng lại`;
  $('#scriptDl').classList.remove('hide');
  box.classList.remove('hide');
  box.innerHTML = sc.units.map((u, k) => `
    <div class="script-row${u.text !== u.base ? ' edited' : ''}" data-k="${k}">
      <div class="script-meta">
        <span class="t">${fmtTime(u.start)}</span>
        ${u.speaker ? `<span class="spk s${spkSlot(u.speaker)}">${esc(spkName(u.speaker))}</span>` : ''}
        <span class="n muted">${u.cues.length} dòng</span>
      </div>
      <textarea rows="1" spellcheck="false" aria-label="Câu đọc ${k + 1}">${esc(u.text)}</textarea>
      <button type="button" class="btn sm ghost reset" title="Trả về câu tự dựng" aria-label="Trả về câu tự dựng">${icon("rotate")} Trả về</button>
    </div>`).join('');
  box.querySelectorAll('textarea').forEach(fitArea);
}

function fitArea(t) {
  t.style.height = 'auto';
  t.style.height = t.scrollHeight + 2 + 'px';
}

function scriptStale() {
  return S.dubScript && S.dubScript.sig !== scriptSig();
}

/** Câu đã sửa để gửi kèm lúc xuất (rỗng nếu chưa sửa câu nào). */
function collectScript() {
  if (!S.dubScript) return [];
  return S.dubScript.units
    .filter(u => u.text.trim() && u.text !== u.base)
    .map(u => ({ cues: u.cues, base: u.base, text: u.text.trim() }));
}

function scriptText() {
  return S.dubScript.units.map(u =>
    `[${fmtTime(u.start)}] ${u.speaker ? spkName(u.speaker) + ': ' : ''}${u.text}`).join('\n') + '\n';
}

$('#scriptBtn').addEventListener('click', buildScript);
$('#scriptDl').addEventListener('click', () => {
  if (!S.dubScript) return;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([scriptText()], { type: 'text/plain;charset=utf-8' }));
  a.download = (S.mediaName || 'video').replace(/\.[^.]+$/, '') + '.kichban.txt';
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
});
$('#scriptList').addEventListener('input', e => {
  const row = e.target.closest('.script-row');
  if (!row || e.target.tagName !== 'TEXTAREA') return;
  const u = S.dubScript.units[+row.dataset.k];
  u.text = e.target.value;
  row.classList.toggle('edited', u.text !== u.base);
  fitArea(e.target);
  const edited = S.dubScript.units.filter(x => x.text !== x.base).length;
  $('#scriptCount').textContent = `${S.dubScript.units.length} câu đọc · ${S.cues.length} dòng phụ đề`
    + (edited ? ` · ${edited} câu đã sửa` : '');
});
$('#scriptList').addEventListener('click', e => {
  const b = e.target.closest('.reset');
  if (!b) return;
  const row = b.closest('.script-row');
  const u = S.dubScript.units[+row.dataset.k];
  u.text = u.base;
  renderScript();
});

/** Phụ đề đổi sau khi dựng kịch bản: báo để dựng lại; đổi hẳn dự án thì bỏ kịch bản cũ. */
function markScriptStale() {
  const sc = S.dubScript;
  if (!sc) return;
  const maxIdx = Math.max(-1, ...sc.units.flatMap(u => u.cues));
  if (maxIdx >= S.cues.length) {
    S.dubScript = null;
    $('#scriptList').classList.add('hide');
    $('#scriptDl').classList.add('hide');
    $('#scriptCount').textContent = '';
    $('#scriptBtn').innerHTML = `${icon('file-text')} Dựng kịch bản`;
    return;
  }
  const stale = scriptStale();
  $('#scriptList').classList.toggle('stale', stale);
  $('#scriptMsg').textContent = stale ? 'Phụ đề đã đổi — bấm Dựng lại để cập nhật kịch bản.' : '';
}

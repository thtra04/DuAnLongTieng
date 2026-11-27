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
  if (on) $('#draftVoices').open = true;
  if (on && !S.voicesLoaded) await loadVoices();
  if (on) renderSpeakerVoices();
});

let loadingVoices;
function loadVoices() {
  loadingVoices ||= fetchVoices().finally(() => { loadingVoices = null; });
  return loadingVoices;
}
$('#draftVoices').addEventListener('toggle', () => {
  if ($('#draftVoices').open && !S.voicesLoaded) loadVoices();
});

async function fetchVoices() {
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
    const savedVoice = S.analyzed?.dub_review?.playback?.voice;
    if (savedVoice && [...sel.options].some(o => o.value === savedVoice)) sel.value = savedVoice;
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

$('#dubTest').addEventListener('click', () => auditionCue(Math.max(0, S.activeCue)));

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

function useDetectedProfiles(speakers) {
  for (const s of speakers || []) {
    if (s.gender && !S.speakerGenders[s.id]) S.speakerGenders[s.id] = s.gender;
    if (s.age && !S.speakerAges[s.id]) S.speakerAges[s.id] = s.age;
    if (s.name && !S.speakerNames[s.id]) S.speakerNames[s.id] = s.name;
  }
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
  const toggle = $('#diarizeOn'), token = $('#hfToken'), hint = $('#diarizeHint'), check = $('#diarizeCheck');
  const state = d.state || (d.available ? 'configured' : 'needs_token');
  const needsHub = ['needs_token', 'configured'].includes(state);
  const links = $('#diarizeModels');
  links.replaceChildren();
  for (const repo of d.model_pages || [d.model]) {
    if (!/^[\w.-]+\/[\w.-]+$/.test(repo || '')) continue;
    const a = document.createElement('a');
    a.href = 'https://huggingface.co/' + repo;
    a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = repo;
    if (links.childNodes.length) links.append(' và ');
    links.append(a);
  }
  if (!links.childNodes.length) links.textContent = 'trang model (bỏ qua nếu dùng bản cục bộ)';
  token.placeholder = d.has_token ? 'Để trống để dùng token máy chủ' : 'hf_...';
  const notes = {
    configured: 'Đã cấu hình token trên máy chủ. Có thể kiểm tra quyền trước khi chạy.',
    cached: 'Đã có các tệp model trong cache. Không cần nhập token.',
    loaded: 'Model đã nạp trên máy chủ. Không cần nhập token.',
    local_config: 'Đang dùng cấu hình model cục bộ. Các trọng số sẽ được kiểm tra khi nạp.',
    missing_dependency: `${d.reason} Chủ máy có thể dùng: uv sync --inexact --extra diarize`,
    needs_token: d.reason || 'Cần token đọc cho lần tải đầu tiên.',
    offline: d.reason,
  };
  let revision = 0;
  function refresh() {
    revision++;
    const on = toggle.checked;
    $('#diarizeOpts').classList.toggle('hide', !on);
    $('#numSpeakers').disabled = !on;
    $('#hfTokenWrap').classList.toggle('hide', !needsHub);
    token.disabled = !on || !needsHub;
    if (token.disabled) token.value = '';
    check.classList.toggle('hide', !needsHub);
    check.disabled = !on || !needsHub || (!d.has_token && !token.value.trim());
    hint.textContent = token.value.trim() ? 'Token không được lưu vào dự án. Bấm kiểm tra để xác minh quyền đọc model.'
      : notes[state] || d.reason;
  }
  toggle.onchange = token.oninput = refresh;
  $('#diarizeBasic').onclick = () => {
    toggle.checked = false;
    $('#genderOn').checked = true;
    refresh();
    $('#genderOn').focus();
    toast('Đã bật tách vai theo từng câu, không cần token. Nếu không dùng được WeSpeaker, tool chỉ ước lượng theo cao độ.', 'ok', 6500);
  };
  check.onclick = async () => {
    const request = ++revision;
    check.disabled = true;
    hint.textContent = 'Đang kiểm tra quyền đọc trên Hugging Face…';
    try {
      const r = await api('/api/diarize/check', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ hf_token: token.value.trim() }) });
      if (request === revision) hint.textContent = (r.ok ? 'Đã kiểm tra: ' : 'Chưa dùng được: ') + r.message;
    } catch (e) {
      if (request === revision) hint.textContent = 'Không kiểm tra được: ' + e.message;
    } finally {
      if (request === revision) check.disabled = false;
    }
  };
  refresh();
}

function diarizeOptions() {
  if (!$('#diarizeOn').checked) return { diarize: false };
  const d = S.sys.diarize || {}, count = $('#numSpeakers'), field = $('#hfToken');
  if (['missing_dependency', 'offline'].includes(d.state)) {
    toast(d.reason, 'warn');
    return null;
  }
  if (!count.reportValidity()) return null;
  const token = field.disabled ? '' : field.value.trim();
  if ((!d.available && !token) || (token && !/^hf_\S+$/.test(token))) {
    field.focus();
    toast('Dùng token đọc Hugging Face hoặc chọn “Dùng cách không cần token”.', 'warn');
    return null;
  }
  return { diarize: true, num_speakers: count.value ? count.valueAsNumber : null, ...(token ? { hf_token: token } : {}) };
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
    const i = S.cues.findIndex(c => c.speaker === btn.dataset.spk);
    if (i >= 0) auditionCue(i);
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

/* ------------------------- kịch bản lồng tiếng -------------------------- */
// The server binds the approved reading lines to this project's cue revision.
S.dubScript = null;

function scriptSig() {
  return JSON.stringify([
    S.jobId, S.analyzed?.source_lang, S.analyzed?.target_lang, S.cues, $('#dubShorten').checked,
  ]);
}

const unitKey = u => JSON.stringify([u.cues, u.start, u.end, u.speaker, u.base ?? u.text]);
let scriptRequest = 0;

function readingMix() {
  return { voice: $('#dubVoice').value, voices: collectSpeakerVoices(), style: $('#dubStyle').value || 'tu_nhien',
    max_speed: +$('#dubSpeed').value / 100, offset: +$('#stOffset').value || 0 };
}

function mixKey(m) {
  return JSON.stringify([m.voice, m.style, m.max_speed, m.offset, Object.entries(m.voices).sort()]);
}

function restoreReadingMix(m) {
  if (!m) return;
  Object.assign(S.speakerVoices, m.voices);
  if (S.voicesLoaded) $('#dubVoice').value = m.voice;
  $('#dubStyle').value = m.style;
  $('#dubSpeed').value = Math.round(m.max_speed * 100);
  $('#dubSpeed').dispatchEvent(new Event('input'));
  $('#stOffset').value = m.offset;
  $('#stOffset').dispatchEvent(new Event('input'));
}

function auditionSettings(u) {
  return { voice: S.speakerVoices?.[u.speaker] || $('#dubVoice').value, style: $('#dubStyle').value || 'tu_nhien',
    max_speed: +$('#dubSpeed').value / 100, offset: +$('#stOffset').value || 0 };
}

function auditionKey(u) { return JSON.stringify([u.text, auditionSettings(u)]); }
function takeIdentity(u, settings = auditionSettings(u)) { return JSON.stringify([u.text.trim(), settings.voice, settings.style]); }
function selectedVariant(u) { return u.variant && u.variant.for === takeIdentity(u) ? u.variant.id : undefined; }
function checkedTake(u) { return u.monitor && u.monitor.key === auditionKey(u) ? u.monitor : null; }

function takeMessage(u) {
  const check = checkedTake(u);
  return !check ? '' : check.over ? `Dòng #${u.cues[0] + 1} vượt khung ${check.over.toFixed(3)}s. `
    + 'Rút gọn lời đọc, nới mốc hoặc tăng tốc tối đa rồi nghe lại.' : 'Bản nghe thử này sẽ dùng khi xuất.';
}

function paintTake(u, row) {
  row?.querySelector('.retake')?.classList.toggle('hide', !u.monitor && !u.variant);
  const note = row?.querySelector('.script-check');
  if (note) {
    note.textContent = takeMessage(u);
    note.classList.toggle('over', !!checkedTake(u)?.over);
  }
}

function scriptCounts(sc) {
  const count = sc.units.filter(u => u.text.trim()).length, edited = sc.units.filter(u => u.text !== u.base).length;
  return `${count} câu đọc · ${S.cues.length} dòng phụ đề` + (edited ? ` · ${edited} câu đã sửa` : '');
}

async function buildScript() {
  const btn = $('#scriptBtn');
  if (!S.cues?.length) return toast('Chưa có phụ đề để dựng kịch bản.', 'warn');
  btn.disabled = true;
  const request = ++scriptRequest;
  const sig = scriptSig(), project = S.jobId;
  $('#scriptMsg').textContent = 'Đang dựng…';
  try {
    const r = await api('/api/tts/script', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cues: S.cues, project, source_lang: S.analyzed?.source_lang || '',
        target_lang: S.analyzed?.target_lang || '',
        shorten: $('#dubShorten').checked,
      }),
    });
    // giữ lại câu đã sửa nếu câu đó vẫn y như cũ
    if (request !== scriptRequest) return;
    if (sig !== scriptSig()) {
      $('#scriptMsg').textContent = 'Kịch bản đã đổi trong lúc dựng. Hãy dựng lại.';
      return;
    }
    const old = new Map((S.dubScript?.project === project ? S.dubScript.units : []).map(u => [unitKey(u), u]));
    const units = r.units.map(u => {
      const prev = old.get(unitKey(u));
      return { ...u, base: u.text, text: prev ? prev.text : u.text, variant: prev?.variant,
        monitor: S.dubScript?.sig === sig ? prev?.monitor : null };
    });
    const saved = !S.dubScript && S.analyzed?.dub_review;
    const restore = saved && saved.revision === r.revision && saved.units.length === units.length;
    if (restore) units.forEach((u, i) => {
      u.text = saved.units[i].text;
      if (saved.units[i].variant && saved.playback) {
        const m = saved.playback;
        u.variant = { id: saved.units[i].variant, for: takeIdentity(u, { voice: m.voices[u.speaker] || m.voice, style: m.style }) };
      }
    });
    S.dubScript = { units, sig, project, revision: r.revision, issues: r.issues || [], translated: r.use_translation,
      approved: restore && saved.token, playback: restore && saved.playback };
    renderScript();
    return S.dubScript;
  } catch (e) {
    if (request !== scriptRequest || project !== S.jobId) return;
    $('#scriptMsg').textContent = '';
    toast('Không dựng được kịch bản: ' + e.message, 'err', 7000);
  } finally {
    if (request === scriptRequest) btn.disabled = false;
  }
}

function renderScript() {
  const sc = S.dubScript, box = $('#scriptList');
  if (!sc) { box.classList.add('hide'); return; }
  $('#scriptCount').textContent = scriptCounts(sc);
  $('#scriptBtn').innerHTML = `${icon('refresh')} Dựng lại`;
  $('#scriptDl').classList.remove('hide');
  box.classList.remove('hide');
  box.classList.remove('stale');
  box.inert = false;
  $('#scriptIssues').innerHTML = sc.issues.length ? `<b>Cần sửa ${sc.issues.length} dòng trước khi duyệt:</b> ` +
    sc.issues.map(x => `<button type="button" class="btn sm ghost" data-fix-cue="${x.cue}">#${x.cue + 1} · ${fmtTime(S.cues[x.cue].start)} · ${esc(x.reason)}</button>`).join(' ') : '';
  box.innerHTML = sc.units.map((u, k) => `${scriptMinuteHeading(sc.units, k) ? `<b>${scriptMinuteHeading(sc.units, k)}</b>` : ''}
    <div class="script-row${u.text !== u.base ? ' edited' : ''}" data-k="${k}">
      <div class="script-meta">
        <span class="t">${fmtTime(u.start)}</span>
        ${u.speaker ? `<span class="spk s${spkSlot(u.speaker)}">${esc(spkName(u.speaker))}</span>` : ''}
        <span class="n muted">#${u.cues.map(i => i + 1).join(', #')}</span>
        <button type="button" class="btn sm ghost" data-audition="${u.cues[0]}">${icon('volume')} Xem &amp; nghe</button>
        <button type="button" class="btn sm ghost retake${u.monitor || u.variant ? '' : ' hide'}" data-retake="${u.cues[0]}">Tạo lượt đọc khác</button>
      </div>
      <small class="script-sub muted">Phụ đề: ${esc(u.cues.map(i => sc.translated ? S.cues[i].text2 || 'Chưa có bản dịch' : S.cues[i].text).join(' '))}</small>
      <textarea rows="1" spellcheck="false" aria-label="Câu đọc ${k + 1}">${esc(u.text)}</textarea>
      <small class="script-check muted${checkedTake(u)?.over ? ' over' : ''}">${esc(takeMessage(u))}</small>
      <button type="button" class="btn sm ghost reset" title="Trả về câu tự dựng" aria-label="Trả về câu tự dựng">${icon("rotate")} Trả về</button>
    </div>`).join('');
  const fields = [...box.querySelectorAll('textarea')], heights = fields.map(t => t.scrollHeight);
  fields.forEach((t, i) => { if (heights[i]) t.style.height = heights[i] + 2 + 'px'; });
  syncScriptApproval();
}

function scriptMinuteHeading(units, k) {
  const m = Math.floor(units[k].start / 60);
  return k === 0 || m !== Math.floor(units[k - 1].start / 60) ? `Phút ${m} · ${fmtDur(m * 60)}` : '';
}

function fitArea(t) {
  t.style.height = 'auto';
  t.style.height = t.scrollHeight + 2 + 'px';
}

function scriptStale() {
  return S.dubScript && S.dubScript.sig !== scriptSig();
}

function approvedScript() {
  const sc = S.dubScript;
  if (!sc?.approved || scriptStale()) return null;
  if (sc.playback && S.voicesLoaded && mixKey(sc.playback) !== mixKey(readingMix())) return null;
  return sc.approved;
}

function syncScriptApproval() {
  const sc = S.dubScript, stale = scriptStale();
  const empty = sc?.units.find(u => !u.text.trim());
  const over = sc?.units.find(u => u.monitor?.over && checkedTake(u));
  const ready = sc && !stale && !sc.issues.length && sc.units.length && !empty && !over;
  if (sc && !ready) sc.approved = false;
  const approved = approvedScript();
  $('#scriptApprove').disabled = !ready || !!approved || sc.saving;
  $('#scriptApprove').textContent = approved ? 'Đã duyệt' : 'Duyệt kịch bản này';
  $('#scriptMsg').textContent = stale ? 'Phụ đề đã đổi — bấm Dựng lại để đối chiếu.' :
    over ? takeMessage(over) : approved ? 'Có thể bật lồng tiếng.' :
    sc?.approved ? 'Giọng, tốc độ hoặc độ lệch mốc đã đổi. Hãy nghe và duyệt lại.' :
    empty ? `Dòng #${empty.cues[0] + 1} đang trống lời đọc.` :
    sc && !ready ? 'Chưa đủ lời đọc để duyệt.' :
    sc ? 'Chưa duyệt — kiểm tra lời đọc trước khi lồng tiếng.' : '';
  const toggle = $('#dubOn');
  toggle.disabled = (!!S.projectId && !S.videoSrc) || (!toggle.checked && !approved);
}

$('#scriptApprove').addEventListener('click', async () => {
  if ($('#scriptApprove').disabled || scriptStale()) return;
  const sc = S.dubScript, project = S.jobId;
  if (!$('#cueForm').classList.contains('hide'))
    return toast('Áp dụng hoặc hủy câu đang sửa trước khi duyệt.', 'warn');
  const rows = () => sc.units.map(u => ({ cues: u.cues, text: u.text.trim(), variant: selectedVariant(u) }));
  const edits = () => JSON.stringify(sc.units.map(u => [u.text, u.variant?.id]));
  const atClick = edits();
  sc.saving = true;
  $('#scriptApprove').disabled = true;
  try {
    if (S.sys?.tts?.available && !S.voicesLoaded) {
      await loadVoices();
      if (!S.voicesLoaded) throw new Error('Chưa nạp được giọng đọc.');
    }
    if (project !== S.jobId || sc !== S.dubScript || scriptStale()) return;
    if (atClick !== edits()) throw new Error('Lời đọc đã đổi trong khi nạp giọng. Hãy kiểm tra và duyệt lại.');
    const review = { revision: sc.revision, units: rows() };
    const playback = S.voicesLoaded ? readingMix() : null, shorten = $('#dubShorten').checked;
    const r = await api(`/api/projects/${encodeURIComponent(project)}/dub-review`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({
        cues: S.cues, source_lang: S.analyzed.source_lang, target_lang: S.analyzed.target_lang,
        shorten, playback, revision: S.analyzed.revision,
        previous: S.analyzed.dub_review?.token, review }),
    });
    if (project !== S.jobId) return;
    S.analyzed.dub_review = { ...review, token: r.token, playback: r.playback, shorten };
    S.analyzed.revision = r.revision;
    if (sc === S.dubScript && !scriptStale() && JSON.stringify(rows()) === JSON.stringify(review.units)) {
      sc.approved = r.token;
      sc.playback = r.playback;
      $('#minuteStatus').textContent = 'Đã lưu phụ đề và kịch bản đọc';
    }
  } catch (e) {
    if (project === S.jobId) toast('Chưa duyệt: ' + e.message, 'warn', 8000);
  } finally {
    sc.saving = false;
    if (project === S.jobId) syncScriptApproval();
  }
});
$('#scriptIssues').addEventListener('click', e => {
  const b = e.target.closest('[data-fix-cue]');
  if (b && !scriptStale()) {
    showCueForm(S.cues[+b.dataset.fixCue]);
    const issue = S.dubScript.issues.find(x => x.cue === +b.dataset.fixCue);
    $(issue?.field === 'start' ? '#cueStart' : S.dubScript.translated ? '#cueTranslation' : '#cueOriginal').focus();
  }
});
$('#dubOn').addEventListener('change', syncScriptApproval);

function readingSettingsChanged() {
  stopAudition();
  S.dubScript?.units.forEach((u, k) => {
    if (u.monitor) paintTake(u, $(`#scriptList [data-k="${k}"]`));
  });
  syncScriptApproval();
}
$('#draftVoices').addEventListener('change', readingSettingsChanged);
$('#spkList').addEventListener('click', e => { if (e.target.closest('.spkgender')) readingSettingsChanged(); });
$('#stOffset').addEventListener('input', readingSettingsChanged);

function scriptText() {
  return S.dubScript.units.map((u, k, units) => {
    const title = scriptMinuteHeading(units, k);
    return (title ? title + '\n' : '') + `[${fmtTime(u.start)} → ${fmtTime(u.end)}] ${u.speaker ? spkName(u.speaker) + ': ' : ''}${u.text}`;
  }).join('\n') + '\n';
}

$('#scriptBtn').addEventListener('click', buildScript);
$('#scriptDl').addEventListener('click', () => {
  if (!S.dubScript) return;
  if (scriptStale()) return toast('Dựng lại kịch bản trước khi tải để lấy đúng mốc mới.', 'warn');
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
  S.dubScript.approved = false;
  syncScriptApproval();
  row.classList.toggle('edited', u.text !== u.base);
  fitArea(e.target);
  paintTake(u, row);
  $('#scriptCount').textContent = scriptCounts(S.dubScript);
});
$('#scriptList').addEventListener('click', e => {
  const b = e.target.closest('.reset');
  if (!b) return;
  const row = b.closest('.script-row');
  const u = S.dubScript.units[+row.dataset.k];
  u.text = u.base;
  S.dubScript.approved = false;
  stopAudition();
  renderScript();
});

/** Phụ đề đổi sau khi dựng kịch bản: báo để dựng lại; đổi hẳn dự án thì bỏ kịch bản cũ. */
function markScriptStale() {
  stopAudition();
  const sc = S.dubScript;
  if (!sc || sc.project !== S.jobId) {
    S.dubScript = null;
    $('#scriptList').classList.add('hide');
    $('#scriptDl').classList.add('hide');
    $('#scriptCount').textContent = '';
    $('#scriptMsg').textContent = '';
    $('#scriptIssues').textContent = '';
    $('#scriptBtn').innerHTML = `${icon('file-text')} Dựng kịch bản`;
    if ($('#dubOn').checked) {
      $('#dubOn').checked = false;
      $('#dubOn').dispatchEvent(new Event('change'));
    }
    return syncScriptApproval();
  }
  const stale = scriptStale();
  $('#scriptList').classList.toggle('stale', stale);
  $('#scriptList').inert = !!stale;
  syncScriptApproval();
}
$('#dubShorten').addEventListener('change', markScriptStale);

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
        ? '🧬 Nhân bản giọng người nói trong video'
        : '🧬 Nhân bản giọng — chưa dùng được (cần uv sync --extra clone)') +
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

$('#dubKeepOrig').addEventListener('change', e => {
  $('#origVolWrap').style.opacity = e.target.checked ? '1' : '.4';
  $('#dubOrigVol').disabled = !e.target.checked;
});

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
  (list || []).forEach(c => {
    if (c.name) S.speakerNames[c.label] = c.name;
    if (c.voice) S.speakerVoices[c.label] = c.voice;
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

  // Mặc định: mỗi nhân vật một giọng dựng sẵn khác nhau. Chọn giọng có sẵn thay
  // vì nhân bản vì nhân bản chậm hơn nhiều và có thể trượt ở vai ít thoại —
  // muốn nhân bản thì đổi một cú bấm.
  speakers.forEach((s, i) => {
    if (!S.speakerVoices[s.id] && voices.length) {
      S.speakerVoices[s.id] = voices[i % voices.length].id;
    }
  });

  list.innerHTML = speakers.map(s => `
    <div class="spkrow" data-spk="${esc(s.id)}">
      <span class="spk s${spkSlot(s.id)} big">${esc(s.id)}</span>
      <div class="spkmain">
        <div class="spkline">
          <input class="spkname" type="text" value="${esc(spkName(s.id))}"
                 data-spk="${esc(s.id)}" maxlength="40" aria-label="Tên nhân vật ${esc(s.id)}">
          <span class="muted">${s.lines} dòng · ${Math.round(s.seconds)}s nói</span>
        </div>
        ${s.sample ? `<div class="spksample">“${esc(s.sample)}”</div>` : ''}
        <div class="spkline">
          <select class="spkvoice" data-spk="${esc(s.id)}" aria-label="Giọng cho ${esc(s.id)}">
            ${voices.map(v => `<option value="${esc(v.id)}"${S.speakerVoices[s.id] === v.id ? ' selected' : ''}>${esc(v.label)}</option>`).join('')}
            <option value="${esc(cloneId)}"${S.speakerVoices[s.id] === cloneId ? ' selected' : ''}
              ${S.cloneOk === false ? ' disabled' : ''}>
              🧬 Nhân bản chính giọng nhân vật này
            </option>
          </select>
          <button class="btn sm ghost spktest" data-spk="${esc(s.id)}">🔊</button>
        </div>
      </div>
    </div>`).join('');

  $$('.spkvoice', list).forEach(sel => sel.addEventListener('change', () => {
    S.speakerVoices[sel.dataset.spk] = sel.value;
    saveCharacter(sel.dataset.spk, { voice: sel.value, style: $('#dubStyle').value });
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


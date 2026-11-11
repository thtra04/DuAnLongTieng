/* frontend/js/editor.js — bước 4: biên tập phụ đề, xem trước chồng lên video.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
/* --------------------------- bước 4: biên tập --------------------------- */
function setupEditor() {
  const player = $('#player');
  const src = S.videoSrc || (S.sourceType === 'file'
    ? `${API_BASE}/api/media/${S.mediaId}/stream`
    : `${API_BASE}/api/media/${S.jobId}/stream`);
  if (player.dataset.src !== src) {
    player.src = src;
    player.dataset.src = src;
    // video khác -> bản đã xuất của video trước không còn liên quan
    if (typeof setMonitorOutput === 'function') setMonitorOutput(null);
  }
  // Không có video gốc thì chỉ xuất được file chữ — khoá sẵn các mục cần video
  const noVideo = !!S.projectId && !S.videoSrc;
  ['#outBurn', '#outSoft', '#dubOn'].forEach(id => {
    const el = $(id);
    if (!el) return;
    if (noVideo && el.checked) { el.checked = false; el.dispatchEvent(new Event('change')); }
    el.disabled = noVideo;
    el.closest('.check, .switch')?.classList.toggle('off', noVideo);
  });

  // Nếu không dịch, mặc định hiển thị nguyên ngữ
  if (!S.analyzed.target_lang) {
    S.display = 'main';
    $$('.tab[data-disp]').forEach(t => t.classList.toggle('active', t.dataset.disp === 'main'));
    $$('.tab[data-disp]').forEach(t => { if (t.dataset.disp !== 'main') t.disabled = true; });
  }

  $('#cueCount').textContent = `${S.cues.length} dòng`;
  renderCues();

  _lastOverlayText = null;  // bộ phụ đề mới -> đừng so với chữ của bộ cũ
  player.onplay = startSync;
  player.onplaying = startSync;
  player.onpause = () => { stopSync(); onTime(); };
  player.onended = () => { stopSync(); onTime(); };
  player.onseeked = onTime;
  player.onratechange = startSync;
  player.ontimeupdate = onTime;  // phao dự phòng khi vòng lặp chưa chạy
  S.activeCue = -1;
  onTime();
  updateOverlay();

  if (!S.analyzed.target_lang) $('#outSrtBoth').closest('.check').classList.add('hide');
  initMask();
  applyOverlayStyle();
  // Lồng tiếng đang bật từ dự án trước thì bảng vai phải dựng lại theo vai của bộ phụ đề mới,
  // không thì vẫn hiện vai cũ cho tới khi người dùng tắt rồi bật lại lồng tiếng.
  if ($('#dubOn').checked && S.voicesLoaded) renderSpeakerVoices();
  if (typeof setupTimeline === 'function') setupTimeline();
}

function renderCues() {
  setupFitButtons();
  const speakerIds = knownSpeakerIds();
  const list = $('#cueList');
  list.innerHTML = S.cues.map((c, i) => {
    const showTr = S.display !== 'main' && S.analyzed.target_lang;
    const len = Math.max(c.text.length, (c.text2 || '').length);
    const cps = (len / Math.max(0.3, c.end - c.start)).toFixed(0);
    const sourceUnits = lengthUnits(c.text);
    const translatedUnits = lengthUnits(c.text2 || '');
    const tooLong = Boolean(c.text2 && translatedUnits > sourceUnits * 1.25);
    return `
    <div class="cue${tooLong ? ' too-long' : ''}" data-i="${i}">
      <div class="cue-top">
        <span class="idx">#${i + 1}</span>
        <span class="tc">${fmtTime(c.start)} → ${fmtTime(c.end)}</span>
        ${c.speaker
          ? `<button type="button" class="spk s${spkSlot(c.speaker)}" data-i="${i}" title="Vai ${esc(c.speaker)} — bấm để chuyển dòng này sang vai khác">${esc(spkName(c.speaker))}</button>`
          : (speakerIds.length ? `<button type="button" class="spk none" data-i="${i}" title="Dòng này chưa gán vai — bấm để gán">+ vai</button>` : '')}
        <span class="len ${cps > 22 ? 'warn' : ''}" title="ký tự/giây — trên 22 là hơi nhanh">${cps} cps</span>
        ${tooLong ? '<span class="len warn" title="Bản dịch dài hơn 125% bản gốc — nên rút gọn trước khi lồng tiếng">Dài</span>' : ''}
        ${cueIsLong(c) && showTr ? `<button type="button" class="fit-btn" data-i="${i}" title="Dịch lại dòng này cho gọn, vừa khung giờ — dùng engine đang chọn ở bước 2">Dịch gọn</button>` : ''}
      </div>
      <textarea class="src" rows="1" data-i="${i}">${escapeHtml(c.text)}</textarea>
      ${showTr ? `<textarea class="tr" rows="1" data-i="${i}">${escapeHtml(c.text2 || '')}</textarea>` : ''}
    </div>`;
  }).join('');

  // Bấm nhãn vai để sửa dòng bị gán nhầm: xoay vòng qua các vai đã biết rồi về "chưa gán"
  $$('.spk[data-i]', list).forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    const c = S.cues[+b.dataset.i];
    const ring = [...speakerIds, ''];
    c.speaker = ring[(ring.indexOf(c.speaker || '') + 1) % ring.length];
    renderCues();
    renderSpeakerVoices();
  }));

  $$('.cue', list).forEach(el => el.addEventListener('click', e => {
    if (e.target.tagName === 'TEXTAREA') return;
    const i = +el.dataset.i;
    $('#player').currentTime = S.cues[i].start + 0.02;
    if (hasTimeline) tlReveal(S.cues[i].start);
  }));
  // Sửa chữ thì khối trên dòng thời gian đổi theo, và thời lượng đọc được dự đoán lại
  const hasTimeline = typeof renderTimeline === 'function';
  const retitle = i => {
    if (!hasTimeline) return;
    const b = document.querySelector(`#tlInner .tl-lane[data-spk] .tl-blk[data-i="${i}"] b`);
    if (b) b.textContent = tlBlockText(S.cues[i]);
    tlQueueBudget();
  };
  $$('textarea.src', list).forEach(t => t.addEventListener('input', () => {
    S.cues[+t.dataset.i].text = t.value;
    updateOverlay();
    retitle(+t.dataset.i);
  }));
  $$('textarea.tr', list).forEach(t => t.addEventListener('input', () => {
    S.cues[+t.dataset.i].text2 = t.value;
    updateOverlay();
    retitle(+t.dataset.i);
  }));
  $$('.fit-btn', list).forEach(b => b.addEventListener('click', e => {
    e.stopPropagation();
    fitLines([+b.dataset.i], b);
  }));
  syncFitButtons();
  if (hasTimeline && TL.dur) renderTimeline();
}

/* ------------------------------ dịch gọn câu dài ------------------------------ */
// Dòng bị gắn cờ: bản dịch dài quá 125 % bản gốc ("Dài") hoặc quá 22 ký tự/giây ("cps" vàng)
function cueIsLong(c) {
  if (!c.text2) return false;
  if (lengthUnits(c.text2) > lengthUnits(c.text) * 1.25) return true;
  return c.text2.length / Math.max(0.3, c.end - c.start) > 22;
}

function syncFitButtons() {
  const all = $('#fitAllBtn');
  if (!all) return;
  const n = S.display !== 'main' && S.analyzed && S.analyzed.target_lang ? S.cues.filter(cueIsLong).length : 0;
  all.classList.toggle('hide', !n);
  $('#fitAllText').textContent = `Dịch gọn ${n} câu dài`;
  $('#fitUndoBtn').classList.toggle('hide', !(S.fitUndo && S.fitUndo.length));
}

async function fitLines(indices, btn) {
  if (S.fitBusy) return;
  if (!aiKeyOk()) {
    return toast('Engine AI đang chọn ở bước 2 chưa có API key — dán key ở bước 2 rồi bấm lại.', 'warn', 7000);
  }
  S.fitBusy = true;
  const label = btn ? btn.textContent : '';
  if (btn) { btn.disabled = true; btn.textContent = 'Đang dịch…'; }
  $('#fitAllBtn').disabled = true;
  try {
    const r = await api('/api/fit-lines', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        cues: S.cues.map(c => ({ start: c.start, end: c.end, text: c.text, text2: c.text2 || '', speaker: c.speaker || '' })),
        indices,
        source_lang: (S.analyzed && S.analyzed.source_lang) || '',
        target_lang: (S.analyzed && S.analyzed.target_lang) || $('#tgtLang').value,
        ...aiPayload(),
      }),
    });
    const how = { ai: 'engine AI dịch lại', nllb: 'NLLB + LoRA dịch lại', rules: 'bộ luật rút gọn (engine đang chọn không dịch gọn được)' }[r.method] || '';
    if (!r.changes.length) {
      toast(r.asked ? `Không câu nào gọn hơn được — ${how}.` : 'Không có câu nào đang dài.', 'warn', 7000);
    } else {
      S.fitUndo = r.changes.map(ch => ({ i: ch.i, text2: S.cues[ch.i].text2 }));
      r.changes.forEach(ch => { S.cues[ch.i].text2 = ch.text2; });
      const tight = r.changes.filter(ch => ch.fits).length;
      toast(`Đã dịch gọn ${r.changes.length}/${r.asked} câu (${tight} câu vừa hẳn khung) — ${how}.`, 'ok', 8000);
    }
  } catch (e) {
    toast(e.message, 'err', 9000);
  } finally {
    S.fitBusy = false;
    if (btn) { btn.disabled = false; btn.textContent = label; }
    $('#fitAllBtn').disabled = false;
    renderCues();
    updateOverlay();
    if (typeof tlQueueBudget === 'function') tlQueueBudget();
  }
}

function setupFitButtons() {
  if (S.fitBound) return;
  S.fitBound = true;
  $('#fitAllBtn').addEventListener('click', () => fitLines([], null));
  $('#fitUndoBtn').addEventListener('click', () => {
    (S.fitUndo || []).forEach(u => { if (S.cues[u.i]) S.cues[u.i].text2 = u.text2; });
    S.fitUndo = [];
    renderCues();
    updateOverlay();
    if (typeof tlQueueBudget === 'function') tlQueueBudget();
  });
}

function lengthUnits(text) {
  if (!/[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]/.test(text || '')) {
    return Math.max(1, (text || '').trim().split(/\s+/).filter(Boolean).length);
  }
  if (/[-]/.test(text || '') && !/[\u0080-\uFFFF]/.test(text || '')) {
    return Math.max(1, (text || '').trim().split(/\s+/).filter(Boolean).length);
  }
  return Math.max(1, (text || '').replace(/\s+/g, '').length);
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>]/g, m => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[m]));
}

$$('.tab[data-disp]').forEach(t => t.addEventListener('click', () => {
  if (t.disabled) return;
  $$('.tab[data-disp]').forEach(x => x.classList.remove('active'));
  t.classList.add('active');
  S.display = t.dataset.disp;
  renderCues();
  updateOverlay();
}));

function currentText(c) {
  if (S.display === 'main' || !c.text2) return c.text;
  if (S.display === 'second') return c.text2;
  return c.text + '\n' + c.text2;
}

let _lastOverlayText = null;
let _syncRaf = null;

/* Sự kiện `timeupdate` của thẻ video chỉ nổ ~4 lần/giây, nên phụ đề xem trước
   trễ tới ~250 ms so với tiếng. Lúc video đang chạy ta bám theo khung hình
   (~60 lần/giây) để chữ đổi đúng lúc; dừng phát thì tắt vòng lặp cho nhẹ máy. */
function startSync() {
  if (_syncRaf !== null) return;
  const tick = () => {
    _syncRaf = null;
    onTime();
    const p = $('#player');
    if (p && !p.paused && !p.ended) _syncRaf = requestAnimationFrame(tick);
  };
  _syncRaf = requestAnimationFrame(tick);
}

function stopSync() {
  if (_syncRaf !== null) {
    cancelAnimationFrame(_syncRaf);
    _syncRaf = null;
  }
}

function onTime() {
  const t = $('#player').currentTime + (+$('#stOffset').value || 0) * -1;
  const idx = cueAt(t);
  if (idx !== S.activeCue) {
    S.activeCue = idx;
    $$('.cue').forEach(el => el.classList.toggle('active', +el.dataset.i === idx));
    const el = $(`.cue[data-i="${idx}"]`);
    if (el) {
      const box = $('#cueList');
      const top = el.offsetTop - box.offsetTop;
      if (top < box.scrollTop || top > box.scrollTop + box.clientHeight - 90) {
        box.scrollTo({ top: top - 60, behavior: 'smooth' });
      }
    }
  }
  updateOverlayText();
  if (typeof timelineTick === 'function') timelineTick($('#player').currentTime);
}

/** Dòng phụ đề đang ứng với giây `t`, hoặc -1. Cue xếp theo giờ nên tìm nhị phân. */
function cueAt(t) {
  let lo = 0, hi = S.cues.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1, c = S.cues[mid];
    if (t < c.start) hi = mid - 1;
    else if (t > c.end) lo = mid + 1;
    else return mid;
  }
  return -1;
}

function updateOverlay() {
  updateOverlayText();
  applyOverlayStyle();
}

/** Chỉ đổi chữ — hàm này chạy mỗi khung hình nên phải thật nhẹ. */
function updateOverlayText() {
  const c = S.cues[S.activeCue];
  const text = c ? wrapPreview(currentText(c), +$('#stLineChars').value) : '';
  if (text === _lastOverlayText) return;  // không đụng DOM khi chữ không đổi
  _lastOverlayText = text;
  paintOverlay(text);
}

function paintOverlay(text) {
  const ov = $('#subOverlay');
  ov.style.opacity = text ? '1' : '0';
  // Kiểu "nền hộp" cần bọc <span> để nền bám theo từng dòng chữ
  if (text && $('#stBox').checked) {
    ov.innerHTML = `<span>${escapeHtml(text).replace(/\n/g, '<br>')}</span>`;
  } else {
    ov.textContent = text;
  }
}

function applyOverlayStyle() {
  if (typeof paintMask === 'function') paintMask();
  const ov = $('#subOverlay');
  const pw = $('#player').clientWidth || 640;
  const size = +$('#stSize').value * (pw / 1920) * 1.0;
  ov.style.fontSize = Math.max(10, size) + 'px';
  ov.style.color = $('#stColor').value;
  ov.style.fontFamily = $('#stFont').value + ', sans-serif';
  ov.style.fontWeight = $('#stBold').checked ? '800' : '500';
  const oc = $('#stOutlineColor').value, ow = Math.max(1, +$('#stOutline').value);
  ov.style.textShadow = $('#stBox').checked ? 'none'
    : `0 0 ${ow}px ${oc}, 0 0 ${ow * 2}px ${oc}, 0 ${ow / 2}px ${ow * 2}px rgba(0,0,0,.85)`;
  ov.className = 'sub-overlay ' + $('#stPos').value + ($('#stBox').checked ? ' boxed' : '');
  paintOverlay(_lastOverlayText || '');  // bật/tắt nền hộp -> vẽ lại chữ
  const mv = +$('#stMargin').value / 1080 * 100;
  if ($('#stPos').value === 'top') {
    ov.style.top = mv + '%'; ov.style.bottom = 'auto';
  } else if ($('#stPos').value === 'bottom') {
    // cộng thêm chiều cao thanh điều khiển để chữ không bị che khi xem trước —
    // trừ lúc đang che phụ đề gốc: khi đó chữ phải nằm đúng trong dải che như bản xuất
    const ctrl = $('#maskOn')?.checked ? 0 : 38;
    ov.style.bottom = `calc(${mv}% + ${ctrl}px)`;
    ov.style.top = 'auto';
  }
}

function wrapPreview(text, max) {
  return text.split('\n').map(line => {
    if (line.length <= max) return line;
    const words = line.split(' ');
    const out = []; let cur = '';
    for (const w of words) {
      const cand = (cur + ' ' + w).trim();
      if (cand.length <= max || !cur) cur = cand;
      else { out.push(cur); cur = w; }
    }
    if (cur) out.push(cur);
    return out.slice(0, 2).join('\n');
  }).join('\n');
}

['#stFont', '#stSize', '#stColor', '#stOutlineColor', '#stOutline', '#stPos',
  '#stMargin', '#stLineChars', '#stBold', '#stBox'].forEach(id => {
    $(id).addEventListener('input', updateOverlay);
    $(id).addEventListener('change', updateOverlay);
  });
// Lệch giờ đổi thì chọn lại dòng ngay, để thấy hiệu quả cả khi đang tạm dừng
['input', 'change'].forEach(ev => $('#stOffset').addEventListener(ev, onTime));
$$('.check').forEach(c => {
  const inp = $('input', c);
  if (inp) inp.addEventListener('change', () => c.classList.toggle('on', inp.checked));
});

$('#prevCue').addEventListener('click', () => jumpCue(-1));
$('#nextCue').addEventListener('click', () => jumpCue(1));
function jumpCue(dir) {
  const i = Math.max(0, Math.min(S.cues.length - 1, (S.activeCue < 0 ? 0 : S.activeCue) + dir));
  if (S.cues[i]) $('#player').currentTime = S.cues[i].start + 0.02;
}

$('#outBurn').addEventListener('change', e => {
  $('#burnOpts').classList.toggle('hide', !e.target.checked);
  if (e.target.checked && S.sys && !S.sys.ffmpeg.libass) {
    toast('ffmpeg hiện tại không nung được phụ đề. Chạy: uv run python -m app.setup_ffmpeg', 'err', 10000);
  }
});


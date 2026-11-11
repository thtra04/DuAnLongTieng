/* frontend/js/timeline.js — dòng thời gian của bước 4 (bố cục "bàn dựng phim").
   Mỗi nhân vật một rãnh, mỗi dòng phụ đề một khối: kéo khối để dời mốc giờ, kéo mép
   để co giãn, kéo sang rãnh khác để đổi vai. Rãnh "Lồng tiếng" vẽ thời lượng đọc dự
   đoán (máy chủ tính bằng đúng hàm lúc xuất) và tô đỏ phần tràn khung. Dưới cùng là
   sóng âm của tiếng gốc, hoặc giọng gốc / nhạc nền nếu dự án đã tách giọng.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */

const TL = {
  pps: 40,          // điểm ảnh mỗi giây
  fit: 4,           // pps để thấy trọn cả video
  dur: 0,
  drag: null,
  waves: [],        // [{id, label, peaks}]
  waveDur: 0,
  waveFor: '',      // dự án đã nạp sóng âm
  budget: [],       // [{cues, start, predicted, budget, over}]
  tolerance: 0.05,
  budgetTimer: 0,
  budgetSeq: 0,
  drawRaf: 0,
  bound: false,
};
const TL_MAX_PPS = 240;
const TL_MIN_LEN = 0.2;     // giây — khối ngắn hơn thì không còn bấm được
const TL_TICKS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600];

const tlEl = id => document.getElementById(id);
const tlClamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function setupTimeline() {
  if (!tlEl('tlInner')) return;
  const player = $('#player');
  const last = S.cues.length ? S.cues[S.cues.length - 1].end : 0;
  TL.dur = Math.max(last + 1, (S.analyzed?.info?.duration) || 0, player.duration || 0, 5);
  tlBind();
  tlFit();
  renderTimeline();
  tlLoadWaves();
  tlQueueBudget(0);
}

/* ------------------------------ dựng hình ------------------------------ */
function tlLanes() {
  const ids = knownSpeakerIds();
  const lanes = ids.map(id => ({ id, name: spkName(id), slot: spkSlot(id) }));
  if (!ids.length || S.cues.some(c => !c.speaker)) {
    lanes.push({ id: '', name: ids.length ? 'Chưa gán vai' : 'Phụ đề', slot: 0 });
  }
  return lanes;
}

function tlBlockText(c) {
  return (S.display !== 'main' && c.text2) ? c.text2 : c.text;
}

function renderTimeline() {
  const inner = tlEl('tlInner');
  if (!inner || !TL.dur) return;
  const lanes = tlLanes();
  const px = t => (t * TL.pps).toFixed(1);
  const hasDub = !!S.analyzed?.target_lang && S.cues.some(c => c.text2);

  let step = TL_TICKS[TL_TICKS.length - 1];
  for (const s of TL_TICKS) { if (s * TL.pps >= 72) { step = s; break; } }
  let ruler = '';
  for (let t = 0; t < TL.dur; t += step) {
    ruler += `<span style="left:${px(t)}px">${fmtTime(t).slice(0, -3)}</span>`;
  }

  const rows = lanes.map(l => {
    const blocks = S.cues.map((c, i) => ((c.speaker || '') === l.id
      ? `<div class="tl-blk s${l.slot}${i === S.activeCue ? ' active' : ''}" data-i="${i}" tabindex="0" role="button"
             style="left:${px(c.start)}px;width:${px(Math.max(0.05, c.end - c.start))}px"
             title="#${i + 1} · ${fmtTime(c.start)} → ${fmtTime(c.end)}"><i class="h l"></i><b>${escapeHtml(tlBlockText(c))}</b><i class="h r"></i></div>`
      : '')).join('');
    return `<div class="tl-lane" data-spk="${esc(l.id)}">${blocks}</div>`;
  }).join('');

  const dub = hasDub ? `<div class="tl-lane tl-dub" id="tlDub">${tlDubBlocks()}</div>` : '';
  const waves = TL.waves.map(w => `<div class="tl-lane tl-wave"><canvas data-wave="${esc(w.id)}"></canvas></div>`).join('');

  inner.style.width = px(TL.dur) + 'px';
  inner.innerHTML = `<div class="tl-ruler">${ruler}</div>${rows}${dub}${waves}<div class="tl-head" id="tlHead"></div>`;

  tlEl('tlNames').innerHTML = '<div class="tl-ruler"></div>'
    + lanes.map(l => `<div class="tl-name"><span class="spk s${l.slot}${l.id ? '' : ' none'}">${esc(l.name)}</span></div>`).join('')
    + (hasDub ? '<div class="tl-name" title="Thời lượng đọc dự đoán của từng câu lồng tiếng; phần đỏ là đọc tràn khung giờ">Lồng tiếng</div>' : '')
    + TL.waves.map(w => `<div class="tl-name tl-wave">${esc(w.label)}</div>`).join('');

  timelineTick($('#player').currentTime || 0);
  tlDrawWaves();
}

function tlDubBlocks() {
  const px = t => (t * TL.pps).toFixed(1);
  return TL.budget.map(it => {
    const over = it.over > TL.tolerance;
    const share = over ? (it.budget / it.predicted * 100).toFixed(1) : 100;
    const vn = x => x.toFixed(1).replace('.', ',');
    const label = over ? `tràn ${vn(it.over)} s` : '';
    const tip = `Dòng ${it.cues[0] + 1}${it.cues.length > 1 ? '–' + (it.cues[it.cues.length - 1] + 1) : ''}: `
      + `đọc khoảng ${vn(it.predicted)} s trong khung ${vn(it.budget)} s`;
    return `<div class="tl-blk dub${over ? ' over' : ''}" data-i="${it.cues[0]}" style="left:${px(it.start)}px;`
      + `width:${px(it.predicted)}px;--fit:${share}%" title="${esc(tip)}"><b>${label}</b></div>`;
  }).join('');
}

/* --------------------------- thu phóng, cuộn --------------------------- */
function tlFit() {
  const w = tlEl('tlScroll').clientWidth || 800;
  TL.fit = Math.max(0.5, w / TL.dur);
  // Mặc định thấy khoảng 45 giây: đủ rộng để đọc chữ trong khối
  TL.pps = tlClamp(w / Math.min(TL.dur, 45), TL.fit, TL_MAX_PPS);
  tlSyncZoom();
}

function tlSyncZoom() {
  const z = tlEl('tlZoom');
  if (z) z.value = Math.round(Math.log(TL.pps / TL.fit) / Math.log(TL_MAX_PPS / TL.fit) * 100) || 0;
}

function tlSetZoom(pps) {
  const sc = tlEl('tlScroll');
  const mid = (sc.scrollLeft + sc.clientWidth / 2) / TL.pps;
  TL.pps = tlClamp(pps, TL.fit, TL_MAX_PPS);
  renderTimeline();
  sc.scrollLeft = mid * TL.pps - sc.clientWidth / 2;
}

/** Gọi mỗi khung hình khi video chạy (editor.js › onTime): dời vạch phát và giữ nó trong tầm nhìn. */
function timelineTick(t) {
  const head = tlEl('tlHead');
  if (!head) return;
  const x = t * TL.pps;
  head.style.transform = `translateX(${x.toFixed(1)}px)`;
  const sc = tlEl('tlScroll');
  const p = $('#player');
  if (!TL.drag && p && !p.paused && (x < sc.scrollLeft || x > sc.scrollLeft + sc.clientWidth - 40)) {
    sc.scrollLeft = Math.max(0, x - sc.clientWidth * 0.2);
  }
  if (TL.activeShown !== S.activeCue) {
    TL.activeShown = S.activeCue;
    $$('.tl-blk.active', tlEl('tlInner')).forEach(b => b.classList.remove('active'));
    const cur = tlEl('tlInner').querySelector(`.tl-lane[data-spk] .tl-blk[data-i="${S.activeCue}"]`);
    if (cur) cur.classList.add('active');
  }
}

/** Đưa giây `t` vào giữa khung nhìn (bấm một dòng ở danh sách thoại thì dòng thời gian chạy theo). */
function tlReveal(t) {
  const sc = tlEl('tlScroll');
  const x = t * TL.pps;
  if (x < sc.scrollLeft + 30 || x > sc.scrollLeft + sc.clientWidth - 60) {
    sc.scrollLeft = Math.max(0, x - sc.clientWidth * 0.3);
  }
}

/* ------------------------------- kéo thả ------------------------------- */
function tlBind() {
  if (TL.bound) return;
  TL.bound = true;
  const inner = tlEl('tlInner'), sc = tlEl('tlScroll');

  inner.addEventListener('pointerdown', e => {
    if (e.button) return;
    const blk = e.target.closest('.tl-blk');
    if (!blk || blk.classList.contains('dub')) {
      // bấm chỗ trống / thước / khối lồng tiếng -> tua tới đó
      const t = blk ? S.cues[+blk.dataset.i].start + 0.02
        : (e.clientX - inner.getBoundingClientRect().left) / TL.pps;
      $('#player').currentTime = tlClamp(t, 0, TL.dur);
      return;
    }
    const i = +blk.dataset.i, c = S.cues[i];
    const mode = e.target.classList.contains('h') ? (e.target.classList.contains('l') ? 'l' : 'r') : 'move';
    // Dòng phụ đề phải giữ thứ tự thời gian (cueAt tìm nhị phân), nên khối chỉ đi được tới mép hàng xóm
    const lo = Math.min(c.start, i > 0 ? S.cues[i - 1].end : 0);
    const hi = Math.max(c.end, i < S.cues.length - 1 ? S.cues[i + 1].start : TL.dur);
    TL.drag = { i, mode, x: e.clientX, y: e.clientY, start: c.start, end: c.end, lo, hi, blk, moved: false,
                from: c.speaker || '', to: null };
    blk.setPointerCapture(e.pointerId);
    e.preventDefault();
  });

  inner.addEventListener('pointermove', e => {
    const d = TL.drag;
    if (!d) return;
    const dxp = e.clientX - d.x, dyp = e.clientY - d.y;
    if (!d.moved && Math.abs(dxp) < 4 && Math.abs(dyp) < 10) return;
    d.moved = true;
    d.blk.classList.add('dragging');
    const c = S.cues[d.i], dx = dxp / TL.pps;
    if (d.mode === 'move') {
      const shift = tlClamp(dx, d.lo - d.start, d.hi - d.end);
      c.start = d.start + shift; c.end = d.end + shift;
      const lane = document.elementFromPoint(e.clientX, e.clientY)?.closest('.tl-lane[data-spk]');
      $$('.tl-lane.drop', inner).forEach(l => l.classList.remove('drop'));
      d.to = lane ? lane.dataset.spk : null;
      if (lane && d.to !== d.from) lane.classList.add('drop');
    } else if (d.mode === 'l') {
      c.start = tlClamp(d.start + dx, d.lo, d.end - TL_MIN_LEN);
    } else {
      c.end = tlClamp(d.end + dx, d.start + TL_MIN_LEN, d.hi);
    }
    d.blk.style.left = (c.start * TL.pps).toFixed(1) + 'px';
    d.blk.style.width = ((c.end - c.start) * TL.pps).toFixed(1) + 'px';
    tlEl('tlReadout').textContent = `#${d.i + 1} · ${fmtTime(c.start)} → ${fmtTime(c.end)}`;
  });

  const finish = e => {
    const d = TL.drag;
    if (!d) return;
    TL.drag = null;
    const c = S.cues[d.i];
    if (!d.moved) {  // chỉ bấm, không kéo -> tua tới câu đó
      $('#player').currentTime = c.start + 0.02;
      return;
    }
    if (e.type === 'pointercancel') { c.start = d.start; c.end = d.end; d.to = null; }
    c.start = Math.round(c.start * 100) / 100;
    c.end = Math.round(c.end * 100) / 100;
    const changedSpeaker = d.to !== null && d.to !== d.from;
    if (changedSpeaker) c.speaker = d.to;
    tlEl('tlReadout').textContent = '';
    renderCues();  // vẽ lại danh sách thoại (mốc giờ, nhãn vai) — tự gọi renderTimeline
    if (changedSpeaker && typeof renderSpeakerVoices === 'function') renderSpeakerVoices();
    onTime();
    tlQueueBudget();
  };
  inner.addEventListener('pointerup', finish);
  inner.addEventListener('pointercancel', finish);

  // Bàn phím: Enter/Space tua tới câu; Alt+←/→ dời khối 0,1 giây
  inner.addEventListener('keydown', e => {
    const blk = e.target.closest('.tl-lane[data-spk] .tl-blk');
    if (!blk) return;
    const i = +blk.dataset.i, c = S.cues[i];
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      $('#player').currentTime = c.start + 0.02;
    } else if (e.altKey && (e.key === 'ArrowLeft' || e.key === 'ArrowRight')) {
      e.preventDefault();
      const lo = i > 0 ? S.cues[i - 1].end : 0;
      const hi = i < S.cues.length - 1 ? S.cues[i + 1].start : TL.dur;
      const shift = tlClamp(e.key === 'ArrowLeft' ? -0.1 : 0.1, Math.min(0, lo - c.start), Math.max(0, hi - c.end));
      c.start = Math.round((c.start + shift) * 100) / 100;
      c.end = Math.round((c.end + shift) * 100) / 100;
      renderCues();
      tlEl('tlInner').querySelector(`.tl-lane[data-spk] .tl-blk[data-i="${i}"]`)?.focus();
      tlQueueBudget();
    }
  });

  sc.addEventListener('scroll', tlDrawWavesSoon, { passive: true });
  window.addEventListener('resize', () => { if (TL.dur) { TL.fit = Math.max(0.5, sc.clientWidth / TL.dur); tlDrawWavesSoon(); } });
  // Ctrl + lăn chuột để thu phóng quanh con trỏ
  sc.addEventListener('wheel', e => {
    if (!e.ctrlKey) return;
    e.preventDefault();
    tlSetZoom(TL.pps * (e.deltaY < 0 ? 1.2 : 1 / 1.2));
    tlSyncZoom();
  }, { passive: false });

  tlEl('tlZoom').addEventListener('input', e => {
    tlSetZoom(TL.fit * Math.pow(TL_MAX_PPS / TL.fit, +e.target.value / 100));
  });
  tlEl('tlFitBtn').addEventListener('click', () => { tlSetZoom(TL.fit); tlSyncZoom(); });
  $('#player').addEventListener('loadedmetadata', () => {
    const d = $('#player').duration;
    if (d && d > TL.dur) { TL.dur = d; TL.fit = Math.max(0.5, sc.clientWidth / d); renderTimeline(); }
  });
}

/* ------------------------- thời lượng đọc dự đoán ------------------------- */
function tlQueueBudget(delay = 700) {
  clearTimeout(TL.budgetTimer);
  TL.budgetTimer = setTimeout(tlLoadBudget, delay);
}

async function tlLoadBudget() {
  if (!S.analyzed?.target_lang || !S.cues.some(c => c.text2)) {
    TL.budget = [];
    return;
  }
  const seq = ++TL.budgetSeq;
  try {
    const res = await api('/api/reading-budget', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cues: S.cues.map(c => ({ start: c.start, end: c.end, text: c.text, text2: c.text2 || '', speaker: c.speaker || '' })) }),
    });
    if (seq !== TL.budgetSeq) return;  // đã có lượt mới hơn
    TL.budget = res.items || [];
    TL.tolerance = res.tolerance ?? 0.05;
  } catch { return; }
  const lane = tlEl('tlDub');
  if (lane) lane.innerHTML = tlDubBlocks(); else renderTimeline();
  const over = TL.budget.filter(it => it.over > TL.tolerance).length;
  tlEl('tlOver').textContent = over ? `${over} câu đọc tràn khung` : '';
}

/* -------------------------------- sóng âm -------------------------------- */
async function tlLoadWaves() {
  const id = S.projectId || S.jobId;
  if (!id || TL.waveFor === id) { tlDrawWaves(); return; }
  TL.waves = [];
  TL.waveFor = id;
  try {
    const points = Math.round(tlClamp(TL.dur * 25, 400, 8000));
    const res = await api(`/api/projects/${encodeURIComponent(id)}/waveform?points=${points}`);
    if (TL.waveFor !== id) return;
    TL.waves = res.tracks || [];
    TL.waveDur = res.duration || TL.dur;
  } catch { TL.waves = []; }
  renderTimeline();
}

function tlDrawWavesSoon() {
  if (TL.drawRaf) return;
  TL.drawRaf = requestAnimationFrame(() => { TL.drawRaf = 0; tlDrawWaves(); });
}

/** Chỉ vẽ phần đang thấy: canvas rộng bằng khung nhìn và trượt theo thanh cuộn,
    vì phim dài phóng to thì cả dải rộng hàng trăm nghìn điểm ảnh — quá cỡ canvas. */
function tlDrawWaves() {
  const sc = tlEl('tlScroll');
  if (!sc || !TL.waves.length) return;
  const w = sc.clientWidth, left = sc.scrollLeft;
  const dpr = window.devicePixelRatio || 1;
  $$('canvas[data-wave]', sc).forEach(cv => {
    const track = TL.waves.find(x => x.id === cv.dataset.wave);
    if (!track) return;
    const h = cv.parentElement.clientHeight;
    cv.style.left = left + 'px';
    cv.style.width = w + 'px';
    cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr);
    const g = cv.getContext('2d');
    g.scale(dpr, dpr);
    g.fillStyle = getComputedStyle(cv).color;
    const n = track.peaks.length, perSec = n / (TL.waveDur || TL.dur);
    for (let x = 0; x < w; x += 3) {
      const a = Math.floor((left + x) / TL.pps * perSec);
      const b = Math.max(a + 1, Math.floor((left + x + 3) / TL.pps * perSec));
      if (a >= n) break;
      let v = 0;
      for (let k = a; k < b && k < n; k++) v = Math.max(v, track.peaks[k]);
      const bar = Math.max(1, v * (h - 6));
      g.fillRect(x, (h - bar) / 2, 2, bar);
    }
  });
}

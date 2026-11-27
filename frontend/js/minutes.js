/* Minute views project the canonical cue array; filtering never renumbers a line. */
const minutes = { selected: 0, editing: null, gaps: [] };

function knownDuration() {
  const player = $('#player');
  return Number(S.analyzed?.duration) || Number(S.analyzed?.info?.duration)
    || (Number.isFinite(player.duration) ? player.duration : 0);
}

function scriptExtent() {
  const last = S.cues.reduce((t, c) => Math.max(t, c.end), 0);
  return Math.max(knownDuration(), last) || 60;
}

function inputTime(t) {
  const ms = Math.round(t * 1000);
  return `${String(Math.floor(ms / 60000)).padStart(2, '0')}:${String(Math.floor(ms / 1000) % 60).padStart(2, '0')}.${String(ms % 1000).padStart(3, '0')}`;
}

function parseCueTime(value) {
  const parts = value.trim().replace(',', '.').split(':');
  if (parts.length > 3 || !parts.every((p, i) =>
    (i === parts.length - 1 ? /^\d+(?:\.\d{1,3})?$/ : /^\d+$/).test(p) && (!i || +p < 60))) return NaN;
  return parts.reduce((t, p) => t * 60 + Number(p), 0);
}

function freeCueRanges(a, b, first = 0) {
  const out = [];
  for (let i = first; i < S.cues.length; i++) {
    const c = S.cues[i];
    if (c.start >= b) break;
    if (c.end <= a) continue;
    if (a < c.start) out.push([a, c.start]);
    a = Math.max(a, c.end);
  }
  if (a < b) out.push([a, b]);
  return out;
}

function cueVisible(c) {
  const m = minutes.selected;
  return m < 0 || (c.start < (m + 1) * 60 && c.end > m * 60);
}

function minuteLabels() {
  const extent = scriptExtent(), n = Math.ceil(extent / 60);
  minutes.selected = Math.min(minutes.selected, n - 1);
  const counts = Array(n).fill(0), missing = Array(n).fill(0);
  for (const c of S.cues) {
    for (let m = Math.max(0, Math.floor(c.start / 60)); m < Math.min(n, Math.ceil(c.end / 60)); m++) {
      counts[m]++;
      if (S.analyzed.target_lang && !(c.text2 || '').trim()) missing[m]++;
    }
  }
  let first = 0;
  const gaps = (S.analyzed.speech_gaps || []).flatMap(([a, b]) => {
    while (first < S.cues.length && S.cues[first].end <= a) first++;
    return freeCueRanges(a, b, first);
  }).filter(([a, b]) => b - a >= 0.15);
  const review = new Set();
  for (const [a, b] of gaps)
    for (let m = Math.floor(a / 60); m < Math.ceil(b / 60); m++) review.add(m);
  const el = $('#cueMinute');
  el.innerHTML = counts.map((v, m) =>
    `<option value="${m}">${fmtDur(m * 60)} – ${fmtDur(Math.min(extent, (m + 1) * 60))} · ${v} câu${missing[m] ? ` · ${missing[m]} chưa dịch` : ''}${review.has(m) ? ' · cần nghe' : ''}</option>`
  ).join('') + '<option value="-1">Toàn bộ kịch bản</option>';
  el.value = String(minutes.selected);
  $('#cueFill').classList.toggle('hide', minutes.selected < 0 ||
    !S.cues.some(c => cueVisible(c) && c.text.trim() && !(c.text2 || '').trim()));
  const m = minutes.selected, lo = m < 0 ? 0 : m * 60, hi = m < 0 ? extent : (m + 1) * 60;
  minutes.gaps = gaps.filter(([a, b]) => a < hi && b > lo).map(([a, b]) => [Math.max(a, lo), Math.min(b, hi)]);
  $('#minuteGaps').innerHTML = minutes.gaps.length ? '<p class="hint">Có dấu hiệu tiếng nói nhưng chưa có chữ. Bấm mốc để nghe kiểm tra và bổ sung:</p>'
    + minutes.gaps.map(([a, b], i) => `<button type="button" class="btn sm ghost" data-gap="${i}">${fmtTime(a)} → ${fmtTime(b)}</button>`).join('') : '';
}

function closeCueForm() {
  minutes.editing = null;
  $('#cueForm').classList.add('hide');
  $('#cueFormError').textContent = '';
}

function setupMinutes() {
  minutes.selected = 0;
  S.fitUndo = [];
  closeCueForm();
  $('#minuteStatus').textContent = '';
}

function followMinute(t) {
  if (!$('#minuteFollow').checked || minutes.selected < 0 || !$('#cueForm').classList.contains('hide')
      || document.activeElement?.closest('#cueList textarea')) return;
  const m = Math.min(Math.max(0, Math.floor(t / 60)), $('#cueMinute').options.length - 2);
  if (m >= 0 && minutes.selected !== m) {
    minutes.selected = m;
    renderCues(false);
  }
}

function seekScript(t) {
  const player = $('#player');
  if (!S.projectId || S.videoSrc) player.currentTime = Math.max(0, t + (+$('#stOffset').value || 0));
  if (typeof tlReveal === 'function') tlReveal(t);
}

function showCueForm(c = null, gap = null) {
  let start, end;
  if (c) ({ start, end } = c);
  else if (gap) [start, end] = gap;
  else {
    const t = Math.max(0, $('#player').currentTime - (+$('#stOffset').value || 0));
    const m = minutes.selected < 0 ? Math.floor(t / 60) : minutes.selected;
    const ranges = freeCueRanges(m * 60, Math.min(scriptExtent(), (m + 1) * 60))
      .filter(([a, b]) => b - a >= 0.1);
    const r = ranges.find(([a, b]) => b >= t + 0.1) || ranges[0];
    if (!r) return toast('Phút này đã kín lời. Sửa mốc hoặc xóa một câu để tạo khoảng trống.', 'warn');
    start = t >= r[0] && t <= r[1] - 0.1 ? t : r[0];
    end = Math.min(r[1], start + 2);
  }
  $('#player').pause();
  minutes.editing = c;
  $('#cueStart').value = inputTime(start);
  $('#cueEnd').value = inputTime(end);
  $('#cueOriginal').value = c?.text || '';
  $('#cueTranslation').value = c?.text2 || '';
  $('#cueFormTitle').textContent = c ? 'Sửa câu và mốc giờ' : 'Thêm câu vào kịch bản';
  $('#cueFormError').textContent = '';
  $('#cueForm').classList.remove('hide');
  seekScript(start);
  $('#cueOriginal').focus();
}

function updateAfterCueEdit(t) {
  S.fitUndo = [];
  S.activeCue = -1;
  TL.budget = [];
  TL.budgetSeq++;
  if (minutes.selected >= 0) minutes.selected = Math.floor(t / 60);
  $('#minuteStatus').textContent = 'Chưa lưu';
  renderCues();
  seekScript(t);
  onTime();
  tlQueueBudget(0);
  markScriptStale();
}

async function removeCue(c) {
  if (!c || !(await askConfirm(`Xóa câu tại ${fmtTime(c.start)}? Các câu khác giữ nguyên mốc giờ.`))) return;
  const i = S.cues.indexOf(c);
  if (i < 0) return;
  S.cues.splice(i, 1);
  closeCueForm();
  updateAfterCueEdit(c.start);
}

$('#cueMinute').addEventListener('change', e => {
  minutes.selected = Number(e.target.value);
  closeCueForm();
  if (minutes.selected >= 0) seekScript(minutes.selected * 60);
  renderCues(false);
});
$('#minuteFollow').addEventListener('change', () => onTime());
$('#cueAdd').addEventListener('click', () => showCueForm());
$('#cueFill').addEventListener('click', async () => {
  if (!aiKeyOk()) return toast('Bổ sung API key cho engine đang chọn ở bước 2.', 'warn');
  const btn = $('#cueFill'), job = S.jobId, target = S.analyzed.target_lang || $('#tgtLang').value || 'vi';
  const lines = S.cues.filter(cueVisible), snapshot = lines.map(c => JSON.stringify(c));
  btn.disabled = true;
  try {
    const r = await api('/api/translate-missing', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cues: lines, source_lang: S.analyzed.source_lang, target_lang: target, ...aiPayload() }),
    });
    if (job !== S.jobId) return;
    let filled = 0;
    for (const { i, text2 } of r.changes) {
      const c = lines[i];
      if (S.cues.includes(c) && !(c.text2 || '').trim() && snapshot[i] === JSON.stringify(c)) {
        c.text2 = text2;
        filled++;
      }
    }
    if (filled) {
      S.analyzed.target_lang = target;
      S.display = 'second';
      syncDisplayTabs();
      $('#minuteStatus').textContent = 'Chưa lưu';
      renderCues();
      updateOverlay();
      tlQueueBudget(0);
      markScriptStale();
    }
    toast(`Đã bổ sung ${filled} câu.${r.remaining ? ` Engine chưa trả lời cho ${r.remaining} câu.` : ''}`, filled ? 'ok' : 'warn');
  } catch (e) { toast('Không dịch được câu thiếu: ' + e.message, 'err'); }
  finally { btn.disabled = false; }
});
$('#cueCancel').addEventListener('click', closeCueForm);
$('#minuteGaps').addEventListener('click', e => {
  const b = e.target.closest('[data-gap]');
  if (b) showCueForm(null, minutes.gaps[+b.dataset.gap]);
});
$('#cueForm').addEventListener('submit', e => {
  e.preventDefault();
  const start = parseCueTime($('#cueStart').value), end = parseCueTime($('#cueEnd').value);
  const text = $('#cueOriginal').value.trim(), text2 = $('#cueTranslation').value.trim();
  const current = minutes.editing;
  let error = '';
  if (!Number.isFinite(end) || !(start >= 0 && end > start)) error = 'Mốc giờ không hợp lệ. Ví dụ: 02:03.250 → 02:05.000.';
  else if (knownDuration() && end > knownDuration() + 0.001) error = 'Mốc kết thúc vượt thời lượng video.';
  else if (!text && !text2) error = 'Nhập lời gốc hoặc bản dịch.';
  else if ((!current || current.start !== start || current.end !== end)
      && S.cues.some(c => c !== current && start < c.end && end > c.start)) error = 'Khung này chồng lên câu khác.';
  if (error) { $('#cueFormError').textContent = error; return; }
  const cue = Object.assign(current || { speaker: '' }, { start, end, text, text2, pinned: true });
  if (!current) S.cues.push(cue);
  S.cues.sort((a, b) => a.start - b.start);
  if (text2 && !S.analyzed.target_lang) {
    S.analyzed.target_lang = $('#tgtLang').value || 'vi';
    S.display = 'second';
    syncDisplayTabs();
  }
  closeCueForm();
  updateAfterCueEdit(start);
  if (e.submitter?.id === 'cueApplyPreview') auditionCue(S.cues.indexOf(cue));
});
$('#cueSave').addEventListener('click', async () => {
  const id = S.jobId, btn = $('#cueSave');
  if (!$('#cueForm').classList.contains('hide')) return toast('Áp dụng hoặc hủy câu đang sửa trước khi lưu.', 'warn');
  const revision = S.analyzed?.revision;
  const snapshot = () => JSON.stringify({ cues: S.cues, target_lang: S.analyzed?.target_lang || '', revision });
  const body = snapshot();
  btn.disabled = true;
  try {
    const r = await api(`/api/projects/${encodeURIComponent(id)}/cues`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body,
    });
    if (id === S.jobId) {
      S.analyzed.revision = r.revision;
      if (body === snapshot()) $('#minuteStatus').textContent = `Đã lưu ${r.cue_count} câu`;
    }
  } catch (e) { toast('Chưa lưu được kịch bản: ' + e.message, 'err'); }
  finally { btn.disabled = false; }
});

/* frontend/js/source.js — bước 1: nguồn video (file / link nhiều phần / kịch bản / .srt).
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
/* ------------------------- bước 1: nguồn video -------------------------- */
function setSource(type) {
  if (type === 'file' && S.sourceType === 'url') clearLinkInfo();
  S.sourceType = type;
  $$('.tab[data-src]').forEach(x => x.classList.toggle('active', x.dataset.src === type));
  $$('.tabpane[data-pane]').forEach(p => p.classList.toggle('active', p.dataset.pane === type));
  updateSourceSummary();
}

$$('.tab[data-src]').forEach(t => t.addEventListener('click', () => setSource(t.dataset.src)));

/** Cho biết rõ nguồn nào sẽ được xử lý — tránh chuyện tải file lên
 *  nhưng tool lại đi lấy link cũ. */
function updateSourceSummary() {
  const el = $('#srcSummary');
  if (!el) return;
  let txt = '';
  if (S.sourceType === 'file') {
    txt = S.mediaName
      ? `Sẽ xử lý file: <b>${esc(S.mediaName)}</b>`
      : 'Chưa chọn file nào.';
  } else {
    const u = $('#urlInput').value.trim();
    const info = S.linkChecked === u ? S.linkInfo : null;
    if (!u) {
      txt = 'Chưa dán link nào.';
    } else if (info && info.multi) {
      const p = info.parts.find(x => x.index === S.part);
      txt = p
        ? `Sẽ tải &amp; xử lý <b>phần ${p.index}/${info.count}</b>`
          + (p.title ? ` — ${esc(p.title)}` : '')
          + (p.duration ? ` · ${fmtLength(p.duration)}` : '')
        : `Link có <b>${info.count} phần</b> — bạn chưa chọn phần nào.`;
    } else {
      txt = `Sẽ tải &amp; xử lý link: <b>${esc(u.slice(0, 70))}</b>`;
    }
  }
  const other = S.sourceType === 'file' ? $('#urlInput').value.trim() : S.mediaName;
  if (other) {
    txt += `<br><span class="muted">Nguồn còn lại (${S.sourceType === 'file' ? 'link' : 'file'})
            đang bị bỏ qua — bấm tab bên trên để đổi.</span>`;
  }
  el.innerHTML = txt;
  el.classList.remove('hide');
}

const drop = $('#drop'), fileInput = $('#fileInput');
drop.addEventListener('click', () => fileInput.click());
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.add('over');
}));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => {
  e.preventDefault(); drop.classList.remove('over');
}));
drop.addEventListener('drop', e => {
  const f = e.dataTransfer.files[0];
  if (f) uploadFile(f);
});

$('#urlInput').addEventListener('input', () => {
  // đổi link thì kết quả kiểm tra cũ không còn đúng nữa
  if ($('#urlInput').value.trim() !== S.linkChecked) clearLinkInfo();
  if ($('#urlInput').value.trim() && S.sourceType !== 'url') setSource('url');
  else updateSourceSummary();
});
$('#urlInput').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.isComposing) { e.preventDefault(); inspectLink(); }
});
$('#checkLink').addEventListener('click', () => inspectLink());
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

/* ----------------- link nhiều phần: hỏi xử lý phần nào ------------------ */
function videoLink(value) {
  let url = value.trim();
  if (!url) throw new Error('Bạn chưa dán link video.');
  if (/^(?:file:|[a-z]:[\\/]|[\\/]|\.{1,2}[\\/])/i.test(url) ||
      (!url.includes('/') && /\.(mp4|mkv|mov|avi|webm|flv|m4v|wmv|ts|mp3|wav|aac|m4a|flac|ogg)$/i.test(url))) {
    throw new Error('Đây là đường dẫn hoặc tên tệp. Chọn “File từ máy” rồi chọn video.');
  }
  if (/^[\w-]{32}$/.test(url)) {
    throw new Error('Ô này cần link video. Nếu đây là mã mời, hãy nhập ở “Có mã mời? Đăng ký”.');
  }
  // Only infer HTTPS for a domain followed by a path, not arbitrary text or a filename.
  if (/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,63}(?::\d+)?\/[^\s\\]+$/i.test(url)) url = 'https://' + url;
  if (/^https?:\/\/[^/?#\\\s]/i.test(url) && !/[\s\\]/.test(url)) {
    try {
      const parsed = new URL(url);
      if (parsed.hostname && !parsed.username && !parsed.password) return url;
    } catch { /* Show the same field hint for malformed links. */ }
  }
  throw new Error('Dán riêng địa chỉ video, ví dụ https://youtu.be/…; nếu video đã có trong thư viện, bấm “Mở ra sửa”.');
}

let linkPending = null;
function clearLinkInfo() {
  linkPending?.controller.abort();
  linkPending = null;
  $('#checkLink').disabled = false;
  $('#urlInput').removeAttribute('aria-invalid');
  S.url = '';
  S.linkInfo = null;
  S.linkChecked = '';
  S.part = null;
  $('#linkState').textContent = '';
  $('#linkParts').innerHTML = '';
  $('#linkParts').classList.add('hide');
}

/** Đọc link để biết có bao nhiêu phần. Trả về info, hoặc null nếu lỗi. */
async function inspectLink() {
  if (S.sourceType !== 'url') return null;
  const field = $('#urlInput'), status = $('#linkState');
  let url;
  try { url = videoLink(field.value); }
  catch (e) {
    clearLinkInfo();
    status.textContent = e.message;
    field.setAttribute('aria-invalid', 'true');
    field.focus();
    return null;
  }
  field.value = url;
  if (S.linkChecked === url && S.linkInfo) return S.linkInfo;
  if (linkPending?.url === url) return linkPending.promise;
  clearLinkInfo();
  const request = { url, controller: new AbortController() };
  linkPending = request;
  $('#checkLink').disabled = true;
  status.textContent = 'Đang đọc link…';
  request.promise = (async () => {
    try {
      const info = await api('/api/link/inspect', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }), signal: request.controller.signal,
      });
      if (linkPending !== request) return null;
      S.url = S.linkChecked = url;
      S.linkInfo = info;
      renderLinkParts(info);
      return info;
    } catch (e) {
      if (linkPending === request) status.textContent = e.message;
      return null;
    } finally {
      if (linkPending === request) { $('#checkLink').disabled = false; linkPending = null; }
    }
  })();
  return request.promise;
}

function renderLinkParts(info) {
  const box = $('#linkParts'), state = $('#linkState');

  if (!info.multi) {
    box.innerHTML = '';
    box.classList.add('hide');
    state.innerHTML = icon('check-circle') + ' Link chỉ có một video'
      + (info.title ? ` · <b>${esc(info.title.slice(0, 60))}</b>` : '')
      + (info.duration ? ` · ${fmtLength(info.duration)}` : '');
    updateSourceSummary();
    return;
  }

  state.innerHTML = `${icon('alert')} Link có <b>${info.count}</b> phần — chọn phần bên dưới.`;
  const rows = info.parts.map(p => `
    <div class="part" data-part="${p.index}" role="button" tabindex="0">
      <span class="no">P${p.index}</span>
      <span class="nm">${esc(p.title || 'Phần ' + p.index)}</span>
      <span class="dur${p.duration >= 3600 ? ' long' : ''}">${p.duration ? fmtLength(p.duration) : '—'}</span>
    </div>`).join('');

  box.innerHTML = `
    <div class="parts-head">
      Link này gồm <b>${info.count} phần</b>${info.truncated ? ` (chỉ hiện ${info.parts.length} phần đầu)` : ''}.
      Tool xử lý <b>một phần mỗi lần</b> — hãy chọn phần bạn muốn tạo phụ đề &amp; dịch.
      ${info.title ? `<br><span class="muted">${esc(info.title.slice(0, 120))}</span>` : ''}
    </div>
    <div class="partlist">${rows}</div>`;
  box.classList.remove('hide');

  $$('.part', box).forEach(el => el.addEventListener('click', () => {
    $$('.part', box).forEach(x => x.classList.remove('on'));
    el.classList.add('on');
    S.part = +el.dataset.part;
    updateSourceSummary();
  }));
  updateSourceSummary();
}

async function uploadFile(file) {
  $('#fileCard').innerHTML = `
    <div class="filecard"><span class="ic">${icon('loader', 'spin')}</span>
      <div class="meta"><b>${esc(file.name)}</b><span>Đang tải lên… ${fmtBytes(file.size)}</span></div></div>`;
  const fd = new FormData();
  fd.append('file', file);
  try {
    const r = await api('/api/upload', { method: 'POST', body: fd });
    S.mediaId = r.media_id;
    S.mediaName = r.name;
    S.mediaInfo = r.info;
    // Tải file lên nghĩa là muốn xử lý file đó, không phải link đã dán trước đó
    setSource('file');
    const i = r.info;
    $('#fileCard').innerHTML = `
      <div class="filecard"><span class="ic">${icon('film')}</span>
        <div class="meta"><b>${esc(r.name)}</b>
          <span>${fmtBytes(r.size)} · ${i.width}×${i.height} · ${fmtTime(i.duration)}
          ${i.has_audio ? '' : ' · <b style="color:#ffb648">không có tiếng!</b>'}</span></div></div>`;
    if (!i.has_audio && S.subMode !== 'srt') {
      toast('Video không có âm thanh — hãy chọn chế độ "Đã có file .srt/.vtt".', 'warn', 8000);
    }
    unlock(2);
    toast('Đã tải lên xong.', 'ok', 2500);
  } catch (e) {
    $('#fileCard').innerHTML = '';
    toast('Tải lên thất bại: ' + e.message, 'err', 8000);
  }
}

// chế độ nội dung phụ đề
$$('.choice[data-mode]').forEach(el => el.addEventListener('click', () => {
  $$('.choice[data-mode]').forEach(x => x.classList.remove('on'));
  el.classList.add('on');
  S.subMode = el.dataset.mode;
  $('#modeText').classList.toggle('hide', S.subMode !== 'text');
  $('#modeSrt').classList.toggle('hide', S.subMode !== 'srt');
}));

$('#pickTxt').addEventListener('click', () => $('#txtInput').click());
$('#txtInput').addEventListener('change', async () => {
  const f = $('#txtInput').files[0];
  if (!f) return;
  $('#scriptText').value = await f.text();
  toast('Đã nạp văn bản.', 'ok', 2200);
});

const dropSrt = $('#dropSrt'), srtInput = $('#srtInput');
dropSrt.addEventListener('click', () => srtInput.click());
['dragenter', 'dragover'].forEach(ev => dropSrt.addEventListener(ev, e => {
  e.preventDefault(); dropSrt.classList.add('over');
}));
['dragleave', 'drop'].forEach(ev => dropSrt.addEventListener(ev, e => {
  e.preventDefault(); dropSrt.classList.remove('over');
}));
dropSrt.addEventListener('drop', e => { if (e.dataTransfer.files[0]) loadSrt(e.dataTransfer.files[0]); });
srtInput.addEventListener('change', () => { if (srtInput.files[0]) loadSrt(srtInput.files[0]); });

async function loadSrt(f) {
  S.subtitleText = await f.text();
  const lines = (S.subtitleText.match(/-->/g) || []).length;
  $('#srtCard').innerHTML = `
    <div class="filecard"><span class="ic">${icon('captions')}</span>
      <div class="meta"><b>${esc(f.name)}</b><span>${lines} dòng phụ đề · ${fmtBytes(f.size)}</span></div></div>`;
  toast(`Đã nạp ${lines} dòng phụ đề.`, 'ok', 2500);
}

$('#toStep2').addEventListener('click', async () => {
  const btn = $('#toStep2');
  if (S.sourceType === 'file') {
    if (!S.mediaId) return toast('Bạn chưa chọn video từ máy.', 'warn');
    S.url = '';
    S.part = null;
  } else {
    // Chưa kiểm tra link thì kiểm tra ngay — link nhiều phần phải chọn phần
    btn.disabled = true;
    let info;
    try { info = await inspectLink(); } finally { btn.disabled = false; }
    if (!info) return;
    if (info.multi && !S.part) {
      updateSourceSummary();
      $('#linkParts').scrollIntoView({ behavior: uiScrollBehavior(), block: 'center' });
      return toast(`Link này có ${info.count} phần — hãy chọn phần bạn muốn xử lý.`, 'warn', 7000);
    }
  }
  if (S.subMode === 'text' && !$('#scriptText').value.trim())
    return toast('Bạn chưa dán văn bản kịch bản.', 'warn');
  if (S.subMode === 'srt' && !S.subtitleText.trim())
    return toast('Bạn chưa nạp file phụ đề.', 'warn');

  const what = S.sourceType === 'file'
    ? S.mediaName
    : (S.part ? `phần ${S.part} của link` : S.url);
  toast(`Nguồn đã chọn: ${String(what).slice(0, 60)}`, 'ok', 3000);
  updateStepSummary();
  unlock(2);
  goStep(2);
});

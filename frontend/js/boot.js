/* frontend/js/boot.js — khởi tạo: đọc /api/system, đổ danh sách ngôn ngữ / model / engine.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
/* -------------------------------- khởi tạo ------------------------------ */
async function boot() {
  // Lần gọi đầu có thể trượt vì server đang khởi động lại -> thử lại vài nhịp,
  // thay vì đứng nguyên ở "Đang kiểm tra…" cho tới khi người dùng tự F5.
  for (let attempt = 1; ; attempt++) {
    try {
      S.sys = await api('/api/system');
      break;
    } catch (e) {
      if (attempt >= 5) {
        $('#statusRow').innerHTML =
          '<span class="pill bad"><i class="dot"></i> mất kết nối server</span>';
        toast('Không kết nối được server: ' + e.message + ' — kiểm tra tool còn chạy không, rồi F5.',
          'err', 12000);
        return;
      }
      $('#statusRow').innerHTML =
        `<span class="pill"><i class="dot"></i> đang chờ server… (${attempt}/5)</span>`;
      await new Promise(r => setTimeout(r, 1200));
    }
  }
  renderStatus();
  fillLanguages();
  fillAsrModels();
  fillEngines();
  initTts();
  initDiarize();
  restorePrefs();
  refreshCacheInfo();
  loadProjects();
  restoreJobRecovery();
}

function renderStatus() {
  const s = S.sys, out = [];
  out.push(s.ffmpeg.ok
    ? `<span class="pill ok"><i class="dot"></i> ffmpeg sẵn sàng</span>`
    : `<span class="pill bad"><i class="dot"></i> thiếu ffmpeg</span>`);
  out.push(s.ffmpeg.libass
    ? `<span class="pill ok"><i class="dot"></i> nung phụ đề OK</span>`
    : `<span class="pill bad"><i class="dot"></i> không nung được</span>`);
  out.push(s.gpu
    ? `<span class="pill ok"><i class="dot"></i> GPU tăng tốc</span>`
    : `<span class="pill"><i class="dot"></i> chạy bằng CPU</span>`);
  $('#statusRow').innerHTML = out.join('');
  if (!s.ffmpeg.ok) toast('Không tìm thấy ffmpeg. Chạy: uv run python -m app.setup_ffmpeg', 'err', 12000);
}

function fillLanguages() {
  const src = $('#srcLang'), tgt = $('#tgtLang');
  S.sys.languages.forEach(l => {
    src.insertAdjacentHTML('beforeend', `<option value="${l.code}">${l.flag} ${l.vi}</option>`);
    tgt.insertAdjacentHTML('beforeend', `<option value="${l.code}">${l.flag} ${l.vi}</option>`);
  });
  tgt.value = 'vi';
}

function fillAsrModels() {
  const sel = $('#asrModel');
  S.sys.asr_models.forEach(m => {
    sel.insertAdjacentHTML('beforeend', `<option value="${m.id}">${m.label} · ${m.size}</option>`);
  });
  sel.value = S.sys.default_asr_model;
}

function fillEngines() {
  const grid = $('#engineGrid');
  grid.innerHTML = S.sys.engines.map(e => `
    <div class="choice ${e.id === S.engine ? 'on' : ''} ${e.available ? '' : 'off'}"
         data-engine="${e.id}" ${e.available ? '' : 'title="' + e.reason + '"'}>
      <b>${e.label}</b>
      <small>${e.desc}</small>
      ${e.available ? '' : `<span class="tagline">${e.reason}</span>`}
    </div>`).join('');

  $$('.choice[data-engine]', grid).forEach(el => el.addEventListener('click', () => {
    if (el.classList.contains('off')) {
      toast(el.getAttribute('title') || 'Engine chưa cài đặt.', 'warn');
      return;
    }
    $$('.choice[data-engine]', grid).forEach(x => x.classList.remove('on'));
    el.classList.add('on');
    S.engine = el.dataset.engine;
    syncAiBox();
    savePrefs();
  }));
  syncAiBox();
}

function syncAiBox() {
  const isAi = S.engine === 'claude' || S.engine === 'openai';
  $('#aiBox').classList.toggle('hide', !isAi);
  $('#baseUrlField').classList.toggle('hide', S.engine !== 'openai');
  if (!isAi) return;
  const provider = S.engine === 'claude' ? 'anthropic' : 'openai';
  const sel = $('#aiModel');
  sel.innerHTML = (S.sys.ai_models[provider] || [])
    .map(m => `<option value="${m.id}">${m.label}</option>`).join('');
  const envKey = provider === 'anthropic' ? S.sys.has_anthropic_key : S.sys.has_openai_key;
  const varName = provider === 'anthropic' ? 'ANTHROPIC_API_KEY' : 'OPENAI_API_KEY';
  $('#keyHint').textContent = envKey
    ? `— đã có ${varName} trong môi trường, để trống là dùng key đó`
    : `— hoặc đặt biến môi trường ${varName}`;
}

async function refreshCacheInfo() {
  try {
    const info = await api('/api/translation-cache');
    const kb = (info.bytes / 1024).toFixed(1);
    $('#cacheInfo').textContent = `Cache AI: ${info.entries} mục · ${kb} KB`;
  } catch { $('#cacheInfo').textContent = 'Cache AI chưa khả dụng'; }
}

$('#clearCache').addEventListener('click', async () => {
  if (!confirm('Xoá toàn bộ cache dịch AI?')) return;
  try {
    const result = await api('/api/translation-cache', { method: 'DELETE' });
    toast(`Đã xoá ${result.deleted} mục cache AI.`, 'ok');
    refreshCacheInfo();
  } catch (e) { toast(e.message, 'err'); }
});


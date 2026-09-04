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

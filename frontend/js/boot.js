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
  // Nhãn nói bằng việc làm được, tên công cụ nằm trong lời giải thích khi rê chuột
  const pill = (ok, label, tip, neutral = false) =>
    `<span class="pill ${ok ? 'ok' : neutral ? '' : 'bad'}" title="${tip}" tabindex="0"><i class="dot"></i> ${label}</span>`;
  out.push(s.ffmpeg.ok
    ? pill(true, 'Xử lý video sẵn sàng', 'ffmpeg đã có trên máy. ffmpeg là công cụ mã nguồn mở để đọc, cắt, ghép và mã hoá video / âm thanh — tool dùng nó để tách tiếng, nung phụ đề và ghép bản lồng tiếng.')
    : pill(false, 'Thiếu công cụ xử lý video', 'Chưa tìm thấy ffmpeg (công cụ đọc, cắt, ghép video / âm thanh). Thiếu nó thì không tách tiếng và không xuất video được.'));
  out.push(s.ffmpeg.libass
    ? pill(true, 'Nung phụ đề được', 'Bản ffmpeg này có libass nên in được chữ phụ đề thẳng vào hình.')
    : pill(false, 'Không nung được phụ đề', 'Bản ffmpeg này thiếu libass nên không in chữ vào hình được; vẫn xuất được file .srt và video lồng tiếng.'));
  out.push(s.gpu
    ? pill(true, 'Có GPU tăng tốc', 'Nhận dạng lời thoại chạy trên card đồ hoạ nên nhanh hơn nhiều lần.')
    : pill(false, 'Chạy bằng CPU', 'Không thấy card đồ hoạ dùng được: mọi thứ vẫn chạy, chỉ chậm hơn.', true));
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

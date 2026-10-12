/* frontend/js/hardsub.js — bước 4: che phụ đề đã nung sẵn trong video gốc.
   Máy chủ dò dải phụ đề cũ lúc phân tích (`S.analyzed.hardsub`, toạ độ 0–1 của
   khung hình). Ở đây: bật/tắt, chỉnh dải, xem trước ngay trên video, và đặt phụ
   đề mới vào đúng dải đó. Việc che thật làm lúc nung (backend/core/hardsub.py).
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */

bindRange('#maskTop', '#maskTopOut', v => (+v).toFixed(1));
bindRange('#maskH', '#maskHOut', v => (+v).toFixed(1));
bindRange('#maskW', '#maskWOut');

/** Dải đang chỉnh, toạ độ 0–1. Bề ngang luôn canh giữa vì phụ đề canh giữa. */
function maskBand() {
  const top = +$('#maskTop').value / 100;
  const h = +$('#maskH').value / 100;
  const w = +$('#maskW').value / 100;
  return { y0: top, y1: Math.min(1, top + h), x0: 0.5 - w / 2, x1: 0.5 + w / 2 };
}

/** Cấu hình gửi kèm lúc xuất, hoặc null khi không che. */
function maskConfig() {
  if (!$('#maskOn').checked) return null;
  return { mode: $('#maskMode').value, ...maskBand() };
}

function setBand(b) {
  $('#maskTop').value = (b.y0 * 100).toFixed(1);
  $('#maskH').value = Math.max(2, (b.y1 - b.y0) * 100).toFixed(1);
  $('#maskW').value = Math.round(Math.max(0.2, b.x1 - b.x0) * 100);
  ['#maskTop', '#maskH', '#maskW'].forEach(id => $(id).dispatchEvent(new Event('input')));
}

/** Khung hình thật nằm đâu trong thẻ <video> (video không đúng 16:9 thì có viền đen). */
function videoRect() {
  const v = $('#player');
  const bw = v.clientWidth, bh = v.clientHeight;
  const vw = v.videoWidth || 16, vh = v.videoHeight || 9;
  const scale = Math.min(bw / vw, bh / vh);
  const w = vw * scale, h = vh * scale;
  return { left: (bw - w) / 2, top: (bh - h) / 2, width: w, height: h };
}

function paintMask() {
  const el = $('#hsMask');
  const on = $('#maskOn').checked;
  el.classList.toggle('hide', !on);
  $('#maskOpts').classList.toggle('hide', !on);
  if (!on) return;
  const r = videoRect(), b = maskBand();
  el.className = 'hs-mask ' + $('#maskMode').value;
  Object.assign(el.style, {
    left: `${r.left + b.x0 * r.width}px`, top: `${r.top + b.y0 * r.height}px`,
    width: `${(b.x1 - b.x0) * r.width}px`, height: `${(b.y1 - b.y0) * r.height}px`,
  });
}

/** Đặt phụ đề mới vào giữa dải đang che (đổi Vị trí và Lề dọc). */
function fitSubsToMask() {
  const b = maskBand();
  const lineH = +$('#stSize').value * 1.25;              // theo khung 1080
  const bandH = (b.y1 - b.y0) * 1080;
  const inset = Math.max(4, (bandH - lineH) / 2);
  const bottom = (b.y0 + b.y1) / 2 >= 0.45;
  $('#stPos').value = bottom ? 'bottom' : 'top';
  const margin = bottom ? (1 - b.y1) * 1080 + inset : b.y0 * 1080 + inset;
  const el = $('#stMargin');
  el.value = Math.round(Math.min(+el.max, Math.max(+el.min, margin)));
  ['#stPos', '#stMargin'].forEach(id => $(id).dispatchEvent(new Event('input')));
}

function describeBand(r) {
  return `Video đã có phụ đề nung sẵn ở khoảng ${Math.round(r.y0 * 100)}–${Math.round(r.y1 * 100)}% `
    + 'chiều cao khung — sẽ được che khi xuất Video nung phụ đề.';
}

/** Gọi khi mở bước 4 với một bộ phụ đề mới. */
function initMask() {
  const r = S.analyzed?.hardsub;
  const found = !!(r && r.found);
  $('#maskOn').checked = found;
  $('#maskOn').closest('.switch').classList.toggle('on', found);
  if (found) {
    setBand(r);
    fitSubsToMask();
  }
  $('#maskHint').textContent = found
    ? describeBand(r)
    : (r ? 'Không thấy phụ đề nung sẵn trong video. Bật lên nếu vẫn muốn che một dải.'
         : 'Video gốc đã có chữ nung sẵn thì che đi, rồi đặt phụ đề mới đúng chỗ đó.');
  $('#maskState').textContent = '';
  paintMask();
  // Dự án làm trước khi có tính năng này: chưa từng dò -> dò ngầm luôn, không bắt bấm nút
  if (r == null && (S.projectId || S.jobId) && !(S.projectId && !S.videoSrc)) runDetect(true);
}

$('#maskOn').addEventListener('change', () => {
  // Bật tay mà chưa dò ra gì: đề nghị dải sát đáy, chỗ phụ đề hay nằm nhất
  if ($('#maskOn').checked && !S.analyzed?.hardsub?.found && +$('#maskTop').value === 0) {
    setBand({ y0: 0.82, y1: 0.92, x0: 0.2, x1: 0.8 });
  }
  if ($('#maskOn').checked) fitSubsToMask();
  paintMask();
  applyOverlayStyle();
});
['#maskTop', '#maskH', '#maskW', '#maskMode'].forEach(id => {
  $(id).addEventListener('input', paintMask);
  $(id).addEventListener('change', paintMask);
});
$('#maskFit').addEventListener('click', fitSubsToMask);
$('#player').addEventListener('loadedmetadata', paintMask);

async function runDetect(auto = false) {
  const id = S.projectId || S.jobId;
  if (!id) return;
  const btn = $('#maskDetect');
  btn.disabled = true;
  $('#maskState').textContent = 'Đang xem khung hình…';
  if (auto) $('#maskHint').textContent = 'Đang dò xem video có phụ đề nung sẵn không…';
  try {
    const r = await api(`/api/projects/${id}/hardsub`, { method: 'POST' });
    if ((S.projectId || S.jobId) !== id) return;   // người dùng đã mở dự án khác
    S.analyzed.hardsub = r;
    if (r.found) {
      $('#maskOn').checked = true;
      $('#maskOn').closest('.switch').classList.add('on');
      setBand(r);
      fitSubsToMask();
      $('#maskHint').textContent = describeBand(r);
      $('#maskState').textContent = 'Đã dò lại.';
    } else {
      $('#maskState').textContent = r.reason || 'Không thấy phụ đề nung sẵn.';
      if (auto) $('#maskHint').textContent =
        'Không thấy phụ đề nung sẵn trong video. Bật lên nếu vẫn muốn che một dải.';
    }
    paintMask();
    applyOverlayStyle();
  } catch (e) {
    $('#maskState').textContent = e.message;
    if (auto) $('#maskHint').textContent = 'Chưa dò được phụ đề có sẵn: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}
$('#maskDetect').addEventListener('click', () => runDetect(false));

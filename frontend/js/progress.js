/* frontend/js/progress.js — bước 3: theo dõi tiến độ job.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
/* ---------------------------- bước 3: tiến độ --------------------------- */
const STEP_ICON = { pending: '○', running: '◍', done: '✓', skipped: '–', error: '✕' };

function pollJob() {
  clearInterval(S.poll);
  S.poll = setInterval(async () => {
    let j;
    try { j = await api(`/api/jobs/${S.jobId}`); }
    catch (e) { clearInterval(S.poll); toast('Mất kết nối job: ' + e.message, 'err'); return; }

    paintProgress(j, '#stepsList', '#logBox');

    if (j.status === 'done') {
      clearInterval(S.poll);
      $('#cancelBtn').disabled = true;
      $('#phaseText').textContent = 'hoàn tất';
      S.analyzed = j.result;
      S.cues = (j.result.cues || []).map(c => ({ ...c }));
      await loadCharacters(S.jobId);   // dự án mới -> bảng vai mới, không dính dự án trước
      updateStepSummary();
      $('#toEditor').classList.remove('hide');
      unlock(4);
      setupEditor();
      showCoverage(j.result);
      if (S.target) {
        toast(`Đã gắn vào tập ${S.target.no} của "${S.target.filmName}".`, 'ok', 5000);
        S.target = null;      // xong tập này rồi, đừng gắn lần sau nữa
        renderTargetBar();
      }
      loadProjects();  // dự án mới -> hiện luôn trong dashboard ở bước 1
      toast(`Xong! ${S.cues.length} dòng phụ đề.`, 'ok', 4000);
      clearJobRecovery();
    } else if (j.status === 'error' || j.status === 'cancelled') {
      clearInterval(S.poll);
      $('#cancelBtn').disabled = true;
      $('#phaseText').textContent = j.status === 'cancelled' ? 'đã huỷ' : 'lỗi';
      toast(j.error || 'Xử lý thất bại.', 'err', 12000);
    }
  }, 800);
}

function fmtDur(t) {
  t = Math.round(Math.max(0, t || 0));
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
  return (h ? `${h}:${String(m).padStart(2, '0')}` : `${m}`) + `:${String(s).padStart(2, '0')}`;
}

function showCoverage(res) {
  const box = $('#covWarn');
  const cov = res.coverage ?? 1;
  if (cov >= 0.9) { box.classList.add('hide'); box.innerHTML = ''; return; }

  const dur = res.duration || 0;
  const gaps = (res.gaps || []).map(([a, b]) => `${fmtDur(a)}–${fmtDur(b)}`).join(' · ');
  box.className = 'notice';
  box.innerHTML =
    `<b>⚠ Phụ đề chưa phủ hết video — mới tới ${fmtDur(cov * dur)} / ${fmtDur(dur)}
     (${Math.round(cov * 100)}%).</b>` +
    (gaps ? `<br>Đoạn không có phụ đề: ${gaps}` : '') +
    `<ul>
       <li>Nếu những đoạn đó <b>thật sự không có lời</b> (nhạc nền, im lặng) thì đây là bình thường.</li>
       <li>Nếu <b>có lời</b>: quay lại bước 2, chọn model <b>medium</b> hoặc <b>large-v3</b>,
           và chọn đúng <b>ngôn ngữ gốc</b> thay vì để tự động.</li>
       <li>Kiểm tra <b>Lọc khoảng lặng (VAD)</b> đang tắt — bật nó hay làm mất đoạn hát.</li>
     </ul>`;
  toast(`Phụ đề mới phủ ${Math.round(cov * 100)}% video — xem cảnh báo ở bước 3.`, 'warn', 9000);
}

function paintProgress(j, listSel, logSel) {
  const pct = Math.round((j.progress || 0) * 100);
  const C = 2 * Math.PI * 72;
  const fg = $('#ringFg');
  if (fg && listSel === '#stepsList') {
    fg.setAttribute('stroke-dashoffset', String(C * (1 - (j.progress || 0))));
    $('#pctText').textContent = pct;
    $('#ring').classList.toggle('spin', j.status === 'running');
    const cur = (j.steps || []).find(s => s.status === 'running');
    $('#phaseText').textContent = cur ? cur.label.toLowerCase() : (j.status === 'running' ? 'đang chạy…' : '');
  }

  $(listSel).innerHTML = (j.steps || []).map(s => `
    <div class="stepline ${s.status}">
      <span class="ic">${STEP_ICON[s.status] || '○'}</span>
      <div class="body">
        <b>${s.label}</b>
        ${s.detail ? `<small>${s.detail}</small>` : ''}
        ${s.status === 'running' ? `<div class="bar"><i style="width:${Math.round(s.progress * 100)}%"></i></div>` : ''}
      </div>
      <span class="pct">${s.status === 'done' || s.status === 'skipped' ? '✓' : Math.round(s.progress * 100) + '%'}</span>
    </div>`).join('');

  if (logSel && j.logs) {
    const box = $(logSel);
    const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
    box.textContent = j.logs.join('\n');
    if (atBottom) box.scrollTop = box.scrollHeight;
  }
}

$('#cancelBtn').addEventListener('click', async () => {
  if (!S.jobId) return;
  try { await api(`/api/jobs/${S.jobId}/cancel`, { method: 'POST' }); } catch { }
});

$('#retryFromError').addEventListener('click', () => {
  unlock(2);
  goStep(2);
  toast('Đã quay về cấu hình. Sửa lỗi rồi bấm Bắt đầu xử lý.', 'ok', 4500);
});

$('#toEditor').addEventListener('click', () => goStep(4));


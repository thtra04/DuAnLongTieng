/* frontend/js/core.js — trạng thái chung, khôi phục phiên, tiện ích, gọi API, điều hướng bước.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
/* ======================= VSub Studio — frontend ======================= */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

/* Địa chỉ backend. Rỗng = cùng origin (backend đang phục vụ giao diện).
   Chạy giao diện tách server thì đặt window.VSUB_API_BASE trong frontend/config.js. */
const API_BASE = (window.VSUB_API_BASE || '').replace(/\/+$/, '');
const apiUrl = p => (/^https?:/.test(p) ? p : API_BASE + p);

const S = {
  sys: null,
  sourceType: 'file',
  mediaId: null,
  mediaName: '',
  mediaInfo: null,
  url: '',
  linkInfo: null,   // kết quả /api/link/inspect cho link đang dán
  linkChecked: '',  // link đã kiểm tra xong (để không gọi lại)
  part: null,       // phần được chọn khi link có nhiều phần
  subMode: 'auto',
  scriptText: '',
  subtitleText: '',
  engine: 'google',
  jobId: null,
  poll: null,
  cues: [],
  analyzed: null,
  projectId: null,  // đang mở lại một dự án cũ?
  videoSrc: '',     // ép nguồn video cho trình phát (dùng khi mở dự án cũ)
  dash: null,       // dữ liệu dashboard lần đọc gần nhất
  target: null,     // {filmId, filmName, no} — đang làm cho tập nào
  display: 'second',
  activeCue: -1,
  renderJob: null,
  renderPoll: null,
};

const RECOVERY_KEY = 'vsub.active-job.v1';

function saveJobRecovery(payload) {
  try {
    const safe = { ...payload };
    // Bí mật không được nằm trong localStorage — nó sống qua cả lần đóng trình duyệt
    delete safe.api_key;
    delete safe.hf_token;
    localStorage.setItem(RECOVERY_KEY, JSON.stringify({ jobId: S.jobId, payload: safe }));
  } catch { }
}

function clearJobRecovery() {
  try { localStorage.removeItem(RECOVERY_KEY); } catch { }
}

async function restoreJobRecovery() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem(RECOVERY_KEY) || 'null'); } catch { return; }
  if (!saved?.jobId || !saved.payload) return;
  try {
    const job = await api(`/api/jobs/${saved.jobId}`);
    S.jobId = saved.jobId;
    unlock(2); unlock(3);
    goStep(3);
    paintProgress(job, '#stepsList', '#logBox');
    if (job.status === 'done') {
      S.analyzed = job.result;
      S.cues = (job.result.cues || []).map(c => ({ ...c }));
      unlock(4);
      setupEditor();
      $('#toEditor').classList.remove('hide');
      clearJobRecovery();
      toast('Đã khôi phục kết quả sau khi tải lại trang.', 'ok', 5000);
    } else if (job.status === 'error' || job.status === 'cancelled') {
      $('#cancelBtn').disabled = true;
      $('#phaseText').textContent = job.status === 'cancelled' ? 'đã huỷ' : 'lỗi — có thể sửa và chạy lại';
      $('#retryFromError').classList.remove('hide');
      toast('Đã khôi phục đúng bước lỗi. Sửa cấu hình rồi bấm chạy lại.', 'warn', 8000);
    } else {
      $('#cancelBtn').disabled = false;
      pollJob();
      toast('Đã tiếp tục theo dõi job sau khi tải lại trang.', 'ok', 4000);
    }
  } catch {
    toast('Job cũ không còn trên server; cấu hình nguồn vẫn được giữ lại.', 'warn', 6000);
    restorePayload(saved.payload);
  }
}

function restorePayload(payload) {
  S.sourceType = payload.source_type || 'file';
  S.mediaId = payload.media_id || null;
  S.mediaName = payload.video_name || '';
  S.url = payload.url || '';
  S.subMode = payload.sub_mode || 'auto';
  S.subtitleText = payload.subtitle_text || '';
  $('#urlInput').value = S.url;
  $('#scriptText').value = payload.script_text || '';
  $('#contextNote').value = payload.context_note || '';
  $('#glossary').value = payload.glossary || '';
  if (payload.ai_base_url) $('#aiBaseUrl').value = payload.ai_base_url;
  $('#srcLang').value = payload.source_lang || '';
  $('#tgtLang').value = payload.target_lang || 'vi';
  toast('Đã khôi phục cấu hình cũ. Kiểm tra nguồn rồi chạy lại.', 'warn', 7000);
}

/* ------------------------------- tiện ích ------------------------------- */
function toast(msg, kind = '', ms = 4200) {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = msg;
  $('#toasts').appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    setTimeout(() => el.remove(), 320);
  }, ms);
}

function fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)));
  return (n / Math.pow(1024, i)).toFixed(i ? 1 : 0) + ' ' + u[i];
}

function fmtTime(t) {
  t = Math.max(0, t || 0);
  const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60), cs = Math.floor((t % 1) * 100);
  const base = `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`;
  return h ? `${h}:${base}` : base;
}

/** Thời lượng cho người đọc: "9 giờ 11 phút", "38 phút". */
function fmtLength(sec) {
  sec = Math.round(sec || 0);
  const h = Math.floor(sec / 3600), m = Math.round((sec % 3600) / 60);
  if (h) return m ? `${h} giờ ${m} phút` : `${h} giờ`;
  if (m) return `${m} phút`;
  return `${sec} giây`;
}

/** Tên video/phần lấy từ trang ngoài — phải escape trước khi nhét vào innerHTML. */
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function api(url, opts = {}) {
  const res = await fetch(apiUrl(url), opts);
  let data = null;
  try { data = await res.json(); } catch { /* không phải JSON */ }
  if (!res.ok) throw new Error((data && data.error) || `Lỗi ${res.status}`);
  return data;
}

/* ------------------------------ điều hướng ------------------------------ */
function goStep(n) {
  $$('.panel').forEach(p => p.classList.remove('active'));
  $(`#panel${n}`).classList.add('active');
  $$('.step-btn').forEach(b => {
    const i = +b.dataset.step;
    b.classList.toggle('active', i === n);
    b.classList.toggle('done', i < n);
  });
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function updateStepSummary() {
  const source = S.mediaName || (S.url ? 'Link video' : 'Chưa chọn nguồn');
  $('#step1Sub').textContent = source.length > 28 ? source.slice(0, 27) + '…' : source;
  const target = $('#tgtLang')?.selectedOptions[0]?.textContent?.trim() || 'chưa chọn đích';
  const engine = S.engine === 'google' ? 'Google' : S.engine === 'openai' ? 'OpenAI' : S.engine === 'claude' ? 'Claude' : S.engine;
  $('#step2Sub').textContent = $('#doTranslate')?.checked ? `${target} · ${engine}` : 'Không dịch · phụ đề nguyên ngữ';
  $('#step3Sub').textContent = S.jobId ? 'Đang xử lý hoặc đã hoàn tất' : 'Sẵn sàng chạy';
  $('#step4Sub').textContent = S.cues.length ? `${S.cues.length} dòng · sửa và xuất` : 'Sửa lời, chỉnh kiểu, tải về';
}

function unlock(n) {
  const b = $(`.step-btn[data-step="${n}"]`);
  if (b) b.disabled = false;
}

$$('.step-btn').forEach(b => b.addEventListener('click', () => {
  if (!b.disabled) goStep(+b.dataset.step);
}));
$$('[data-goto]').forEach(b => b.addEventListener('click', () => goStep(+b.dataset.goto)));

/* ------------------------- hộp xác nhận / nhập liệu ---------------------- */
/* Không dùng window.confirm() / prompt(): trong trình duyệt nhúng (khung xem
   của Claude, webview Electron...) chúng không hiện gì mà trả về false/null
   ngay lập tức, nên mọi nút xoá, đổi tên, thêm tập "bấm mà không làm gì".
   Hai hộp dưới đây vẽ trong trang và trả về Promise. */
function _dialog({ message, input = null, ok = 'OK', cancel = 'Thôi', danger = false }) {
  return new Promise(resolve => {
    const wrap = document.createElement('div');
    wrap.className = 'modal-wrap';
    wrap.innerHTML = `
      <div class="modal" role="dialog" aria-modal="true">
        <p class="modal-msg"></p>
        ${input === null ? '' : '<input type="text" class="m-input">'}
        <div class="actions right">
          <button class="btn sm ghost m-cancel" type="button"></button>
          <button class="btn sm ${danger ? 'danger' : 'primary'} m-ok" type="button"></button>
        </div>
      </div>`;
    // textContent chứ không phải innerHTML: tên file/bộ phim là dữ liệu người dùng
    $('.modal-msg', wrap).textContent = message;
    $('.m-cancel', wrap).textContent = cancel;
    $('.m-ok', wrap).textContent = ok;
    const field = $('.m-input', wrap);
    if (field) field.value = input == null ? '' : String(input);
    const value = () => (field ? field.value : true);
    const done = v => { document.removeEventListener('keydown', onKey); wrap.remove(); resolve(v); };
    const onKey = e => {
      if (e.key === 'Escape') done(null);
      else if (e.key === 'Enter' && field && e.target === field) done(value());
    };
    $('.m-cancel', wrap).addEventListener('click', () => done(null));
    $('.m-ok', wrap).addEventListener('click', () => done(value()));
    wrap.addEventListener('click', e => { if (e.target === wrap) done(null); });
    document.addEventListener('keydown', onKey);
    document.body.appendChild(wrap);
    if (field) { field.focus(); field.select(); }
    else $('.m-cancel', wrap).focus();   // Enter vô tình thì huỷ, không xoá
  });
}

// Thay confirm(): true khi bấm nút xác nhận, false khi huỷ.
async function askConfirm(message, { ok = 'Xoá', cancel = 'Thôi', danger = true } = {}) {
  return (await _dialog({ message, ok, cancel, danger })) === true;
}

// Thay prompt(): chuỗi đã nhập, hoặc null khi huỷ (giống prompt để code gọi khỏi đổi).
function askInput(message, def = '', { ok = 'OK', cancel = 'Thôi' } = {}) {
  return _dialog({ message, input: def, ok, cancel });
}

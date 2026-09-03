/* ======================= VSub Studio — frontend ======================= */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

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
  const res = await fetch(url, opts);
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

/* --------------------------- dự án đã làm ------------------------------- */
const LANG_VI = code => {
  const l = (S.sys?.languages || []).find(x => x.code === code);
  return l ? `${l.flag} ${l.vi}` : code;
};

async function loadProjects() {
  const box = $('#projList');
  box.innerHTML = '<p class="muted">Đang đọc…</p>';
  let data;
  try {
    data = await api('/api/films');
  } catch (e) {
    box.innerHTML = `<p class="muted">Không đọc được danh sách: ${esc(e.message)}</p>`;
    return;
  }
  S.dash = data;

  const films = data.films || [];
  const loose = data.loose || [];
  $('#projCount').textContent = films.length;

  const bits = [];
  if (films.length) {
    const eps = films.reduce((n, f) => n + f.total, 0);
    bits.push(`<b>${films.length}</b> bộ phim · <b>${data.total_episodes}</b>/<b>${eps}</b> tập đã làm`);
  }
  if (loose.length) bits.push(`<b>${loose.length}</b> video chưa thuộc bộ nào`);
  $('#projSum').innerHTML = bits.length
    ? bits.join(' · ') + ` · chiếm ${fmtBytes(data.total_size)} trên đĩa`
    : '';

  if (!films.length && !loose.length) {
    box.innerHTML = `<p class="muted">Chưa có bộ phim nào.
      Bấm <b>➕ Tạo dự án phim</b> ở trên để bắt đầu.</p>`;
    return;
  }

  box.innerHTML =
    `<div class="serieslist">${films.map(filmCard).join('')}</div>`
    + (loose.length ? looseSection(loose) : '');

  films.forEach(f => bindFilm(f, box));
  bindLoose(loose, box);
}

function filmCard(f) {
  const pct = f.total ? Math.round(f.done / f.total * 100) : 0;
  const open = f.episodes.length <= 8;
  const doneEps = f.episodes.filter(e => e.project);
  const todoEps = f.episodes.filter(e => !e.project);

  return `
  <div class="sr${open ? ' open' : ''}" data-film="${f.id}">
    <div class="sr-top">
      <span class="ic">🎬</span>
      <div class="sr-main">
        <span class="sr-name">${esc(f.name)}</span>
        <span class="sr-prog">
          ${f.total
            ? `<span class="txt">Đã làm <b>${f.done}</b> trong <b>${f.total}</b> tập</span>
               <span class="pbar${pct >= 100 ? ' full' : ''}"><i style="width:${pct}%"></i></span>`
            : '<span class="txt">Chưa có tập nào</span>'}
        </span>
        <span class="sr-when">
          ${f.done ? `Làm gần nhất ${fmtWhen(f.updated)} · ${fmtBytes(f.size)}`
                   : `Tạo ${fmtWhen(f.created)}`}
          ${f.url ? ' · có link cả bộ' : ''}
        </span>
      </div>
      <div class="sr-ops">
        <button class="btn sm f-addep">➕ Thêm tập</button>
        <button class="btn sm ghost f-rename">✏️ Đổi tên</button>
        <button class="btn sm danger f-del">🗑 Xoá bộ</button>
      </div>
      <span class="sr-caret">▾</span>
    </div>

    <div class="sr-body">
      ${doneEps.length ? `
        <div class="sr-sec">Đã làm — ${doneEps.length} tập</div>
        <div class="eplist">${doneEps.map(e => epDone(f, e)).join('')}</div>` : ''}

      ${todoEps.length ? `
        <div class="sr-sec">Chưa có video — ${todoEps.length} tập</div>
        <div class="eplist">${todoEps.map(e => epTodo(f, e)).join('')}</div>` : ''}

      ${!f.episodes.length ? `
        <div class="sr-sec">Bộ này chưa có tập nào</div>
        <p class="muted">Bấm <b>➕ Thêm tập</b> ở trên để tạo tập đầu tiên.</p>` : ''}
    </div>
  </div>`;
}

/** Tập đã có phụ đề. */
function epDone(f, e) {
  const p = e.project;
  const langs = p.target_lang
    ? `${LANG_VI(p.source_lang || '?')} → ${LANG_VI(p.target_lang)}`
    : `${LANG_VI(p.source_lang || '?')} (chưa dịch)`;
  const files = p.files || [];
  const out = files.length
    ? `Đã xuất: <span class="ep-files">${files.map(x =>
        `<a href="/api/projects/${p.id}/files/${encodeURIComponent(x.name)}" download
            title="${esc(x.name)} · ${fmtBytes(x.size)}">${esc(x.kind.toUpperCase())}</a>`).join('')}</span>`
    : '<span style="color:var(--dim)">Chưa xuất file nào</span>';

  return `
  <div class="ep${p.video_ok ? '' : ' gone'}" data-no="${e.no}" data-id="${p.id}">
    <span class="ep-no"><b>${e.no}</b><span>TẬP</span></span>
    <div class="ep-info">
      <div class="line1" title="${esc(p.video_name)}">
        ${e.title ? esc(e.title) + ' · ' : ''}${langs} · ${p.cue_count} dòng · ${fmtLength(p.duration)}
      </div>
      <div class="line2">
        ${out}
        ${p.video_ok ? '' : ' · <span class="warn">video gốc đã mất — chỉ xuất được file chữ</span>'}
      </div>
    </div>
    <div class="ep-ops">
      <button class="btn sm ep-open">Mở ra sửa</button>
      <button class="btn sm danger ep-del">🗑 Xoá tập</button>
    </div>
  </div>`;
}

/** Tập đã tạo nhưng chưa có video. */
function epTodo(f, e) {
  return `
  <div class="ep todo-ep" data-no="${e.no}">
    <span class="ep-no empty"><b>${e.no}</b><span>TẬP</span></span>
    <div class="ep-info">
      <div class="line1">${e.title ? esc(e.title) : 'Chưa đặt tên tập'}
        ${e.duration ? `<span class="muted"> · ${fmtLength(e.duration)}</span>` : ''}</div>
      <div class="line2">
        ${e.stale
          ? '<span class="warn">Phụ đề của tập này đã bị xoá</span>'
          : '<span style="color:var(--dim)">Chưa có video — cần dán link hoặc upload</span>'}
      </div>
    </div>
    <div class="ep-ops">
      <button class="btn sm primary ep-src">📥 Đưa video vào</button>
      <button class="btn sm danger ep-rm">🗑</button>
    </div>
  </div>`;
}

function looseSection(loose) {
  return `
  <div class="sr open loosebox" data-film="">
    <div class="sr-top" style="cursor:default">
      <span class="ic">📼</span>
      <div class="sr-main">
        <span class="sr-name">Chưa thuộc bộ nào — ${loose.length} video</span>
        <span class="sr-when">Làm trước khi tạo bộ, hoặc upload lẻ. Gán vào bộ để gom lại.</span>
      </div>
    </div>
    <div class="sr-body">
      <div class="eplist">${loose.map(p => `
        <div class="ep${p.video_ok ? '' : ' gone'}" data-id="${p.id}">
          <span class="ep-no"><b>🎞️</b></span>
          <div class="ep-info">
            <div class="line1" title="${esc(p.video_name)}">${esc(p.video_name)}</div>
            <div class="line2">${p.cue_count} dòng · ${fmtLength(p.duration)} ·
              ${p.target_lang ? `${LANG_VI(p.source_lang || '?')} → ${LANG_VI(p.target_lang)}`
                              : LANG_VI(p.source_lang || '?')}</div>
          </div>
          <div class="ep-ops">
            <button class="btn sm lo-assign">Gán vào bộ</button>
            <button class="btn sm lo-open">Mở ra sửa</button>
            <button class="btn sm danger lo-del">🗑</button>
          </div>
        </div>`).join('')}</div>
    </div>
  </div>`;
}

function bindFilm(f, box) {
  const card = $(`.sr[data-film="${f.id}"]`, box);
  if (!card) return;

  $('.sr-top', card).addEventListener('click', e => {
    if (e.target.closest('.btn')) return;
    card.classList.toggle('open');
  });
  $('.f-addep', card).addEventListener('click', () => addEpisode(f));
  $('.f-rename', card).addEventListener('click', () => renameFilm(f));
  $('.f-del', card).addEventListener('click', () => deleteFilm(f));

  $$('.ep', card).forEach(row => {
    const no = +row.dataset.no;
    const ep = f.episodes.find(x => x.no === no);
    $('.ep-open', row)?.addEventListener('click', () => openProject(row.dataset.id));
    $('.ep-del', row)?.addEventListener('click', () => removeEpisode(f, ep, true));
    $('.ep-rm', row)?.addEventListener('click', () => removeEpisode(f, ep, false));
    $('.ep-src', row)?.addEventListener('click', () => giveSource(f, ep));
  });
}

function bindLoose(loose, box) {
  const card = $('.loosebox', box);
  if (!card) return;
  $$('.ep', card).forEach(row => {
    const p = loose.find(x => x.id === row.dataset.id);
    $('.lo-open', row)?.addEventListener('click', () => openProject(row.dataset.id));
    $('.lo-del', row)?.addEventListener('click', () => deleteProject(p, null));
    $('.lo-assign', row)?.addEventListener('click', () => assignLoose(p));
  });
}

/** "hôm nay 13:09" dễ đọc hơn "13:09:59 12/8/2026". */
function fmtWhen(ts) {
  const d = new Date(ts * 1000);
  const hm = d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
  const day = new Date(d).setHours(0, 0, 0, 0);
  const today = new Date().setHours(0, 0, 0, 0);
  const diff = Math.round((today - day) / 86400000);
  if (diff === 0) return `hôm nay ${hm}`;
  if (diff === 1) return `hôm qua ${hm}`;
  if (diff < 7) return `${diff} ngày trước, ${hm}`;
  return d.toLocaleDateString('vi-VN') + ' ' + hm;
}

/* ---------------------- tạo bộ phim / thêm tập -------------------------- */
$('#filmNew').addEventListener('click', () => {
  $('#filmForm').classList.remove('hide');
  $('#filmName').focus();
});
$('#filmCancel').addEventListener('click', () => {
  $('#filmForm').classList.add('hide');
  $('#filmName').value = ''; $('#filmUrl').value = '';
});
$('#filmSave').addEventListener('click', createFilm);

async function createFilm() {
  const name = $('#filmName').value.trim();
  const url = $('#filmUrl').value.trim();
  if (!name && !url) return toast('Đặt tên bộ phim, hoặc dán link để tool tự lấy tên.', 'warn');

  const btn = $('#filmSave');
  btn.disabled = true;
  btn.textContent = url ? 'Đang đọc link…' : 'Đang tạo…';
  try {
    const r = await api('/api/films', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, url }),
    });
    const n = (r.film.episodes || []).length;
    toast(`Đã tạo bộ "${r.film.name}"${n ? ` với ${n} tập` : ''}.`, 'ok', 4000);
    if (r.adopted) toast(`Tự gắn ${r.adopted} tập bạn đã làm trước đó vào bộ này.`, 'ok', 7000);
    $('#filmCancel').click();
    await loadProjects();
  } catch (e) {
    toast('Không tạo được: ' + e.message, 'err', 10000);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Tạo bộ phim';
  }
}

async function renameFilm(f) {
  const name = prompt('Tên bộ phim:', f.name);
  if (name === null) return;
  try {
    await api(`/api/films/${f.id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    });
  } catch (e) {
    return toast('Không đổi được tên: ' + e.message, 'err', 9000);
  }
  loadProjects();
}

async function deleteFilm(f) {
  const ok = confirm(
    `Xoá bộ "${f.name}"?\n\n`
    + `Bộ này có ${f.total} tập, trong đó ${f.done} tập đã có phụ đề.\n`
    + 'Xoá bộ là mất luôn phụ đề và file đã xuất của những tập đó.\n'
    + 'File video gốc trên máy bạn không bị đụng tới.'
  );
  if (!ok) return;
  try {
    const r = await api(`/api/films/${f.id}?with_jobs=1&with_source=1`, { method: 'DELETE' });
    toast(`Đã xoá bộ, dọn ${r.removed} tập, giải phóng ${fmtBytes(r.freed)}.`, 'ok', 4500);
  } catch (e) {
    return toast('Xoá không được: ' + e.message, 'err', 9000);
  }
  loadProjects();
}

async function addEpisode(f) {
  const used = f.episodes.map(e => e.no);
  const next = used.length ? Math.max(...used) + 1 : 1;
  const raw = prompt(`Thêm tập số mấy?\n\n(bộ đang có: ${used.join(', ') || 'chưa có tập nào'})`, next);
  if (raw === null) return;
  const no = parseInt(raw, 10);
  if (!Number.isFinite(no) || no < 1) return toast('Số tập phải là số từ 1 trở lên.', 'warn');
  try {
    await api(`/api/films/${f.id}/episodes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ no }),
    });
    toast(`Đã thêm tập ${no}. Giờ bấm "📥 Đưa video vào" để làm nó.`, 'ok', 5000);
  } catch (e) {
    return toast('Không thêm được tập: ' + e.message, 'err', 9000);
  }
  loadProjects();
}

async function removeEpisode(f, ep, hasJob) {
  if (!ep) return;
  const ok = confirm(hasJob
    ? `Xoá tập ${ep.no} của "${f.name}"?\n\nMất phụ đề và file đã xuất của tập này.\nCác tập khác vẫn còn.`
    : `Bỏ tập ${ep.no} khỏi bộ "${f.name}"?\n\nTập này chưa có video nên không mất gì cả.`);
  if (!ok) return;
  try {
    const r = await api(`/api/films/${f.id}/episodes/${ep.no}?with_job=1&with_source=1`,
      { method: 'DELETE' });
    toast(r.freed ? `Đã xoá tập ${ep.no}, giải phóng ${fmtBytes(r.freed)}.`
                  : `Đã bỏ tập ${ep.no}.`, 'ok', 3500);
  } catch (e) {
    return toast('Xoá không được: ' + e.message, 'err', 9000);
  }
  loadProjects();
}

/* -------- bước 3 của luồng: đưa video vào một tập cụ thể --------------- */

/** Đặt tập đang làm, về bước 1, và dán sẵn link/phần nếu bộ có link. */
async function giveSource(f, ep) {
  S.target = { filmId: f.id, filmName: f.name, no: ep.no };
  renderTargetBar();
  goStep(1);

  if (!f.url) {
    setSource('file');
    toast(`Đang làm tập ${ep.no} của "${f.name}" — chọn video từ máy hoặc dán link.`, 'ok', 7000);
    return;
  }
  setSource('url');
  $('#urlInput').value = f.url;
  $('#urlInput').dispatchEvent(new Event('input', { bubbles: true }));
  const info = await inspectLink();
  if (!info) return;
  if (info.multi) {
    const el = $(`.part[data-part="${ep.no}"]`);
    if (el) {
      el.click();
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      toast(`Đã chọn phần ${ep.no} — bấm "Tiếp tục →".`, 'ok', 6000);
      return;
    }
    toast(`Link không có phần ${ep.no} — chọn phần khác trong danh sách.`, 'warn', 8000);
  }
}

function renderTargetBar() {
  const bar = $('#targetBar');
  if (!S.target) {
    bar.classList.add('hide');
    bar.innerHTML = '';
    return;
  }
  bar.innerHTML = `🎯 Đang làm <b>tập ${S.target.no}</b> của bộ <b>${esc(S.target.filmName)}</b>
    — xong sẽ tự gắn vào đúng tập này.
    <button class="btn ghost" id="targetClear">Bỏ, làm video lẻ</button>`;
  bar.classList.remove('hide');
  $('#targetClear').addEventListener('click', () => {
    S.target = null;
    renderTargetBar();
    toast('Đã bỏ — video này sẽ không gắn vào bộ nào.', 'ok', 3500);
  });
}

/** Gán một video lẻ (đã làm rồi) vào một tập của bộ nào đó. */
async function assignLoose(p) {
  const films = (S.dash?.films || []);
  if (!films.length) return toast('Chưa có bộ phim nào. Tạo bộ trước đã.', 'warn', 6000);

  const menu = films.map((f, i) => `${i + 1}. ${f.name} (${f.done}/${f.total} tập)`).join('\n');
  const pick = prompt(`Gán "${p.video_name}" vào bộ nào?\n\n${menu}\n\nNhập số:`, '1');
  if (pick === null) return;
  const film = films[parseInt(pick, 10) - 1];
  if (!film) return toast('Số không hợp lệ.', 'warn');

  const free = film.episodes.filter(e => !e.project).map(e => e.no);
  if (!free.length) return toast(`Bộ "${film.name}" không còn tập nào trống.`, 'warn', 7000);
  const rawNo = prompt(`Gán vào tập số mấy của "${film.name}"?\n\nCác tập còn trống: ${free.join(', ')}`,
    free[0]);
  if (rawNo === null) return;

  try {
    await api(`/api/films/${film.id}/episodes/${parseInt(rawNo, 10)}/bind`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job: p.id }),
    });
    toast(`Đã gán vào tập ${rawNo} của "${film.name}".`, 'ok', 4000);
  } catch (e) {
    return toast('Không gán được: ' + e.message, 'err', 9000);
  }
  loadProjects();
}

async function openProject(id) {
  let p;
  try {
    p = await api(`/api/projects/${id}`);
  } catch (e) {
    return toast('Không mở được dự án: ' + e.message, 'err', 9000);
  }
  if (!p.cues || !p.cues.length) return toast('Dự án này không có dòng phụ đề nào.', 'warn');

  S.jobId = id;                       // xuất file vẫn dùng state.json của job này
  S.projectId = id;
  S.videoSrc = p.video_ok ? `/api/projects/${id}/video` : '';
  S.cues = p.cues.map(c => ({ ...c }));
  S.analyzed = {
    source_lang: p.source_lang, target_lang: p.target_lang,
    duration: p.duration, width: p.width, height: p.height,
    cue_count: p.cue_count, coverage: 1,
  };
  S.display = p.target_lang ? 'second' : 'main';
  if (p.source_lang) $('#srcLang').value = p.source_lang;
  if (p.target_lang) $('#tgtLang').value = p.target_lang;

  unlock(4);
  goStep(4);
  setupEditor();
  toast(`Đã mở "${p.video_name}" — ${p.cue_count} dòng.`, 'ok', 3500);
  if (!p.video_ok) {
    toast('Video gốc không còn trên máy: vẫn sửa & xuất được phụ đề, nhưng không xem trước '
      + 'và không nung vào video.', 'warn', 11000);
  }
}

async function deleteProject(ep, group) {
  const what = group && !group.standalone && ep.part
    ? `tập ${ep.part} của bộ "${group.name}"`
    : `"${ep.video_name}"`;
  const ok = confirm(
    `Xoá ${what}?\n\n`
    + 'CHỈ xoá tập này, các tập khác trong bộ vẫn còn.\n\n'
    + 'Mất: phụ đề đã làm, các file đã xuất, và bản video mà tool đang giữ.\n'
    + 'File video gốc trên máy bạn thì không bị đụng tới.'
  );
  if (!ok) return;
  try {
    // with_source: dọn luôn bản video tool đang giữ, nếu không dự án nào khác dùng
    const r = await api(`/api/projects/${ep.id}?with_source=1`, { method: 'DELETE' });
    toast(`Đã xoá, giải phóng ${fmtBytes(r.freed)}.`, 'ok', 3500);
  } catch (e) {
    return toast('Xoá không được: ' + e.message, 'err', 9000);
  }
  if (S.projectId === ep.id) { S.projectId = null; S.videoSrc = ''; }
  loadProjects();
}

$('#projReload').addEventListener('click', loadProjects);

/* ------------------------- bước 1: nguồn video -------------------------- */
function setSource(type) {
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
// dán xong rồi rời ô (hoặc Enter) là tự kiểm tra luôn
$('#urlInput').addEventListener('change', () => {
  if ($('#urlInput').value.trim()) inspectLink();
});
$('#checkLink').addEventListener('click', () => inspectLink());
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) uploadFile(fileInput.files[0]);
});

/* ----------------- link nhiều phần: hỏi xử lý phần nào ------------------ */
function clearLinkInfo() {
  S.linkInfo = null;
  S.linkChecked = '';
  S.part = null;
  $('#linkState').textContent = '';
  $('#linkParts').innerHTML = '';
  $('#linkParts').classList.add('hide');
}

let linkPending = { url: '', promise: null };

/** Đọc link để biết có bao nhiêu phần. Trả về info, hoặc null nếu lỗi. */
async function inspectLink() {
  const url = $('#urlInput').value.trim();
  if (!url) return null;
  if (S.linkChecked === url && S.linkInfo) return S.linkInfo;
  if (linkPending.url === url && linkPending.promise) return linkPending.promise;

  $('#checkLink').disabled = true;
  $('#linkState').textContent = '⏳ Đang đọc link…';

  linkPending = {
    url,
    promise: (async () => {
      try {
        const info = await api('/api/link/inspect', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url }),
        });
        S.linkInfo = info;
        S.linkChecked = url;
        S.part = null;
        renderLinkParts(info);
        return info;
      } catch (e) {
        clearLinkInfo();
        toast('Không đọc được link: ' + e.message, 'err', 9000);
        return null;
      } finally {
        $('#checkLink').disabled = false;
        linkPending = { url: '', promise: null };
      }
    })(),
  };
  return linkPending.promise;
}

function renderLinkParts(info) {
  const box = $('#linkParts'), state = $('#linkState');

  if (!info.multi) {
    box.innerHTML = '';
    box.classList.add('hide');
    state.innerHTML = '✅ Link chỉ có một video'
      + (info.title ? ` · <b>${esc(info.title.slice(0, 60))}</b>` : '')
      + (info.duration ? ` · ${fmtLength(info.duration)}` : '');
    updateSourceSummary();
    return;
  }

  state.innerHTML = `⚠ Link có <b>${info.count}</b> phần — chọn phần bên dưới.`;
  const rows = info.parts.map(p => `
    <div class="part" data-part="${p.index}">
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
    <div class="filecard"><span class="ic">⏳</span>
      <div class="meta"><b>${file.name}</b><span>Đang tải lên… ${fmtBytes(file.size)}</span></div></div>`;
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
      <div class="filecard"><span class="ic">🎞️</span>
        <div class="meta"><b>${r.name}</b>
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
    <div class="filecard"><span class="ic">🗂️</span>
      <div class="meta"><b>${f.name}</b><span>${lines} dòng phụ đề · ${fmtBytes(f.size)}</span></div></div>`;
  toast(`Đã nạp ${lines} dòng phụ đề.`, 'ok', 2500);
}

$('#toStep2').addEventListener('click', async () => {
  const btn = $('#toStep2');
  if (S.sourceType === 'file') {
    if (!S.mediaId) return toast('Bạn chưa chọn video từ máy.', 'warn');
    S.url = '';
    S.part = null;
  } else {
    S.url = $('#urlInput').value.trim();
    if (!S.url) return toast('Bạn chưa dán link video.', 'warn');

    // Chưa kiểm tra link thì kiểm tra ngay — link nhiều phần phải chọn phần
    btn.disabled = true;
    let info;
    try { info = await inspectLink(); } finally { btn.disabled = false; }
    if (!info) return;
    if (info.multi && !S.part) {
      updateSourceSummary();
      $('#linkParts').scrollIntoView({ behavior: 'smooth', block: 'center' });
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

/* --------------------------- bước 2: cấu hình --------------------------- */
$('#doTranslate').addEventListener('change', e => {
  const on = e.target.checked;
  $('#engineCard').classList.toggle('hide', !on);
  $('#tgtLang').disabled = !on;
  updateStepSummary();
});

function bindRange(id, outId, fmt = v => v) {
  const el = $(id), out = $(outId);
  const upd = () => { out.textContent = fmt(el.value); };
  el.addEventListener('input', upd); upd();
}
bindRange('#maxChars', '#maxCharsOut');
bindRange('#stSize', '#stSizeOut');
bindRange('#stOutline', '#stOutlineOut');
bindRange('#stMargin', '#stMarginOut');
bindRange('#stLineChars', '#stLineCharsOut');
bindRange('#crf', '#crfOut');

$('#startBtn').addEventListener('click', startAnalyze);

async function startAnalyze() {
  if ($('#doTranslate').checked && (S.engine === 'claude' || S.engine === 'openai')) {
    const hasEnvKey = S.engine === 'claude' ? S.sys.has_anthropic_key : S.sys.has_openai_key;
    if (!$('#apiKey').value.trim() && !hasEnvKey) {
      return toast('Hãy nhập API key hoặc đặt biến môi trường cho engine AI đã chọn.', 'warn', 7000);
    }
  }
  const payload = {
    source_type: S.sourceType,
    media_id: S.mediaId,
    url: S.url,
    part: S.sourceType === 'url' ? S.part : null,
    // xong thì tự gắn kết quả vào đúng tập của bộ phim đang làm
    film_id: S.target?.filmId || '',
    episode_no: S.target?.no ?? null,
    series_name: S.sourceType === 'url' ? (S.linkInfo?.title || '') : '',
    series_total: S.sourceType === 'url' ? (S.linkInfo?.count || 0) : 0,
    sub_mode: S.subMode,
    script_text: $('#scriptText').value,
    subtitle_text: S.subtitleText,
    source_lang: $('#srcLang').value || null,
    target_lang: $('#tgtLang').value,
    translate: $('#doTranslate').checked,
    engine: S.engine,
    api_key: $('#apiKey').value.trim(),
    ai_model: $('#aiModel').value || '',
    ai_base_url: S.engine === 'openai' ? $('#aiBaseUrl').value.trim() : '',
    context_note: $('#contextNote').value.trim(),
    translation_mode: $('#translationMode').value,
    glossary: $('#glossary').value.trim(),
    asr_model: $('#asrModel').value,
    device: $('#device').value,
    vad: $('#vad').checked,
    auto_fix: $('#autoFix').checked,
    prompt: $('#prompt').value.trim(),
    max_chars: +$('#maxChars').value,
    diarize: $('#diarizeOn').checked,
    num_speakers: +$('#numSpeakers').value || null,
    hf_token: $('#hfToken').value.trim(),
    // HP-5: chỉ có nghĩa với engine AI — máy chủ tự bỏ qua với Google/MyMemory
    budget_loop: !!($('#budgetLoop') && $('#budgetLoop').checked),
  };
  savePrefs();

  // Chạy mới thì thôi không còn dính vào dự án cũ đang mở
  S.projectId = null;
  S.videoSrc = '';

  $('#startBtn').disabled = true;
  try {
    const r = await api('/api/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    S.jobId = r.job_id;
    saveJobRecovery(payload);
    updateStepSummary();
    unlock(3);
    goStep(3);
    $('#toEditor').classList.add('hide');
    $('#cancelBtn').disabled = false;
    pollJob();
  } catch (e) {
    toast(e.message, 'err', 8000);
  } finally {
    $('#startBtn').disabled = false;
  }
}

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

/* --------------------------- bước 4: biên tập --------------------------- */
function setupEditor() {
  const player = $('#player');
  const src = S.videoSrc || (S.sourceType === 'file'
    ? `/api/media/${S.mediaId}/stream`
    : `/api/media/${S.jobId}/stream`);
  if (player.dataset.src !== src) {
    player.src = src;
    player.dataset.src = src;
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
}

function renderCues() {
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
        ${c.speaker ? `<span class="spk s${spkSlot(c.speaker)}" title="Nhân vật ${esc(c.speaker)}">${esc(spkName(c.speaker))}</span>` : ''}
        <span class="len ${cps > 22 ? 'warn' : ''}" title="ký tự/giây — trên 22 là hơi nhanh">${cps} cps</span>
        ${tooLong ? '<span class="len warn" title="Bản dịch dài hơn 125% bản gốc — nên rút gọn trước khi lồng tiếng">Dài</span>' : ''}
      </div>
      <textarea class="src" rows="1" data-i="${i}">${escapeHtml(c.text)}</textarea>
      ${showTr ? `<textarea class="tr" rows="1" data-i="${i}">${escapeHtml(c.text2 || '')}</textarea>` : ''}
    </div>`;
  }).join('');

  $$('.cue', list).forEach(el => el.addEventListener('click', e => {
    if (e.target.tagName === 'TEXTAREA') return;
    const i = +el.dataset.i;
    $('#player').currentTime = S.cues[i].start + 0.02;
  }));
  $$('textarea.src', list).forEach(t => t.addEventListener('input', () => {
    S.cues[+t.dataset.i].text = t.value;
    updateOverlay();
  }));
  $$('textarea.tr', list).forEach(t => t.addEventListener('input', () => {
    S.cues[+t.dataset.i].text2 = t.value;
    updateOverlay();
  }));
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
    // cộng thêm chiều cao thanh điều khiển để chữ không bị che khi xem trước
    ov.style.bottom = `calc(${mv}% + 38px)`;
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

/* ------------------------------ lồng tiếng ------------------------------ */
bindRange('#dubOrigVol', '#dubOrigVolOut', v => v + '%');
bindRange('#dubVol', '#dubVolOut', v => v + '%');
bindRange('#dubSpeed', '#dubSpeedOut', v => (v / 100).toFixed(2) + '×');

function initTts() {
  const t = S.sys.tts || {};
  $('#dubStyle').innerHTML = (t.styles || [])
    .map(s => `<option value="${s.id}">${s.label}</option>`).join('');
  if (!t.available) {
    $('#ttsBox').classList.add('hide');
    $('#ttsUnavailable').classList.remove('hide');
    $('#ttsReason').innerHTML =
      `Chưa bật được lồng tiếng — ${t.reason || 'thiếu VieNeu-TTS'}.<br>` +
      `Cài bằng: <code>uv sync --extra tts</code> rồi khởi động lại tool.`;
  }
}

$('#dubOn').addEventListener('change', async e => {
  const on = e.target.checked;
  $('#dubOpts').classList.toggle('hide', !on);
  $('#outDubWrap').classList.toggle('hide', !on);
  $('#outDubWavWrap').classList.toggle('hide', !on);
  const outDub = $('#outDub');
  outDub.checked = on;
  outDub.closest('.check').classList.toggle('on', on);
  if (on && !S.voicesLoaded) await loadVoices();
  if (on) renderSpeakerVoices();
});

async function loadVoices() {
  const sel = $('#dubVoice');
  sel.innerHTML = '<option value="">Đang tải model giọng… (lần đầu ~1 phút)</option>';
  try {
    const r = await api('/api/tts/voices');
    if (!r.available) throw new Error(r.reason);
    const clone = r.clone_id || '__clone__';
    // Thiếu thư viện thì khoá sẵn mục nhân bản, đừng để chọn rồi xuất mới lỗi
    const cloneOk = r.clone !== false;
    S.voices = r.voices || [];
    S.cloneOk = cloneOk;
    sel.innerHTML =
      r.voices.map(v => `<option value="${v.id}">${esc(v.label)}</option>`).join('') +
      `<option value="${clone}"${cloneOk ? '' : ' disabled'}>` +
      (cloneOk
        ? '🧬 Nhân bản giọng người nói trong video'
        : '🧬 Nhân bản giọng — chưa dùng được (cần uv sync --extra clone)') +
      '</option>';
    S.voicesLoaded = true;
    renderSpeakerVoices();
    toast(`Đã nạp ${r.voices.length} giọng đọc.`, 'ok', 2600);
    if (!cloneOk && r.clone_reason) {
      toast('Nhân bản giọng: ' + r.clone_reason, 'warn', 9000);
    }
  } catch (e) {
    sel.innerHTML = '<option value="">— không tải được —</option>';
    toast('Không lấy được danh sách giọng: ' + e.message, 'err', 9000);
  }
}

$('#dubKeepOrig').addEventListener('change', e => {
  $('#origVolWrap').style.opacity = e.target.checked ? '1' : '.4';
  $('#dubOrigVol').disabled = !e.target.checked;
});

$('#dubTest').addEventListener('click', async () => {
  const btn = $('#dubTest'), msg = $('#dubTestMsg');
  const voice = $('#dubVoice').value;
  if (!voice) return toast('Chưa chọn giọng.', 'warn');
  if (voice === (S.sys.tts?.clone_id || '__clone__'))
    return toast('Giọng nhân bản chỉ tạo được lúc xuất video.', 'warn', 6000);

  // đọc thử chính dòng đang chọn, không có thì dùng câu mẫu
  const c = S.cues[S.activeCue] || S.cues[0];
  const text = (c && (c.text2 || c.text)) || 'Xin chào, đây là giọng đọc thử.';

  btn.disabled = true; msg.textContent = 'đang tạo…';
  try {
    const res = await fetch('/api/tts/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 300), voice, style: $('#dubStyle').value }),
    });
    if (!res.ok) throw new Error((await res.json()).error || 'lỗi');
    const url = URL.createObjectURL(await res.blob());
    const a = $('#dubAudio');
    a.src = url; a.classList.remove('hide'); a.controls = true;
    $('#player').pause();
    await a.play();
    msg.textContent = '';
  } catch (e) {
    msg.textContent = '';
    toast('Nghe thử lỗi: ' + e.message, 'err', 8000);
  } finally {
    btn.disabled = false;
  }
});

/* --------------------------- nhân vật & giọng --------------------------- */

/* Nhãn nhân vật từ máy chủ là S1, S2… Người dùng đổi tên được, tên đổi chỉ nằm
   trong phiên làm việc — nó thuần tuý để nhìn cho dễ, máy chủ vẫn dùng nhãn gốc. */
const SPK_SLOTS = 6;

function spkSlot(id) {
  const n = parseInt(String(id).replace(/\D/g, ''), 10);
  return (Number.isFinite(n) ? (n - 1) % SPK_SLOTS : 0) + 1;
}

function spkName(id) {
  const custom = (S.speakerNames || {})[id];
  if (custom) return custom;
  const n = parseInt(String(id).replace(/\D/g, ''), 10);
  return Number.isFinite(n) ? `Vai ${n}` : id;
}

function initDiarize() {
  const d = S.sys.diarize || {};
  const box = $('#diarizeOpts');
  const hint = $('#diarizeHint');

  // Có token trong biến môi trường rồi thì khỏi bắt nhập lại
  if (d.has_token) $('#hfTokenWrap').classList.add('hide');

  $('#diarizeOn').addEventListener('change', e => {
    box.classList.toggle('hide', !e.target.checked);
  });

  if (!d.available && !d.has_token) {
    hint.innerHTML =
      `${esc(d.reason || 'Chưa dùng được.')}<br>` +
      `Model: <code>${esc(d.model || '')}</code> — mở trang model trên Hugging Face, ` +
      `bấm chấp nhận điều khoản, rồi tạo token ở mục Access Tokens.`;
  } else {
    hint.textContent =
      'Chạy trên chính đường tiếng của video nên không phụ thuộc ngôn ngữ — '
      + 'phim Trung, Hàn, Nhật, Anh đều dùng được.';
  }
}

/** Bảng chọn giọng cho từng nhân vật, dựng lại mỗi khi có phụ đề mới. */
function renderSpeakerVoices() {
  const box = $('#spkBox'), list = $('#spkList');
  const speakers = speakersFromCues();

  if (!speakers.length) {
    box.classList.add('hide');
    list.innerHTML = '';
    return;
  }
  box.classList.remove('hide');
  $('#spkCount').textContent =
    `${speakers.length} nhân vật · ${speakers.reduce((n, s) => n + s.lines, 0)} dòng`;

  S.speakerVoices = S.speakerVoices || {};
  const voices = S.voices || [];
  const cloneId = S.sys.tts?.clone_id || '__clone__';

  // Mặc định: mỗi nhân vật một giọng dựng sẵn khác nhau. Chọn giọng có sẵn thay
  // vì nhân bản vì nhân bản chậm hơn nhiều và có thể trượt ở vai ít thoại —
  // muốn nhân bản thì đổi một cú bấm.
  speakers.forEach((s, i) => {
    if (!S.speakerVoices[s.id] && voices.length) {
      S.speakerVoices[s.id] = voices[i % voices.length].id;
    }
  });

  list.innerHTML = speakers.map(s => `
    <div class="spkrow" data-spk="${esc(s.id)}">
      <span class="spk s${spkSlot(s.id)} big">${esc(s.id)}</span>
      <div class="spkmain">
        <div class="spkline">
          <input class="spkname" type="text" value="${esc(spkName(s.id))}"
                 data-spk="${esc(s.id)}" maxlength="40" aria-label="Tên nhân vật ${esc(s.id)}">
          <span class="muted">${s.lines} dòng · ${Math.round(s.seconds)}s nói</span>
        </div>
        ${s.sample ? `<div class="spksample">“${esc(s.sample)}”</div>` : ''}
        <div class="spkline">
          <select class="spkvoice" data-spk="${esc(s.id)}" aria-label="Giọng cho ${esc(s.id)}">
            ${voices.map(v => `<option value="${esc(v.id)}"${S.speakerVoices[s.id] === v.id ? ' selected' : ''}>${esc(v.label)}</option>`).join('')}
            <option value="${esc(cloneId)}"${S.speakerVoices[s.id] === cloneId ? ' selected' : ''}
              ${S.cloneOk === false ? ' disabled' : ''}>
              🧬 Nhân bản chính giọng nhân vật này
            </option>
          </select>
          <button class="btn sm ghost spktest" data-spk="${esc(s.id)}">🔊</button>
        </div>
      </div>
    </div>`).join('');

  $$('.spkvoice', list).forEach(sel => sel.addEventListener('change', () => {
    S.speakerVoices[sel.dataset.spk] = sel.value;
  }));
  $$('.spkname', list).forEach(inp => inp.addEventListener('input', () => {
    S.speakerNames = S.speakerNames || {};
    S.speakerNames[inp.dataset.spk] = inp.value.trim();
    renderCues();
  }));
  $$('.spktest', list).forEach(btn => btn.addEventListener('click', () => {
    previewSpeaker(btn.dataset.spk, btn);
  }));
}

/** Danh sách nhân vật rút thẳng từ cue đang có trên màn hình.
    Lấy từ cue chứ không lấy từ `S.analyzed.speakers` để người dùng sửa nhãn ở
    bước 4 thì bảng giọng cập nhật theo ngay. */
function speakersFromCues() {
  const table = {};
  S.cues.forEach(c => {
    const id = (c.speaker || '').trim();
    if (!id) return;
    const item = table[id] || (table[id] = { id, lines: 0, seconds: 0, sample: '' });
    item.lines++;
    item.seconds += Math.max(0, c.end - c.start);
    if (!item.sample) item.sample = (c.text2 || c.text || '').trim().slice(0, 70);
  });
  return Object.values(table).sort((a, b) => b.seconds - a.seconds);
}

/** {nhãn nhân vật: id giọng} gửi kèm lúc xuất file. */
function collectSpeakerVoices() {
  const out = {};
  speakersFromCues().forEach(s => {
    const v = (S.speakerVoices || {})[s.id];
    if (v) out[s.id] = v;
  });
  return out;
}

async function previewSpeaker(id, btn) {
  const voice = (S.speakerVoices || {})[id];
  const cloneId = S.sys.tts?.clone_id || '__clone__';
  if (!voice) return toast('Chưa chọn giọng cho nhân vật này.', 'warn');
  if (voice === cloneId) {
    return toast('Giọng nhân bản chỉ tạo được lúc xuất video — nó cần cắt mẫu từ chính video.', 'warn', 7000);
  }
  const line = S.cues.find(c => (c.speaker || '') === id && (c.text2 || c.text || '').trim());
  const text = line ? (line.text2 || line.text) : 'Xin chào, đây là giọng đọc thử.';

  btn.disabled = true;
  try {
    const res = await fetch('/api/tts/preview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: text.slice(0, 300), voice, style: $('#dubStyle').value }),
    });
    if (!res.ok) throw new Error((await res.json()).error || 'lỗi');
    const a = $('#dubAudio');
    a.src = URL.createObjectURL(await res.blob());
    a.classList.remove('hide'); a.controls = true;
    $('#player').pause();
    await a.play();
  } catch (e) {
    toast(`Nghe thử ${spkName(id)} lỗi: ${e.message}`, 'err', 8000);
  } finally {
    btn.disabled = false;
  }
}

/* ------------------------------ xuất file ------------------------------- */
$('#renderBtn').addEventListener('click', async () => {
  const outputs = {
    srt: $('#outSrt').checked,
    vtt: $('#outVtt').checked,
    srt_both: $('#outSrtBoth').checked,
    txt: $('#outTxt').checked,
    burn: $('#outBurn').checked,
    soft: $('#outSoft').checked,
    dub: $('#dubOn').checked && $('#outDub').checked,
  };
  if (!Object.values(outputs).some(Boolean)) return toast('Chọn ít nhất một định dạng.', 'warn');
  if (outputs.dub && !$('#dubVoice').value)
    return toast('Chưa chọn giọng đọc cho phần lồng tiếng.', 'warn');

  const payload = {
    cues: S.cues,
    display: S.display,
    outputs,
    // Dữ liệu để máy chủ dựng lại phiên nếu thư mục job đã bị dọn / server khởi động lại
    media_id: S.mediaId,
    source_lang: S.analyzed?.source_lang || null,
    target_lang: S.analyzed?.target_lang || '',
    offset: +$('#stOffset').value || 0,
    line_chars: +$('#stLineChars').value,
    max_lines: 2,
    crf: +$('#crf').value,
    preset: $('#preset').value,
    style: {
      font: $('#stFont').value,
      size: +$('#stSize').value,
      primary: $('#stColor').value,
      outline_color: $('#stOutlineColor').value,
      outline: +$('#stOutline').value,
      position: $('#stPos').value,
      margin_v: +$('#stMargin').value,
      bold: $('#stBold').checked,
      box: $('#stBox').checked,
      play_res_y: 1080,
    },
    dub: {
      voice: $('#dubVoice').value,
      style: $('#dubStyle').value,
      keep_original: $('#dubKeepOrig').checked,
      original_volume: +$('#dubOrigVol').value / 100,
      dub_volume: +$('#dubVol').value / 100,
      auto_level: $('#dubAutoLevel').checked,
      duck: $('#dubDuck').checked,
      max_speed: +$('#dubSpeed').value / 100,
      keep_wav: $('#outDubWav').checked,
      voices: collectSpeakerVoices(),
    },
  };

  $('#renderBtn').disabled = true;
  $('#resultBox').classList.add('hide');
  $('#renderProgress').classList.remove('hide');
  try {
    const r = await api(`/api/jobs/${S.jobId}/render`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    S.renderJob = r.job_id;
    pollRender();
  } catch (e) {
    $('#renderBtn').disabled = false;
    $('#renderProgress').classList.add('hide');
    if (/hết hạn|không còn|không tìm thấy file video/i.test(e.message)) {
      // Phụ đề vẫn nằm trong S.cues nên chỉ cần chọn lại video là xuất được tiếp
      S.needReupload = true;
      toast(e.message, 'err', 14000);
      showReupload();
    } else {
      toast(e.message, 'err', 9000);
    }
  }
});

function showReupload() {
  const box = $('#covWarn');
  box.className = 'notice';
  box.innerHTML =
    `<b>⚠ Máy chủ không còn file video gốc.</b><br>
     ${S.cues.length} dòng phụ đề bạn đã sửa <b>vẫn được giữ nguyên</b> trong trang này.
     Chỉ cần chọn lại đúng file video đó ở bước 1 rồi bấm Xuất file lại — không phải nhận dạng lại từ đầu.
     <br><br><button class="btn sm" id="reupBtn">↺ Chọn lại video</button>`;
  goStep(3);
  $('#reupBtn').addEventListener('click', () => {
    goStep(1);
    $('#fileInput').click();
  });
}

function pollRender() {
  clearInterval(S.renderPoll);
  S.renderPoll = setInterval(async () => {
    let j;
    try { j = await api(`/api/jobs/${S.renderJob}`); }
    catch (e) { clearInterval(S.renderPoll); toast('Mất kết nối: ' + e.message, 'err'); return; }

    paintProgress(j, '#renderSteps', null);

    if (j.status === 'done') {
      clearInterval(S.renderPoll);
      $('#renderBtn').disabled = false;
      showFiles(j.result.files || []);
      loadProjects();  // file vừa xuất -> hiện trong danh sách dự án
      toast('Xuất file xong!', 'ok', 4000);
    } else if (j.status === 'error' || j.status === 'cancelled') {
      clearInterval(S.renderPoll);
      $('#renderBtn').disabled = false;
      toast(j.error || 'Xuất file thất bại.', 'err', 12000);
    }
  }, 700);
}

const FILE_ICON = { srt: '📄', vtt: '📄', txt: '📃', ass: '🎨', mp4: '🎬', mkv: '🎬', wav: '🔊' };

function showFiles(files) {
  $('#resultBox').classList.remove('hide');
  $('#fileList').innerHTML = files.map((f, i) => `
    <div class="fileitem" style="animation-delay:${i * 60}ms">
      <span class="ic">${FILE_ICON[f.kind] || '📁'}</span>
      <div class="meta"><b>${f.name}</b><small>${fmtBytes(f.size)}</small></div>
      <a class="btn sm" href="/api/jobs/${S.renderJob}/files/${encodeURIComponent(f.name)}" download>⬇ Tải</a>
    </div>`).join('');
  $('#resultBox').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

/* ---------------------------- lưu tuỳ chọn ------------------------------ */
const PREF_KEY = 'vsub.prefs.v1';
function savePrefs() {
  try {
    localStorage.setItem(PREF_KEY, JSON.stringify({
      engine: S.engine,
      tgt: $('#tgtLang').value,
      src: $('#srcLang').value,
      asr: $('#asrModel').value,
      device: $('#device').value,
      aiModel: $('#aiModel').value,
      aiBaseUrl: $('#aiBaseUrl').value,
      contextNote: $('#contextNote').value,
      translationMode: $('#translationMode').value,
      glossary: $('#glossary').value,
    }));
  } catch { }
}
function restorePrefs() {
  let p;
  try { p = JSON.parse(localStorage.getItem(PREF_KEY) || '{}'); } catch { return; }
  if (p.tgt) $('#tgtLang').value = p.tgt;
  if (p.src) $('#srcLang').value = p.src;
  if (p.asr) $('#asrModel').value = p.asr;
  if (p.device) $('#device').value = p.device;
  if (p.contextNote) $('#contextNote').value = p.contextNote;
  if (p.translationMode) $('#translationMode').value = p.translationMode;
  if (p.glossary) $('#glossary').value = p.glossary;
  if (p.aiBaseUrl) $('#aiBaseUrl').value = p.aiBaseUrl;
  if (p.engine && S.sys.engines.some(e => e.id === p.engine && e.available)) {
    S.engine = p.engine;
    $$('.choice[data-engine]').forEach(x => x.classList.toggle('on', x.dataset.engine === p.engine));
    syncAiBox();
    if (p.aiModel) $('#aiModel').value = p.aiModel;
  }
}
['#tgtLang', '#srcLang', '#asrModel', '#device', '#translationMode']
  .forEach(id => $(id).addEventListener('change', savePrefs));
['#contextNote', '#glossary'].forEach(id => $(id).addEventListener('input', savePrefs));

/* ------------------------------ phím tắt -------------------------------- */
document.addEventListener('keydown', e => {
  if (e.target.matches('input, textarea, select')) return;
  const p = $('#player');
  if (!p || !$('#panel4').classList.contains('active')) return;
  if (e.code === 'Space') { e.preventDefault(); p.paused ? p.play() : p.pause(); }
  if (e.code === 'ArrowLeft') { e.preventDefault(); jumpCue(-1); }
  if (e.code === 'ArrowRight') { e.preventDefault(); jumpCue(1); }
});

window.addEventListener('resize', () => { if (S.cues.length) updateOverlay(); });

boot();

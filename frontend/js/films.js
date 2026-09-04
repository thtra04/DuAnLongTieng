/* frontend/js/films.js — dashboard bộ phim & tập, tạo bộ, thêm tập, đưa video vào tập.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
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
        `<a href="${API_BASE}/api/projects/${p.id}/files/${encodeURIComponent(x.name)}" download
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
  S.videoSrc = p.video_ok ? `${API_BASE}/api/projects/${id}/video` : '';
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


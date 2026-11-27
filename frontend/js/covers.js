/* Private library covers: an uploaded photo takes precedence over an automatic frame. */
const libraryCovers = (() => {
  const slots = new Map(), versions = new Map();
  const panel = $('#coverDialog'), fileInput = $('#coverFile'), notice = $('#coverNotice');
  const upload = $('#coverUpload'), auto = $('#coverAuto');
  let active = null, activeSlot = null, saving = false;
  const filmPath = (f, e) => `films/${encodeURIComponent(f.id)}/cover${e ? '?episode=' + e.no : ''}`;
  const jobPath = p => `projects/${encodeURIComponent(p.id)}`;
  const frame = p => p?.has_thumbnail ? [jobPath(p) + '/thumbnail'] : [];
  const fromJob = p => p?.has_cover ? [jobPath(p) + '/cover', ...frame(p)] : frame(p);
  const editable = role => role === 'owner' || role === 'editor';

  function tile(path, item, title, role, automatic, no) {
    slots.set(path, {path, item, title, automatic});
    const edit = editable(role), tag = edit ? 'button' : 'span';
    return `<${tag} class="library-still" data-cover="${esc(path)}"
      ${edit ? `type="button" aria-label="Chọn ảnh bìa: ${esc(title)}" aria-haspopup="dialog" aria-controls="coverDialog"` : ''}>
      <span class="still-empty"><span>${edit ? 'Thêm ảnh' : 'Chưa có ảnh'}</span></span>
      ${no == null ? '' : `<span class="still-number">Tập ${esc(String(no).padStart(2, '0'))}</span>`}
      ${edit ? `<span class="still-edit" aria-hidden="true">${icon('pencil')}</span>` : ''}
    </${tag}>`;
  }

  function paint(el) {
    const s = slots.get(el.dataset.cover);
    const paths = [...new Set([...(s.item?.has_cover ? [s.path] : []), ...s.automatic()])];
    const empty = $('.still-empty span', el);
    empty.parentElement.hidden = false;
    el.querySelector('img')?.remove();
    delete el.dataset.source;
    delete el.dataset.sourcePath;
    const clear = () => {
      empty.textContent = el.matches('button') ? 'Thêm ảnh' : 'Chưa có ảnh';
      el.title = el.matches('button') ? 'Chọn ảnh bìa' : 'Chưa có ảnh bìa';
    };
    clear();
    if (!paths.length) return;
    empty.textContent = 'Đang lấy ảnh…';
    const img = new Image();
    img.alt = ''; img.loading = 'lazy'; img.decoding = 'async'; img.fetchPriority = 'low';
    let index = 0;
    function next() {
      const path = paths[index];
      const version = versions.get(path);
      img.src = apiUrl('/api/' + path) + (version ? (path.includes('?') ? '&' : '?') + 'v=' + version : '');
    }
    img.onload = () => {
      if (!el.isConnected || !el.contains(img)) return;
      const path = el.dataset.sourcePath = paths[index];
      el.dataset.source = path.endsWith('/thumbnail') ? 'Khung hình từ video'
        : path.startsWith('films/') && !path.includes('?') && el.closest('.ep') ? 'Ảnh bìa của bộ phim' : 'Ảnh tải lên';
      el.title = el.dataset.source + (el.matches('button') ? ' · Đổi ảnh bìa' : '');
      empty.parentElement.hidden = true;
      img.classList.add('ready');
      if (panel.open && active === el) preview();
    };
    img.onerror = () => {
      if (!el.isConnected || !el.contains(img)) return;
      if (++index < paths.length) next();
      else { img.remove(); clear(); if (panel.open && active === el) preview(); }
    };
    el.append(img);
    next();
  }

  function preview() {
    const sample = $('#coverSample'), current = $('img.ready', active);
    sample.hidden = !current;
    if (current) sample.src = current.currentSrc || current.src;
    else sample.removeAttribute('src');
    $('#coverOrigin').textContent = active.dataset.source ? 'Đang dùng: ' + active.dataset.source.toLowerCase() + '.'
      : $('img', active) ? 'Đang đọc ảnh bìa…' : 'Chưa có bìa. Bạn có thể tải ảnh lên ngay cả khi chưa có video.';
  }

  $('#projList').addEventListener('click', e => {
    const el = e.target.closest('button.library-still');
    if (!el) return;
    active = el;
    const s = activeSlot = slots.get(el.dataset.cover);
    $('#coverTitle').textContent = s.title;
    auto.disabled = !s.item.has_cover;
    notice.textContent = ''; fileInput.value = '';
    preview(); panel.showModal();
  });
  $('#coverClose').onclick = () => panel.close();
  panel.addEventListener('cancel', e => { if (saving) e.preventDefault(); });
  panel.addEventListener('close', () => { active = activeSlot = null; $('#coverSample').removeAttribute('src'); });
  upload.onclick = () => fileInput.click();
  fileInput.onchange = () => { if (fileInput.files.length) save(fileInput.files[0]); };
  auto.onclick = () => save(null);

  async function save(file) {
    if (!active || saving) return;
    const el = active, s = activeSlot;
    notice.classList.add('is-error');
    if (file && file.size > 5 * 1024 * 1024) {
      notice.textContent = 'Ảnh bìa tối đa 5 MB. Hãy chọn ảnh nhỏ hơn.'; fileInput.value = ''; return;
    }
    saving = upload.disabled = auto.disabled = $('#coverClose').disabled = true;
    notice.classList.remove('is-error'); notice.textContent = 'Đang lưu bìa…';
    try {
      const query = file ? '' : (s.path.includes('?') ? '&' : '?') + 'mode=auto';
      const result = await api('/api/' + s.path + query, {method: 'POST', body: file});
      s.item.has_cover = result.has_cover;
      versions.set(s.path, Date.now());
      if (el.isConnected) {
        paint(el);
        const card = el.closest('.sr'), header = $('.sr-top > .library-still', card);
        if (header !== el) paint(header);
        else $$('.ep .library-still', card).filter(child =>
          !child.dataset.sourcePath || child.dataset.sourcePath === s.path).forEach(paint);
      } else await loadProjects();
      panel.close();
      toast(file ? 'Đã lưu ảnh bìa.' : 'Đã trở về bìa tự động.', 'ok');
    } catch (err) {
      notice.classList.add('is-error'); notice.textContent = err.message;
    } finally {
      saving = upload.disabled = $('#coverClose').disabled = false;
      auto.disabled = !s.item.has_cover; fileInput.value = '';
    }
  }

  return {
    clear: () => slots.clear(),
    paintAll: box => $$('.library-still', box).forEach(paint),
    film: f => tile(filmPath(f), f, f.name, f.role, () => f.episodes.flatMap(e =>
      [...(e.has_cover ? [filmPath(f, e)] : []), ...fromJob(e.project)])),
    episode: (f, e) => tile(filmPath(f, e), e, `${f.name} · Tập ${e.no}`, f.role,
      () => [...fromJob(e.project), ...(f.has_cover ? [filmPath(f)] : [])], e.no),
    loose: p => tile(jobPath(p) + '/cover', p, p.video_name, p.role, () => frame(p)),
    shelf: list => tile('loose-shelf', null, '', null, () => list.flatMap(fromJob)),
  };
})();

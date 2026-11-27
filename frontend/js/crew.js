/* Team membership is not a project grant. Both screens use the API's effective role. */
const crewRoles = {owner: 'Chủ dự án', editor: 'Biên tập', viewer: 'Chỉ xem', member: 'Thành viên', admin: 'Quản trị viên'};
const crewJson = (method, data) => ({method, headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)});
const crewDialog = $('#crewDialog');
let crewSeq = 0, rosterSeq = 0, crewMembers = [];

function teamChoices(teams) {
  const field = $('#filmTeam'), last = field.value;
  field.replaceChildren(new Option('Cá nhân', ''), ...teams.filter(t => t.joined).map(t => new Option(t.name, t.id)));
  if ([...field.options].some(o => o.value === last)) field.value = last;
}
async function refreshTeamChoices() {
  teamChoices((await api('/api/teams')).teams);
}
function crewRow(name, detail, ops) {
  return `<div class="crew-row"><div><b>${esc(name)}</b><small>${esc(detail)}</small></div><div class="crew-ops">${ops}</div></div>`;
}
function roleOptions(selected, roles) {
  return roles.map(r => `<option value="${r}"${selected === r ? ' selected' : ''}>${crewRoles[r]}</option>`).join('');
}
function paintDirectory() {
  const term = $('#crewSearch').value.trim().toLocaleLowerCase('vi');
  const state = $('#adminMemberState').value;
  $('#memberDirectory').innerHTML = crewMembers.filter(u => (!state || u.active === (state === 'active')) &&
    [u.username, u.display_name, ...u.teams].join(' ').toLocaleLowerCase('vi').includes(term)).map(u =>
    crewRow(u.display_name || u.username, `@${u.username} · ${crewRoles[u.role]} · ${u.teams.join(', ') || 'Chưa vào nhóm'} · ${u.active ? 'Đang hoạt động' : 'Đã khóa'}`,
      u.self ? 'Tài khoản của bạn' : `<select aria-label="Quyền của ${esc(u.username)}">${roleOptions(u.role, ['member','admin'])}</select>
      <button class="btn sm" data-role-user="${u.id}">Lưu quyền</button>
      <button class="btn sm ghost" data-toggle-user="${u.id}">${u.active ? 'Khóa' : 'Mở khóa'}</button>`)).join('') || 'Không có tài khoản phù hợp.';
}
function selectAdminSection(name) {
  $$('[data-admin-tab]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.adminTab === name)));
  $$('[data-admin-section]').forEach(s => s.classList.toggle('hide', s.dataset.adminSection !== name));
}
function clearAdminDirectory() {
  ++crewSeq;
  crewMembers = [];
  for (const id of ['#memberDirectory', '#adminTeams', '#adminFilms']) $(id).replaceChildren();
  for (const id of ['#adminMembersCount', '#adminTeamsCount', '#adminFilmsCount']) $(id).textContent = '—';
  $('#crewSearch').value = $('#adminMemberState').value = '';
  selectAdminSection('members');
  if (crewDialog.open) crewDialog.close();
}
async function loadCrew(adminView, message = '') {
  const page = $(adminView ? '#adminPage' : '#crewPage');
  if (page.classList.contains('hide') || (adminView && S.member?.role !== 'admin')) return;
  const note = adminView ? '#adminNotice' : '#crewNotice';
  const teamList = $(adminView ? '#adminTeams' : '#crewTeams'), filmList = $(adminView ? '#adminFilms' : '#crewFilms');
  const seq = ++crewSeq;
  const title = adminView ? 'Quản trị studio' : 'Nhóm & cộng tác';
  document.title = `${title} · VSub Studio`;
  profileFeedback(note, 'Đang tải…');
  teamList.replaceChildren();
  filmList.replaceChildren();
  if (adminView) {
    crewMembers = [];
    $('#memberDirectory').replaceChildren();
  }
  try {
    const [teams, dash, members] = await Promise.all([api('/api/teams'), api('/api/films'),
      adminView ? api('/api/admin/members') : Promise.resolve(null)]);
    if (seq !== crewSeq || page.classList.contains('hide')) return;
    S.dash = dash;
    teamChoices(teams.teams);
    if (adminView) {
      crewMembers = members.members;
      $('#adminMembersCount').textContent = crewMembers.length;
      $('#adminTeamsCount').textContent = teams.teams.length;
      $('#adminFilmsCount').textContent = dash.films.length;
      paintDirectory();
    }
    teamList.innerHTML = teams.teams.filter(t => adminView || t.joined).map(t => crewRow(t.name, t.manage ? 'Quản lý nhóm' : 'Thành viên',
      `<button class="btn sm" data-team="${esc(t.id)}">${t.manage ? 'Quản lý nhóm' : 'Xem thành viên'}</button>` +
      (t.manage ? ` <button class="btn sm ghost" data-rename="${esc(t.id)}">Đổi tên</button>
        <button class="btn sm ghost" data-dissolve="${esc(t.id)}">Giải tán</button>` : ''))).join('') ||
      (adminView ? 'Studio chưa có nhóm sản xuất.' : 'Chưa có nhóm. Tạo nhóm mới hoặc nhập mã TM của trưởng nhóm.');
    const options = teams.teams.map(t => `<option value="${esc(t.id)}">${esc(t.name)}</option>`).join('');
    filmList.innerHTML = dash.films.map(f => crewRow(f.name,
      `${teams.teams.find(t => t.id === f.team_id)?.name || (f.legacy ? 'Kho cũ chưa phân công' : 'Cá nhân')} · ${crewRoles[f.role]}`,
      `<button class="btn sm" data-film-roster="${esc(f.id)}">Cộng tác</button>` +
      (adminView && f.legacy && options ? `<select aria-label="Nhóm nhận dự án">${options}</select>
        <button class="btn sm ghost" data-assign="${esc(f.id)}">Giao cho trưởng nhóm</button>` : ''))).join('') ||
      (adminView ? 'Studio chưa có dự án phim.' : 'Chưa có dự án. Tạo bộ phim ở thư viện hoặc dùng mã PJ do chủ dự án gửi.');
    profileFeedback(note, message);
  } catch (e) {
    if (seq === crewSeq && !page.classList.contains('hide')) {
      profileFeedback(note, e.message, true);
      if (adminView && e.status === 403) refreshStudioMember();
    }
  }
}
$$('[data-admin-tab]').forEach(b => b.onclick = () => selectAdminSection(b.dataset.adminTab));
$('#adminReload').onclick = () => loadCrew(true);
$('#adminMemberState').addEventListener('change', paintDirectory);
$('#crewSearch').addEventListener('input', paintDirectory);
for (const list of $$('#crewTeams, #adminTeams')) list.addEventListener('click', async e => {
  const adminView = list.id === 'adminTeams';
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.team) return openRoster('teams', b.dataset.team);
  const name = $('b', b.closest('.crew-row')).textContent;
  try {
    if (b.dataset.rename) {
      const value = await askInput('Tên mới của nhóm:', name);
      if (!value || value === name) return;
      await api(`/api/teams/${b.dataset.rename}`, crewJson('PATCH', {name:value}));
    } else if (b.dataset.dissolve) {
      if (!(await askConfirm(`Giải tán nhóm "${name}"? Mọi mã nhóm sẽ mất hiệu lực. Nhóm còn phim sẽ không bị xóa.`, {ok:'Giải tán'}))) return;
      await api(`/api/teams/${b.dataset.dissolve}`, {method:'DELETE'});
    }
    await loadCrew(adminView, 'Đã cập nhật nhóm.');
  } catch (err) { profileFeedback(adminView ? '#adminNotice' : '#crewNotice', err.message, true); }
});
for (const list of $$('#crewFilms, #adminFilms')) list.addEventListener('click', async e => {
  const b = e.target.closest('button');
  if (!b) return;
  if (b.dataset.filmRoster) return openRoster('films', b.dataset.filmRoster);
  if (!b.dataset.assign) return;
  const field = $('select', b.parentElement);
  if (!(await askConfirm(`Giao dự án này cho trưởng nhóm ${field.selectedOptions[0].text}?`, {ok: 'Giao dự án', danger: false}))) return;
  try {
    await api(`/api/admin/legacy/${b.dataset.assign}`, crewJson('POST', {team_id: field.value}));
    await loadCrew(true, 'Đã giao dự án. Thành viên khác vẫn cần mã dự án.');
    loadProjects();
  } catch (err) { profileFeedback('#adminNotice', err.message, true); }
});
$('#memberDirectory').addEventListener('click', async e => {
  const b = e.target.closest('button');
  if (!b) return;
  const u = crewMembers.find(m => m.id === Number(b.dataset.roleUser || b.dataset.toggleUser));
  if (!u) return;
  const role = b.dataset.roleUser ? $('select', b.parentElement).value : null;
  if (role === u.role) return;
  const action = role ? `Đổi quyền của ${u.username} thành ${crewRoles[role]}` : `${u.active ? 'Khóa' : 'Mở khóa'} tài khoản ${u.username}`;
  if (!(await askConfirm(action + '?', {ok: 'Xác nhận', danger: !!u.active && !role}))) return;
  try {
    await api(`/api/admin/members/${u.id}`, crewJson('PATCH', role ? {role} : {active: !u.active}));
    await loadCrew(true, 'Đã cập nhật tài khoản.');
  } catch (err) { profileFeedback('#adminNotice', err.message, true); }
});
for (const id of ['crewJoin', 'crewCreate']) {
  $('#' + id).addEventListener('submit', async e => {
    e.preventDefault();
    const form = e.currentTarget, btn = $('button', form);
    btn.disabled = true;
    try {
      const data = Object.fromEntries(new FormData(form));
      const result = id === 'crewJoin' ? await api('/api/collab/join', crewJson('POST', data)) : await api('/api/teams', crewJson('POST', data));
      form.reset();
      await loadCrew(false, `${id === 'crewJoin' ? 'Đã tham gia' : 'Đã tạo nhóm'}: ${result.name}.`);
      loadProjects();
    } catch (err) { profileFeedback('#crewNotice', err.message, true); }
    finally { btn.disabled = false; }
  });
}

function dialogStart(label, name) {
  const seq = ++rosterSeq;
  $('#crewDialogLabel').textContent = label;
  $('#crewDialogTitle').textContent = name;
  $('#crewDialogBody').replaceChildren();
  profileFeedback('#crewDialogNotice', '');
  if (!crewDialog.open) crewDialog.showModal();
  return seq;
}
$('#crewClose').onclick = () => crewDialog.close();
crewDialog.addEventListener('close', () => {
  rosterSeq++;
  $('#crewDialogBody').replaceChildren();
  profileFeedback('#crewDialogNotice', '');
});
function drawCode(code) {
  const box = document.createElement('div');
  box.innerHTML = '<p>Chỉ hiện mã một lần. Gửi riêng cho một người; mã hết hạn sau 24 giờ.</p>'+
    '<label class="field"><span>Mã mời</span><input class="crew-code" type="text" readonly autocomplete="off"></label>'+
    '<button type="button" class="btn sm">Sao chép mã</button>';
  const field = $('input', box);
  field.value = code;
  $('button', box).onclick = async () => {
    try { await navigator.clipboard.writeText(field.value); profileFeedback('#crewDialogNotice', 'Đã sao chép mã.'); }
    catch { field.focus(); field.select(); profileFeedback('#crewDialogNotice', 'Đã chọn mã. Dùng lệnh Sao chép của thiết bị.'); }
  };
  $('#crewDialogBody').append(box);
}
$('#registrationCode').onclick = async () => {
  const seq = dialogStart('Đăng ký tài khoản', 'Mã vào studio');
  try {
    const r = await api('/api/admin/invites', {method:'POST'});
    if (seq === rosterSeq) drawCode(r.code);
  } catch (e) { if (seq === rosterSeq) profileFeedback('#crewDialogNotice', e.message, true); }
};
async function openRoster(kind, id) {
  const team = kind === 'teams';
  const seq = dialogStart(team ? 'Ê-kíp / Thành viên' : 'Dự án / Cộng tác', 'Đang tải…'), body = $('#crewDialogBody');
  try {
    const r = await api(`/api/collab/${kind}/${id}`);
    if (seq !== rosterSeq) return;
    $('#crewDialogTitle').textContent = r.name;
    body.innerHTML = `<p>${team ? 'Vào nhóm không tự mở quyền xem phim.' : 'Quyền áp dụng cho mọi tập, kịch bản và bản xuất của bộ phim này.'}</p>` +
      r.members.map(u => crewRow(u.name, `@${u.username} · ${team && u.role === 'owner' ? 'Trưởng nhóm' : crewRoles[u.role]}`,
        !r.manage || u.role === 'owner' ? '' :
        (!team ? `<select aria-label="Vai trò của ${esc(u.username)}">${roleOptions(u.role, ['viewer','editor'])}</select>
        <button class="btn sm" data-change="${u.id}">Lưu quyền</button>` : '') + ` <button class="btn sm ghost" data-remove="${u.id}">Gỡ</button>`)).join('') +
      (r.manage ? `<div class="crew-row"><div><b>Mời cộng tác</b><small>Mỗi mã chỉ dùng một lần.</small></div><div class="crew-ops">
        ${team ? '' : `<select aria-label="Quyền khi dùng mã" id="inviteRole">${roleOptions('viewer', ['viewer','editor'])}</select>`}
        <button class="btn primary sm" data-issue>Tạo mã ${team ? 'nhóm' : 'dự án'}</button></div></div>` +
        r.invites.map(i => crewRow(`Mã đang chờ · ${crewRoles[i.role]}`, `Hết hạn: ${new Date(i.expires * 1000).toLocaleString('vi-VN')}`,
          `<button class="btn sm ghost" data-revoke="${esc(i.id)}">Thu hồi mã</button>`)).join('') : '');
    body.onclick = async e => {
      const b = e.target.closest('button');
      if (!b || !Object.keys(b.dataset).length || seq !== rosterSeq) return;
      const {change, remove, revoke} = b.dataset;
      if ((remove || revoke) && !b.dataset.armed) { b.dataset.armed = '1'; b.textContent = remove ? 'Xác nhận gỡ' : 'Xác nhận thu hồi'; return; }
      b.disabled = true;
      try {
        if (b.hasAttribute('data-issue')) {
          const role = $('#inviteRole')?.value;
          const issued = await api(`/api/collab/${kind}/${id}/invites`, crewJson('POST', {role}));
          if (seq !== rosterSeq) return;
          body.replaceChildren();
          drawCode(issued.code);
          return;
        }
        if (change) await api(`/api/collab/films/${id}/members/${change}`, crewJson('PATCH', {role: $('select', b.parentElement).value}));
        if (remove) await api(`/api/collab/${kind}/${id}/members/${remove}`, {method:'DELETE'});
        if (revoke) await api(`/api/collab/${kind}/${id}/invites/${revoke}`, {method:'DELETE'});
        if (seq === rosterSeq) await openRoster(kind, id);
      } catch (err) { if (seq === rosterSeq) profileFeedback('#crewDialogNotice', err.message, true); }
      finally { b.disabled = false; }
    };
  } catch (e) { if (seq === rosterSeq) profileFeedback('#crewDialogNotice', e.message, true); }
}
function showScriptProof(p) {
  dialogStart('Phòng duyệt / Chỉ xem', p.video_name);
  $('#crewDialogBody').innerHTML = (p.video_ok ? `<video controls preload="metadata" src="${esc(apiUrl(`/api/projects/${encodeURIComponent(p.id)}/video`))}"></video>` : '') +
    '<ol class="crew-proof">' + p.cues.map(c => `<li><small>${fmtTime(c.start)} – ${fmtTime(c.end)} · ${esc(c.speaker || '')}</small>
      <b>${esc(c.text2 || c.text)}</b>${c.text2 ? esc(c.text) : ''}</li>`).join('') + '</ol>';
}

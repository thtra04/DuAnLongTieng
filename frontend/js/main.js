/* frontend/js/main.js — điểm khởi động, phải nạp SAU mọi file js khác. */
let registering = false;
let accessReady = false;
const missingStudioApi = 'Địa chỉ này không có API tài khoản của bản VSub hiện tại. Hãy mở địa chỉ do máy chủ VSub mới hiển thị, rồi tải lại trang.';
$('#studioToggle').onclick = e => {
  const open = $('#studioTools').classList.toggle('expanded');
  e.currentTarget.setAttribute('aria-expanded', String(open));
};
const accessForm = $('#accessForm'), accessMsg = $('#accessMessage');
function accessMode(on) {
  registering = on;
  $('#accessTitle').textContent = on ? 'Đăng ký thành viên' : 'Đăng nhập';
  $('#accessSubmit').textContent = on ? 'Tạo tài khoản' : 'Vào studio';
  $('#accessMode').textContent = on ? 'Đã có tài khoản? Đăng nhập' : 'Có mã mời? Đăng ký';
  $('#inviteField').classList.toggle('hide', !on);
  $('#inviteCode').required = on;
  $('#accountPass').autocomplete = on ? 'new-password' : 'current-password';
  accessMsg.textContent = '';
}
function setStudioMember(user) {
  S.member = user;
  $('#adminOperator').textContent = `@${user.username} · Hồ sơ`;
  $('#signOut').title = `${user.username} · Đăng xuất khỏi thiết bị này`;
  $$('[data-admin-link]').forEach(el => el.classList.toggle('hide', user.role !== 'admin'));
}
async function refreshStudioMember() {
  const previous = S.member;
  if (!previous) return;
  try {
    const user = await api('/api/auth/me');
    if (S.member !== previous) return;
    if (user?.username !== previous.username || (previous.role === 'admin' && user.role !== 'admin')) {
      location.reload();
      return;
    }
    setStudioMember(user);
    if (location.hash === '#profile') paintProfile(user);
  } catch (err) {
    if (location.hash === '#profile') profileFeedback('#profileMessage', err.message, true);
  }
}
document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshStudioMember(); });
async function enterStudio(user) {
  if (!user?.username || !['member', 'admin'].includes(user.role)) {
    throw Object.assign(new Error(missingStudioApi), {status: 404});
  }
  await refreshTeamChoices();
  setStudioMember(user);
  accessForm.reset();
  $('#accessGate').classList.add('hide');
  if (user.role === 'admin' && !location.hash) history.replaceState(null, '', '#admin');
  if (user.role !== 'admin' && location.hash === '#admin') history.replaceState(null, '', '#studio');
  syncProfileView();
  await boot();
  refreshMemoryInfo();
}
$('#accessMode').addEventListener('click', () => accessMode(!registering));
accessForm.addEventListener('submit', async e => {
  e.preventDefault();
  const b = $('#accessSubmit');
  if (!accessReady || b.disabled) return;
  b.disabled = true;
  try {
    await api(`/api/auth/${registering ? 'register' : 'login'}`, {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({username: $('#accountName').value, password: $('#accountPass').value,
        ...(registering ? {invite: $('#inviteCode').value.trim()} : {})})
    });
    await enterStudio(await api('/api/auth/me'));
  } catch (err) {
    if ([404, 405].includes(err.status)) {
      accessReady = false;
      $('#accessMode').disabled = true;
    }
    accessMsg.textContent = accessReady ? err.message : missingStudioApi;
  } finally { b.disabled = !accessReady; }
});
$$('[data-sign-out]').forEach(b => b.addEventListener('click', async () => {
  try {
    await api('/api/auth/logout', {method:'POST'});
    clearJobRecovery(); localStorage.removeItem(accountKey(PREF_KEY));
    history.replaceState(null, '', location.pathname + location.search);
    location.reload();
  } catch (err) { toast(err.message, 'err'); }
}));
window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
api('/api/auth/me').then(enterStudio).catch(err => {
  const dest = new URL(apiUrl('/api/auth/me'), location.href);
  const safe = dest.protocol === 'https:' || (dest.protocol === 'http:' && ['localhost','127.0.0.1','[::1]'].includes(dest.hostname));
  accessReady = safe && err.status === 401;
  $('#accessSubmit').disabled = $('#accessMode').disabled = !accessReady;
  if (!accessReady) accessMsg.textContent = [404, 405].includes(err.status) ? missingStudioApi
    : !safe ? 'Hãy kết nối qua HTTPS hoặc localhost.' : `${err.message} Hãy kiểm tra máy chủ rồi tải lại trang.`;
});

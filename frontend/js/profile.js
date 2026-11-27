const studioTitle = document.title;
const profileForm = $('#profileForm');
const passwordForm = $('#passwordForm');
const profileFields = ['display_name', 'contact_email', 'crew_role', 'bio'];

function paintProfile(user) {
  const name = user.display_name || user.username;
  const missing = 'Chưa có dữ liệu';
  const detail = value => typeof value === 'string' ? value || 'Chưa bổ sung' : missing;
  $('#profileName').textContent = name;
  $('#profileInitial').textContent = Array.from(name)[0].toLocaleUpperCase('vi-VN');
  $('#profileUsername').textContent = user.username;
  $('#profileAccountRole').textContent = user.role === 'admin' ? 'Quản trị viên' : user.role === 'member' ? 'Thành viên' : missing;
  $('#profileCrewRole').textContent = detail(user.crew_role);
  $('#profileEmail').textContent = detail(user.contact_email);
  $('#profileBio').textContent = detail(user.bio);
  $('#profileLink').title = `Trang cá nhân của ${name}`;
  const time = $('#profileCreated');
  const joined = typeof user.created === 'number' && user.created > 0 ? new Date(user.created * 1000) : null;
  if (joined && Number.isFinite(joined.getTime())) {
    time.dateTime = joined.toISOString();
    time.textContent = joined.toLocaleDateString('vi-VN', {day: 'numeric', month: 'long', year: 'numeric'});
  } else {
    time.removeAttribute('datetime');
    time.textContent = missing;
  }
  // A running older backend can serve the new static page but cannot save these fields.
  const canEdit = profileFields.every(key => typeof user[key] === 'string');
  $('#profileUpgrade').classList.toggle('hide', canEdit);
  $('#editProfile').disabled = !canEdit;
  $('fieldset', passwordForm).disabled = typeof user.display_name !== 'string';
  $('#displayName').placeholder = user.username;
  passwordForm.elements.username.value = user.username;
}

function setProfileEditing(editing) {
  $('#profileDetails').classList.toggle('hide', editing);
  profileForm.classList.toggle('hide', !editing);
  $('#editProfile').setAttribute('aria-expanded', String(editing));
  if (editing) {
    for (const key of profileFields) profileForm.elements[key].value = S.member[key];
    $('#displayName').focus();
  }
}

$('#editProfile').addEventListener('click', () => {
  $('#profileMessage').textContent = '';
  setProfileEditing(true);
});
$('#cancelProfile').addEventListener('click', () => {
  setProfileEditing(false);
  $('#profileMessage').textContent = '';
  $('#editProfile').focus();
});

function syncProfileView() {
  if (!S.member) return;
  if (location.hash === '#admin' && S.member.role !== 'admin') history.replaceState(null, '', '#studio');
  const page = $('#profilePage'), show = location.hash === '#profile';
  const crew = location.hash === '#teams', admin = location.hash === '#admin';
  if (!admin && !$('#adminPage').classList.contains('hide')) clearAdminDirectory();
  const wasOpen = !page.classList.contains('hide');
  $('#studioShell').classList.toggle('hide', show || crew || admin);
  page.classList.toggle('hide', !show);
  $('#crewPage').classList.toggle('hide', !crew);
  $('#adminPage').classList.toggle('hide', !admin);
  if (crew || admin) {
    $$('#studioShell video, #studioShell audio').forEach(media => media.pause());
    passwordForm.reset();
    $(admin ? '#adminTitle' : '#crewTitle').focus();
    window.scrollTo(0, 0);
    loadCrew(admin);
    return;
  }
  document.title = show ? 'Trang cá nhân · VSub Studio' : studioTitle;
  if (!show && !wasOpen) return;
  setProfileEditing(false);
  passwordForm.reset();
  $('#profileMessage').textContent = '';
  $('#passwordMessage').textContent = '';
  if (show) {
    $$('#studioShell video, #studioShell audio').forEach(media => media.pause());
    paintProfile(S.member);
    $('#profileTitle').focus();
  } else {
    $('#profileLink').focus();
  }
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', () => {
  syncProfileView();
  if (location.hash === '#profile') refreshStudioMember();
});

function profileFeedback(id, message, error = false) {
  const el = $(id);
  el.classList.toggle('is-error', error);
  el.textContent = message;
}

profileForm.addEventListener('submit', async e => {
  e.preventDefault();
  const button = $('button[type=submit]', e.currentTarget);
  button.disabled = true;
  try {
    const user = await api('/api/auth/me', {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(profileForm)))
    });
    setStudioMember(user);
    paintProfile(user);
    setProfileEditing(false);
    profileFeedback('#profileMessage', 'Đã lưu hồ sơ.');
    $('#editProfile').focus();
  } catch (err) {
    profileFeedback('#profileMessage', err.message, true);
  } finally { button.disabled = false; }
});

passwordForm.addEventListener('submit', async e => {
  e.preventDefault();
  const {current_password, new_password, confirmation} = passwordForm.elements;
  if (confirmation.value !== new_password.value) {
    profileFeedback('#passwordMessage', 'Hai lần nhập mật khẩu mới không khớp.', true);
    confirmation.focus();
    return;
  }
  const button = $('button[type=submit]', passwordForm);
  button.disabled = true;
  try {
    await api('/api/auth/password', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({current_password: current_password.value, new_password: new_password.value})
    });
    passwordForm.reset();
    profileFeedback('#passwordMessage', 'Đã đổi mật khẩu. Các phiên đăng nhập cũ đã kết thúc.');
  } catch (err) {
    profileFeedback('#passwordMessage', err.message, true);
  } finally { button.disabled = false; }
});

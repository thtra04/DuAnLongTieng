/* The source video is the clock; only the selected utterance is synthesized. */
let audition = null, auditionCache = null, auditionContext = null, auditionAnchor = null;

function stopDraftSound(d) {
  if (!d.sound) return;
  d.sound.onended = null;
  d.sound.stop();
  d.sound.disconnect();
  d.sound = null;
}

function stopAudition(done = false) {
  const d = audition;
  if (d) {
    audition = null;
    d.controller.abort();
    stopDraftSound(d);
    if (d.ownsPlayer) {
      d.player.pause();
      d.player.muted = d.muted;
    }
  }
  $('#draftMonitor').classList.toggle('hide', !done);
  $('#draftStop').classList.toggle('hide', done);
  if (done) $('#draftStatus').textContent = d?.warning || 'Đã nghe hết câu nháp.';
}

function waitForMedia(player, event, signal) {
  return new Promise((resolve, reject) => {
    const clean = () => {
      clearTimeout(timer);
      player.removeEventListener(event, ok);
      player.removeEventListener('error', fail);
      signal.removeEventListener('abort', fail);
    };
    const ok = () => { clean(); resolve(); };
    const fail = () => { clean(); reject(new Error('Không tải được đoạn video ở mốc này.')); };
    const timer = setTimeout(fail, 15000);
    player.addEventListener(event, ok);
    player.addEventListener('error', fail);
    signal.addEventListener('abort', fail, { once: true });
    if (signal.aborted || player.error) fail();
  });
}

async function auditionCue(index, fromScript = false, another = false) {
  stopAudition();
  const player = $('#player'), id = S.jobId;
  if (!id || !S.cues[index] || (S.projectId && !S.videoSrc))
    return toast('Cần video gốc để xem và nghe thử ở mốc này.', 'warn');
  if (!S.sys?.tts?.available) return toast('Chưa có bộ đọc VieNeu-TTS trên máy chủ.', 'warn');
  if (fromScript && scriptStale()) return toast('Phụ đề đã đổi. Bấm Dựng lại trước khi thử câu đọc.', 'warn');
  player.pause();
  monitorShow('orig', false);
  const controller = new AbortController(), signal = controller.signal;
  const d = { player, controller, muted: player.muted, ownsPlayer: false };
  audition = d;
  const cancelPending = () => { if (!d.ownsPlayer) stopAudition(); };
  player.addEventListener('play', cancelPending, { signal });
  const atClick = player.currentTime;
  player.addEventListener('seeking', () => {
    if (Math.abs(player.currentTime - atClick) > 0.03) cancelPending();
  }, { signal });
  auditionAnchor = { id, index, fromScript };
  $('#draftMonitor').classList.remove('hide');
  $('#draftStatus').textContent = `Đang tạo lời đọc cho dòng #${index + 1}…`;
  player.scrollIntoView({ block: 'nearest' });
  try {
    // Unlock audio on the click itself, before the asynchronous TTS request (mobile browsers).
    auditionContext ||= new (window.AudioContext || window.webkitAudioContext)();
    await auditionContext.resume();
    const sig = scriptSig();
    if (signal.aborted) return;
    const sc = S.dubScript?.sig === sig ? S.dubScript : await buildScript();
    if (signal.aborted) return;
    if (!sc || sc.sig !== scriptSig()) throw new Error('Kịch bản đã đổi; hãy bấm nghe lại.');
    const issue = sc.issues.find(x => x.cue === index);
    if (issue) throw new Error(`Dòng #${index + 1}: ${issue.reason}.`);
    const u = sc.units.find(u => u.cues.includes(index));
    if (!u?.text.trim()) throw new Error('Câu này chưa có lời đọc.');
    if (!S.voicesLoaded) await loadVoices();
    if (signal.aborted) return;
    if (!S.voicesLoaded) throw new Error('Không nạp được giọng đọc.');
    if (u.speaker && !S.speakerVoices?.[u.speaker]) renderSpeakerVoices();
    const payload = { cues: S.cues, unit: { cues: u.cues, text: u.text, variant: selectedVariant(u) },
      ...auditionSettings(u), duration: knownDuration(), another };
    const key = auditionKey(u);
    const body = JSON.stringify(payload);
    let clip = auditionCache;
    if (another || !clip || clip.id !== id || clip.body !== body) {
      const resp = await fetch(apiUrl(`/api/projects/${encodeURIComponent(id)}/dub-preview`), {
        method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body, signal });
      if (!resp.ok) throw new Error((await resp.json()).error || `Lỗi ${resp.status}`);
      const buffer = await auditionContext.decodeAudioData(await resp.arrayBuffer());
      if (signal.aborted) return;
      clip = { id, body, start: Number(resp.headers.get('X-Preview-Start') ?? (u.start + payload.offset)),
        over: Number(resp.headers.get('X-Preview-Overrun')), variant: resp.headers.get('X-Preview-Variant'), buffer };
      auditionCache = clip;
    }
    if (another) {
      if (!clip.variant) throw new Error('Máy chủ chưa hỗ trợ lưu lượt đọc mới.');
      u.variant = { id: clip.variant, for: takeIdentity(u) };
      sc.approved = false;
    }
    u.monitor = { key, over: clip.over };
    paintTake(u, $(`#scriptList [data-audition="${index}"]`)?.closest('.script-row'));
    syncScriptApproval();
    if (clip.over) { d.warning = takeMessage(u); toast(d.warning, 'warn', 7500); }
    if (!player.readyState) await waitForMedia(player, 'loadedmetadata', signal);
    if (signal.aborted) return;
    if (clip.start >= player.duration) throw new Error('Mốc câu nằm ngoài video gốc.');
    d.ownsPlayer = true;
    player.muted = true;
    player.currentTime = clip.start;
    if (player.seeking) await waitForMedia(player, 'seeked', signal);
    if (signal.aborted) return;

    const sync = () => {
      stopDraftSound(d);
      if (player.paused || player.seeking || player.readyState < 2) return;
      const offset = Math.max(0, player.currentTime - clip.start);
      if (offset >= clip.buffer.duration) return stopAudition(true);
      const sound = auditionContext.createBufferSource();
      sound.buffer = clip.buffer;
      sound.playbackRate.value = player.playbackRate;
      sound.connect(auditionContext.destination);
      d.sound = sound;
      sound.onended = () => { if (audition === d) stopAudition(true); };
      sound.start(0, offset);
    };
    player.addEventListener('playing', sync, { signal });
    player.addEventListener('ratechange', sync, { signal });
    player.addEventListener('waiting', () => stopDraftSound(d), { signal });
    player.addEventListener('seeking', () => stopAudition(), { signal });
    player.addEventListener('pause', () => { if (!player.ended) stopAudition(); }, { signal });
    player.addEventListener('error', () => stopAudition(), { signal });
    $('#draftStatus').textContent = d.warning || `Bản nháp · ${fmtTime(clip.start)} · đang nghe riêng lời đọc`;
    await player.play();
  } catch (e) {
    if (audition === d) {
      stopAudition();
      toast('Chưa xem thử được: ' + e.message, 'warn', 7500);
    }
  }
}

$('#panel4').addEventListener('click', e => {
  const again = e.target.closest('[data-retake]');
  if (again) return auditionCue(Number(again.dataset.retake), true, true);
  const b = e.target.closest('[data-audition]');
  if (b) auditionCue(Number(b.dataset.audition), !!b.closest('#scriptList'));
});
$('#panel4').addEventListener('input', e => {
  if (audition && e.target.closest('#cueList, #cueForm, #scriptList, #draftVoices, #dubOpts, #stOffset')) stopAudition();
});
$('#draftStop').addEventListener('click', () => stopAudition());
$('#draftEdit').addEventListener('click', () => {
  const a = auditionAnchor;
  stopAudition();
  if (!a || a.id !== S.jobId || !S.cues[a.index]) return;
  if (!a.fromScript && !cueVisible(S.cues[a.index])) {
    minutes.selected = Math.floor(S.cues[a.index].start / 60);
    renderCues(false);
  }
  const row = a.fromScript ? $(`#scriptList [data-audition="${a.index}"]`)?.closest('.script-row')
    : $(`#cueList .cue[data-i="${a.index}"]`);
  (row?.querySelector('textarea.tr') || row?.querySelector('textarea'))?.focus();
});
window.addEventListener('pagehide', () => stopAudition());
window.addEventListener('hashchange', () => stopAudition());
document.addEventListener('visibilitychange', () => { if (document.hidden) stopAudition(); });

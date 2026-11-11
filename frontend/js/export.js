/* frontend/js/export.js — xuất file: /api/jobs/{id}/render, tải kết quả.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
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
    mask: maskConfig(),   // che phụ đề nung sẵn của video gốc (hardsub.js)
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
      original_mode: $('#dubOrigMode').value,   // voice_off | keep | mute
      original_volume: +$('#dubOrigVol').value / 100,
      dub_volume: +$('#dubVol').value / 100,
      auto_level: $('#dubAutoLevel').checked,
      duck: $('#dubDuck').checked,
      max_speed: +$('#dubSpeed').value / 100,
      shorten: $('#dubShorten').checked,      // HP-5 lúc xuất: rút gọn bằng luật trước khi đọc
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
    `<b>${icon('alert')} Máy chủ không còn file video gốc.</b><br>
     ${S.cues.length} dòng phụ đề bạn đã sửa <b>vẫn được giữ nguyên</b> trong trang này.
     Chỉ cần chọn lại đúng file video đó ở bước 1 rồi bấm Xuất file lại — không phải nhận dạng lại từ đầu.
     <br><br><button class="btn sm" id="reupBtn">${icon('rotate')} Chọn lại video</button>`;
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

const FILE_ICON = { srt: 'captions', vtt: 'captions', txt: 'file-text', ass: 'palette', mp4: 'film', mkv: 'film', wav: 'volume' };

function showFiles(files) {
  const urlOf = f => `${API_BASE}/api/jobs/${S.renderJob}/files/${encodeURIComponent(f.name)}`;
  const burned = files.some(f => /\.hardsub\.mp4$/i.test(f.name));
  $('#resultBox').classList.remove('hide');
  $('#fileList').innerHTML = files.map((f, i) => `
    <div class="fileitem" style="animation-delay:${i * 60}ms">
      <span class="ic">${icon(FILE_ICON[f.kind] || 'folder')}</span>
      <div class="meta"><b>${f.name}</b><small>${fmtBytes(f.size)}</small></div>
      ${f.kind === 'mp4' ? `<button type="button" class="btn sm ghost play" data-play="${i}">${icon('film')} Xem thử</button>` : ''}
      <a class="btn sm" href="${urlOf(f)}" download>${icon('download')} Tải</a>
    </div>`).join('');
  const labelOf = f => /\.longtieng\./i.test(f.name) ? 'Bản lồng tiếng'
    : /\.hardsub\./i.test(f.name) ? 'Bản nung phụ đề' : 'Bản đã xuất';
  const asOutput = f => ({
    url: `${urlOf(f)}?download=0`, label: labelOf(f),
    burned: /\.hardsub\./i.test(f.name) || (/\.longtieng\./i.test(f.name) && burned),
  });
  $$('#fileList [data-play]').forEach(b => b.addEventListener('click', () => {
    setMonitorOutput(asOutput(files[+b.dataset.play]));
    monitorShow('out');
    $('#player').scrollIntoView({ behavior: 'smooth', block: 'center' });
  }));
  // Vừa xuất bản lồng tiếng -> đưa luôn lên màn hình xem để nghe và sửa tiếp
  const dubbed = files.find(f => /\.longtieng\.mp4$/i.test(f.name));
  if (dubbed) {
    setMonitorOutput(asOutput(dubbed));
    monitorShow('out');
    toast('Bản lồng tiếng đã lên màn hình xem — bấm một dòng để nghe đúng câu đó, sửa rồi xuất lại.', 'ok', 8000);
  } else {
    $('#resultBox').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

/* ---------------- màn hình xem: video gốc ↔ bản đã xuất ----------------
   Nghe bản lồng tiếng ngay trong trình biên tập: cùng một khung xem, cùng danh sách
   thoại và dòng thời gian, chỉ đổi nguồn phát. Đổi nguồn thì giữ nguyên vị trí đang xem. */
function setMonitorOutput(out) {
  S.monOut = out || null;
  $('#monSrc').classList.toggle('hide', !S.monOut);
  if (S.monOut) $('#monOutBtn').textContent = S.monOut.label;
  if (!S.monOut) monitorShow('orig');
}

function monitorShow(which) {
  const p = $('#player');
  const useOut = which === 'out' && !!S.monOut;
  const url = useOut ? S.monOut.url : p.dataset.src;
  if (url && p.getAttribute('src') !== url) {
    const at = p.currentTime || 0, playing = !p.paused;
    p.src = url;
    p.addEventListener('loadedmetadata', () => {
      p.currentTime = at;
      if (playing) p.play().catch(() => {});
    }, { once: true });
  }
  $$('#monSrc button').forEach(b => b.classList.toggle('on', (b.dataset.mon === 'out') === useOut));
  // Bản xuất đã nung chữ thì ẩn lớp phụ đề xem trước, không là thấy hai lần chữ
  $('#subOverlay').classList.toggle('hide', useOut && !!S.monOut.burned);
  const note = $('#monNote');
  note.classList.toggle('hide', !useOut);
  note.textContent = useOut
    ? `Đang phát ${S.monOut.label.toLowerCase()} đã xuất. Chữ bạn sửa sau lần xuất đó chưa có trong tiếng — xuất lại để nghe bản mới.`
    : '';
}
$$('#monSrc button').forEach(b => b.addEventListener('click', () => monitorShow(b.dataset.mon)));


/* frontend/js/prefs.js — lưu tuỳ chọn, phím tắt.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */
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
['#contextNote', '#glossary', '#aiModel', '#aiBaseUrl'].forEach(id => $(id).addEventListener('input', savePrefs));

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


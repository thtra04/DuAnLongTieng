/* frontend/js/ai.js — mọi thứ về engine dịch AI (Claude / OpenAI-compatible):
   chọn engine, API key, model, endpoint, phong cách, bộ thuật ngữ, vòng lặp
   ngân sách (HP-5) và cache dịch. Phần AI gửi lên máy chủ gom ở aiPayload().
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */

const AI_ENGINES = ['claude', 'openai'];
const isAiEngine = () => AI_ENGINES.includes(S.engine);
const aiProvider = () => (S.engine === 'claude' ? 'anthropic' : 'openai');

// Máy chủ đã có sẵn biến môi trường chứa key cho engine đang chọn chưa?
function aiEnvKey() {
  return aiProvider() === 'anthropic' ? !!S.sys?.has_anthropic_key : !!S.sys?.has_openai_key;
}

/* ------------------------------ chọn engine ------------------------------ */
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

// Hiện/ẩn khung AI theo engine, nạp danh sách model và gợi ý về key
function syncAiBox() {
  const isAi = isAiEngine();
  $('#aiBox').classList.toggle('hide', !isAi);
  $('#baseUrlField').classList.toggle('hide', S.engine !== 'openai');
  if (!isAi) return;
  const provider = aiProvider();
  // Ô model là ô gõ tự do có gợi ý: endpoint OpenAI-compatible (9Router, b.ai,
  // Ollama...) có model riêng, không thể liệt kê hết. Gợi ý theo provider. Đổi
  // provider thì về model mặc định của bên đó, trừ khi giá trị đang có vốn là
  // một model quen của bên đó; còn ở nguyên provider thì giữ đúng thứ đang gõ.
  const models = S.sys.ai_models[provider] || [];
  $('#aiModelList').innerHTML = models
    .map(m => `<option value="${m.id}">${m.label}</option>`).join('');
  const field = $('#aiModel');
  const known = models.some(m => m.id === field.value.trim());
  if (!field.value.trim() || (S.aiProvider !== provider && !known)) {
    field.value = models[0]?.id || '';
  }
  S.aiProvider = provider;
  const varName = provider === 'anthropic' ? 'ANTHROPIC_API_KEY' : 'OPENAI_API_KEY';
  $('#keyHint').textContent = aiEnvKey()
    ? `— đã có ${varName} trong môi trường, để trống là dùng key đó`
    : `— hoặc đặt biến môi trường ${varName}`;
}

/* --------------------------- gửi lên máy chủ ---------------------------- */
// Kiểm tra trước khi chạy: engine AI cần key, nhập tay hoặc qua biến môi trường.
function aiReady() {
  if (!$('#doTranslate').checked || !isAiEngine()) return true;
  if ($('#apiKey').value.trim() || aiEnvKey()) return true;
  toast('Hãy nhập API key hoặc đặt biến môi trường cho engine AI đã chọn.', 'warn', 7000);
  return false;
}

// Phần AI của payload /api/analyze. Key chỉ đi thẳng lên máy chủ trong request
// này, không bao giờ được lưu lại phía trình duyệt (xem saveJobRecovery).
function aiPayload() {
  return {
    engine: S.engine,
    api_key: $('#apiKey').value.trim(),
    ai_model: $('#aiModel').value || '',
    ai_base_url: S.engine === 'openai' ? $('#aiBaseUrl').value.trim() : '',
    context_note: $('#contextNote').value.trim(),
    translation_mode: $('#translationMode').value,
    glossary: $('#glossary').value.trim(),
    // HP-5: chỉ có nghĩa với engine AI — máy chủ tự bỏ qua với Google/MyMemory
    budget_loop: !!($('#budgetLoop') && $('#budgetLoop').checked),
  };
}

/* ----------------------------- cache dịch AI ----------------------------- */
async function refreshCacheInfo() {
  try {
    const info = await api('/api/translation-cache');
    const kb = (info.bytes / 1024).toFixed(1);
    $('#cacheInfo').textContent = `Cache AI: ${info.entries} mục · ${kb} KB`;
  } catch { $('#cacheInfo').textContent = 'Cache AI chưa khả dụng'; }
}

$('#clearCache').addEventListener('click', async () => {
  if (!(await askConfirm('Xoá toàn bộ cache dịch AI?'))) return;
  try {
    const result = await api('/api/translation-cache', { method: 'DELETE' });
    toast(`Đã xoá ${result.deleted} mục cache AI.`, 'ok');
    refreshCacheInfo();
  } catch (e) { toast(e.message, 'err'); }
});

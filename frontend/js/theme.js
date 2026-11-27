/* The login screen and the workspace share one local appearance panel. */
(() => {
  const panel = $('#appearancePanel'), theme = $('#lookTheme'), accent = $('#accentPick');
  const depth = $('#lookDepth'), motion = $('#lookMotion'), clearAccent = $('#accentReset');
  for (const [id, name] of Object.entries(THEMES)) theme.add(new Option(name, id));

  function sync() {
    const colors = getComputedStyle(document.documentElement);
    theme.value = appearance.theme;
    accent.value = appearance.accent || colors.getPropertyValue('--brand').trim();
    clearAccent.disabled = !appearance.accent;
    depth.checked = appearance.depth === 'layered';
    motion.checked = appearance.motion === 'reduce';
    $('#lookName').textContent = THEMES[appearance.theme];
    $('#lookHex').textContent = accent.value.toUpperCase();
    $('meta[name="theme-color"]').content = colors.getPropertyValue('--bg').trim();
  }

  function update(patch) {
    appearance = { ...appearance, ...patch };
    applyAppearance();
    sync();
    try { localStorage.setItem(THEME_KEY, JSON.stringify(appearance)); } catch { /* session only */ }
  }

  theme.addEventListener('change', () => update({ theme: theme.value, accent: '' }));
  accent.addEventListener('input', () => update({ accent: accent.value }));
  clearAccent.addEventListener('click', () => update({ accent: '' }));
  depth.addEventListener('change', () => update({ depth: depth.checked ? 'layered' : 'flat' }));
  motion.addEventListener('change', () => update({ motion: motion.checked ? 'reduce' : 'system' }));
  $('#lookReset').addEventListener('click', () => update(DEFAULT_APPEARANCE));
  $$('[data-appearance-open]').forEach(button => button.addEventListener('click', () => panel.showModal()));
  $('#lookClose').addEventListener('click', () => panel.close());
  panel.addEventListener('click', e => {
    if (e.target !== panel) return;
    const r = panel.getBoundingClientRect();
    if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) panel.close();
  });
  sync();
})();

/* frontend/js/theme.js — chủ đề màu: 11 bảng màu dựng sẵn + màu nhấn tuỳ chọn.
   Lưu trong localStorage; đoạn script inline ở <head> áp data-theme trước khi
   vẽ để không nháy từ sáng sang tối, file này lo phần còn lại.
   Các file js dùng chung một phạm vi toàn cục; thứ tự nạp ghi trong index.html. */

const THEME_KEY = 'vsub.theme.v1';
// Chưa chọn gì thì dùng bảng này — phải trùng với đoạn script inline trong index.html
const DEFAULT_THEME = 'studio';

// id trùng với data-theme trong css/style.css; `sw` là màu hiện trên nút tròn
const THEMES = [
  { id: 'studio', label: 'Studio (xám, xanh dương)', sw: 'linear-gradient(135deg, #262930 48%, #5b93ff 52%)' },
  { id: 'sang', label: 'Sáng (trắng, xanh dương)', sw: 'linear-gradient(135deg, #ffffff 48%, #2f5be0 52%)' },
  { id: 'rap',  label: 'Rạp chiếu', sw: 'linear-gradient(135deg, #0a0a0c 48%, #f0a53a 52%)' },
  { id: 'vang', label: 'Hoàng kim', sw: 'linear-gradient(135deg, #17130c 48%, #e2b659 52%)' },
  { id: 'nga',  label: 'Ngà',       sw: 'linear-gradient(135deg, #f5f1e8 48%, #a16207 52%)' },
  { id: 'hong', label: 'Hồng baby', sw: '#f0609a' },
  { id: 'mint', label: 'Bạc hà',    sw: '#14b89a' },
  { id: 'tim',  label: 'Oải hương', sw: '#8b5cf6' },
  { id: 'dao',  label: 'Đào',       sw: '#ff7a45' },
  { id: 'toi',  label: 'Đêm',       sw: '#1b2a6b' },
  { id: 'than', label: 'Than',      sw: '#2b2f38' },
];
const DARK_THEMES = new Set(['toi', 'than', 'vang', 'rap', 'studio']);

function readTheme() {
  try { return JSON.parse(localStorage.getItem(THEME_KEY) || '{}'); } catch { return {}; }
}
function saveTheme(p) {
  try { localStorage.setItem(THEME_KEY, JSON.stringify(p)); } catch { }
}

/* ------------------------------ đổi màu -------------------------------- */
function hexToRgb(hex) {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const n = parseInt(m[1], 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgbToHex(r, g, b) {
  return '#' + [r, g, b].map(v => Math.round(Math.max(0, Math.min(255, v))).toString(16).padStart(2, '0')).join('');
}
function rgbToHsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min;
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h;
  if (max === r) h = (g - b) / d + (g < b ? 6 : 0);
  else if (max === g) h = (b - r) / d + 2;
  else h = (r - g) / d + 4;
  return [h * 60, s, l];
}
function hslToRgb(h, s, l) {
  h = ((h % 360) + 360) % 360 / 360;
  if (s === 0) return [l * 255, l * 255, l * 255];
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s, p = 2 * l - q;
  const f = t => {
    if (t < 0) t += 1; if (t > 1) t -= 1;
    if (t < 1 / 6) return p + (q - p) * 6 * t;
    if (t < 1 / 2) return q;
    if (t < 2 / 3) return p + (q - p) * (2 / 3 - t) * 6;
    return p;
  };
  return [f(h + 1 / 3) * 255, f(h) * 255, f(h - 1 / 3) * 255];
}
// Độ sáng cảm nhận (WCAG) — quyết định chữ đen hay trắng trên nền màu nhấn
function luminance(r, g, b) {
  const c = [r, g, b].map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}

const ACCENT_VARS = ['--brand', '--brand-rgb', '--brand-2', '--brand-2-rgb', '--brand-text', '--on-brand'];

/* Màu nhấn tuỳ chọn: người dùng chọn MỘT màu, còn lại suy ra — màu phụ cho
   gradient lệch sắc 28°, chữ trên nền màu nhấn chọn đen/trắng theo độ sáng,
   chữ màu nhấn đậm hơn trên nền sáng và nhạt hơn trên nền tối để còn đọc được. */
function applyAccent(hex) {
  const root = document.documentElement;
  const rgb = hex ? hexToRgb(hex) : null;
  if (!rgb) { ACCENT_VARS.forEach(v => root.style.removeProperty(v)); return; }
  const [r, g, b] = rgb;
  const [h, s, l] = rgbToHsl(r, g, b);
  const dark = DARK_THEMES.has(root.dataset.theme || 'hong');
  const b2 = hslToRgb(h + 28, s, Math.min(0.82, l + 0.08));
  const text = hslToRgb(h, Math.min(1, s * 1.05), dark ? 0.78 : 0.32);
  root.style.setProperty('--brand', rgbToHex(r, g, b));
  root.style.setProperty('--brand-rgb', `${r},${g},${b}`);
  root.style.setProperty('--brand-2', rgbToHex(...b2));
  root.style.setProperty('--brand-2-rgb', b2.map(Math.round).join(','));
  root.style.setProperty('--brand-text', rgbToHex(...text));
  root.style.setProperty('--on-brand', luminance(r, g, b) > 0.4 ? '#1a1020' : '#ffffff');
}

function applyTheme(id, accent) {
  const root = document.documentElement;
  const theme = THEMES.some(t => t.id === id) ? id : DEFAULT_THEME;
  // 'hong' là bộ biến gốc ở :root trong CSS nên không cần data-theme
  if (theme === 'hong') delete root.dataset.theme;
  else root.dataset.theme = theme;
  applyAccent(accent || '');
  $$('.swatch[data-theme]').forEach(s => {
    const on = s.dataset.theme === theme && !accent;
    s.classList.toggle('on', on);
    s.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  const custom = $('#accentPick');
  if (custom) {
    custom.parentElement.classList.toggle('on', !!accent);
    if (accent) custom.value = accent;
  }
}

/* --------------------------- bộ chọn trên header ------------------------- */
function buildThemePicker() {
  const box = $('#themePick');
  if (!box) return;
  box.innerHTML = `<span class="lbl" title="Màu giao diện">${icon('palette')}</span>`
    + THEMES.map(t =>
      `<button type="button" class="swatch" data-theme="${t.id}" style="--sw:${t.sw}" title="${t.label}" aria-label="Bảng màu ${t.label}"></button>`
    ).join('')
    + '<label class="swatch custom" title="Màu nhấn tuỳ ý"><input type="color" id="accentPick" aria-label="Màu nhấn tuỳ ý"></label>';

  $$('.swatch[data-theme]', box).forEach(btn => btn.addEventListener('click', () => {
    // Chọn bảng màu sẵn là bỏ màu nhấn tuỳ chọn — hai thứ chồng nhau chỉ rối
    const p = { theme: btn.dataset.theme, accent: '' };
    saveTheme(p);
    applyTheme(p.theme, p.accent);
  }));
  $('#accentPick').addEventListener('input', e => {
    const p = { ...readTheme(), accent: e.target.value };
    saveTheme(p);
    applyTheme(p.theme, p.accent);
  });

  const cur = readTheme();
  applyTheme(cur.theme, cur.accent);
}

buildThemePicker();

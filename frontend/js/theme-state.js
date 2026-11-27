/* Nạp trước CSS để cả màn hình đăng nhập cũng có đúng diện mạo ngay từ khung hình đầu. */
const THEME_KEY = 'vsub.theme.v1';
const DEFAULT_APPEARANCE = { theme: 'champagne', accent: '', depth: 'layered', motion: 'system' };
const THEMES = {
  champagne: 'Champagne sáng',
  premiere: 'Première', nga: 'Ngà', vang: 'Hoàng kim', rap: 'Rạp chiếu',
  studio: 'Studio', sang: 'Sáng', than: 'Than', toi: 'Đêm',
  hong: 'Hồng baby', mint: 'Bạc hà', tim: 'Oải hương', dao: 'Đào',
};
const DARK_THEMES = new Set(['premiere', 'toi', 'than', 'vang', 'rap', 'studio']);

function readTheme() {
  try {
    const p = JSON.parse(localStorage.getItem(THEME_KEY)) || {};
    const accent = typeof p.accent === 'string' && /^#[0-9a-f]{6}$/i.test(p.accent) ? p.accent.toLowerCase() : '';
    // Bản cũ có thể chỉ lưu màu nhấn, khi đó bảng nền thực tế là Ngà.
    const fallback = !p.theme && accent ? 'nga' : DEFAULT_APPEARANCE.theme;
    return {
      theme: typeof p.theme === 'string' && Object.hasOwn(THEMES, p.theme) ? p.theme : fallback,
      accent, depth: p.depth === 'flat' ? 'flat' : DEFAULT_APPEARANCE.depth,
      motion: p.motion === 'reduce' ? 'reduce' : DEFAULT_APPEARANCE.motion,
    };
  } catch { return { ...DEFAULT_APPEARANCE }; }
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
  const ends = [luminance(r, g, b), luminance(...b2)];
  const black = (Math.min(...ends) + 0.05) / 0.05, white = 1.05 / (Math.max(...ends) + 0.05);
  root.style.setProperty('--on-brand', black >= white ? '#000000' : '#ffffff');
}

let appearance = readTheme();
function uiScrollBehavior() {
  return appearance.motion === 'reduce' || matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
}
function applyAppearance() {
  const { theme, accent, depth, motion } = appearance;
  Object.assign(document.documentElement.dataset, { theme, depth, motion });
  applyAccent(accent);
}
applyAppearance();

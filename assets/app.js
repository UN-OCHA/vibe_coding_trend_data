/* ---------------------------------------------------------------------
   Vibecode Daily -- shared data helpers
   Everything here runs client-side against the static CSV/JSON files
   committed by the two GitHub Actions workflows. No build step, no
   backend: this file is what a static host (GitHub Pages / Cloudflare
   Pages / Netlify) actually serves.
--------------------------------------------------------------------- */

/** Minimal CSV parser for the simple, quote-free `date,source,metric,value`
 *  shape produced by fetch_trends.py. Not a general-purpose CSV parser. */
function parseSimpleCsv(text) {
  const lines = text.trim().split(/\r?\n/);
  const header = lines[0].split(",");
  return lines.slice(1).filter(Boolean).map((line) => {
    const cells = line.split(",");
    const row = {};
    header.forEach((h, i) => { row[h.trim()] = (cells[i] || "").trim(); });
    return row;
  });
}

async function fetchCsv(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return parseSimpleCsv(await res.text());
}

async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`Failed to load ${path}: ${res.status}`);
  return res.json();
}

/** Groups rows by metric, sorted by date, values coerced to numbers. */
function seriesByMetric(rows) {
  const out = {};
  for (const row of rows) {
    if (!out[row.metric]) out[row.metric] = [];
    out[row.metric].push({ date: row.date, value: Number(row.value) });
  }
  for (const metric in out) out[metric].sort((a, b) => a.date.localeCompare(b.date));
  return out;
}

function latest(series, metric) {
  const points = series[metric];
  if (!points || !points.length) return null;
  return points[points.length - 1].value;
}

/** Animates a number counting up from 0. Respects reduced-motion. */
function countUp(el, target, { duration = 900, decimals = 0, suffix = "" } = {}) {
  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (prefersReduced) {
    el.textContent = target.toLocaleString(undefined, { maximumFractionDigits: decimals }) + suffix;
    return;
  }
  const start = performance.now();
  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = target * eased;
    el.textContent = value.toLocaleString(undefined, { maximumFractionDigits: decimals }) + suffix;
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

/** Fires `onEnter` once, the first time `el` scrolls into view. */
function onScrollIntoView(el, onEnter) {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        onEnter();
        observer.unobserve(el);
      }
    });
  }, { threshold: 0.3 });
  observer.observe(el);
}

const CATEGORY_CLASS = {
  Tools: "tools", Industry: "industry", Culture: "culture",
  Risks: "risks", Research: "research", Education: "education",
};

function categoryClass(cat) {
  return CATEGORY_CLASS[cat] || "uncategorized";
}

function formatCompact(n) {
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

/** Renders a faint, decorative area chart behind the hero text -- a
 *  visual echo of the headline's data (the leading tool's repo-count
 *  trend), not a readable chart in its own right, so it carries no
 *  axes/labels/tooltips. Requires smoothPathD (assets/trend-chart.js). */
function renderHeroGraphic(svgEl, points) {
  const width = 800, height = 340;
  svgEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svgEl.setAttribute("preserveAspectRatio", "none");
  svgEl.innerHTML = "";
  if (!points || points.length < 2) return;

  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const bandTop = height * 0.32, bandBottom = height * 0.92;

  const x = (i) => (i / (points.length - 1)) * width;
  const y = (v) => bandBottom - ((v - min) / range) * (bandBottom - bandTop);
  const coords = points.map((p, i) => [x(i), y(p.value)]);
  const linePath = smoothPathD(coords);
  const areaPath = `${linePath} L${width},${height} L0,${height} Z`;

  const gradId = "hero-graphic-fill-" + Math.random().toString(36).slice(2, 8);
  svgEl.innerHTML = `
    <defs>
      <linearGradient id="${gradId}" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stop-color="#e8a86a" stop-opacity="0.18" />
        <stop offset="100%" stop-color="#e8a86a" stop-opacity="0" />
      </linearGradient>
    </defs>
    <path d="${areaPath}" fill="url(#${gradId})"></path>
    <path d="${linePath}" fill="none" stroke="#e8a86a" stroke-width="2" stroke-opacity="0.45"></path>
  `;

  svgEl.style.opacity = "0";
  requestAnimationFrame(() => {
    svgEl.style.transition = "opacity 900ms ease";
    svgEl.style.opacity = "1";
  });
}

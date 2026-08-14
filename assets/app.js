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

/* ---------------------------------------------------------------------
   Generic animated line chart -- draws each series' line in via
   stroke-dashoffset when the chart scrolls into view. Shares the same
   hand-rolled SVG approach as bump-chart.js (no charting library).

   Expects: seriesByName = { "Claude Code": [{date, value}, ...], ... }
            weekLabels    = ["Jul 13", "Jul 20", ...] (same length/order
                             as every series)
--------------------------------------------------------------------- */

/** Builds a smooth (Catmull-Rom -> cubic Bezier) SVG path "d" string
 *  through a list of [x, y] coordinate pairs. Shared by the trend charts
 *  and the hero background graphic so lines read as curves, not zig-zags. */
function smoothPathD(coords) {
  if (!coords.length) return "";
  if (coords.length === 1) return `M${coords[0][0]},${coords[0][1]}`;
  if (coords.length === 2) return `M${coords[0][0]},${coords[0][1]} L${coords[1][0]},${coords[1][1]}`;

  let d = `M${coords[0][0]},${coords[0][1]}`;
  for (let i = 0; i < coords.length - 1; i++) {
    const p0 = coords[i - 1] || coords[i];
    const p1 = coords[i];
    const p2 = coords[i + 1];
    const p3 = coords[i + 2] || p2;
    const cp1x = p1[0] + (p2[0] - p0[0]) / 6;
    const cp1y = p1[1] + (p2[1] - p0[1]) / 6;
    const cp2x = p2[0] - (p3[0] - p1[0]) / 6;
    const cp2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${cp1x},${cp1y} ${cp2x},${cp2y} ${p2[0]},${p2[1]}`;
  }
  return d;
}

function renderTrendChart(svgEl, seriesByName, weekLabels, opts = {}) {
  const {
    colors = {},
    defaultColor = "#9a8f7f",
    yFormatter = (v) => String(Math.round(v)),
    yDomain = null, // [min, max] override; otherwise auto from data
  } = opts;

  const width = 600, height = 200;
  const marginLeft = 34, marginRight = 116, marginTop = 16, marginBottom = 26;
  const plotWidth = width - marginLeft - marginRight;
  const plotHeight = height - marginTop - marginBottom;
  const numWeeks = weekLabels.length;

  svgEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svgEl.innerHTML = "";

  const allValues = Object.values(seriesByName).flat().map((p) => p.value);
  const [yMin, yMax] = yDomain || [Math.min(0, ...allValues), Math.max(...allValues)];
  const yRange = yMax - yMin || 1;

  const x = (i) => marginLeft + (i / Math.max(numWeeks - 1, 1)) * plotWidth;
  const y = (v) => marginTop + plotHeight - ((v - yMin) / yRange) * plotHeight;

  [yMin, (yMin + yMax) / 2, yMax].forEach((v) => {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    line.setAttribute("x1", marginLeft);
    line.setAttribute("x2", width - marginRight);
    line.setAttribute("y1", y(v));
    line.setAttribute("y2", y(v));
    line.setAttribute("stroke", "#2a251d");
    line.setAttribute("stroke-width", "1");
    svgEl.appendChild(line);

    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", marginLeft - 6);
    label.setAttribute("y", y(v) + 3);
    label.setAttribute("fill", "#8a8078");
    label.setAttribute("font-size", "9");
    label.setAttribute("text-anchor", "end");
    label.textContent = yFormatter(v);
    svgEl.appendChild(label);
  });

  weekLabels.forEach((w, i) => {
    const mid = Math.floor((numWeeks - 1) / 2);
    if (numWeeks > 2 && i !== 0 && i !== numWeeks - 1 && i !== mid) return;
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", x(i));
    t.setAttribute("y", height - 6);
    t.setAttribute("fill", "#8a8078");
    t.setAttribute("font-size", "10");
    t.setAttribute("text-anchor", "middle");
    t.textContent = w;
    svgEl.appendChild(t);
  });

  const lines = [];
  const labelInfos = [];
  const svgNS = "http://www.w3.org/2000/svg";

  Object.entries(seriesByName).forEach(([name, points]) => {
    const color = colors[name] || defaultColor;
    const coords = points.map((p, i) => [x(i), y(p.value)]);

    // Each series lives in its own <g> so hover-highlight (style.css:
    // .chart-card svg:has(.trend-series:hover) dims the rest) and the
    // click-to-toggle below can target the whole line+dots+label as one.
    const g = document.createElementNS(svgNS, "g");
    g.setAttribute("class", "trend-series");
    g.setAttribute("data-name", name);

    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", smoothPathD(coords));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", "2.5");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("stroke-linecap", "round");
    g.appendChild(path);

    coords.forEach(([px, py], i) => {
      const c = document.createElementNS(svgNS, "circle");
      c.setAttribute("class", "trend-dot");
      c.setAttribute("cx", px);
      c.setAttribute("cy", py);
      c.setAttribute("r", 3);
      c.setAttribute("fill", color);
      const title = document.createElementNS(svgNS, "title");
      title.textContent = `${name} — ${weekLabels[i]}: ${yFormatter(points[i].value)}`;
      c.appendChild(title);
      g.appendChild(c);
    });

    const [lastX, lastY] = coords[coords.length - 1];
    labelInfos.push({ g, name, color, x: lastX + 10, y: lastY + 4 });

    svgEl.appendChild(g);
    lines.push(path);
  });

  // Lines that converge near the same end value would otherwise stack
  // unreadably on top of each other (e.g. every series indexed to the
  // same starting point), so labels are nudged apart vertically after
  // all of them are placed, closest-together pair first.
  declutterLabels(labelInfos, 12).forEach(({ g, name, color, x, y }) => {
    const label = document.createElementNS(svgNS, "text");
    label.setAttribute("class", "trend-label");
    label.setAttribute("x", x);
    label.setAttribute("y", y);
    label.setAttribute("fill", color);
    label.setAttribute("font-size", "11");
    label.textContent = name;
    label.addEventListener("click", () => g.classList.toggle("trend-series-hidden"));
    g.appendChild(label);
  });

  return lines;
}

/** Pushes vertically-crowded labels apart in place (sorted by y) so text
 *  doesn't overlap when multiple series end near the same value. */
function declutterLabels(labelInfos, minGap) {
  const sorted = [...labelInfos].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) {
    const minY = sorted[i - 1].y + minGap;
    if (sorted[i].y < minY) sorted[i].y = minY;
  }
  return sorted;
}

/** Animates each polyline's stroke drawing in left to right. Respects
 *  reduced-motion by jumping straight to the fully-drawn state. */
function animateLinesIn(lines, { duration = 1100 } = {}) {
  const prefersReduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const lengths = lines.map((line) => line.getTotalLength());

  lines.forEach((line, i) => {
    line.style.strokeDasharray = String(lengths[i]);
    line.style.strokeDashoffset = prefersReduced ? "0" : String(lengths[i]);
  });
  if (prefersReduced) return;

  const start = performance.now();
  function tick(now) {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    lines.forEach((line, i) => {
      line.style.strokeDashoffset = String(lengths[i] * (1 - eased));
    });
    if (progress < 1) requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);
}

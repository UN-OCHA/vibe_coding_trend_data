/* ---------------------------------------------------------------------
   Generic animated line chart -- draws each series' line in via
   stroke-dashoffset when the chart scrolls into view. Shares the same
   hand-rolled SVG approach as bump-chart.js (no charting library).

   Expects: seriesByName = { "Claude Code": [{date, value}, ...], ... }
            weekLabels    = ["Jul 13", "Jul 20", ...] (same length/order
                             as every series)
--------------------------------------------------------------------- */

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

  Object.entries(seriesByName).forEach(([name, points]) => {
    const color = colors[name] || defaultColor;
    const coords = points.map((p, i) => [x(i), y(p.value)]);
    const pointsAttr = coords.map(([px, py]) => `${px},${py}`).join(" ");

    const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    poly.setAttribute("points", pointsAttr);
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", color);
    poly.setAttribute("stroke-width", "2.5");
    poly.setAttribute("stroke-linejoin", "round");
    poly.setAttribute("stroke-linecap", "round");
    svgEl.appendChild(poly);

    coords.forEach(([px, py]) => {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", px);
      c.setAttribute("cy", py);
      c.setAttribute("r", 3);
      c.setAttribute("fill", color);
      svgEl.appendChild(c);
    });

    const [lastX, lastY] = coords[coords.length - 1];
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", lastX + 10);
    label.setAttribute("y", lastY + 4);
    label.setAttribute("fill", color);
    label.setAttribute("font-size", "11");
    label.textContent = name;
    svgEl.appendChild(label);

    lines.push(poly);
  });

  return lines;
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

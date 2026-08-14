/* ---------------------------------------------------------------------
   Rank-over-time "bump chart" -- draws itself in on load, one line per
   tool, y-axis is RANK (1 = top) not raw value. This is the leaderboard's
   signature visual: it shows who overtook whom, week to week.

   Expects: seriesByWeek = { "Claude Code": [rank_w1, rank_w2, ...], ... }
            weekLabels    = ["Jul 13", "Jul 20", ...]
--------------------------------------------------------------------- */

const BUMP_COLORS = {
  "Claude Code": "#e8a86a",
  "Codex": "#85c99e",
  "Cursor": "#8ab8d6",
  "GitHub Copilot": "#9a8f7f",
};

/** Same Catmull-Rom -> cubic Bezier smoothing as assets/trend-chart.js,
 *  duplicated rather than shared since this file has no dependency on
 *  trend-chart.js (index.html and leaderboard.html load different scripts). */
function bumpSmoothPathD(coords) {
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

/** Pushes vertically-crowded labels apart in place (sorted by y) so text
 *  doesn't overlap when multiple series end at the same or adjacent rank.
 *  Duplicated from trend-chart.js for the same reason as bumpSmoothPathD. */
function declutterLabels(labelInfos, minGap) {
  const sorted = [...labelInfos].sort((a, b) => a.y - b.y);
  for (let i = 1; i < sorted.length; i++) {
    const minY = sorted[i - 1].y + minGap;
    if (sorted[i].y < minY) sorted[i].y = minY;
  }
  return sorted;
}

function renderBumpChart(svgEl, seriesByWeek, weekLabels, upToWeek) {
  const width = 600, height = 200;
  const marginLeft = 60, marginRight = 110, marginTop = 20, marginBottom = 30;
  const plotWidth = width - marginLeft - marginRight;
  const numWeeks = weekLabels.length;
  const numTools = Object.keys(seriesByWeek).length;
  const svgNS = "http://www.w3.org/2000/svg";

  svgEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svgEl.innerHTML = "";

  const x = (i) => marginLeft + (i / (numWeeks - 1)) * plotWidth;
  const y = (rank) => marginTop + ((rank - 1) / Math.max(numTools - 1, 1)) * (height - marginTop - marginBottom);

  const visibleWeeks = Math.min(upToWeek + 1, numWeeks);
  const labelInfos = [];

  Object.entries(seriesByWeek).forEach(([name, ranks]) => {
    const color = BUMP_COLORS[name] || "#9a8f7f";
    const visibleRanks = ranks.slice(0, visibleWeeks);
    const coords = visibleRanks.map((r, i) => [x(i), y(r)]);

    const g = document.createElementNS(svgNS, "g");
    g.setAttribute("class", "bump-series");
    g.setAttribute("data-name", name);

    const path = document.createElementNS(svgNS, "path");
    path.setAttribute("d", bumpSmoothPathD(coords));
    path.setAttribute("fill", "none");
    path.setAttribute("stroke", color);
    path.setAttribute("stroke-width", "2.5");
    path.setAttribute("stroke-linejoin", "round");
    path.setAttribute("stroke-linecap", "round");
    g.appendChild(path);

    visibleRanks.forEach((r, i) => {
      const c = document.createElementNS(svgNS, "circle");
      c.setAttribute("class", "bump-dot");
      c.setAttribute("cx", x(i));
      c.setAttribute("cy", y(r));
      c.setAttribute("r", 4);
      c.setAttribute("fill", color);
      const title = document.createElementNS(svgNS, "title");
      title.textContent = `${name} — ${weekLabels[i]}: rank #${r}`;
      c.appendChild(title);
      g.appendChild(c);
    });

    const lastIdx = visibleWeeks - 1;
    labelInfos.push({ g, name, color, x: x(lastIdx) + 10, y: y(visibleRanks[lastIdx]) + 4 });

    svgEl.appendChild(g);
  });

  declutterLabels(labelInfos, 12).forEach(({ g, name, color, x, y }) => {
    const label = document.createElementNS(svgNS, "text");
    label.setAttribute("class", "bump-label");
    label.setAttribute("x", x);
    label.setAttribute("y", y);
    label.setAttribute("fill", color);
    label.setAttribute("font-size", "11");
    label.textContent = name;
    label.addEventListener("click", () => g.classList.toggle("bump-series-hidden"));
    g.appendChild(label);
  });

  weekLabels.forEach((w, i) => {
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", x(i));
    t.setAttribute("y", height - 8);
    t.setAttribute("fill", "#8a8078");
    t.setAttribute("font-size", "10");
    t.setAttribute("text-anchor", "middle");
    t.textContent = w;
    svgEl.appendChild(t);
  });
}

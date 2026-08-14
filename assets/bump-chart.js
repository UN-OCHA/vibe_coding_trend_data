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

function renderBumpChart(svgEl, seriesByWeek, weekLabels, upToWeek) {
  const width = 600, height = 200;
  const marginLeft = 60, marginRight = 110, marginTop = 20, marginBottom = 30;
  const plotWidth = width - marginLeft - marginRight;
  const numWeeks = weekLabels.length;
  const numTools = Object.keys(seriesByWeek).length;

  svgEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svgEl.innerHTML = "";

  const x = (i) => marginLeft + (i / (numWeeks - 1)) * plotWidth;
  const y = (rank) => marginTop + ((rank - 1) / Math.max(numTools - 1, 1)) * (height - marginTop - marginBottom);

  const visibleWeeks = Math.min(upToWeek + 1, numWeeks);

  Object.entries(seriesByWeek).forEach(([name, ranks]) => {
    const color = BUMP_COLORS[name] || "#9a8f7f";
    const points = ranks.slice(0, visibleWeeks).map((r, i) => `${x(i)},${y(r)}`).join(" ");

    const poly = document.createElementNS("http://www.w3.org/2000/svg", "polyline");
    poly.setAttribute("points", points);
    poly.setAttribute("fill", "none");
    poly.setAttribute("stroke", color);
    poly.setAttribute("stroke-width", "2.5");
    poly.setAttribute("stroke-linejoin", "round");
    svgEl.appendChild(poly);

    ranks.slice(0, visibleWeeks).forEach((r, i) => {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", x(i));
      c.setAttribute("cy", y(r));
      c.setAttribute("r", 4);
      c.setAttribute("fill", color);
      svgEl.appendChild(c);
    });

    const lastIdx = visibleWeeks - 1;
    const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
    label.setAttribute("x", x(lastIdx) + 10);
    label.setAttribute("y", y(ranks[lastIdx]) + 4);
    label.setAttribute("fill", color);
    label.setAttribute("font-size", "11");
    label.textContent = name;
    svgEl.appendChild(label);
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

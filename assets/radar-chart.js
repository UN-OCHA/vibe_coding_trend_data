/* ---------------------------------------------------------------------
   Radar / spider chart -- compares several tools across a handful of
   normalized [0,1] axes at once. Same hand-rolled SVG approach as
   trend-chart.js (no charting library, no build step).

   Expects: seriesByTool = { "Claude Code": [0.8, 0.4, ...], ... }
                            (one value per axis, aligned with axisLabels,
                             each already normalized to [0,1])
            axisLabels    = ["Momentum", "Community", "Buzz", "Interest"]

   opts.noDataAxes = { "Cursor": [3] } -- axis indices to render as an
   explicit "no data" marker (hollow dashed dot) rather than a real
   value, for a tool with a genuine data gap on that axis. The polygon
   still passes through 0 there so the shape stays honest about what
   isn't known, rather than silently omitting or faking a number.

   opts.emptyAxes = [3] -- axis indices where NONE of the tools shown
   have data at all (e.g. a growth signal with only one snapshot so far,
   nothing to diff yet). Without this, every tool's per-tool "no data"
   marker from noDataAxes would stack on top of each other at dead
   center, indistinguishable from nothing being drawn there. Instead the
   spoke itself is dashed/muted and gets a single "not enough data yet"
   label, and the redundant per-tool markers on that axis are skipped.
--------------------------------------------------------------------- */

function renderRadarChart(svgEl, seriesByTool, axisLabels, opts = {}) {
  const { colors = {}, defaultColor = "#9a8f7f", noDataAxes = {}, emptyAxes = [] } = opts;

  const width = 420, height = 340;
  const cx = width / 2, cy = height / 2 - 6;
  const outerR = 100;
  const numAxes = axisLabels.length;
  const svgNS = "http://www.w3.org/2000/svg";

  svgEl.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svgEl.innerHTML = "";

  const angleFor = (i) => (Math.PI * 2 * i) / numAxes - Math.PI / 2;
  const pointFor = (i, frac) => [
    cx + Math.cos(angleFor(i)) * outerR * frac,
    cy + Math.sin(angleFor(i)) * outerR * frac,
  ];

  // Grid rings, faint
  [0.25, 0.5, 0.75, 1].forEach((frac) => {
    const ring = document.createElementNS(svgNS, "polygon");
    ring.setAttribute("points", axisLabels.map((_, i) => pointFor(i, frac).join(",")).join(" "));
    ring.setAttribute("fill", "none");
    ring.setAttribute("stroke", "#2a251d");
    ring.setAttribute("stroke-width", "1");
    svgEl.appendChild(ring);
  });

  // Axis spokes + labels
  axisLabels.forEach((label, i) => {
    const isEmpty = emptyAxes.includes(i);
    const [ex, ey] = pointFor(i, 1);
    const line = document.createElementNS(svgNS, "line");
    line.setAttribute("x1", cx);
    line.setAttribute("y1", cy);
    line.setAttribute("x2", ex);
    line.setAttribute("y2", ey);
    line.setAttribute("stroke", isEmpty ? "#4a4238" : "#2a251d");
    line.setAttribute("stroke-width", "1");
    if (isEmpty) line.setAttribute("stroke-dasharray", "3,3");
    svgEl.appendChild(line);

    // Anchor away from center rather than always "middle" - a label
    // whose point sits to the right/left of center (Community/Interest
    // in the default 4-axis layout) would otherwise have half its text
    // extend back over the outermost (rank 1.0) dot on that axis, since
    // text-anchor="middle" centers the string on the point instead of
    // pushing it outward. Top/bottom labels stay centered since they
    // don't have that horizontal collision.
    const [lx, ly] = pointFor(i, 1.16);
    const dx = lx - cx;
    const anchor = dx > 4 ? "start" : dx < -4 ? "end" : "middle";
    const text = document.createElementNS(svgNS, "text");
    text.setAttribute("x", lx);
    text.setAttribute("y", ly + 3);
    text.setAttribute("fill", isEmpty ? "#8a8071" : "#c9beb0");
    text.setAttribute("font-size", "11");
    text.setAttribute("text-anchor", anchor);
    text.textContent = label;
    svgEl.appendChild(text);

    if (isEmpty) {
      // One shared "not enough data yet" label per empty axis, placed
      // partway along the spoke - not per tool, since every tool's
      // individual marker would sit at the exact same point and be
      // unreadable stacked on top of each other.
      const [mx, my] = pointFor(i, 0.56);
      const mdx = mx - cx;
      const manchor = mdx > 4 ? "start" : mdx < -4 ? "end" : "middle";
      const note = document.createElementNS(svgNS, "text");
      note.setAttribute("x", mx);
      note.setAttribute("y", my + 3);
      note.setAttribute("fill", "#6b6154");
      note.setAttribute("font-size", "9");
      note.setAttribute("font-style", "italic");
      note.setAttribute("text-anchor", manchor);
      note.textContent = "no data yet";
      svgEl.appendChild(note);
    }
  });

  Object.entries(seriesByTool).forEach(([name, values]) => {
    const color = colors[name] || defaultColor;
    const clamped = values.map((v) => Math.max(0, Math.min(1, v)));
    const coords = clamped.map((v, i) => pointFor(i, v));
    const noData = noDataAxes[name] || [];

    const g = document.createElementNS(svgNS, "g");
    g.setAttribute("class", "radar-series");
    g.setAttribute("data-name", name);

    const poly = document.createElementNS(svgNS, "polygon");
    poly.setAttribute("points", coords.map((c) => c.join(",")).join(" "));
    poly.setAttribute("fill", color);
    poly.setAttribute("fill-opacity", "0.14");
    poly.setAttribute("stroke", color);
    poly.setAttribute("stroke-width", "2");
    poly.setAttribute("stroke-linejoin", "round");
    // A later-drawn tool's fill (even at 14% opacity) sits on top of an
    // earlier tool's dots wherever the two shapes overlap, and an SVG
    // fill captures hover/click by default - so a dot underneath one of
    // these polygons was literally unreachable by the mouse. Turning off
    // pointer-events on the fill/stroke lets hover pass through to
    // whatever dot is actually there, regardless of paint order.
    poly.setAttribute("pointer-events", "none");
    g.appendChild(poly);

    coords.forEach(([px, py], i) => {
      // Skip the per-tool marker on an axis where NOTHING is tracked yet
      // (opts.emptyAxes) - it'd sit at the exact same point as every other
      // tool's marker there, stacked unreadably. The shared spoke-level
      // "no data yet" label drawn above already covers it once for the
      // whole axis.
      if (emptyAxes.includes(i)) return;
      const isNoData = noData.includes(i);
      const dot = document.createElementNS(svgNS, "circle");
      dot.setAttribute("cx", px);
      dot.setAttribute("cy", py);
      dot.setAttribute("r", isNoData ? 3.5 : 4);
      dot.setAttribute("fill", isNoData ? "#17140f" : color);
      dot.setAttribute("stroke", color);
      dot.setAttribute("stroke-width", isNoData ? "1.5" : "0");
      if (isNoData) dot.setAttribute("stroke-dasharray", "2,1.5");
      const title = document.createElementNS(svgNS, "title");
      title.textContent = isNoData
        ? `${name} — ${axisLabels[i]}: no data`
        : `${name} — ${axisLabels[i]}: ${Math.round(clamped[i] * 100)}`;
      dot.appendChild(title);
      g.appendChild(dot);
    });

    svgEl.appendChild(g);
  });
}

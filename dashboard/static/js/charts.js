/* Charts — pequena biblioteca SVG sem dependências.
 * Specs (skill dataviz): barras <=24px com ponta arredondada de 4px e base reta,
 * linhas de 2px, marcadores >=8px com anel de 2px da cor da superfície,
 * grid/eixos em hairline sólida, rótulos seletivos, tooltip em toda marca,
 * alvo de hover maior que a marca, texto sempre em tokens de texto.
 * Todo texto vindo de dados entra via textContent.
 */
const Charts = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const root = document.documentElement;
  const css = (name) => getComputedStyle(root).getPropertyValue(name).trim();

  function svgEl(tag, attrs = {}, parent) {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) n.setAttribute(k, v);
    if (parent) parent.appendChild(n);
    return n;
  }
  function text(parent, x, y, s, attrs = {}) {
    const { halo, ...rest } = attrs;
    const t = svgEl("text", { x, y, "font-size": 12, fill: css("--text-secondary"), ...rest }, parent);
    if (halo) { t.setAttribute("stroke", css("--surface-1")); t.setAttribute("stroke-width", 4); t.setAttribute("stroke-linejoin", "round"); t.setAttribute("paint-order", "stroke"); }
    t.textContent = s;
    return t;
  }

  // ---- medição de texto (para não cortar rótulos) ------------------------
  const ctx = document.createElement("canvas").getContext("2d");
  function measure(s, size = 12, weight = 400) {
    ctx.font = `${weight} ${size}px ${getComputedStyle(document.body).fontFamily}`;
    return ctx.measureText(s).width;
  }

  // ---- escalas -------------------------------------------------------------
  function niceStep(span, count) {
    const raw = span / Math.max(1, count);
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const norm = raw / mag;
    return (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  }
  function niceTicks(min, max, count = 4) {
    if (max === min) max = min + 1;
    const step = niceStep(max - min, count);
    const lo = Math.floor(min / step) * step;
    const hi = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = lo; v <= hi + step / 2; v += step) ticks.push(+v.toFixed(10));
    return ticks;
  }
  const linear = (d0, d1, r0, r1) => (v) => r0 + ((v - d0) / (d1 - d0 || 1)) * (r1 - r0);

  // ---- formas --------------------------------------------------------------
  // coluna: base reta, topo arredondado 4px
  function colPath(x, y, w, h, r = 4) {
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }
  // barra horizontal: base reta à esquerda, ponta arredondada à direita
  function barPath(x, y, w, h, r = 4) {
    r = Math.min(r, h / 2, w);
    if (w <= 0) return "";
    return `M${x},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h - r}Q${x + w},${y + h} ${x + w - r},${y + h}H${x}Z`;
  }

  // ---- tooltip -------------------------------------------------------------
  const tip = document.getElementById("tooltip");
  function fillTip(title, rows) {
    tip.replaceChildren();
    if (title) {
      const t = document.createElement("div");
      t.className = "tt-titulo";
      t.textContent = title;
      tip.appendChild(t);
    }
    for (const r of rows) {
      const line = document.createElement("div");
      line.className = "tt-linha";
      const key = document.createElement("span");
      key.className = "tt-key";
      if (r.color) {
        const i = document.createElement("i");
        i.style.background = r.color;
        key.appendChild(i);
      }
      key.appendChild(document.createTextNode(r.key));
      const val = document.createElement("span");
      val.className = "tt-val";
      val.textContent = r.value;
      line.append(key, val);   // valor em destaque, rótulo secundário
      tip.appendChild(line);
    }
  }
  function placeTip(cx, cy) {
    tip.hidden = false;
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = cx + 14, y = cy - h - 10;
    if (x + w > innerWidth - 8) x = cx - w - 14;
    if (y < 8) y = cy + 16;
    tip.style.left = `${Math.max(8, x)}px`;
    tip.style.top = `${y}px`;
  }
  function hideTip() { tip.hidden = true; }
  // mesmo conteúdo no hover e no foco do teclado
  function bindTip(node, content) {
    node.setAttribute("tabindex", "0");
    const show = (x, y) => { const c = content(); fillTip(c.title, c.rows); placeTip(x, y); };
    node.addEventListener("pointermove", (e) => show(e.clientX, e.clientY));
    node.addEventListener("pointerleave", hideTip);
    node.addEventListener("focus", () => { const b = node.getBoundingClientRect(); show(b.left + b.width / 2, b.top); });
    node.addEventListener("blur", hideTip);
    const c = content();
    node.setAttribute("aria-label", [c.title, ...c.rows.map((r) => `${r.key}: ${r.value}`)].filter(Boolean).join(". "));
  }

  function svgFor(container, height) {
    container.replaceChildren();
    const width = Math.max(240, container.clientWidth);
    const svg = svgEl("svg", { width, height, viewBox: `0 0 ${width} ${height}`, role: "img" }, container);
    return { svg, width, height };
  }

  function yAxis(svg, ticks, y, x0, x1, fmt) {
    const g = svgEl("g", {}, svg);
    ticks.forEach((t, i) => {
      svgEl("line", { x1: x0, x2: x1, y1: y(t), y2: y(t), stroke: i === 0 ? css("--baseline") : css("--grid"), "stroke-width": 1, "shape-rendering": "crispEdges" }, g);
      text(g, x0 - 8, y(t) + 4, fmt(t), { "text-anchor": "end", "font-size": 11, fill: css("--axis-label"), "font-variant-numeric": "tabular-nums" });
    });
  }

  // =========================================================================
  // Colunas (série única, com "emphasis": fora da janela em cinza)
  // =========================================================================
  function columns(container, o) {
    const H = o.height || 240;
    const { svg, width } = svgFor(container, H);
    svg.setAttribute("aria-label", o.ariaLabel || "");
    const vals = o.data.map(o.y);
    const ticks = niceTicks(0, Math.max(...vals) * 1.05, 4);
    const ml = Math.max(...ticks.map((t) => measure(o.fmtAxis(t), 11))) + 14;
    const m = { t: 22, r: 4, b: 26, l: ml };
    const iw = width - m.l - m.r, ih = H - m.t - m.b;
    const y = linear(0, ticks[ticks.length - 1], m.t + ih, m.t);
    yAxis(svg, ticks, y, m.l, width - m.r, o.fmtAxis);

    const n = o.data.length, band = iw / n;
    const bw = Math.min(24, band * 0.62);
    const maxLabelW = Math.max(...o.data.map((d) => measure(o.x(d), 11)));
    const every = Math.ceil((maxLabelW + 8) / band);
    const labelIdx = new Set(o.labelAt ? o.labelAt(o.data) : [n - 1]);

    o.data.forEach((d, i) => {
      const v = o.y(d), cx = m.l + band * i + band / 2;
      const g = svgEl("g", { class: "item" }, svg);
      svgEl("rect", { class: "hit", x: m.l + band * i, y: m.t, width: band, height: ih, rx: 4 }, g);
      const top = y(v), h = y(0) - top;
      svgEl("path", { class: "mark", d: colPath(cx - bw / 2, top, bw, h), fill: o.color(d) }, g);
      if (labelIdx.has(i)) text(g, cx, top - 6, o.fmtLabel(v), { "text-anchor": "middle", fill: css("--text-primary"), "font-weight": 600, "font-size": 11 });
      if ((n - 1 - i) % every === 0) text(svg, cx, H - 8, o.x(d), { "text-anchor": "middle", "font-size": 11, fill: css("--axis-label") });
      bindTip(g, () => o.tip(d));
    });
  }

  // =========================================================================
  // Linha com crosshair + linha de referência (meta)
  // =========================================================================
  function line(container, o) {
    const H = o.height || 240;
    const { svg, width } = svgFor(container, H);
    svg.setAttribute("aria-label", o.ariaLabel || "");
    const vals = o.data.map(o.y);
    const lo = Math.min(...vals, o.ref ? o.ref.value : Infinity);
    const hi = Math.max(...vals, o.ref ? o.ref.value : -Infinity);
    const pad = (hi - lo) * 0.12 || 0.05;
    const ticks = niceTicks(Math.max(o.floor ?? -Infinity, lo - pad), Math.min(o.ceil ?? Infinity, hi + pad), 4);
    const endLabel = o.fmtLabel(vals[vals.length - 1]);
    const ml = Math.max(...ticks.map((t) => measure(o.fmtAxis(t), 11))) + 14;
    const m = { t: 14, r: measure(endLabel, 12, 600) + 16, b: 26, l: ml };
    const iw = width - m.l - m.r, ih = H - m.t - m.b;
    const y = linear(ticks[0], ticks[ticks.length - 1], m.t + ih, m.t);
    const n = o.data.length;
    const x = (i) => m.l + (n === 1 ? iw / 2 : (iw * i) / (n - 1));
    yAxis(svg, ticks, y, m.l, width - m.r, o.fmtAxis);

    // referência (meta): hairline sólida + rótulo
    if (o.ref) {
      const ry = y(o.ref.value);
      svgEl("line", { x1: m.l, x2: width - m.r, y1: ry, y2: ry, stroke: css("--text-secondary"), "stroke-width": 1, "shape-rendering": "crispEdges" }, svg);
      const lbl = o.ref.label;
      svgEl("rect", { x: m.l + 4, y: ry - 17, width: measure(lbl, 11, 600) + 8, height: 15, rx: 3, fill: css("--surface-1") }, svg);
      text(svg, m.l + 8, ry - 6, lbl, { "font-size": 11, "font-weight": 600, fill: css("--text-secondary") });
    }

    // rótulos do eixo x
    const maxLabelW = Math.max(...o.data.map((d) => measure(o.x(d), 11)));
    const every = Math.ceil((maxLabelW + 10) / (iw / Math.max(1, n - 1)));
    o.data.forEach((d, i) => {
      if ((n - 1 - i) % every === 0) text(svg, x(i), H - 8, o.x(d), { "text-anchor": "middle", "font-size": 11, fill: css("--axis-label") });
    });

    // segmentos: contexto em cinza, janela no acento
    const accent = css("--series-1"), deemph = css("--deemph");
    for (let i = 1; i < n; i++) {
      const inWin = o.emph(o.data[i]) && o.emph(o.data[i - 1]);
      svgEl("line", { x1: x(i - 1), y1: y(vals[i - 1]), x2: x(i), y2: y(vals[i]), stroke: inWin ? accent : deemph, "stroke-width": 2, "stroke-linecap": "round" }, svg);
    }
    // ponto final + rótulo de valor na ponta
    const surf = css("--surface-1");
    svgEl("circle", { cx: x(n - 1), cy: y(vals[n - 1]), r: 5, fill: accent, stroke: surf, "stroke-width": 2 }, svg);
    text(svg, x(n - 1) + 9, y(vals[n - 1]) + 4, endLabel, { "font-weight": 600, fill: css("--text-primary") });
    // extremo (mínimo) rotulado: é a história do pico
    if (o.labelMin) {
      const iMin = vals.indexOf(Math.min(...vals));
      if (iMin !== n - 1) {
        svgEl("circle", { cx: x(iMin), cy: y(vals[iMin]), r: 4, fill: o.emph(o.data[iMin]) ? accent : deemph, stroke: surf, "stroke-width": 2 }, svg);
        text(svg, x(iMin), y(vals[iMin]) + 18, o.fmtLabel(vals[iMin]), { "text-anchor": "middle", "font-weight": 600, "font-size": 11, fill: css("--text-primary") });
      }
    }

    // crosshair
    const cross = svgEl("line", { y1: m.t, y2: m.t + ih, stroke: css("--baseline"), "stroke-width": 1, visibility: "hidden" }, svg);
    const dot = svgEl("circle", { r: 5, fill: accent, stroke: surf, "stroke-width": 2, visibility: "hidden" }, svg);
    const overlay = svgEl("rect", { x: m.l - 10, y: m.t, width: iw + 20, height: ih, fill: "transparent", tabindex: 0, "aria-label": "Use as setas para percorrer os meses" }, svg);
    let cur = n - 1;
    const show = (i, cx, cy) => {
      cur = i;
      cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
      dot.setAttribute("cx", x(i)); dot.setAttribute("cy", y(vals[i])); dot.setAttribute("visibility", "visible");
      dot.setAttribute("fill", o.emph(o.data[i]) ? accent : deemph);
      const c = o.tip(o.data[i]);
      fillTip(c.title, c.rows);
      placeTip(cx, cy);
    };
    const hide = () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); hideTip(); };
    overlay.addEventListener("pointermove", (e) => {
      const b = svg.getBoundingClientRect();
      const px = e.clientX - b.left;
      const i = Math.max(0, Math.min(n - 1, Math.round(((px - m.l) / iw) * (n - 1))));
      show(i, e.clientX, e.clientY);
    });
    overlay.addEventListener("pointerleave", hide);
    const focusShow = (i) => { const b = svg.getBoundingClientRect(); show(i, b.left + x(i), b.top + y(vals[i])); };
    overlay.addEventListener("focus", () => focusShow(cur));
    overlay.addEventListener("blur", hide);
    overlay.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft") { e.preventDefault(); focusShow(Math.max(0, cur - 1)); }
      if (e.key === "ArrowRight") { e.preventDefault(); focusShow(Math.min(n - 1, cur + 1)); }
    });
  }

  // =========================================================================
  // Barras horizontais ranqueadas
  // =========================================================================
  function hbars(container, o) {
    const rowH = o.rowH || 32, bh = Math.min(24, o.barH || 14);
    const H = o.data.length * rowH + (o.ref ? 22 : 6);
    const { svg, width } = svgFor(container, H);
    svg.setAttribute("aria-label", o.ariaLabel || "");
    const labels = o.data.map(o.label);
    const lw = Math.min(width * 0.42, Math.max(...labels.map((s) => measure(s, 12))) + 12);
    const vlabels = o.data.map((d) => o.fmt(o.value(d)));
    const vw = Math.max(...vlabels.map((s) => measure(s, 12, 600))) + 10;
    const top = o.ref ? 18 : 2;
    const x0 = lw, x1 = width - vw;
    const max = o.max ?? Math.max(...o.data.map(o.value));
    const x = linear(0, max, x0, x1);

    if (o.ref) {
      const rx = x(o.ref.value);
      svgEl("line", { x1: rx, x2: rx, y1: top - 4, y2: top + o.data.length * rowH, stroke: css("--text-secondary"), "stroke-width": 1, "shape-rendering": "crispEdges" }, svg);
      text(svg, rx, 11, o.ref.label, { "text-anchor": rx > width - 80 ? "end" : "middle", "font-size": 11, "font-weight": 600 });
    }
    svgEl("line", { x1: x0, x2: x0, y1: top, y2: top + o.data.length * rowH, stroke: css("--baseline"), "stroke-width": 1, "shape-rendering": "crispEdges" }, svg);

    o.data.forEach((d, i) => {
      const v = o.value(d), yy = top + i * rowH;
      const g = svgEl("g", { class: "item" }, svg);
      svgEl("rect", { class: "hit", x: 0, y: yy, width, height: rowH, rx: 4 }, g);
      let lbl = labels[i];
      while (measure(lbl, 12) > lw - 12 && lbl.length > 4) lbl = lbl.slice(0, -2) + "…";
      text(g, lw - 10, yy + rowH / 2 + 4, lbl, { "text-anchor": "end", fill: css("--text-secondary") });
      svgEl("path", { class: "mark", d: barPath(x0, yy + (rowH - bh) / 2, Math.max(0, x(v) - x0), bh), fill: o.color ? o.color(d, i) : css("--series-1") }, g);
      text(g, x(v) + 6, yy + rowH / 2 + 4, vlabels[i], { fill: css("--text-primary"), "font-weight": 600, "font-variant-numeric": "tabular-nums", halo: true });
      bindTip(g, () => o.tip(d));
    });

  }

  // =========================================================================
  // Dumbbell: SLA contratado (tom claro) → entregue (tom forte)
  // =========================================================================
  function dumbbell(container, o) {
    const rowH = 34, top = o.ref ? 20 : 0;
    const H = o.data.length * rowH + 28 + top;
    const { svg, width } = svgFor(container, H);
    svg.setAttribute("aria-label", o.ariaLabel || "");
    const labels = o.data.map(o.label);
    const lw = Math.min(width * 0.36, Math.max(...labels.map((s) => measure(s, 12))) + 14);
    const gaps = o.data.map((d) => o.fmtGap(o.b(d) - o.a(d)));
    const gw = Math.max(...gaps.map((s) => measure(s, 12, 600))) + 14;
    const all = o.data.flatMap((d) => [o.a(d), o.b(d)]);
    const x0 = lw + 8, x1 = width - gw;
    const ticks = niceTicks(Math.min(...all) - 0.02, Math.min(1, Math.max(...all) + 0.01), Math.max(2, Math.min(5, Math.floor((x1 - x0) / 56))));
    const x = linear(ticks[0], ticks[ticks.length - 1], x0, x1);
    const yBottom = top + o.data.length * rowH;

    ticks.forEach((t) => {
      svgEl("line", { x1: x(t), x2: x(t), y1: top, y2: yBottom, stroke: css("--grid"), "stroke-width": 1, "shape-rendering": "crispEdges" }, svg);
      text(svg, x(t), yBottom + 18, o.fmtAxis(t), { "text-anchor": "middle", "font-size": 11, fill: css("--axis-label"), "font-variant-numeric": "tabular-nums" });
    });
    if (o.ref) {
      const rx = x(o.ref.value);
      svgEl("line", { x1: rx, x2: rx, y1: top - 4, y2: yBottom, stroke: css("--text-secondary"), "stroke-width": 1, "shape-rendering": "crispEdges" }, svg);
      if (o.ref.label) text(svg, rx, 11, o.ref.label, { "text-anchor": "middle", "font-size": 11, "font-weight": 600 });
    }

    const cA = css("--seq-250"), cB = css("--series-1"), surf = css("--surface-1"), conn = css("--baseline");
    o.data.forEach((d, i) => {
      const yy = top + i * rowH + rowH / 2, a = o.a(d), b = o.b(d);
      const g = svgEl("g", { class: "item" }, svg);
      svgEl("rect", { class: "hit", x: 0, y: top + i * rowH, width, height: rowH, rx: 4 }, g);
      text(g, lw, yy + 4, labels[i], { "text-anchor": "end", fill: css("--text-secondary") });
      svgEl("line", { class: "mark", x1: x(a), x2: x(b), y1: yy, y2: yy, stroke: conn, "stroke-width": 2, "stroke-linecap": "round" }, g);
      svgEl("circle", { class: "mark", cx: x(a), cy: yy, r: 5, fill: cA, stroke: surf, "stroke-width": 2 }, g);
      svgEl("circle", { class: "mark", cx: x(b), cy: yy, r: 5, fill: cB, stroke: surf, "stroke-width": 2 }, g);
      text(g, width - 4, yy + 4, gaps[i], { "text-anchor": "end", fill: css("--text-primary"), "font-weight": 600, "font-variant-numeric": "tabular-nums" });
      bindTip(g, () => o.tip(d));
    });
  }

  // =========================================================================
  // Sparkline (stat tile): linha em cinza, período atual no acento
  // =========================================================================
  function sparkline(values, { w = 96, h = 32, emph } = {}) {
    const svg = svgEl("svg", { width: w, height: h, viewBox: `0 0 ${w} ${h}`, class: "spark", "aria-hidden": "true" });
    const v = values.filter((p) => p != null);
    if (v.length < 2) return svg;
    const lo = Math.min(...v), hi = Math.max(...v);
    const x = (i) => 4 + ((w - 8) * i) / (values.length - 1);
    const y = linear(lo, hi === lo ? lo + 1 : hi, h - 5, 5);
    const pts = values.map((p, i) => `${x(i)},${y(p)}`).join(" ");
    svgEl("polyline", { points: pts, fill: "none", stroke: css("--deemph"), "stroke-width": 1.5, "stroke-linejoin": "round", "stroke-linecap": "round" }, svg);
    const last = values.length - 1;
    svgEl("circle", { cx: x(last), cy: y(values[last]), r: 3.5, fill: emph || css("--series-1"), stroke: css("--surface-1"), "stroke-width": 1.5 }, svg);
    return svg;
  }

  // =========================================================================
  // Barra segmentada alta (parte-do-todo, <=6 partes)
  // =========================================================================
  function segmentedBar(container, o) {
    container.replaceChildren();
    const bar = document.createElement("div");
    bar.className = "seg-bar";
    bar.setAttribute("role", "img");
    bar.setAttribute("aria-label", o.data.map((d) => `${o.label(d)} ${o.fmtPct(o.share(d))}`).join(", "));
    container.appendChild(bar);
    const totalW = container.clientWidth;
    o.data.forEach((d) => {
      const share = o.share(d);
      if (!(share > 0)) return;
      const b = document.createElement("div");
      b.className = "bloco";
      b.style.flex = `${share} 1 0`;
      b.style.background = o.color(d);
      b.style.color = o.onColor(d);
      const lbl = o.fmtPct(share);
      if (measure(lbl, 12, 600) + 12 < totalW * share - 2) b.textContent = lbl;  // só imprime se couber
      bar.appendChild(b);
      bindTip(b, () => o.tip(d));
    });
  }

  // =========================================================================
  // Tabela (visão acessível de cada gráfico, e scorecard)
  // =========================================================================
  function table(container, cols, rows, { sortable = false, initialSort } = {}) {
    container.replaceChildren();
    const t = document.createElement("table");
    const thead = t.createTHead(), tr = thead.insertRow();
    const tbody = t.createTBody();
    let sortKey = initialSort?.key, dir = initialSort?.dir || "asc";
    const render = () => {
      const data = [...rows];
      if (sortKey) {
        const col = cols.find((c) => c.key === sortKey);
        const val = col.sortValue || ((r) => r[col.key]);
        data.sort((a, b) => {
          const va = val(a), vb = val(b);
          const r = typeof va === "string" ? va.localeCompare(vb, "pt-BR") : (va ?? -Infinity) - (vb ?? -Infinity);
          return dir === "asc" ? r : -r;
        });
      }
      tbody.replaceChildren();
      for (const r of data) {
        const row = tbody.insertRow();
        for (const c of cols) {
          const td = row.insertCell();
          if (c.num) td.className = "n";
          const v = c.render ? c.render(r) : c.fmt ? c.fmt(r[c.key]) : r[c.key];
          if (v instanceof Node) td.appendChild(v); else td.textContent = v ?? "—";
        }
      }
      [...tr.children].forEach((th) => th.removeAttribute("aria-sort"));
      if (sortKey) tr.children[cols.findIndex((c) => c.key === sortKey)].setAttribute("aria-sort", dir === "asc" ? "ascending" : "descending");
    };
    cols.forEach((c) => {
      const th = document.createElement("th");
      th.textContent = c.label;
      th.scope = "col";
      if (c.num) th.className = "n";
      if (sortable) {
        th.dataset.sort = c.key;
        th.tabIndex = 0;
        const go = () => { dir = sortKey === c.key && dir === "desc" ? "asc" : sortKey === c.key ? "desc" : (c.num ? "desc" : "asc"); sortKey = c.key; render(); };
        th.addEventListener("click", go);
        th.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
      }
      tr.appendChild(th);
    });
    render();
    container.appendChild(t);
  }

  return { columns, line, hbars, dumbbell, sparkline, segmentedBar, table, css, measure, hideTip };
})();

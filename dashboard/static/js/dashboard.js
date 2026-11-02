/* Painel executivo — busca /api/painel, aplica filtros e desenha tudo. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const css = Charts.css;

  // ---- formatação pt-BR ----------------------------------------------------
  const nf = (o) => new Intl.NumberFormat("pt-BR", o);
  const F = {
    int: (v) => nf({ maximumFractionDigits: 0 }).format(v),
    brl: (v) => nf({ style: "currency", currency: "BRL" }).format(v),
    brl0: (v) => nf({ style: "currency", currency: "BRL", maximumFractionDigits: 0 }).format(v),
    brl_compacto: (v) => nf({ style: "currency", currency: "BRL", notation: "compact", maximumFractionDigits: 1 }).format(v),
    compacto: (v) => nf({ notation: "compact", maximumFractionDigits: 1 }).format(v),
    pct: (v) => nf({ style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v),
    pct0: (v) => nf({ style: "percent", maximumFractionDigits: 0 }).format(v),
    nota: (v) => nf({ minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v),
    nota1: (v) => nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v),
    h: (v) => `${nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v)} h`,
    pp: (v) => `${v >= 0 ? "+" : "−"}${nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Math.abs(v * 100))} p.p.`,
    rel: (v) => `${v >= 0 ? "+" : "−"}${nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(Math.abs(v * 100))}%`,
  };
  const fmt = (k, v) => (v == null ? "—" : F[k](v));

  // ---- ícones de status (cor nunca sozinha: ícone + rótulo) ----------------
  const SEV = {
    critical: { label: "Crítico", color: "--critical", path: "M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13z", glyph: "!" },
    serious:  { label: "Alto",    color: "--serious",  path: "M8 1.8l6.6 11.7H1.4z", glyph: "!" },
    warning:  { label: "Atenção", color: "--warning",  path: "M8 1.2l6.8 6.8L8 14.8 1.2 8z", glyph: "!" },
    good:     { label: "Positivo",color: "--good",     path: "M8 1.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13z", glyph: "✓" },
  };
  function sevIcon(sev, size = 16) {
    const s = SEV[sev];
    const NS = "http://www.w3.org/2000/svg";
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", size); svg.setAttribute("height", size); svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("aria-hidden", "true");
    const p = document.createElementNS(NS, "path");
    p.setAttribute("d", s.path); p.setAttribute("fill", css(s.color));
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", 8); t.setAttribute("y", sev === "serious" ? 12.6 : 11.6);
    t.setAttribute("text-anchor", "middle"); t.setAttribute("font-size", sev === "good" ? 9 : 10);
    t.setAttribute("font-weight", 700);
    t.setAttribute("fill", sev === "warning" ? "#0b0b0b" : "#ffffff");
    t.textContent = s.glyph;
    svg.append(p, t);
    return svg;
  }
  const h = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };

  // ---- estado + URL --------------------------------------------------------
  const qs = new URLSearchParams(location.search);
  const state = { periodo: qs.get("periodo") || "12m", regiao: qs.get("regiao") || "todas", segmento: qs.get("segmento") || "todos" };
  let payload = null, reqId = 0;

  async function carregar() {
    const id = ++reqId;
    const main = $("#conteudo");
    if (payload) main.classList.add("carregando");   // mantém o quadro anterior
    main.setAttribute("aria-busy", "true");
    history.replaceState(null, "", `?${new URLSearchParams(state)}`);
    try {
      const r = await fetch(`/api/painel?${new URLSearchParams(state)}`);
      const j = await r.json();
      if (id !== reqId) return;
      if (!r.ok) throw new Error(j.erro || r.statusText);
      payload = j;
      $("#erro").hidden = true;
      render();
    } catch (e) {
      const box = $("#erro");
      box.textContent = `Não foi possível carregar os dados: ${e.message}`;
      box.hidden = false;
    } finally {
      if (id === reqId) { main.classList.remove("carregando"); main.setAttribute("aria-busy", "false"); }
    }
  }

  function montarFiltros(f) {
    const seg = $("#f-periodo");
    if (!seg.children.length) {
      f.periodos.forEach((p) => {
        const b = h("button", null, p.label);
        b.type = "button"; b.setAttribute("role", "radio"); b.dataset.id = p.id;
        b.addEventListener("click", () => { state.periodo = p.id; carregar(); });
        seg.appendChild(b);
      });
      const fill = (sel, items) => items.forEach((v) => { const o = h("option", null, v); o.value = v; sel.appendChild(o); });
      fill($("#f-regiao"), f.regioes);
      fill($("#f-segmento"), f.segmentos);
      $("#f-regiao").addEventListener("change", (e) => { state.regiao = e.target.value; carregar(); });
      $("#f-segmento").addEventListener("change", (e) => { state.segmento = e.target.value; carregar(); });
    }
    [...seg.children].forEach((b) => b.setAttribute("aria-checked", String(b.dataset.id === f.periodo)));
    $("#f-regiao").value = f.regiao;
    $("#f-segmento").value = f.segmento;
  }

  // ---- delta ---------------------------------------------------------------
  function deltaEl(k, curto) {
    const d = h("div", "delta");
    if (k.delta == null) { d.appendChild(h("span", null, "sem base comparável")); return d; }
    const neutro = k.delta_tipo === "pp" ? Math.abs(k.delta) < 0.0005 : Math.abs(k.delta) < 0.005;
    const bom = (k.delta > 0) === (k.bom_quando === "up");
    d.classList.add(neutro ? "neutro" : bom ? "bom" : "ruim");
    const s = h("strong", null, `${neutro ? "≈" : k.delta > 0 ? "▲" : "▼"} ${k.delta_tipo === "pp" ? F.pp(k.delta) : F.rel(k.delta)}`);
    d.append(s, h("span", null, curto));
    return d;
  }
  const compCurta = () => (payload.periodo.comparacao ? (payload.periodo.comparacao.startsWith("vs ano anterior") ? "vs ano anterior" : payload.periodo.comparacao) : "");

  // ---- hero (OTD) ----------------------------------------------------------
  function renderHero(k) {
    const el = $("#hero");
    el.replaceChildren();
    const rot = h("div", "rotulo", k.label);
    const info = h("span", "info", "i"); info.title = k.ajuda; rot.appendChild(info);
    const linha = h("div", "linha-valor");
    linha.append(h("div", "valor", fmt("pct", k.valor)), deltaEl(k, compCurta()));

    const gap = k.valor - k.meta;
    const sev = gap >= 0 ? "good" : gap >= -0.05 ? "warning" : "critical";
    const fillColor = gap >= 0 ? css("--series-1") : css(SEV[sev].color);
    const pill = h("span", "status-pill");
    pill.append(sevIcon(sev, 14), document.createTextNode(gap >= 0 ? "Na meta" : `${F.pp(gap).replace("−", "")} abaixo da meta`));

    // meter: escala 50–100% para dar leitura à distância da meta
    const lo = 0.5, pos = (v) => `${Math.max(0, Math.min(1, (v - lo) / (1 - lo))) * 100}%`;
    const meter = h("div", "meter");
    meter.setAttribute("role", "meter");
    meter.setAttribute("aria-valuemin", "0"); meter.setAttribute("aria-valuemax", "100");
    meter.setAttribute("aria-valuenow", (k.valor * 100).toFixed(1));
    meter.setAttribute("aria-label", `OTD ${fmt("pct", k.valor)}, meta ${F.pct0(k.meta)}`);
    const fill = h("div", "fill"); fill.style.width = pos(k.valor); fill.style.background = fillColor;
    const alvo = h("div", "alvo"); alvo.style.left = `calc(${pos(k.meta)} - 1px)`;
    alvo.appendChild(h("span", null, `Meta ${F.pct0(k.meta)}`));
    meter.style.background = `color-mix(in srgb, ${fillColor} 24%, ${css("--surface-1")})`;
    meter.append(fill, alvo);
    const escala = h("div", "meter-escala");
    escala.append(h("span", null, "50%"), h("span", null, "75%"), h("span", null, "100%"));

    // pior mês na janela
    const pts = k.spark.filter((p) => p.v != null);
    const pior = pts.reduce((a, b) => (b.v < a.v ? b : a), pts[0]);
    const melhor = pts.reduce((a, b) => (b.v > a.v ? b : a), pts[0]);
    const rod = h("p", "rodape-hero");
    const algumNaMeta = pts.some((p) => p.v >= k.meta);
    rod.textContent = pts.length > 1
      ? `Melhor mês: ${melhor.mes} (${fmt("pct", melhor.v)}). Pior mês: ${pior.mes} (${fmt("pct", pior.v)}).${algumNaMeta ? "" : ` Nenhum mês atingiu a meta de ${F.pct0(k.meta)}.`}`
      : k.ajuda;

    el.append(rot, linha, pill, meter, escala, rod);
  }

  // ---- KPI tiles -----------------------------------------------------------
  function renderKpis(kpis) {
    const box = $("#kpis");
    box.replaceChildren();
    for (const k of kpis) {
      const t = h("article", "card tile");
      const rot = h("div", "rotulo", k.label);
      const info = h("span", "info", "i"); info.title = k.ajuda; rot.appendChild(info);
      const valor = h("div", "valor", fmt(k.fmt, k.valor));
      valor.title = k.fmt === "brl_compacto" ? F.brl(k.valor) : "";
      const rod = h("div", "rodape-tile");
      rod.append(deltaEl(k, compCurta()), Charts.sparkline(k.spark.map((p) => p.v)));
      t.append(rot, valor, rod);
      box.appendChild(t);
    }
  }

  // ---- insights ------------------------------------------------------------
  function renderInsights(list) {
    const box = $("#insights");
    box.replaceChildren();
    for (const i of list) {
      const c = h("article", "card insight");
      const sev = h("span", "sev");
      sev.append(sevIcon(i.sev, 14), document.createTextNode(SEV[i.sev].label));
      c.append(sev, h("h3", null, i.titulo), h("p", null, i.texto));
      if (i.acao) {
        const a = h("div", "acao");
        a.append(h("b", null, "Ação →"), h("span", null, i.acao));
        c.appendChild(a);
      }
      box.appendChild(c);
    }
  }

  // ---- cartões de gráfico --------------------------------------------------
  const card = (id) => $(`[data-chart="${id}"]`);
  function setSub(id, s) { card(id).querySelector("[data-sub]").textContent = s; }
  function setTable(id, cols, rows) { Charts.table(card(id).querySelector("[data-table]"), cols, rows); }
  function legend(id, items) {
    const box = card(id).querySelector("[data-legend]");
    box.replaceChildren();
    for (const it of items) {
      const s = h("span");
      const sw = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      sw.setAttribute("width", 12); sw.setAttribute("height", 12); sw.setAttribute("aria-hidden", "true");
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", 6); c.setAttribute("cy", 6); c.setAttribute("r", 5); c.setAttribute("fill", it.color);
      sw.appendChild(c);
      s.append(sw, document.createTextNode(it.label));
      box.appendChild(s);
    }
  }

  // segmento → slot fixo (a cor segue a entidade, nunca o ranking)
  const SEG_SLOT = { "Atacado": 1, "Indústria": 2, "Varejo": 3, "Farma": 4, "E-commerce": 5 };
  const segColor = (s) => css(`--series-${SEG_SLOT[s] || 1}`);
  const segOn = (s) => (SEG_SLOT[s] === 4 ? css("--on-fill-yellow") : css("--on-fill"));

  function renderCharts() {
    const p = payload;
    const serie = p.serie_mensal;
    const temCtx = serie.some((d) => !d.na_janela);
    const accent = css("--series-1"), deemph = css("--deemph");

    // Receita mensal
    const totRec = p.kpis.find((k) => k.id === "receita");
    const picoRec = serie.reduce((a, b) => (b.receita > a.receita ? b : a), serie[0]);
    setSub("receita", `${fmt("brl_compacto", totRec.valor)} no período. Pico em ${picoRec.mes} (${fmt("brl_compacto", picoRec.receita)}).${temCtx ? " Meses fora do período em cinza, como contexto." : ""}`);
    Charts.columns(card("receita").querySelector("[data-plot]"), {
      data: serie, x: (d) => d.mes, y: (d) => d.receita || 0,
      color: (d) => (d.na_janela ? accent : deemph),
      fmtAxis: (v) => (v === 0 ? "0" : F.compacto(v)), fmtLabel: F.brl_compacto,
      labelAt: (data) => [data.length - 1, data.indexOf(picoRec)],
      ariaLabel: "Receita de mercadorias por mês",
      tip: (d) => ({ title: d.mes + (d.na_janela ? "" : " · fora do período"), rows: [
        { key: "Receita", value: fmt("brl", d.receita), color: d.na_janela ? accent : deemph },
        { key: "Pedidos", value: fmt("int", d.pedidos) },
        { key: "Ticket médio", value: fmt("brl", d.ticket) },
      ] }),
    });
    setTable("receita", [
      { key: "mes", label: "Mês" },
      { key: "receita", label: "Receita", num: true, fmt: (v) => fmt("brl", v) },
      { key: "pedidos", label: "Pedidos", num: true, fmt: (v) => fmt("int", v) },
      { key: "ticket", label: "Ticket médio", num: true, fmt: (v) => fmt("brl", v) },
      { key: "na_janela", label: "No período", fmt: (v) => (v ? "Sim" : "Não") },
    ], serie);

    // OTD mensal
    const naMeta = serie.filter((d) => d.na_janela && d.otd >= p.meta_otd).length;
    const janela = serie.filter((d) => d.na_janela);
    const minOtd = serie.reduce((a, b) => (b.otd < a.otd ? b : a), serie[0]);
    setSub("otd", `${naMeta} de ${janela.length} ${janela.length === 1 ? "mês" : "meses"} na meta de ${F.pct0(p.meta_otd)}. Vale em ${minOtd.mes}: ${fmt("pct", minOtd.otd)}.`);
    Charts.line(card("otd").querySelector("[data-plot]"), {
      data: serie.filter((d) => d.otd != null), x: (d) => d.mes, y: (d) => d.otd, emph: (d) => d.na_janela,
      ref: { value: p.meta_otd, label: `Meta ${F.pct0(p.meta_otd)}` }, ceil: 1, labelMin: true,
      fmtAxis: F.pct0, fmtLabel: F.pct, ariaLabel: "Percentual de entregas no prazo por mês, com meta de 95%",
      tip: (d) => ({ title: d.mes, rows: [
        { key: "No prazo", value: fmt("pct", d.otd), color: d.na_janela ? accent : deemph },
        { key: "vs meta", value: F.pp(d.otd - p.meta_otd) },
        { key: "Entregas", value: fmt("int", d.entregas) },
        { key: "Nota média", value: fmt("nota", d.nota) },
      ] }),
    });
    setTable("otd", [
      { key: "mes", label: "Mês" },
      { key: "otd", label: "No prazo", num: true, fmt: (v) => fmt("pct", v) },
      { key: "otd_meta", label: "vs meta", num: true, render: (r) => (r.otd == null ? "—" : F.pp(r.otd - p.meta_otd)) },
      { key: "entregas", label: "Entregas", num: true, fmt: (v) => fmt("int", v) },
      { key: "nota", label: "Nota média", num: true, fmt: (v) => fmt("nota", v) },
    ], serie);

    // SLA × entregue
    const tr = p.transportadoras;
    const abaixo = tr.filter((t) => t.gap < 0).length;
    setSub("sla", tr.length ? `${abaixo} de ${tr.length} ${tr.length === 1 ? "transportadora" : "transportadoras"} abaixo do SLA. À direita, a distância entre o entregue e o contratado.` : "Sem entregas suficientes no recorte.");
    legend("sla", [{ label: "SLA contratado", color: css("--seq-250") }, { label: "Entregue no prazo (OTD)", color: accent }]);
    const plotSla = card("sla").querySelector("[data-plot]");
    if (tr.length) {
      Charts.dumbbell(plotSla, {
        data: tr, label: (d) => d.nome, a: (d) => d.sla, b: (d) => d.otd,
        fmtGap: F.pp, fmtAxis: F.pct0, ref: { value: p.meta_otd, label: `Meta ${F.pct0(p.meta_otd)}` },
        ariaLabel: "SLA contratado versus percentual entregue no prazo por transportadora",
        tip: (d) => ({ title: `${d.nome} · ${d.modal}`, rows: [
          { key: "Entregue no prazo", value: fmt("pct", d.otd), color: accent },
          { key: "SLA contratado", value: fmt("pct", d.sla), color: css("--seq-250") },
          { key: "Gap", value: F.pp(d.gap) },
          { key: "Entregas", value: fmt("int", d.entregas) },
        ] }),
      });
    } else plotSla.replaceChildren();
    setTable("sla", [
      { key: "nome", label: "Transportadora" },
      { key: "sla", label: "SLA", num: true, fmt: (v) => fmt("pct", v) },
      { key: "otd", label: "Entregue", num: true, fmt: (v) => fmt("pct", v) },
      { key: "gap", label: "Gap", num: true, fmt: (v) => (v == null ? "—" : F.pp(v)) },
      { key: "entregas", label: "Entregas", num: true, fmt: (v) => fmt("int", v) },
    ], tr);

    // Motivos de atraso
    const mot = p.motivos;
    const top3 = mot.slice(0, 3).reduce((a, b) => a + b.pct, 0);
    setSub("motivos", mot.length ? `% das entregas atrasadas, por causa. As 3 primeiras concentram ${F.pct0(top3)}.` : "Sem atrasos no recorte.");
    const plotMot = card("motivos").querySelector("[data-plot]");
    if (mot.length) Charts.hbars(plotMot, {
      data: mot, label: (d) => d.motivo, value: (d) => d.pct, fmt: F.pct0, rowH: 30,
      ariaLabel: "Participação de cada motivo no total de atrasos",
      tip: (d) => ({ title: d.motivo, rows: [{ key: "Participação", value: fmt("pct", d.pct), color: accent }, { key: "Ocorrências", value: fmt("int", d.qtd) }] }),
    }); else plotMot.replaceChildren();
    setTable("motivos", [
      { key: "motivo", label: "Motivo" },
      { key: "qtd", label: "Ocorrências", num: true, fmt: (v) => fmt("int", v) },
      { key: "pct", label: "Participação", num: true, fmt: (v) => fmt("pct", v) },
    ], mot);

    // Regiões
    const otdGeral = p.hero.valor;
    setSub("regioes", `Linha vertical = média do recorte (${fmt("pct", otdGeral)}).`);
    Charts.hbars(card("regioes").querySelector("[data-plot]"), {
      data: p.regioes, label: (d) => d.regiao, value: (d) => d.otd, fmt: F.pct, max: 1, rowH: 34,
      ref: { value: otdGeral, label: "Média" },
      ariaLabel: "Percentual de entregas no prazo por região",
      tip: (d) => ({ title: d.regiao, rows: [
        { key: "No prazo", value: fmt("pct", d.otd), color: accent },
        { key: "vs média", value: F.pp(d.otd - otdGeral) },
        { key: "Custo por entrega", value: fmt("brl", d.custo_entrega) },
        { key: "Frete/receita", value: fmt("pct", d.frete_receita) },
        { key: "Entregas", value: fmt("int", d.entregas) },
      ] }),
    });
    setTable("regioes", [
      { key: "regiao", label: "Região" },
      { key: "otd", label: "No prazo", num: true, fmt: (v) => fmt("pct", v) },
      { key: "custo_entrega", label: "Custo/entrega", num: true, fmt: (v) => fmt("brl", v) },
      { key: "frete_receita", label: "Frete/receita", num: true, fmt: (v) => fmt("pct", v) },
      { key: "entregas", label: "Entregas", num: true, fmt: (v) => fmt("int", v) },
    ], p.regioes);

    // Nota × atraso
    const npa = p.nota_por_atraso;
    setSub("nota", npa.length > 1 ? `De ${F.nota1(npa[0].nota)} no prazo para ${F.nota1(npa[npa.length - 1].nota)} com ${npa[npa.length - 1].faixa} de atraso (escala 1–5).` : "Poucas avaliações no recorte.");
    const plotNota = card("nota").querySelector("[data-plot]");
    if (npa.length) Charts.columns(plotNota, {
      data: npa, x: (d) => d.faixa, y: (d) => d.nota, color: () => accent, height: 230,
      fmtAxis: (v) => F.nota1(v).replace(",0", ""), fmtLabel: F.nota1,
      labelAt: (data) => data.map((_, i) => i),   // 6 colunas: valor no topo de cada uma
      ariaLabel: "Nota média do cliente por faixa de dias de atraso",
      tip: (d) => ({ title: d.faixa, rows: [{ key: "Nota média", value: fmt("nota", d.nota), color: accent }, { key: "Avaliações", value: fmt("int", d.respostas) }] }),
    }); else plotNota.replaceChildren();
    setTable("nota", [
      { key: "faixa", label: "Atraso" },
      { key: "nota", label: "Nota média", num: true, fmt: (v) => fmt("nota", v) },
      { key: "respostas", label: "Avaliações", num: true, fmt: (v) => fmt("int", v) },
    ], npa);

    // Segmentos (barra segmentada alta + lista com frete/receita)
    const segs = [...p.segmentos].sort((a, b) => (SEG_SLOT[a.segmento] || 9) - (SEG_SLOT[b.segmento] || 9));
    const top2 = [...p.segmentos].slice(0, 2);
    setSub("segmentos", top2.length === 2 ? `${top2[0].segmento} e ${top2[1].segmento} somam ${F.pct0(top2[0].pct + top2[1].pct)} da receita.` : "");
    const plotSeg = card("segmentos").querySelector("[data-plot]");
    Charts.segmentedBar(plotSeg, {
      data: segs, label: (d) => d.segmento, share: (d) => d.pct, color: (d) => segColor(d.segmento), onColor: (d) => segOn(d.segmento),
      fmtPct: F.pct0,
      tip: (d) => ({ title: d.segmento, rows: [
        { key: "Receita", value: fmt("brl", d.receita), color: segColor(d.segmento) },
        { key: "Participação", value: fmt("pct", d.pct) },
        { key: "Frete/receita", value: fmt("pct", d.frete_receita) },
        { key: "Ticket médio", value: fmt("brl", d.ticket) },
      ] }),
    });
    const cab = h("div", "seg-cab");
    cab.append(h("span"), h("span", null, "Segmento"), h("span", null, "Receita"), h("span", null, "Frete/receita"));
    const ul = h("ul", "seg-lista");
    for (const s of segs) {
      const li = h("li");
      const sw = h("span", "sw"); sw.style.background = segColor(s.segmento);
      const rec = h("span", "num"); rec.appendChild(h("strong", null, fmt("brl_compacto", s.receita)));
      li.append(sw, h("span", null, s.segmento), rec, h("span", "num", fmt("pct", s.frete_receita)));
      ul.appendChild(li);
    }
    plotSeg.append(cab, ul);
    setTable("segmentos", [
      { key: "segmento", label: "Segmento" },
      { key: "receita", label: "Receita", num: true, fmt: (v) => fmt("brl", v) },
      { key: "pct", label: "Participação", num: true, fmt: (v) => fmt("pct", v) },
      { key: "frete_receita", label: "Frete/receita", num: true, fmt: (v) => fmt("pct", v) },
      { key: "ticket", label: "Ticket médio", num: true, fmt: (v) => fmt("brl", v) },
    ], segs);

    // CDs
    const cds = p.cds;
    if (cds.length) {
      const med = cds.reduce((a, c) => a + c.lead_h * c.pedidos, 0) / cds.reduce((a, c) => a + c.pedidos, 0);
      setSub("cds", `Horas entre o pedido e o despacho. Linha = média ponderada (${F.h(med)}).`);
      Charts.hbars(card("cds").querySelector("[data-plot]"), {
        data: cds, label: (d) => d.cd, value: (d) => d.lead_h, fmt: F.h, rowH: 30,
        ref: { value: med, label: "Média" },
        ariaLabel: "Tempo médio de expedição por centro de distribuição",
        tip: (d) => ({ title: d.cd, rows: [
          { key: "Expedição", value: F.h(d.lead_h), color: accent },
          { key: "No prazo", value: fmt("pct", d.otd) },
          { key: "Pedidos despachados", value: fmt("int", d.pedidos) },
        ] }),
      });
    } else { setSub("cds", ""); card("cds").querySelector("[data-plot]").replaceChildren(); }
    setTable("cds", [
      { key: "cd", label: "CD" },
      { key: "lead_h", label: "Expedição", num: true, fmt: (v) => (v == null ? "—" : F.h(v)) },
      { key: "otd", label: "No prazo", num: true, fmt: (v) => fmt("pct", v) },
      { key: "pedidos", label: "Pedidos", num: true, fmt: (v) => fmt("int", v) },
    ], cds);

    // Scorecard
    Charts.table($("#scorecard"), [
      { key: "nome", label: "Transportadora", render: (r) => {
        const d = h("div", "nome-cell");
        d.append(h("span", null, r.nome), h("small", null, r.modal));
        return d;
      } },
      { key: "entregas", label: "Entregas", num: true, fmt: (v) => fmt("int", v) },
      { key: "participacao", label: "Volume", num: true, fmt: (v) => fmt("pct", v) },
      { key: "sla", label: "SLA", num: true, fmt: (v) => F.pct0(v) },
      { key: "otd", label: "OTD", num: true, fmt: (v) => fmt("pct", v) },
      { key: "gap", label: "Gap", num: true, render: (r) => {
        const s = h("span", "gap-cell");
        const sev = r.gap >= 0 ? "good" : r.gap >= -0.05 ? "warning" : r.gap >= -0.1 ? "serious" : "critical";
        const ic = sevIcon(sev, 13);
        ic.setAttribute("role", "img"); ic.setAttribute("aria-label", SEV[sev].label); ic.removeAttribute("aria-hidden");
        s.append(ic, document.createTextNode(F.pp(r.gap)));
        return s;
      } },
      { key: "custo_medio", label: "Custo médio", num: true, fmt: (v) => fmt("brl", v) },
      { key: "avaria", label: "Avaria", num: true, fmt: (v) => fmt("pct", v) },
      { key: "nota", label: "Nota", num: true, fmt: (v) => fmt("nota", v) },
    ], tr, { sortable: true, initialSort: { key: "gap", dir: "asc" } });
  }

  function render() {
    const p = payload;
    montarFiltros(p.filtros);
    $("#meta-dados").textContent = `Dados até ${p.periodo.dados_ate} · atualizado ${p.periodo.atualizado_em}`;
    $("#contexto-periodo").textContent = `${p.periodo.intervalo}${p.periodo.comparacao ? ` · variações ${p.periodo.comparacao}` : ""}`;
    renderHero(p.hero);
    renderKpis(p.kpis);
    renderInsights(p.insights);
    renderCharts();
  }

  // ---- alternância de tabela -----------------------------------------------
  document.addEventListener("click", (e) => {
    const b = e.target.closest(".btn-tabela");
    if (!b) return;
    const fig = b.closest("figure");
    const on = b.getAttribute("aria-pressed") !== "true";
    b.setAttribute("aria-pressed", String(on));
    fig.querySelector("[data-table]").hidden = !on;
    fig.querySelector("[data-plot]").hidden = on;
    const lg = fig.querySelector("[data-legend]"); if (lg) lg.hidden = on;
  });

  // ---- tema ----------------------------------------------------------------
  $("#btn-tema").addEventListener("click", () => {
    const atual = root().dataset.theme || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    const novo = atual === "dark" ? "light" : "dark";
    root().dataset.theme = novo;
    try { localStorage.setItem("tema", novo); } catch (e) { /* armazenamento indisponível */ }
    if (payload) render();
  });
  function root() { return document.documentElement; }
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => payload && render());

  // ---- redimensionamento ---------------------------------------------------
  let rt, lastW = 0;
  new ResizeObserver(([e]) => {
    const w = Math.round(e.contentRect.width);
    if (!payload || w === lastW) return;
    lastW = w;
    clearTimeout(rt);
    rt = setTimeout(() => { Charts.hideTip(); renderCharts(); }, 120);
  }).observe($("#conteudo"));

  carregar();
})();

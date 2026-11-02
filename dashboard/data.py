"""Camada de dados do painel: carrega a base de logística do Supabase e calcula
KPIs, séries, rankings e insights para um recorte (período × região × segmento).

A base tem ~30 mil pedidos, então carregamos uma tabela-fato (pedido + entrega +
dimensões) uma vez, guardamos em memória com TTL e agregamos com pandas. Cada
requisição de filtro responde em milissegundos, sem ida ao banco.
"""

from __future__ import annotations

import math
import os
import threading
import time
from dataclasses import dataclass

import pandas as pd
import psycopg

META_OTD = 0.95          # meta corporativa de entregas no prazo
CACHE_TTL_S = 600        # 10 min

FACT_SQL = """
select
    p.id                        as pedido_id,
    p.data_pedido,
    p.canal,
    p.prioridade,
    p.valor_mercadoria,
    p.peso_kg,
    p.status,
    c.segmento,
    c.regiao,
    cd.nome                     as cd,
    t.nome                      as transportadora,
    t.modal,
    t.sla_contratado_pct,
    e.data_despacho,
    e.custo_frete,
    e.status_entrega,
    e.no_prazo,
    e.dias_atraso,
    e.motivo_atraso,
    e.avaria,
    e.nota_cliente
from public.pedidos p
join public.clientes c              on c.id  = p.cliente_id
join public.centros_distribuicao cd on cd.id = p.cd_id
left join public.entregas e         on e.pedido_id = p.id
left join public.transportadoras t  on t.id  = e.transportadora_id
"""

MESES_PT = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]

PERIODOS = {
    "1m":  "Último mês",
    "3m":  "Últimos 3 meses",
    "ytd": "Ano até a data",
    "12m": "Últimos 12 meses",
    "all": "Todo o histórico",
}


# --------------------------------------------------------------------------- #
# Carga + cache
# --------------------------------------------------------------------------- #

class Store:
    def __init__(self) -> None:
        self._df: pd.DataFrame | None = None
        self._loaded_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> tuple[pd.DataFrame, float]:
        with self._lock:
            if self._df is None or time.time() - self._loaded_at > CACHE_TTL_S:
                self._df = _preparar(_carregar())
                self._loaded_at = time.time()
            return self._df, self._loaded_at


def _carregar() -> pd.DataFrame:
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        raise RuntimeError("Defina SUPABASE_DB_URL no .env (veja .env.example).")
    with psycopg.connect(url, connect_timeout=15) as conn, conn.cursor() as cur:
        cur.execute(FACT_SQL)
        cols = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=cols)


def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    for c in ("valor_mercadoria", "peso_kg", "sla_contratado_pct", "custo_frete"):
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    df["nota_cliente"] = pd.to_numeric(df["nota_cliente"], errors="coerce").astype(float)
    df["dias_atraso"] = pd.to_numeric(df["dias_atraso"], errors="coerce").astype(float)
    df["data_pedido"] = pd.to_datetime(df["data_pedido"])
    df["data_despacho"] = pd.to_datetime(df["data_despacho"])

    df["mes_idx"] = df["data_pedido"].dt.year * 12 + df["data_pedido"].dt.month - 1
    df["ativo"] = df["status"] != "Cancelado"
    df["tem_entrega"] = df["status_entrega"].notna()
    # OTD só sobre entregas finalizadas; devolução conta como fora do prazo
    df["finalizada"] = df["status_entrega"].isin(["Entregue", "Devolvido"])
    df["no_prazo_ok"] = df["no_prazo"].astype("boolean").fillna(False).astype(bool) & df["finalizada"]
    df["avaria"] = df["avaria"].astype("boolean").fillna(False).astype(bool)
    df["atrasada"] = df["finalizada"] & ~df["no_prazo_ok"]
    df["lead_h"] = (df["data_despacho"] - df["data_pedido"]).dt.total_seconds() / 3600
    m, d = df["data_pedido"].dt.month, df["data_pedido"].dt.day
    df["pico"] = ((m == 11) & (d >= 20)) | ((m == 12) & (d <= 22))
    return df


STORE = Store()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _mes_label(idx: int, com_ano: bool = True) -> str:
    ano, mes = divmod(idx, 12)
    return f"{MESES_PT[mes]}/{str(ano)[2:]}" if com_ano else MESES_PT[mes]


def _num(x) -> float | None:
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else x


def _safe_div(a, b):
    return a / b if b else float("nan")


def metricas(d: pd.DataFrame) -> dict[str, float | None]:
    ativos = d[d["ativo"]]
    ent = d[d["tem_entrega"]]
    fin = d[d["finalizada"]]
    receita = ativos["valor_mercadoria"].sum()
    frete = ent["custo_frete"].sum()
    return {k: _num(v) for k, v in {
        "receita": receita,
        "pedidos": len(ativos),
        "otd": fin["no_prazo_ok"].mean() if len(fin) else float("nan"),
        "frete_receita": _safe_div(frete, receita),
        "custo_entrega": _safe_div(frete, len(ent)),
        "nota": ent["nota_cliente"].mean(),
        "avaria": ent["avaria"].mean() if len(ent) else float("nan"),
        "ticket": _safe_div(receita, len(ativos)),
        "entregas": len(fin),
    }.items()}


@dataclass
class Janela:
    inicio: int          # mes_idx inclusivo
    fim: int             # mes_idx inclusivo
    meses_dados: list[int]

    @property
    def meses(self) -> list[int]:
        return [m for m in range(self.inicio, self.fim + 1) if m in self.meses_dados]


def _janela(df: pd.DataFrame, periodo: str) -> Janela:
    disponiveis = sorted(df["mes_idx"].unique().tolist())
    ultimo_dia = df["data_pedido"].max()
    fim = disponiveis[-1]
    # mês corrente incompleto fica de fora: comparamos sempre meses fechados
    if (ultimo_dia + pd.Timedelta(days=1)).month == ultimo_dia.month:
        fim -= 1
    disponiveis = [m for m in disponiveis if m <= fim]
    n = {"1m": 1, "3m": 3, "12m": 12}.get(periodo)
    if n:
        inicio = fim - n + 1
    elif periodo == "ytd":
        inicio = (fim // 12) * 12
    else:
        inicio = disponiveis[0]
    return Janela(max(inicio, disponiveis[0]), fim, disponiveis)


# --------------------------------------------------------------------------- #
# Montagem do payload
# --------------------------------------------------------------------------- #

def painel(periodo: str = "12m", regiao: str = "todas", segmento: str = "todos") -> dict:
    base, carregado_em = STORE.get()
    if periodo not in PERIODOS:
        periodo = "12m"

    janela = _janela(base, periodo)
    df = base
    if regiao != "todas":
        df = df[df["regiao"] == regiao]
    if segmento != "todos":
        df = df[df["segmento"] == segmento]

    meses = janela.meses
    cur = df[df["mes_idx"].isin(meses)]

    # Comparação ano contra ano, só sobre meses que têm base no ano anterior
    comparaveis = [m for m in meses if (m - 12) in janela.meses_dados]
    if comparaveis:
        m_cur = metricas(df[df["mes_idx"].isin(comparaveis)])
        m_prev = metricas(df[df["mes_idx"].isin([m - 12 for m in comparaveis])])
        if len(comparaveis) == len(meses):
            comp_label = f"vs mesmo período de {(meses[0] - 12) // 12}" if len(meses) > 1 \
                else f"vs {_mes_label(meses[0] - 12)}"
        else:
            comp_label = f"vs ano anterior · base comparável de {len(comparaveis)} meses"
    else:
        m_cur = m_prev = None
        comp_label = None

    # Série mensal de contexto: no mínimo 12 meses, com a janela em destaque
    ctx_inicio = max(janela.meses_dados[0], min(meses[0], janela.fim - 11))
    ctx_meses = [m for m in range(ctx_inicio, janela.fim + 1) if m in janela.meses_dados]
    serie = []
    for m in ctx_meses:
        mm = metricas(df[df["mes_idx"] == m])
        serie.append({"mes": _mes_label(m), "na_janela": m in meses, **mm})

    atual = metricas(cur)

    def delta(k: str):
        if not m_cur or m_cur.get(k) is None or m_prev.get(k) in (None, 0):
            return None
        if k in ("otd", "frete_receita", "avaria"):
            return _num(m_cur[k] - m_prev[k])                # diferença em p.p. (fração)
        return _num(m_cur[k] / m_prev[k] - 1)                # variação relativa

    spark_meses = meses if len(meses) >= 4 else ctx_meses
    spark = {m: metricas(df[df["mes_idx"] == m]) for m in spark_meses}

    def kpi(k, label, fmt, bom, ajuda):
        return {
            "id": k, "label": label, "valor": atual[k], "fmt": fmt, "bom_quando": bom,
            "delta": delta(k), "delta_tipo": "pp" if k in ("otd", "frete_receita", "avaria") else "rel",
            "ajuda": ajuda,
            "spark": [{"mes": _mes_label(m), "v": spark[m][k], "na_janela": m in meses} for m in spark_meses],
        }

    kpis = [
        kpi("receita", "Receita de mercadorias", "brl_compacto", "up", "Valor dos pedidos não cancelados"),
        kpi("pedidos", "Pedidos", "int", "up", "Pedidos não cancelados"),
        kpi("frete_receita", "Frete sobre receita", "pct", "down", "Custo de frete ÷ receita"),
        kpi("custo_entrega", "Custo médio por entrega", "brl", "down", "Frete total ÷ entregas despachadas"),
        kpi("nota", "Nota média do cliente", "nota", "up", "Escala de 1 a 5, pesquisas respondidas"),
        kpi("avaria", "Taxa de avaria", "pct", "down", "Entregas com avaria ÷ despachadas"),
    ]
    hero = kpi("otd", "Entregas no prazo (OTD)", "pct", "up",
               "Entregas finalizadas dentro da data prometida; devoluções contam como fora do prazo")
    hero["meta"] = META_OTD

    return {
        "filtros": {
            "periodo": periodo, "regiao": regiao, "segmento": segmento,
            "periodos": [{"id": k, "label": v} for k, v in PERIODOS.items()],
            "regioes": sorted(base["regiao"].unique().tolist()),
            "segmentos": sorted(base["segmento"].unique().tolist()),
        },
        "periodo": {
            "label": PERIODOS[periodo],
            "intervalo": f"{_mes_label(meses[0])} – {_mes_label(meses[-1])}" if len(meses) > 1 else _mes_label(meses[0]),
            "comparacao": comp_label,
            "atualizado_em": pd.Timestamp(carregado_em, unit="s").tz_localize("UTC")
                               .tz_convert("America/Sao_Paulo").strftime("%d/%m/%Y %H:%M"),
            "dados_ate": base["data_pedido"].max().strftime("%d/%m/%Y"),
        },
        "hero": hero,
        "kpis": kpis,
        "serie_mensal": serie,
        "transportadoras": _transportadoras(cur),
        "motivos": _motivos(cur),
        "regioes": _regioes(cur, atual),
        "nota_por_atraso": _nota_por_atraso(cur),
        "segmentos": _segmentos(cur),
        "cds": _cds(cur),
        "insights": _insights(cur, atual),
        "meta_otd": META_OTD,
    }


# --------------------------------------------------------------------------- #
# Blocos analíticos
# --------------------------------------------------------------------------- #

def _transportadoras(cur: pd.DataFrame) -> list[dict]:
    ent = cur[cur["tem_entrega"]]
    out = []
    for nome, g in ent.groupby("transportadora"):
        fin = g[g["finalizada"]]
        if len(fin) < 30:
            continue
        otd = fin["no_prazo_ok"].mean()
        sla = g["sla_contratado_pct"].iloc[0] / 100
        out.append({
            "nome": nome, "modal": g["modal"].iloc[0], "entregas": int(len(g)),
            "participacao": len(g) / len(ent),
            "sla": _num(sla), "otd": _num(otd), "gap": _num(otd - sla),
            "custo_medio": _num(g["custo_frete"].mean()),
            "avaria": _num(g["avaria"].mean()), "nota": _num(g["nota_cliente"].mean()),
        })
    return sorted(out, key=lambda r: r["gap"])


def _motivos(cur: pd.DataFrame) -> list[dict]:
    atr = cur[cur["atrasada"] & cur["motivo_atraso"].notna()]
    tot = len(atr)
    vc = atr["motivo_atraso"].value_counts()
    return [{"motivo": k, "qtd": int(v), "pct": float(v / tot)} for k, v in vc.items()] if tot else []


def _regioes(cur: pd.DataFrame, atual: dict) -> list[dict]:
    out = []
    for reg, g in cur.groupby("regiao"):
        m = metricas(g)
        out.append({"regiao": reg, "otd": m["otd"], "entregas": int(m["entregas"] or 0),
                    "frete_receita": m["frete_receita"], "custo_entrega": m["custo_entrega"],
                    "nota": m["nota"]})
    return sorted([r for r in out if r["otd"] is not None], key=lambda r: r["otd"], reverse=True)


def _nota_por_atraso(cur: pd.DataFrame) -> list[dict]:
    ent = cur[(cur["status_entrega"] == "Entregue") & cur["nota_cliente"].notna()]
    faixas = [("No prazo", 0, 0), ("1 dia", 1, 1), ("2 dias", 2, 2), ("3 dias", 3, 3),
              ("4–5 dias", 4, 5), ("6+ dias", 6, 999)]
    out = []
    for label, lo, hi in faixas:
        g = ent[(ent["dias_atraso"] >= lo) & (ent["dias_atraso"] <= hi)]
        if len(g) >= 10:
            out.append({"faixa": label, "nota": _num(g["nota_cliente"].mean()), "respostas": int(len(g))})
    return out


def _segmentos(cur: pd.DataFrame) -> list[dict]:
    at = cur[cur["ativo"]]
    tot = at["valor_mercadoria"].sum()
    out = []
    for seg, g in cur.groupby("segmento"):
        m = metricas(g)
        out.append({"segmento": seg, "receita": m["receita"], "pct": _num(_safe_div(m["receita"] or 0, tot)),
                    "frete_receita": m["frete_receita"], "pedidos": int(m["pedidos"] or 0),
                    "ticket": m["ticket"]})
    return sorted(out, key=lambda r: r["receita"] or 0, reverse=True)


def _cds(cur: pd.DataFrame) -> list[dict]:
    ent = cur[cur["tem_entrega"]]
    out = []
    for cd, g in ent.groupby("cd"):
        fin = g[g["finalizada"]]
        out.append({"cd": cd, "lead_h": _num(g["lead_h"].mean()), "pedidos": int(len(g)),
                    "otd": _num(fin["no_prazo_ok"].mean()) if len(fin) else None})
    return sorted(out, key=lambda r: r["lead_h"] or 0, reverse=True)


# --------------------------------------------------------------------------- #
# Insights — frases geradas a partir do recorte, ordenadas por severidade
# --------------------------------------------------------------------------- #

def _pct(x: float, casas: int = 1) -> str:
    return f"{x * 100:.{casas}f}%".replace(".", ",")


def _pp(x: float) -> str:
    return f"{x * 100:+.1f}".replace(".", ",").replace("-", "−") + " p.p."


def _dec(x: float, casas: int = 1) -> str:
    return f"{x:.{casas}f}".replace(".", ",")


def _int(x: float) -> str:
    return f"{int(round(x)):,}".replace(",", ".")


def _brl(x: float) -> str:
    return "R$ " + f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


SEV_ORDEM = {"critical": 0, "serious": 1, "warning": 2, "good": 3}


def _insights(cur: pd.DataFrame, atual: dict) -> list[dict]:
    ins: list[dict] = []
    fin = cur[cur["finalizada"]]
    if len(fin) < 50:
        return [{"sev": "warning", "titulo": "Amostra pequena",
                 "texto": "Há poucas entregas finalizadas neste recorte para conclusões confiáveis. Amplie o período ou remova filtros."}]

    otd = atual["otd"] or 0

    # 1. Transportadoras abaixo do SLA contratado
    tr = _transportadoras(cur)
    abaixo = [t for t in tr if t["gap"] < 0]
    if tr:
        pior = tr[0]
        vol_abaixo = sum(t["entregas"] for t in abaixo) / max(1, sum(t["entregas"] for t in tr))
        if pior["gap"] < -0.02:
            ins.append({
                "sev": "critical" if pior["gap"] <= -0.08 else "serious",
                "titulo": f"{len(abaixo)} de {len(tr)} transportadoras entregam abaixo do SLA contratado",
                "texto": (f"{pior['nome']} cumpre {_pct(pior['otd'])} dos prazos contra {_pct(pior['sla'], 0)} "
                          f"contratados ({_pp(pior['gap'])}). As transportadoras abaixo do SLA carregam "
                          f"{_pct(vol_abaixo, 0)} do volume — o contrato não está sendo cobrado."),
                "acao": "Aplicar cláusulas de penalidade e rever a alocação de volume por desempenho.",
            })

    # 2. Alta temporada
    pico = fin[fin["pico"]]
    resto = fin[~fin["pico"]]
    if len(pico) >= 200 and len(resto) >= 200:
        otd_p, otd_r = pico["no_prazo_ok"].mean(), resto["no_prazo_ok"].mean()
        ent = cur[cur["tem_entrega"]]
        c_p = ent[ent["pico"]]["custo_frete"].mean()
        c_r = ent[~ent["pico"]]["custo_frete"].mean()
        if otd_r - otd_p > 0.03:
            ins.append({
                "sev": "critical" if otd_r - otd_p > 0.08 else "serious",
                "titulo": "A operação não aguenta o pico de Black Friday e Natal",
                "texto": (f"Entre 20/nov e 22/dez o OTD cai para {_pct(otd_p)} (vs {_pct(otd_r)} no restante), "
                          f"enquanto o custo médio por entrega sobe {_pct(c_p / c_r - 1, 0)}. "
                          f"O pico concentra {_pct(len(pico) / len(fin), 0)} das entregas do período."),
                "acao": "Contratar capacidade extra de expedição e frota com antecedência de 60 dias.",
            })

    # 3. Região mais crítica
    regs = _regioes(cur, atual)
    if len(regs) >= 2:
        pior_r = regs[-1]
        if otd - pior_r["otd"] > 0.03:
            ins.append({
                "sev": "serious",
                "titulo": f"{pior_r['regiao']} é a região com pior nível de serviço",
                "texto": (f"OTD de {_pct(pior_r['otd'])}, {_dec(abs(pior_r['otd'] - otd) * 100)} p.p. abaixo da média "
                          f"geral, com custo médio de {_brl(pior_r['custo_entrega'])} por entrega "
                          f"em {_int(pior_r['entregas'])} entregas."),
                "acao": "Avaliar hub avançado ou parceiro regional especializado.",
            })

    # 4. Atraso derruba a nota
    npa = _nota_por_atraso(cur)
    if len(npa) >= 3:
        no_prazo = npa[0]["nota"]
        atrasos = [r for r in npa[1:] if r["faixa"] not in ("1 dia", "2 dias")]
        if atrasos:
            pior_n = min(atrasos, key=lambda r: r["nota"])
            ins.append({
                "sev": "serious",
                "titulo": "Cada dia de atraso custa satisfação do cliente",
                "texto": (f"Entregas no prazo recebem nota {_dec(no_prazo)}; com {pior_n['faixa']} de atraso, "
                          f"a nota cai para {_dec(pior_n['nota'])}. Um único dia de atraso já tira "
                          f"{_dec(no_prazo - npa[1]['nota'])} ponto da avaliação."),
                "acao": "Comunicar proativamente atrasos previstos e priorizar reentrega.",
            })

    # 5. Causa raiz dos atrasos
    mot = _motivos(cur)
    if mot:
        controlaveis = {"Falha operacional da transportadora", "Falta de veículo / capacidade",
                        "Atraso na expedição do CD"}
        pct_c = sum(m["pct"] for m in mot if m["motivo"] in controlaveis)
        ins.append({
            "sev": "warning",
            "titulo": f"{_pct(pct_c, 0)} dos atrasos têm causa operacional controlável",
            "texto": (f"\"{mot[0]['motivo']}\" lidera com {_pct(mot[0]['pct'], 0)} dos casos. "
                      f"Falhas de transportadora, falta de veículo e atraso de expedição no CD "
                      f"somam {_int(sum(m['qtd'] for m in mot if m['motivo'] in controlaveis))} ocorrências."),
            "acao": "Atacar primeiro as causas internas e contratuais antes das externas (clima, trânsito).",
        })

    # 6. CD mais lento
    cds = [c for c in _cds(cur) if c["pedidos"] >= 100]
    if len(cds) >= 2:
        lento, rapido = cds[0], cds[-1]
        if lento["lead_h"] > rapido["lead_h"] * 1.15:
            ins.append({
                "sev": "warning",
                "titulo": f"{lento['cd']} é o gargalo de expedição",
                "texto": (f"Leva em média {_dec(lento['lead_h'])} h entre pedido e despacho, contra "
                          f"{_dec(rapido['lead_h'])} h no {rapido['cd']}. O tempo parado no CD consome a folga "
                          f"do prazo antes de o frete começar."),
                "acao": "Revisar layout de separação e turnos do CD.",
            })

    # 7. Frete pesa no E-commerce
    segs = [s for s in _segmentos(cur) if s["frete_receita"] is not None and s["pedidos"] >= 100]
    if len(segs) >= 2 and atual["frete_receita"]:
        caro = max(segs, key=lambda s: s["frete_receita"])
        if caro["frete_receita"] > atual["frete_receita"] * 1.5:
            ins.append({
                "sev": "serious" if caro["frete_receita"] > atual["frete_receita"] * 3 else "warning",
                "titulo": f"No {caro['segmento']}, o frete consome {_pct(caro['frete_receita'], 0)} da receita",
                "texto": (f"Contra {_pct(atual['frete_receita'])} na média da operação. Ticket médio de "
                          f"{_brl(caro['ticket'])} não dilui o custo fixo de cada envio."),
                "acao": "Testar frete mínimo, consolidação de envios ou pedido mínimo para frete grátis.",
            })

    # 8. Boa notícia: melhor transportadora
    if tr:
        melhor = max(tr, key=lambda t: t["otd"])
        if melhor["gap"] >= -0.01:
            ins.append({
                "sev": "good",
                "titulo": f"{melhor['nome']} é a referência da malha",
                "texto": (f"{_pct(melhor['otd'])} no prazo ({_pp(melhor['gap'])} vs SLA), avaria de "
                          f"{_pct(melhor['avaria'])} e nota {_dec(melhor['nota'] or 0)} — mas recebe só "
                          f"{_pct(melhor['participacao'], 0)} do volume."),
                "acao": "Migrar volume das transportadoras abaixo do SLA para este parceiro.",
            })

    ins.sort(key=lambda i: SEV_ORDEM[i["sev"]])
    return ins[:6]

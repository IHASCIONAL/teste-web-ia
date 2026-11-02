#!/usr/bin/env python3
"""
Gera uma base sintética de logística (5 tabelas relacionadas) e grava no Supabase.

Tabelas:
    centros_distribuicao  -> CDs da operação (capacidade, custo fixo, eficiência)
    transportadoras       -> parceiros de frete (modal, SLA contratado, custo/km)
    clientes              -> carteira de clientes (segmento, cidade, região)
    pedidos               -> pedidos (cliente x CD, valor, peso, canal, prioridade)
    entregas              -> execução do frete (prazos, atrasos, custo, avaria, NPS)

Relacionamentos:
    pedidos.cliente_id        -> clientes.id
    pedidos.cd_id             -> centros_distribuicao.id
    entregas.pedido_id        -> pedidos.id  (1:1, pedidos cancelados não têm entrega)
    entregas.transportadora_id-> transportadoras.id

Os dados não são uniformes de propósito: há sazonalidade (Black Friday, Natal),
crescimento mês a mês, transportadoras que entregam abaixo do SLA contratado,
CDs com expedição mais lenta e atrasos que derrubam a nota do cliente. Isso dá
material para uma análise executiva (OTIF, custo por pedido, frete/receita,
ranking de transportadoras, gargalos por região, etc.).

Uso:
    uv sync
    # preencha SUPABASE_DB_URL no .env
    uv run gerar_dados_logistica.py                # cria tabelas e carrega
    uv run gerar_dados_logistica.py --recriar      # apaga e recria as 5 tabelas
    uv run gerar_dados_logistica.py --dry-run      # só gera e mostra o resumo
"""

from __future__ import annotations

import argparse
import math
import os
import random
import sys
from datetime import date, datetime, timedelta, time

# --------------------------------------------------------------------------- #
# Dados de referência
# --------------------------------------------------------------------------- #

# (nome, cidade, uf, regiao, lat, lon, capacidade_m3, custo_fixo_mensal, eficiencia)
# eficiencia: 1.0 = expedição no prazo; valores menores = CD mais lento
CDS = [
    ("CD Cajamar",        "Cajamar",          "SP", "Sudeste",      -23.356, -46.877, 120_000, 1_850_000, 1.00),
    ("CD Duque de Caxias","Duque de Caxias",  "RJ", "Sudeste",      -22.786, -43.311,  70_000, 1_150_000, 0.90),
    ("CD Contagem",       "Contagem",         "MG", "Sudeste",      -19.932, -44.054,  60_000,   890_000, 0.95),
    ("CD São José dos Pinhais", "São José dos Pinhais", "PR", "Sul", -25.535, -49.206, 50_000,  760_000, 0.97),
    ("CD Canoas",         "Canoas",           "RS", "Sul",          -29.917, -51.183,  35_000,   540_000, 0.93),
    ("CD Jaboatão",       "Jaboatão dos Guararapes", "PE", "Nordeste", -8.113, -35.015, 45_000,  610_000, 0.82),
    ("CD Camaçari",       "Camaçari",         "BA", "Nordeste",     -12.698, -38.324,  30_000,   430_000, 0.86),
    ("CD Anápolis",       "Anápolis",         "GO", "Centro-Oeste", -16.328, -48.953,  40_000,   520_000, 0.91),
]

# (nome, modal, sla_contratado_pct, custo_fixo_envio, custo_km, custo_kg, confiabilidade_real, taxa_avaria)
# confiabilidade_real é "escondida": não vai para o banco. A análise deve revelar
# a diferença entre o SLA contratado e o que de fato foi entregue.
TRANSPORTADORAS = [
    ("RotaSul Cargas",        "Rodoviário",          95.0, 18.0, 0.42, 0.00, 0.93, 0.010),
    ("Expresso Horizonte",    "Rodoviário",          95.0, 16.0, 0.38, 0.00, 0.84, 0.022),
    ("TransBrasil Log",       "Rodoviário",          93.0, 14.0, 0.33, 0.00, 0.80, 0.030),
    ("Via Norte Transportes", "Rodoviário",          92.0, 15.0, 0.36, 0.00, 0.78, 0.018),
    ("Carga Certa",           "Rodoviário",          96.0, 20.0, 0.47, 0.00, 0.95, 0.008),
    ("FlashLog Express",      "Rodoviário Expresso", 97.0, 28.0, 0.62, 0.00, 0.92, 0.012),
    ("Pronto Entrega",        "Rodoviário Expresso", 97.0, 25.0, 0.58, 0.00, 0.86, 0.015),
    ("AeroCargo Brasil",      "Aéreo",               98.0, 45.0, 0.00, 6.80, 0.95, 0.006),
    ("JetFrete",              "Aéreo",               98.0, 40.0, 0.00, 6.10, 0.89, 0.009),
    ("Última Milha Urbana",   "Rodoviário",          94.0, 12.0, 0.55, 0.00, 0.88, 0.014),
]

# (cidade, uf, regiao, lat, lon, peso_demanda)
CIDADES = [
    ("São Paulo", "SP", "Sudeste", -23.550, -46.633, 120), ("Campinas", "SP", "Sudeste", -22.906, -47.061, 18),
    ("Ribeirão Preto", "SP", "Sudeste", -21.177, -47.810, 10), ("Sorocaba", "SP", "Sudeste", -23.502, -47.458, 9),
    ("São José dos Campos", "SP", "Sudeste", -23.179, -45.887, 9), ("Santos", "SP", "Sudeste", -23.961, -46.333, 7),
    ("Rio de Janeiro", "RJ", "Sudeste", -22.907, -43.173, 60), ("Niterói", "RJ", "Sudeste", -22.883, -43.104, 8),
    ("Belo Horizonte", "MG", "Sudeste", -19.917, -43.934, 30), ("Uberlândia", "MG", "Sudeste", -18.919, -48.277, 9),
    ("Juiz de Fora", "MG", "Sudeste", -21.764, -43.350, 6), ("Vitória", "ES", "Sudeste", -20.315, -40.312, 10),
    ("Curitiba", "PR", "Sul", -25.429, -49.271, 22), ("Londrina", "PR", "Sul", -23.310, -51.163, 7),
    ("Maringá", "PR", "Sul", -23.420, -51.933, 6), ("Porto Alegre", "RS", "Sul", -30.034, -51.217, 20),
    ("Caxias do Sul", "RS", "Sul", -29.168, -51.179, 6), ("Florianópolis", "SC", "Sul", -27.595, -48.548, 10),
    ("Joinville", "SC", "Sul", -26.304, -48.846, 8), ("Blumenau", "SC", "Sul", -26.919, -49.066, 5),
    ("Recife", "PE", "Nordeste", -8.047, -34.877, 18), ("Salvador", "BA", "Nordeste", -12.971, -38.501, 20),
    ("Fortaleza", "CE", "Nordeste", -3.732, -38.527, 19), ("Natal", "RN", "Nordeste", -5.794, -35.211, 8),
    ("João Pessoa", "PB", "Nordeste", -7.115, -34.861, 7), ("Maceió", "AL", "Nordeste", -9.666, -35.735, 7),
    ("Aracaju", "SE", "Nordeste", -10.947, -37.073, 5), ("Teresina", "PI", "Nordeste", -5.089, -42.802, 6),
    ("São Luís", "MA", "Nordeste", -2.530, -44.303, 7), ("Feira de Santana", "BA", "Nordeste", -12.267, -38.967, 4),
    ("Goiânia", "GO", "Centro-Oeste", -16.686, -49.264, 16), ("Brasília", "DF", "Centro-Oeste", -15.794, -47.882, 26),
    ("Campo Grande", "MS", "Centro-Oeste", -20.469, -54.620, 7), ("Cuiabá", "MT", "Centro-Oeste", -15.601, -56.097, 7),
    ("Manaus", "AM", "Norte", -3.119, -60.021, 12), ("Belém", "PA", "Norte", -1.455, -48.502, 11),
    ("Porto Velho", "RO", "Norte", -8.761, -63.903, 4), ("Palmas", "TO", "Norte", -10.184, -48.333, 3),
    ("Macapá", "AP", "Norte", 0.034, -51.069, 2), ("Rio Branco", "AC", "Norte", -9.975, -67.824, 2),
]

# segmento -> (peso na carteira, ticket médio R$, peso médio kg, canal preferido)
SEGMENTOS = {
    "Varejo":      (0.30,  4_800, 180, "B2B"),
    "Atacado":     (0.12, 18_500, 950, "B2B"),
    "E-commerce":  (0.35,    420,   6, "B2C"),
    "Indústria":   (0.10, 26_000, 1_400, "B2B"),
    "Farma":       (0.13,  7_200,  45, "B2B"),
}

PREFIXOS = ["Grupo", "Comercial", "Distribuidora", "Mercantil", "Loja", "Rede", "Casa", "Empório", "Atacadão", "Super"]
NOMES = ["Aurora", "Horizonte", "Bela Vista", "Primavera", "Atlântico", "Ipê", "Cerrado", "Litoral", "Serra Azul",
         "Jacarandá", "Planalto", "Boa Esperança", "Sol Nascente", "Vale Verde", "Pioneira", "Estrela", "Central",
         "Alvorada", "Nova Era", "Três Rios", "Bandeirantes", "Ouro Preto", "Paraná", "Tropical", "Brisa"]
SUFIXOS = ["Ltda", "S.A.", "ME", "EIRELI", "Comércio", "Varejo", "Distribuição"]

MOTIVOS_ATRASO = [
    ("Falha operacional da transportadora", 0.30),
    ("Restrição de tráfego / congestionamento", 0.18),
    ("Destinatário ausente", 0.15),
    ("Endereço incorreto ou incompleto", 0.10),
    ("Condições climáticas", 0.08),
    ("Falta de veículo / capacidade", 0.12),
    ("Problema fiscal / documentação", 0.07),
]

# --------------------------------------------------------------------------- #
# DDL
# --------------------------------------------------------------------------- #

TABELAS = ["entregas", "pedidos", "clientes", "transportadoras", "centros_distribuicao"]

DDL = """
create table if not exists public.centros_distribuicao (
    id                 integer primary key,
    nome               text not null,
    cidade             text not null,
    uf                 char(2) not null,
    regiao             text not null,
    latitude           numeric(8,5) not null,
    longitude          numeric(8,5) not null,
    capacidade_m3      integer not null,
    custo_fixo_mensal  numeric(14,2) not null,
    data_inauguracao   date not null
);

create table if not exists public.transportadoras (
    id                  integer primary key,
    nome                text not null,
    modal               text not null,
    sla_contratado_pct  numeric(5,2) not null,
    custo_fixo_envio    numeric(10,2) not null,
    custo_km            numeric(8,4) not null,
    custo_kg            numeric(8,4) not null,
    inicio_contrato     date not null
);

create table if not exists public.clientes (
    id             integer primary key,
    nome           text not null,
    segmento       text not null,
    cidade         text not null,
    uf             char(2) not null,
    regiao         text not null,
    data_cadastro  date not null
);

create table if not exists public.pedidos (
    id                 bigint primary key,
    cliente_id         integer not null references public.clientes(id),
    cd_id              integer not null references public.centros_distribuicao(id),
    data_pedido        timestamp not null,
    canal              text not null,
    prioridade         text not null,
    qtd_itens          integer not null,
    valor_mercadoria   numeric(14,2) not null,
    peso_kg            numeric(10,2) not null,
    volume_m3          numeric(10,3) not null,
    status             text not null
);

create table if not exists public.entregas (
    id                  bigint primary key,
    pedido_id           bigint not null unique references public.pedidos(id),
    transportadora_id   integer not null references public.transportadoras(id),
    data_despacho       timestamp not null,
    data_prevista       date not null,
    data_entrega        timestamp,
    distancia_km        numeric(10,1) not null,
    custo_frete         numeric(12,2) not null,
    tentativas_entrega  smallint not null,
    status_entrega      text not null,
    no_prazo            boolean,
    dias_atraso         integer,
    motivo_atraso       text,
    avaria              boolean not null,
    nota_cliente        smallint check (nota_cliente between 1 and 5)
);

create index if not exists idx_pedidos_data      on public.pedidos (data_pedido);
create index if not exists idx_pedidos_cliente   on public.pedidos (cliente_id);
create index if not exists idx_pedidos_cd        on public.pedidos (cd_id);
create index if not exists idx_entregas_transp   on public.entregas (transportadora_id);
create index if not exists idx_entregas_despacho on public.entregas (data_despacho);

-- Supabase expõe o schema public pela API. Com RLS ligado e sem policies,
-- a chave anon não lê nada; o acesso fica restrito a service_role / postgres.
alter table public.centros_distribuicao enable row level security;
alter table public.transportadoras      enable row level security;
alter table public.clientes             enable row level security;
alter table public.pedidos              enable row level security;
alter table public.entregas             enable row level security;
"""

# --------------------------------------------------------------------------- #
# Geração
# --------------------------------------------------------------------------- #


def distancia_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distância rodoviária aproximada (haversine x fator de sinuosidade 1,25)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a)) * 1.25


def fator_sazonal(d: date) -> float:
    """Multiplicador de demanda por dia: Black Friday, Natal, janeiro fraco, fim de semana."""
    f = 1.0
    if d.month == 11:
        # Black Friday: 4ª sexta-feira de novembro
        primeiro = date(d.year, 11, 1)
        bf = primeiro + timedelta(days=(4 - primeiro.weekday()) % 7 + 21)
        delta = (d - bf).days
        if -3 <= delta <= 3:
            f *= 2.8 if delta in (0, 3) else 1.9  # sexta e Cyber Monday
        else:
            f *= 1.25
    elif d.month == 12:
        f *= 1.45 if d.day <= 20 else 0.75
    elif d.month == 1:
        f *= 0.80
    elif d.month in (5, 8):   # Dia das Mães / Dia dos Pais
        f *= 1.12
    if d.weekday() == 5:
        f *= 0.55
    elif d.weekday() == 6:
        f *= 0.35
    return f


def em_pico(d: date) -> bool:
    return (d.month == 11 and d.day >= 20) or (d.month == 12 and d.day <= 22)


def nome_empresa(rng: random.Random, usados: set[str]) -> str:
    while True:
        n = f"{rng.choice(PREFIXOS)} {rng.choice(NOMES)} {rng.choice(SUFIXOS)}"
        if n not in usados:
            usados.add(n)
            return n
        n = f"{n} {rng.randint(2, 99)}"
        if n not in usados:
            usados.add(n)
            return n


def gerar(n_pedidos: int, n_clientes: int, inicio: date, fim: date, seed: int) -> dict[str, list[tuple]]:
    rng = random.Random(seed)
    hoje = fim + timedelta(days=1)

    # ---- centros_distribuicao ------------------------------------------------
    cds = []
    for i, (nome, cidade, uf, regiao, lat, lon, cap, custo, _ef) in enumerate(CDS, start=1):
        inaug = date(rng.randint(2012, 2021), rng.randint(1, 12), rng.randint(1, 28))
        cds.append((i, nome, cidade, uf, regiao, lat, lon, cap, custo, inaug))

    # ---- transportadoras ----------------------------------------------------
    transps = []
    for i, (nome, modal, sla, cfix, ckm, ckg, _conf, _av) in enumerate(TRANSPORTADORAS, start=1):
        ini = date(rng.randint(2018, 2023), rng.randint(1, 12), 1)
        transps.append((i, nome, modal, sla, cfix, ckm, ckg, ini))

    por_modal: dict[str, list[int]] = {}
    for i, t in enumerate(TRANSPORTADORAS, start=1):
        por_modal.setdefault(t[1], []).append(i)

    # ---- clientes -----------------------------------------------------------
    pesos_cidade = [c[5] for c in CIDADES]
    segs = list(SEGMENTOS)
    pesos_seg = [SEGMENTOS[s][0] for s in segs]
    usados: set[str] = set()
    clientes = []
    cliente_info = []  # (cidade_idx, segmento, data_cadastro, peso_compra)
    for i in range(1, n_clientes + 1):
        ci = rng.choices(range(len(CIDADES)), weights=pesos_cidade)[0]
        seg = rng.choices(segs, weights=pesos_seg)[0]
        cidade, uf, regiao = CIDADES[ci][:3]
        # 65% já era cliente antes do período; os demais entram ao longo dele
        if rng.random() < 0.65:
            cad = inicio - timedelta(days=rng.randint(30, 2000))
        else:
            cad = inicio + timedelta(days=rng.randint(0, (fim - inicio).days - 30))
        nome = nome_empresa(rng, usados) if seg != "E-commerce" else f"Loja Online {rng.choice(NOMES)} {i}"
        clientes.append((i, nome, seg, cidade, uf, regiao, cad))
        # Pareto: poucos clientes compram muito
        cliente_info.append((ci, seg, cad, rng.paretovariate(1.3)))

    # CD mais próximo de cada cidade (atendimento padrão) + distâncias
    dist_cd_cidade = [[distancia_km(cd[5], cd[6], c[3], c[4]) for c in CIDADES] for cd in cds]
    cd_padrao = [min(range(len(cds)), key=lambda k: dist_cd_cidade[k][ci]) for ci in range(len(CIDADES))]

    # ---- distribuição de pedidos no tempo -----------------------------------
    dias = [inicio + timedelta(days=k) for k in range((fim - inicio).days + 1)]
    total_meses = max(1, (fim.year - inicio.year) * 12 + fim.month - inicio.month)
    pesos_dia = []
    for d in dias:
        meses = (d.year - inicio.year) * 12 + d.month - inicio.month
        crescimento = 1.016 ** meses  # ~21% a.a.
        pesos_dia.append(fator_sazonal(d) * crescimento)
    datas_pedido = sorted(rng.choices(dias, weights=pesos_dia, k=n_pedidos))

    pedidos, entregas = [], []
    idx_clientes = list(range(n_clientes))
    pesos_clientes = [info[3] for info in cliente_info]
    motivos, pesos_motivos = zip(*MOTIVOS_ATRASO)

    for pid, dped in enumerate(datas_pedido, start=1):
        # escolhe cliente já cadastrado na data
        while True:
            k = rng.choices(idx_clientes, weights=pesos_clientes)[0]
            if cliente_info[k][2] <= dped:
                break
        ci, seg, _cad, _w = cliente_info[k]
        _peso_seg, ticket, peso_medio, canal_pref = SEGMENTOS[seg]

        # CD: o mais próximo na maioria; transferência por ruptura nos demais
        cd_idx = cd_padrao[ci] if rng.random() < 0.88 else rng.randrange(len(cds))
        if rng.random() < 0.10:
            cd_idx = 0  # CD Cajamar cobre ruptura nacional
        cd_id = cd_idx + 1
        ef_cd = CDS[cd_idx][8]

        canal = canal_pref
        if seg == "E-commerce":
            canal = "Marketplace" if rng.random() < 0.45 else "B2C"
        elif rng.random() < 0.08:
            canal = "Marketplace"

        prioridade = "Expressa" if rng.random() < (0.30 if seg in ("Farma", "E-commerce") else 0.10) else "Normal"

        valor = round(max(39.9, rng.lognormvariate(math.log(ticket), 0.55)), 2)
        peso = round(max(0.3, rng.lognormvariate(math.log(peso_medio), 0.6)), 2)
        volume = round(peso / rng.uniform(140, 260), 3)
        itens = max(1, int(rng.lognormvariate(math.log(max(1, valor / 180)), 0.5)))

        hora = time(rng.choices(range(24), weights=[1,1,1,1,1,2,4,6,8,9,9,8,7,8,9,9,8,7,6,6,5,4,3,2])[0],
                    rng.randint(0, 59), rng.randint(0, 59))
        dt_pedido = datetime.combine(dped, hora)
        idade = (hoje - dped).days

        # status do pedido
        r = rng.random()
        if r < 0.025:
            status = "Cancelado"
        elif idade <= 1:
            status = "Em separação"
        else:
            status = "Faturado"  # ajustado depois conforme a entrega
        if status != "Cancelado" and idade <= 1:
            pedidos.append([pid, k + 1, cd_id, dt_pedido, canal, prioridade, itens, valor, peso, volume, status])
            continue
        if status == "Cancelado":
            pedidos.append([pid, k + 1, cd_id, dt_pedido, canal, prioridade, itens, valor, peso, volume, status])
            continue

        # ---- entrega --------------------------------------------------------
        dist = dist_cd_cidade[cd_idx][ci] + rng.uniform(8, 45)
        if prioridade == "Expressa" and dist > 900:
            modal = "Aéreo"
        elif prioridade == "Expressa":
            modal = "Rodoviário Expresso"
        elif dist < 60 and seg == "E-commerce":
            modal = "Rodoviário"
        else:
            modal = "Rodoviário" if rng.random() < 0.93 else "Rodoviário Expresso"
        candidatos = por_modal[modal]
        if modal == "Rodoviário" and dist < 60:
            tid = 10 if rng.random() < 0.7 else rng.choice(candidatos)
        else:
            # transportadoras mais baratas ganham mais volume (efeito "menor preço")
            pesos_t = [1 / TRANSPORTADORAS[t - 1][4] if TRANSPORTADORAS[t - 1][4] else 1 for t in candidatos]
            tid = rng.choices(candidatos, weights=pesos_t)[0]
        _n, _m, _sla, cfix, ckm, ckg, conf, tx_av = TRANSPORTADORAS[tid - 1]

        # lead time interno do CD (pedido -> despacho), pior em pico e em CD menos eficiente
        horas_exp = rng.uniform(4, 30) / ef_cd
        if em_pico(dped):
            horas_exp *= rng.uniform(1.4, 2.6)
        if prioridade == "Expressa":
            horas_exp *= 0.5
        dt_desp = dt_pedido + timedelta(hours=horas_exp)

        # prazo prometido a partir da data do pedido
        if modal == "Aéreo":
            dias_transito = 1 + (dist > 2500)
        elif modal == "Rodoviário Expresso":
            dias_transito = 1 + math.ceil(dist / 750)
        else:
            dias_transito = 1 + math.ceil(dist / 450)
        prazo_total = dias_transito + 1  # 1 dia de expedição contratado
        data_prevista = dped + timedelta(days=prazo_total)

        # atraso: falha da transportadora + pico + distância + atraso de expedição
        p_falha = (1 - conf)
        if em_pico(dped):
            p_falha *= 2.2
        if CIDADES[ci][2] == "Norte":
            p_falha *= 1.6
        if dist > 2000:
            p_falha *= 1.3
        p_falha = min(p_falha, 0.85)

        transito_real = dias_transito + rng.uniform(-0.6, 0.3)
        motivo = None
        tentativas = 1
        if rng.random() < p_falha:
            motivo = rng.choices(motivos, weights=pesos_motivos)[0]
            transito_real += rng.choices([1, 2, 3, 4, 6, 9], weights=[40, 25, 15, 10, 6, 4])[0]
            if motivo in ("Destinatário ausente", "Endereço incorreto ou incompleto"):
                tentativas = rng.choice([2, 2, 3])
        dt_entrega_prev = dt_desp + timedelta(days=max(0.15, transito_real))
        if dt_entrega_prev.date() > data_prevista and motivo is None:
            motivo = "Atraso na expedição do CD"

        avaria = rng.random() < tx_av * (1.5 if em_pico(dped) else 1.0)

        # custo do frete
        if modal == "Aéreo":
            custo = cfix + peso * ckg + dist * 0.05
        else:
            fator_peso = 1 + max(0.0, peso - 30) / 400
            custo = cfix + dist * ckm * fator_peso
        custo *= rng.uniform(0.92, 1.10) * (1.12 if em_pico(dped) else 1.0)
        custo *= 1 + 0.35 * (tentativas - 1)
        custo = round(custo, 2)

        if dt_entrega_prev >= datetime.combine(hoje, time(0)):
            # ainda não entregue
            status_ent = "Em trânsito"
            dt_entrega, no_prazo, dias_atraso, nota = None, None, None, None
            motivo = None
            status = "Em trânsito"
        elif avaria and rng.random() < 0.55:
            status_ent = "Devolvido"
            dt_entrega, no_prazo, dias_atraso = None, False, None
            motivo = "Avaria na carga"
            nota = rng.choice([1, 1, 2]) if rng.random() < 0.8 else None
            status = "Devolvido"
        else:
            status_ent = "Entregue"
            dt_entrega = dt_entrega_prev
            atraso = (dt_entrega.date() - data_prevista).days
            no_prazo = atraso <= 0
            dias_atraso = max(0, atraso)
            if no_prazo:
                motivo = None
            status = "Entregue"
            # nota do cliente (só ~55% respondem)
            if rng.random() < 0.55:
                base = 4.6 - 0.45 * dias_atraso - (1.8 if avaria else 0) - 0.3 * (tentativas - 1)
                nota = int(min(5, max(1, round(rng.gauss(base, 0.7)))))
            else:
                nota = None

        pedidos.append([pid, k + 1, cd_id, dt_pedido, canal, prioridade, itens, valor, peso, volume, status])
        entregas.append((len(entregas) + 1, pid, tid, dt_desp.replace(microsecond=0), data_prevista,
                         dt_entrega.replace(microsecond=0) if dt_entrega else None, round(dist, 1), custo,
                         tentativas, status_ent, no_prazo, dias_atraso, motivo, avaria, nota))

    return {
        "centros_distribuicao": cds,
        "transportadoras": transps,
        "clientes": clientes,
        "pedidos": [tuple(p) for p in pedidos],
        "entregas": entregas,
    }


COLUNAS = {
    "centros_distribuicao": ["id", "nome", "cidade", "uf", "regiao", "latitude", "longitude",
                             "capacidade_m3", "custo_fixo_mensal", "data_inauguracao"],
    "transportadoras": ["id", "nome", "modal", "sla_contratado_pct", "custo_fixo_envio",
                        "custo_km", "custo_kg", "inicio_contrato"],
    "clientes": ["id", "nome", "segmento", "cidade", "uf", "regiao", "data_cadastro"],
    "pedidos": ["id", "cliente_id", "cd_id", "data_pedido", "canal", "prioridade", "qtd_itens",
                "valor_mercadoria", "peso_kg", "volume_m3", "status"],
    "entregas": ["id", "pedido_id", "transportadora_id", "data_despacho", "data_prevista", "data_entrega",
                 "distancia_km", "custo_frete", "tentativas_entrega", "status_entrega", "no_prazo",
                 "dias_atraso", "motivo_atraso", "avaria", "nota_cliente"],
}

# --------------------------------------------------------------------------- #
# Resumo / gravação
# --------------------------------------------------------------------------- #


def resumo(dados: dict[str, list[tuple]]) -> None:
    print("\nRegistros gerados:")
    for t in reversed(TABELAS):
        print(f"  {t:<22} {len(dados[t]):>8,}".replace(",", "."))
    ent = [e for e in dados["entregas"] if e[9] == "Entregue"]
    if ent:
        otd = sum(e[10] for e in ent) / len(ent)
        receita = sum(p[7] for p in dados["pedidos"] if p[10] != "Cancelado")
        frete = sum(e[7] for e in dados["entregas"])
        notas = [e[14] for e in ent if e[14] is not None]
        print(f"\n  Entregas no prazo (OTD): {otd:.1%}")
        print(f"  Frete / receita:         {frete / receita:.2%}")
        print(f"  Nota média do cliente:   {sum(notas) / len(notas):.2f}")


def gravar(dados: dict[str, list[tuple]], db_url: str, recriar: bool) -> None:
    try:
        import psycopg
    except ImportError:
        sys.exit("Falta a dependência: rode com \"uv run\" ou faça \"uv sync\"")

    print("\nConectando ao Supabase...")
    with psycopg.connect(db_url, connect_timeout=15) as conn:
        with conn.cursor() as cur:
            if recriar:
                print("Removendo tabelas existentes...")
                for t in TABELAS:
                    cur.execute(f"drop table if exists public.{t} cascade")
            cur.execute(DDL)

            for t in TABELAS:
                cur.execute(f"select exists (select 1 from public.{t})")
                if cur.fetchone()[0]:
                    conn.rollback()
                    sys.exit(f"A tabela '{t}' já tem dados. Rode com --recriar para apagar e recarregar.")

            for t in reversed(TABELAS):  # pais antes dos filhos
                cols = COLUNAS[t]
                with cur.copy(f"copy public.{t} ({', '.join(cols)}) from stdin") as cp:
                    for row in dados[t]:
                        cp.write_row(row)
                print(f"  {t:<22} {len(dados[t]):>8,} linhas".replace(",", "."))
        conn.commit()
    print("Carga concluída.")


def carregar_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def main() -> None:
    carregar_env()
    ontem = date.today() - timedelta(days=1)
    ap = argparse.ArgumentParser(description="Gera base de logística e grava no Supabase.")
    ap.add_argument("--pedidos", type=int, default=30_000, help="quantidade de pedidos (padrão: 30000)")
    ap.add_argument("--clientes", type=int, default=1_200, help="quantidade de clientes (padrão: 1200)")
    ap.add_argument("--meses", type=int, default=24, help="meses de histórico até ontem (padrão: 24)")
    ap.add_argument("--seed", type=int, default=42, help="semente aleatória para reprodutibilidade")
    ap.add_argument("--recriar", action="store_true", help="apaga e recria as 5 tabelas antes de carregar")
    ap.add_argument("--dry-run", action="store_true", help="só gera os dados e mostra o resumo, sem gravar")
    args = ap.parse_args()

    fim = ontem
    inicio = date(fim.year, fim.month, 1)
    for _ in range(args.meses - 1):
        inicio = date(inicio.year - (inicio.month == 1), (inicio.month - 2) % 12 + 1, 1)

    print(f"Gerando dados de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y}...")
    dados = gerar(args.pedidos, args.clientes, inicio, fim, args.seed)
    resumo(dados)

    if args.dry_run:
        return

    db_url = os.environ.get("SUPABASE_DB_URL")
    if not db_url:
        sys.exit("\nDefina SUPABASE_DB_URL (veja .env.example).")
    gravar(dados, db_url, args.recriar)


if __name__ == "__main__":
    main()

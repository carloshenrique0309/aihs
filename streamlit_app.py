from __future__ import annotations

import os
import warnings
from datetime import date
from typing import Any

import pandas as pd
import plotly.express as px
import psycopg2
import streamlit as st


warnings.filterwarnings(
    "ignore",
    message="pandas only supports SQLAlchemy connectable",
    category=UserWarning,
)

DB_CONFIG = {
    "host": "dataiesb.iesbtech.com.br",
    "port": 5432,
    "dbname": "2312120014_Carlos",
    "user": "2312120014_Carlos",
    "password": "2312120014_Carlos",
    "connect_timeout": 20,
}

FACT_TABLE = "public.sih_sus_aih_spabr_clean"
SUBGROUP_TABLE = "public.sih_subgrupo_procedimento"
LONG_VIEW = "public.vw_sih_sus_aih_spabr_long"

REAL_MUNICIPALITY_SQL = (
    "municipio_codigo is not null "
    "and municipio_codigo <> 0 "
    "and coalesce(municipio_ignorado, false) = false"
)
IGNORED_ROW_SQL = (
    "municipio_codigo is null "
    "or municipio_codigo = 0 "
    "or coalesce(municipio_ignorado, false) = true"
)

CONTENT_LABELS = {
    "qtd_aprovada": "Quantidade aprovada",
    "valor_aprovado": "Valor aprovado",
}

PROJECTOR_PALETTE = [
    "#003b73",
    "#b00020",
    "#005f20",
    "#8a5a00",
    "#4b0082",
    "#005f73",
    "#7f1d1d",
    "#1d4ed8",
]


def get_secret(name: str, default: str | None = None) -> str | None:
    env_value = os.environ.get(name)
    if env_value:
        return env_value

    try:
        secret_value = st.secrets.get(name)
        if secret_value:
            return str(secret_value)
    except Exception:
        pass

    return default


def get_db_config() -> dict[str, Any]:
    return {
        "host": get_secret("POSTGRES_HOST", DB_CONFIG["host"]),
        "port": int(get_secret("POSTGRES_PORT", str(DB_CONFIG["port"])) or 5432),
        "dbname": get_secret("POSTGRES_DB", DB_CONFIG["dbname"]),
        "user": get_secret("POSTGRES_USER", DB_CONFIG["user"]),
        "password": get_secret("POSTGRES_PASSWORD", DB_CONFIG["password"]),
        "connect_timeout": 20,
    }


def run_query(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    conn = psycopg2.connect(**get_db_config())
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


@st.cache_data(ttl=600, show_spinner=False)
def cached_query(sql: str, params: tuple[Any, ...] = ()) -> pd.DataFrame:
    return run_query(sql, params)


def as_number(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    copy = frame.copy()
    for column in columns:
        if column in copy.columns:
            copy[column] = pd.to_numeric(copy[column], errors="coerce").fillna(0)
    return copy


def format_int(value: Any) -> str:
    return f"{int(value or 0):,}".replace(",", ".")


def format_decimal(value: Any, digits: int = 2) -> str:
    return f"{float(value or 0):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def format_value(value: Any, content: str) -> str:
    if content == "valor_aprovado":
        return f"R$ {format_decimal(value)}"
    return format_int(value)


def build_filter_where(
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
    *,
    real_only: bool = False,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []

    if real_only:
        clauses.append(REAL_MUNICIPALITY_SQL)

    if uf:
        clauses.append("municipio_uf = %s")
        params.append(uf)

    if municipality_code is not None:
        clauses.append("municipio_codigo = %s")
        params.append(municipality_code)

    if start_period is not None:
        clauses.append("periodo >= %s")
        params.append(start_period)

    if end_period is not None:
        clauses.append("periodo <= %s")
        params.append(end_period)

    return " and ".join(clauses) if clauses else "true", tuple(params)


@st.cache_data(ttl=1800, show_spinner=False)
def uf_options() -> list[str]:
    frame = cached_query(
        f"""
        select distinct municipio_uf
        from {FACT_TABLE}
        where municipio_uf is not null
        order by municipio_uf
        """
    )
    return frame["municipio_uf"].tolist()


@st.cache_data(ttl=1800, show_spinner=False)
def period_options() -> pd.DataFrame:
    return cached_query(
        f"""
        select distinct periodo, periodo_rotulo
        from {FACT_TABLE}
        order by periodo
        """
    )


@st.cache_data(ttl=1800, show_spinner=False)
def municipality_options(uf: str | None = None) -> pd.DataFrame:
    where_sql, params = build_filter_where(uf=uf, real_only=True)
    return cached_query(
        f"""
        select distinct
            municipio_codigo,
            municipio_nome,
            municipio_uf,
            municipio_nome || ' - ' || municipio_uf as municipio_label
        from {FACT_TABLE}
        where {where_sql}
        order by municipio_uf, municipio_nome
        """,
        params,
    )


@st.cache_data(ttl=1800, show_spinner=False)
def database_overview() -> pd.DataFrame:
    return cached_query(
        f"""
        select
            count(*) as registros,
            count(distinct periodo) as periodos,
            to_char(min(periodo), 'MM/YYYY') as primeiro_periodo,
            to_char(max(periodo), 'MM/YYYY') as ultimo_periodo,
            count(distinct case when {REAL_MUNICIPALITY_SQL} then municipio_codigo end) as municipios,
            count(distinct case when municipio_codigo is not null then municipio_codigo end) as codigos_com_zero,
            count(*) filter (where {IGNORED_ROW_SQL}) as linhas_ignoradas,
            count(distinct municipio_uf) filter (where municipio_uf is not null) as ufs,
            (select count(*) from {SUBGROUP_TABLE}) as subgrupos
        from {FACT_TABLE}
        """
    )


@st.cache_data(ttl=1800, show_spinner=False)
def period_audit() -> pd.DataFrame:
    return cached_query(
        f"""
        select
            periodo,
            periodo_rotulo as periodo_label,
            case conteudo
                when 'qtd_aprovada' then 'Quantidade aprovada'
                when 'valor_aprovado' then 'Valor aprovado'
                else conteudo
            end as conteudo,
            count(*) as total_linhas,
            count(*) filter (where {REAL_MUNICIPALITY_SQL}) as municipios,
            count(*) filter (where {IGNORED_ROW_SQL}) as linhas_ignoradas
        from {FACT_TABLE}
        group by periodo, periodo_rotulo, conteudo
        order by periodo desc, conteudo
        """
    )


@st.cache_data(ttl=1800, show_spinner=False)
def subgroup_columns() -> pd.DataFrame:
    return cached_query(
        f"""
        select subgrupo_coluna, subgrupo_codigo, subgrupo_nome
        from {SUBGROUP_TABLE}
        order by subgrupo_coluna
        """
    )


@st.cache_data(ttl=600, show_spinner=False)
def stored_data(
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> pd.DataFrame:
    where_sql, params = build_filter_where(
        uf=uf,
        municipality_code=municipality_code,
        start_period=start_period,
        end_period=end_period,
    )
    frame = cached_query(
        f"""
        select
            periodo_rotulo as periodo,
            case conteudo
                when 'qtd_aprovada' then 'Quantidade aprovada'
                when 'valor_aprovado' then 'Valor aprovado'
                else conteudo
            end as conteudo,
            municipio_codigo,
            municipio_nome,
            municipio_uf,
            case
                when {REAL_MUNICIPALITY_SQL} then 'Municipio'
                else 'Ignorado/exterior'
            end as tipo_linha,
            total_linha as total
        from {FACT_TABLE} t
        where {where_sql}
        order by
            t.periodo desc,
            conteudo,
            case when {REAL_MUNICIPALITY_SQL} then 0 else 1 end,
            municipio_uf,
            municipio_nome
        """,
        params,
    )
    return as_number(frame, ["total"])


@st.cache_data(ttl=1800, show_spinner=False)
def descriptive_stats(
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> pd.DataFrame:
    where_sql, params = build_filter_where(
        uf=uf,
        municipality_code=municipality_code,
        start_period=start_period,
        end_period=end_period,
        real_only=True,
    )
    frame = cached_query(
        f"""
        select
            case conteudo
                when 'qtd_aprovada' then 'Quantidade aprovada'
                when 'valor_aprovado' then 'Valor aprovado'
                else conteudo
            end as conteudo,
            count(*) as linhas_analisadas,
            count(distinct municipio_codigo) as municipios,
            sum(total_linha) as total,
            avg(total_linha) as media,
            min(total_linha) as minimo,
            max(total_linha) as maximo
        from {FACT_TABLE}
        where {where_sql}
        group by conteudo
        order by conteudo
        """,
        params,
    )
    return as_number(
        frame,
        ["linhas_analisadas", "municipios", "total", "media", "minimo", "maximo"],
    )


@st.cache_data(ttl=1800, show_spinner=False)
def monthly_totals(
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> pd.DataFrame:
    where_sql, params = build_filter_where(
        uf=uf,
        municipality_code=municipality_code,
        start_period=start_period,
        end_period=end_period,
        real_only=True,
    )
    frame = cached_query(
        f"""
        select
            periodo,
            periodo_rotulo as periodo_label,
            conteudo,
            sum(total_linha) as total
        from {FACT_TABLE}
        where {where_sql}
        group by periodo, periodo_rotulo, conteudo
        order by periodo, conteudo
        """,
        params,
    )
    return as_number(frame, ["total"])


@st.cache_data(ttl=1800, show_spinner=False)
def top_municipalities(
    content: str,
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
    limit: int = 15,
) -> pd.DataFrame:
    where_sql, params = build_filter_where(
        uf=uf,
        municipality_code=municipality_code,
        start_period=start_period,
        end_period=end_period,
        real_only=True,
    )
    frame = cached_query(
        f"""
        select
            municipio_nome || ' - ' || municipio_uf as municipio,
            municipio_nome,
            municipio_uf,
            sum(total_linha) as total
        from {FACT_TABLE}
        where conteudo = %s
          and {where_sql}
        group by municipio_nome, municipio_uf
        order by total desc
        limit %s
        """,
        (content, *params, limit),
    )
    return as_number(frame, ["total"])


@st.cache_data(ttl=1800, show_spinner=False)
def uf_totals(
    content: str,
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> pd.DataFrame:
    where_sql, params = build_filter_where(
        uf=uf,
        municipality_code=municipality_code,
        start_period=start_period,
        end_period=end_period,
        real_only=True,
    )
    frame = cached_query(
        f"""
        select municipio_uf as uf, sum(total_linha) as total
        from {FACT_TABLE}
        where conteudo = %s
          and {where_sql}
          and municipio_uf is not null
        group by municipio_uf
        order by total desc
        """,
        (content, *params),
    )
    return as_number(frame, ["total"])


@st.cache_data(ttl=1800, show_spinner=False)
def top_subgroups(
    content: str,
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
    limit: int = 15,
) -> pd.DataFrame:
    subgroups = subgroup_columns()
    where_sql, params = build_filter_where(
        uf=uf,
        municipality_code=municipality_code,
        start_period=start_period,
        end_period=end_period,
        real_only=True,
    )
    sum_columns = ",\n            ".join(
        f"sum({row.subgrupo_coluna}) as {row.subgrupo_coluna}"
        for row in subgroups.itertuples(index=False)
    )
    value_rows = ",\n                ".join(
        f"('{row.subgrupo_coluna}', totals.{row.subgrupo_coluna})"
        for row in subgroups.itertuples(index=False)
    )
    frame = cached_query(
        f"""
        with totals as (
            select
            {sum_columns}
            from {FACT_TABLE}
            where conteudo = %s
              and {where_sql}
        )
        select
            d.subgrupo_codigo,
            d.subgrupo_nome,
            v.total
        from totals
        cross join lateral (
            values
                {value_rows}
        ) as v(subgrupo_coluna, total)
        join {SUBGROUP_TABLE} d
            on d.subgrupo_coluna = v.subgrupo_coluna
        order by v.total desc
        limit %s
        """,
        (content, *params, limit),
    )
    return as_number(frame, ["total"])


def apply_style() -> None:
    st.markdown(
        """
        <style>
        :root {
            --ink: #05070a;
            --muted: #202a36;
            --line: #111827;
            --panel: #ffffff;
            --accent: #003b73;
            --accent-2: #b00020;
            --gold: #8a5a00;
        }

        .stApp {
            background: #ffffff;
            color: var(--ink);
        }

        .block-container {
            max-width: 1220px;
            padding-top: 2rem;
            padding-bottom: 4rem;
        }

        [data-testid="stHeader"] {
            background: transparent;
        }

        .hero {
            padding: 1.05rem 1.25rem 1.15rem 1.25rem;
            margin-bottom: 1.1rem;
            border: 3px solid var(--accent);
            border-left: 14px solid var(--accent);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: none;
        }

        .hero p {
            margin: 0;
            color: var(--ink);
            max-width: 860px;
            font-size: 1rem;
        }

        .eyebrow {
            margin: 0 0 0.35rem 0;
            color: #b00020;
            font-size: 0.86rem;
            font-weight: 800;
            letter-spacing: 0;
            text-transform: uppercase;
        }

        .hero h1 {
            margin: 0;
            color: #061225;
            font-size: clamp(2rem, 3.6vw, 3rem);
            font-weight: 900;
            line-height: 1.04;
            letter-spacing: 0;
        }

        .hero h1,
        .hero h1 *,
        .hero [data-testid="stMarkdownContainer"] {
            color: #061225 !important;
        }

        .hero .eyebrow,
        .hero .eyebrow * {
            color: #b00020 !important;
        }

        p, li, span, label, div[data-testid="stMarkdownContainer"] {
            color: var(--ink);
            font-size: 1.04rem;
        }

        .note {
            padding: 0.9rem 1rem;
            border: 2px solid var(--line);
            border-left: 8px solid var(--accent);
            border-radius: 8px;
            background: #f4f7ff;
            color: var(--ink);
        }

        .note strong {
            color: var(--accent);
        }

        [data-testid="stMetric"] {
            padding: 1rem;
            border: 2px solid var(--line);
            border-radius: 8px;
            background: #ffffff;
            box-shadow: none;
        }

        [data-testid="stMetricLabel"],
        [data-testid="stMetricValue"],
        [data-testid="stMetricDelta"] {
            color: var(--ink) !important;
        }

        div[data-testid="stTabs"] button p {
            font-weight: 700;
            color: var(--ink);
        }

        [role="radiogroup"] label {
            font-weight: 800;
        }

        [role="radiogroup"] [aria-checked="true"] {
            outline: 3px solid var(--accent-2);
            outline-offset: 2px;
        }

        [data-testid="stSelectbox"] label,
        [data-testid="stSelectbox"] div {
            color: var(--ink) !important;
            font-weight: 700;
        }

        .stDataFrame {
            border: 2px solid var(--line);
            border-radius: 8px;
            overflow: hidden;
        }

        [data-testid="stDataFrame"] button[title="Download as CSV"],
        [data-testid="stDataFrame"] button[aria-label="Download as CSV"] {
            display: none !important;
        }

        h2, h3 {
            color: var(--ink);
            letter-spacing: 0;
            font-weight: 900;
        }

        @media (max-width: 720px) {
            .block-container {
                padding-top: 1rem;
            }

            .hero {
                padding: 1rem;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header() -> None:
    st.markdown(
        """
        <section class="hero">
            <div class="eyebrow">SIH/SUS DATASUS</div>
            <h1>Producao Hospitalar por Municipio</h1>
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_work() -> None:
    overview = database_overview().iloc[0]

    st.subheader("Sobre o trabalho")
    st.write(
        "Este projeto utiliza dados publicos do SUS disponibilizados no portal DATASUS. "
        "A base escolhida foi a Producao Hospitalar do SIH/SUS, com dados detalhados de AIH "
        "por local de internacao, abrangendo municipios do Brasil no periodo de janeiro/2024 "
        "a janeiro/2026."
    )
    st.write(
        "Os dados foram extraidos automaticamente, limpos para padronizar municipios, periodos "
        "e valores numericos, e depois carregados em um banco PostgreSQL. A aplicacao consulta "
        "esse banco para apresentar uma lista dos registros, estatisticas descritivas e graficos "
        "sobre quantidade aprovada, valor aprovado, UFs, municipios e subgrupos de procedimento."
    )

    st.markdown(
        """
        <div class="note">
            <strong>Fonte dos dados:</strong> DATASUS / TabNet, SIH/SUS - Producao Hospitalar,
            Dados Detalhados de AIH, por local de internacao. As linhas "Ignorado/exterior"
            foram mantidas no banco para preservar a extracao original, mas nao entram na
            contagem de municipios apresentada no painel.
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("O que sera analisado")
    left, right = st.columns(2)
    with left:
        st.markdown(
            """
            - Lista dos dados armazenados no banco
            - Estatisticas descritivas da quantidade aprovada
            - Estatisticas descritivas do valor aprovado
            - Evolucao mensal entre 2024 e 2026
            """
        )
    with right:
        st.markdown(
            """
            - Comparacao dos totais por UF
            - Ranking dos municipios com maiores totais
            - Ranking dos subgrupos de procedimento
            - Comparacao entre quantidade aprovada e valor aprovado
            """
        )

    st.subheader("Base carregada")
    cols = st.columns(5)
    cols[0].metric("Municipios", format_int(overview["municipios"]))
    cols[1].metric("Registros no banco", format_int(overview["registros"]))
    cols[2].metric("Periodos", format_int(overview["periodos"]))
    cols[3].metric("UFs", format_int(overview["ufs"]))
    cols[4].metric("Subgrupos", format_int(overview["subgrupos"]))


def render_filters() -> tuple[str | None, int | None, date | None, date | None]:
    st.subheader("Filtros")
    uf_col, start_col, end_col, municipality_col = st.columns([0.65, 0.85, 0.85, 1.45])

    selected_uf = uf_col.selectbox("UF", ["Todas"] + uf_options())
    uf = None if selected_uf == "Todas" else selected_uf

    periods = period_options()
    period_labels = periods["periodo_rotulo"].tolist()
    selected_start = start_col.selectbox("Periodo inicial", period_labels, index=0)
    selected_end = end_col.selectbox("Periodo final", period_labels, index=len(period_labels) - 1)
    start_period = periods.loc[periods["periodo_rotulo"] == selected_start, "periodo"].iloc[0]
    end_period = periods.loc[periods["periodo_rotulo"] == selected_end, "periodo"].iloc[0]

    if start_period > end_period:
        st.warning("O periodo inicial ficou depois do periodo final. Ajustei o intervalo automaticamente.")
        start_period, end_period = end_period, start_period

    municipalities = municipality_options(uf)
    municipality_labels = ["Todos"] + municipalities["municipio_label"].tolist()
    selected_municipality = municipality_col.selectbox("Municipio", municipality_labels)

    municipality_code = None
    if selected_municipality != "Todos":
        selected_row = municipalities.loc[municipalities["municipio_label"] == selected_municipality].iloc[0]
        municipality_code = int(selected_row["municipio_codigo"])

    return uf, municipality_code, start_period, end_period


def render_data_list(
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> None:
    st.subheader("Lista dos dados armazenados")
    st.caption("Tabela carregada do PostgreSQL conforme os filtros selecionados.")
    frame = stored_data(uf, municipality_code, start_period, end_period)

    col1, col2 = st.columns(2)
    col1.metric("Linhas listadas", format_int(len(frame)))
    col2.metric("Municipios", format_int(frame.loc[frame["tipo_linha"] == "Municipio", "municipio_codigo"].nunique()))

    st.dataframe(frame, width="stretch", height=520, hide_index=True)


def render_statistics(
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> None:
    st.subheader("Estatisticas descritivas")
    st.caption("Estatisticas calculadas sobre os municipios, sem as linhas Ignorado/exterior.")
    stats = descriptive_stats(uf, municipality_code, start_period, end_period)

    display = stats.copy()
    for column in ["total", "media", "minimo", "maximo"]:
        display[column] = display.apply(
            lambda row: format_value(row[column], "valor_aprovado" if row["conteudo"] == "Valor aprovado" else "qtd_aprovada"),
            axis=1,
        )
    display["linhas_analisadas"] = display["linhas_analisadas"].map(format_int)
    display["municipios"] = display["municipios"].map(format_int)
    display = display.rename(
        columns={
            "conteudo": "Conteudo",
            "linhas_analisadas": "Linhas analisadas",
            "municipios": "Municipios",
            "total": "Total",
            "media": "Media",
            "minimo": "Minimo",
            "maximo": "Maximo",
        }
    )
    st.dataframe(display, width="stretch", hide_index=True)

    totals = monthly_totals(uf, municipality_code, start_period, end_period)
    qtd_total = totals.loc[totals["conteudo"] == "qtd_aprovada", "total"].sum()
    valor_total = totals.loc[totals["conteudo"] == "valor_aprovado", "total"].sum()
    col1, col2 = st.columns(2)
    col1.metric("Quantidade aprovada total", format_value(qtd_total, "qtd_aprovada"))
    col2.metric("Valor aprovado total", format_value(valor_total, "valor_aprovado"))


def style_projector_chart(fig, height: int) -> None:
    fig.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=68, b=18),
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        font=dict(color="#05070a", size=15),
        title=dict(font=dict(color="#05070a", size=18)),
        legend=dict(font=dict(color="#05070a", size=13), bgcolor="#ffffff"),
    )
    fig.update_xaxes(
        showline=True,
        linewidth=2,
        linecolor="#111827",
        tickfont=dict(color="#05070a", size=13),
        title_font=dict(color="#05070a", size=15),
        gridcolor="#c7ced8",
        zerolinecolor="#111827",
    )
    fig.update_yaxes(
        showline=True,
        linewidth=2,
        linecolor="#111827",
        tickfont=dict(color="#05070a", size=13),
        title_font=dict(color="#05070a", size=15),
        gridcolor="#c7ced8",
        zerolinecolor="#111827",
    )


def render_line_chart(
    content: str,
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> None:
    label = CONTENT_LABELS[content]
    frame = monthly_totals(uf, municipality_code, start_period, end_period)
    frame = frame[frame["conteudo"] == content].copy()
    line_color = "#003b73" if content == "qtd_aprovada" else "#b00020"
    fig = px.line(
        frame,
        x="periodo_label",
        y="total",
        markers=True,
        title=f"Evolucao mensal - {label}",
        labels={"periodo_label": "Periodo", "total": label},
        color_discrete_sequence=[line_color],
    )
    fig.update_traces(line=dict(width=4), marker=dict(size=8))
    style_projector_chart(fig, 380)
    st.plotly_chart(fig, width="stretch")


def render_top_municipality_chart(
    content: str,
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> None:
    label = CONTENT_LABELS[content]
    frame = top_municipalities(content, uf, municipality_code, start_period, end_period).sort_values("total")
    fig = px.bar(
        frame,
        x="total",
        y="municipio",
        orientation="h",
        color="municipio_uf",
        title=f"Top 15 municipios - {label}",
        labels={"total": label, "municipio": "Municipio", "municipio_uf": "UF"},
        color_discrete_sequence=PROJECTOR_PALETTE,
    )
    style_projector_chart(fig, 480)
    st.plotly_chart(fig, width="stretch")


def render_uf_chart(
    content: str,
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> None:
    label = CONTENT_LABELS[content]
    frame = uf_totals(content, uf, municipality_code, start_period, end_period)
    fig = px.bar(
        frame,
        x="uf",
        y="total",
        title=f"Total por UF - {label}",
        labels={"uf": "UF", "total": label},
        color_discrete_sequence=["#003b73" if content == "qtd_aprovada" else "#b00020"],
    )
    style_projector_chart(fig, 380)
    st.plotly_chart(fig, width="stretch")


def render_subgroup_chart(
    content: str,
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> None:
    label = CONTENT_LABELS[content]
    frame = top_subgroups(content, uf, municipality_code, start_period, end_period).sort_values("total")
    fig = px.bar(
        frame,
        x="total",
        y="subgrupo_nome",
        orientation="h",
        title=f"Top 15 subgrupos de procedimento - {label}",
        labels={"total": label, "subgrupo_nome": "Subgrupo"},
        color_discrete_sequence=["#003b73" if content == "qtd_aprovada" else "#b00020"],
    )
    style_projector_chart(fig, 540)
    st.plotly_chart(fig, width="stretch")


def render_charts(
    uf: str | None = None,
    municipality_code: int | None = None,
    start_period: date | None = None,
    end_period: date | None = None,
) -> None:
    st.subheader("Graficos")
    st.caption("Graficos usando os filtros selecionados e todos os periodos carregados no banco.")

    left, right = st.columns(2)
    with left:
        render_line_chart("qtd_aprovada", uf, municipality_code, start_period, end_period)
    with right:
        render_line_chart("valor_aprovado", uf, municipality_code, start_period, end_period)

    left, right = st.columns(2)
    with left:
        render_uf_chart("qtd_aprovada", uf, municipality_code, start_period, end_period)
    with right:
        render_uf_chart("valor_aprovado", uf, municipality_code, start_period, end_period)

    left, right = st.columns(2)
    with left:
        render_top_municipality_chart("qtd_aprovada", uf, municipality_code, start_period, end_period)
    with right:
        render_top_municipality_chart("valor_aprovado", uf, municipality_code, start_period, end_period)

    left, right = st.columns(2)
    with left:
        render_subgroup_chart("qtd_aprovada", uf, municipality_code, start_period, end_period)
    with right:
        render_subgroup_chart("valor_aprovado", uf, municipality_code, start_period, end_period)


def main() -> None:
    st.set_page_config(page_title="Painel SIH/SUS", layout="wide")
    apply_style()
    render_header()

    section = st.radio(
        "Secao do painel",
        ["Trabalho", "Lista dos dados", "Estatisticas", "Graficos"],
        horizontal=True,
        label_visibility="collapsed",
    )

    if section == "Trabalho":
        render_work()
    else:
        uf, municipality_code, start_period, end_period = render_filters()
        if section == "Lista dos dados":
            render_data_list(uf, municipality_code, start_period, end_period)
        elif section == "Estatisticas":
            render_statistics(uf, municipality_code, start_period, end_period)
        else:
            render_charts(uf, municipality_code, start_period, end_period)


if __name__ == "__main__":
    main()

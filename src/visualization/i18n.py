"""Internationalization — English / Brazilian Portuguese translations."""

from __future__ import annotations

import streamlit as st

# ─── All user-facing strings ──────────────────────────────────────────────────
TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── Page / header ─────────────────────────────────────────────────────
    "page_title": {
        "en": "Araripe Deforestation Monitor",
        "pt": "Monitor de Desmatamento do Araripe",
    },
    "main_title": {
        "en": "Araripe Deforestation Monitor",
        "pt": "Monitor de Desmatamento do Araripe",
    },
    "main_caption": {
        "en": (
            "Satellite-based weekly deforestation monitoring for "
            "Chapada do Araripe (CE/PE/PI, Brazil)"
        ),
        "pt": (
            "Monitoramento semanal de desmatamento por satelite na "
            "Chapada do Araripe (CE/PE/PI, Brasil)"
        ),
    },
    # ── Sidebar ───────────────────────────────────────────────────────────
    "sidebar_title": {
        "en": "Araripe Monitor",
        "pt": "Monitor Araripe",
    },
    "sidebar_caption": {
        "en": "Deforestation monitoring for Chapada do Araripe",
        "pt": "Monitoramento de desmatamento na Chapada do Araripe",
    },
    "date_range": {
        "en": "Date Range",
        "pt": "Periodo",
    },
    "start": {
        "en": "Start",
        "pt": "Inicio",
    },
    "end": {
        "en": "End",
        "pt": "Fim",
    },
    "alert_confidence": {
        "en": "Alert Confidence",
        "pt": "Confianca do Alerta",
    },
    "select_confidence": {
        "en": "Select confidence levels",
        "pt": "Selecione os niveis de confianca",
    },
    "confidence_help": {
        "en": "Choose which confidence levels to include.",
        "pt": "Escolha quais niveis de confianca incluir.",
    },
    "high": {
        "en": "High",
        "pt": "Alta",
    },
    "medium": {
        "en": "Medium",
        "pt": "Media",
    },
    "low": {
        "en": "Low",
        "pt": "Baixa",
    },
    "min_area_label": {
        "en": "Minimum Area",
        "pt": "Area Minima",
    },
    "min_area_input": {
        "en": "Min area (ha)",
        "pt": "Area min. (ha)",
    },
    "min_area_help": {
        "en": "Exclude alerts smaller than this area.",
        "pt": "Excluir alertas menores que esta area.",
    },
    "view_on_map": {
        "en": "View on Map",
        "pt": "Ver no Mapa",
    },
    "view_on_map_help": {
        "en": "Apply current filters to the map and zoom to fit.",
        "pt": "Aplicar filtros atuais no mapa e ajustar o zoom.",
    },
    "sidebar_filter_note": {
        "en": (
            "Filters update the table and metrics instantly. "
            "Press **View on Map** to refresh the map."
        ),
        "pt": (
            "Os filtros atualizam a tabela e metricas instantaneamente. "
            "Pressione **Ver no Mapa** para atualizar o mapa."
        ),
    },
    # ── Metrics ───────────────────────────────────────────────────────────
    "total_alerts": {
        "en": "Total Alerts",
        "pt": "Total de Alertas",
    },
    "total_area_ha": {
        "en": "Total Area (ha)",
        "pt": "Area Total (ha)",
    },
    "high_confidence": {
        "en": "High Confidence",
        "pt": "Alta Confianca",
    },
    "medium_confidence": {
        "en": "Medium Confidence",
        "pt": "Media Confianca",
    },
    "low_confidence": {
        "en": "Low Confidence",
        "pt": "Baixa Confianca",
    },
    # ── Tabs ──────────────────────────────────────────────────────────────
    "tab_map": {
        "en": "Map",
        "pt": "Mapa",
    },
    "tab_timeseries": {
        "en": "Time Series",
        "pt": "Series Temporais",
    },
    "tab_alerts": {
        "en": "Alert History",
        "pt": "Historico de Alertas",
    },
    "tab_about": {
        "en": "About",
        "pt": "Sobre",
    },
    # ── Map tab ───────────────────────────────────────────────────────────
    "map_title": {
        "en": "Deforestation Alert Map",
        "pt": "Mapa de Alertas de Desmatamento",
    },
    "map_showing_n": {
        "en": "Showing **{n}** alert{s} on map. Change filters in the sidebar and press **View on Map** to update.",
        "pt": "Exibindo **{n}** alerta{s} no mapa. Altere os filtros na barra lateral e pressione **Ver no Mapa** para atualizar.",
    },
    "install_folium": {
        "en": "Install `streamlit-folium` for interactive maps: `pip install streamlit-folium`",
        "pt": "Instale `streamlit-folium` para mapas interativos: `pip install streamlit-folium`",
    },
    "alert_explorer": {
        "en": "Alert Explorer",
        "pt": "Explorador de Alertas",
    },
    "alert_explorer_caption": {
        "en": (
            "Showing **{n}** alerts matching current filters. "
            "Adjust filters in the sidebar, then press **View on Map** to update the map."
        ),
        "pt": (
            "Exibindo **{n}** alertas com os filtros atuais. "
            "Ajuste os filtros na barra lateral e pressione **Ver no Mapa** para atualizar o mapa."
        ),
    },
    "total_area_caption": {
        "en": "Total area: {area} ha",
        "pt": "Area total: {area} ha",
    },
    # ── Table columns ─────────────────────────────────────────────────────
    "col_id": {"en": "ID", "pt": "ID"},
    "col_date": {"en": "Date", "pt": "Data"},
    "col_confidence": {"en": "Confidence", "pt": "Confianca"},
    "col_area": {"en": "Area (ha)", "pt": "Area (ha)"},
    "col_lat": {"en": "Lat", "pt": "Lat"},
    "col_lon": {"en": "Lon", "pt": "Lon"},
    # ── Time series tab ───────────────────────────────────────────────────
    "ts_title": {
        "en": "Vegetation Index Time Series",
        "pt": "Series Temporais de Indices de Vegetacao",
    },
    "ts_expander": {
        "en": "What are these indices? Which should I use?",
        "pt": "O que sao esses indices? Qual devo usar?",
    },
    "ts_expander_intro": {
        "en": (
            "These spectral indices are computed from satellite bands and measure "
            "different vegetation properties. **For deforestation monitoring, enable "
            "all three** — they complement each other:"
        ),
        "pt": (
            "Estes indices espectrais sao calculados a partir de bandas de satelite e medem "
            "diferentes propriedades da vegetacao. **Para monitoramento de desmatamento, ative "
            "todos os tres** — eles se complementam:"
        ),
    },
    "ts_select_indices": {
        "en": "Select indices to display",
        "pt": "Selecione os indices para exibir",
    },
    "ts_select_help": {
        "en": "These are the three indices computed by the detection pipeline.",
        "pt": "Estes sao os tres indices calculados pelo pipeline de deteccao.",
    },
    "ts_select_empty": {
        "en": "Select at least one index above.",
        "pt": "Selecione pelo menos um indice acima.",
    },
    "ts_individual": {
        "en": "Individual Index Details",
        "pt": "Detalhes por Indice",
    },
    "ts_no_data": {
        "en": (
            "No time series data available. Run the detection pipeline to "
            "build up observation history."
        ),
        "pt": (
            "Sem dados de series temporais. Execute o pipeline de deteccao "
            "para acumular historico de observacoes."
        ),
    },
    "ts_trend": {
        "en": "Vegetation Trend",
        "pt": "Tendencia da Vegetacao",
    },
    "ts_decreasing": {"en": "Decreasing", "pt": "Decrescente"},
    "ts_increasing": {"en": "Increasing", "pt": "Crescente"},
    "ts_no_trend": {"en": "No trend", "pt": "Sem tendencia"},
    "ts_significant": {"en": " (significant)", "pt": " (significativo)"},
    "ts_not_significant": {"en": " (not significant)", "pt": " (nao significativo)"},
    # ── Index descriptions ────────────────────────────────────────────────
    "ndmi_desc": {
        "en": (
            "Sensitive to canopy water content. Best for detecting "
            "early-stage deforestation where trees are cut but stumps remain. "
            "Primary index for this monitoring system."
        ),
        "pt": (
            "Sensivel ao conteudo de agua do dossel. Ideal para detectar "
            "desmatamento em estagio inicial, onde as arvores sao cortadas mas os tocos permanecem. "
            "Indice principal deste sistema de monitoramento."
        ),
    },
    "ndmi_use": {
        "en": "Primary detection index",
        "pt": "Indice principal de deteccao",
    },
    "nbr_desc": {
        "en": (
            "Responds to both fire damage and clearing. Strong signal for "
            "burned areas and complete canopy removal. Confirms NDMI detections."
        ),
        "pt": (
            "Responde tanto a danos por fogo quanto a desmatamento. Forte sinal para "
            "areas queimadas e remocao completa do dossel. Confirma deteccoes do NDMI."
        ),
    },
    "nbr_use": {
        "en": "Confirmation index (fire + clearing)",
        "pt": "Indice de confirmacao (fogo + corte)",
    },
    "evi2_desc": {
        "en": (
            "Measures green vegetation vigor with reduced soil background influence. "
            "Less affected by atmospheric conditions than NDVI. "
            "Useful for detecting gradual degradation."
        ),
        "pt": (
            "Mede o vigor da vegetacao verde com menor influencia do solo. "
            "Menos afetado por condicoes atmosfericas que o NDVI. "
            "Util para detectar degradacao gradual."
        ),
    },
    "evi2_use": {
        "en": "Degradation tracking",
        "pt": "Rastreamento de degradacao",
    },
    "role_label": {
        "en": "Role",
        "pt": "Funcao",
    },
    # ── Alert history tab ─────────────────────────────────────────────────
    "ah_title": {
        "en": "Alert Statistics Over Time",
        "pt": "Estatisticas de Alertas ao Longo do Tempo",
    },
    "ah_all_records": {
        "en": "All Alert Records",
        "pt": "Todos os Registros de Alertas",
    },
    "ah_caption": {
        "en": (
            "Showing all {n} alerts across all dates "
            "(sidebar date filter applies to charts above, not this table)"
        ),
        "pt": (
            "Exibindo todos os {n} alertas em todas as datas "
            "(o filtro de data da barra lateral se aplica aos graficos acima, nao a esta tabela)"
        ),
    },
    "ah_no_data": {
        "en": "No alert history data available yet.",
        "pt": "Nenhum historico de alertas disponivel ainda.",
    },
    # ── About tab ─────────────────────────────────────────────────────────
    "about_expander": {
        "en": "About this monitoring system",
        "pt": "Sobre este sistema de monitoramento",
    },
    "about_body": {
        "en": """
**Araripe Deforestation Monitor** detects vegetation loss across
Chapada do Araripe using satellite imagery from Sentinel-2 and Landsat.

**Key features:**
- Weekly automated processing via GitHub Actions
- Moisture-based indices (NDMI, NBR) for reliable detection in
  seasonally deciduous Caatinga/Cerrado vegetation
- Z-score anomaly detection against monthly baselines
- Multi-index confirmation for confidence classification
- Drought-adjusted thresholds using SPI rainfall data

**Data sources:**
- Sentinel-2 L2A (10-20m resolution, 5-day revisit)
- Landsat 8/9 Collection 2 (30m resolution)
- NASA HLS (harmonized 30m, 2-3 day revisit)

**Coverage:** ~7-8 S, 39-40 W (Chapada do Araripe, CE/PE/PI, Brazil)
        """,
        "pt": """
O **Monitor de Desmatamento do Araripe** detecta perda de vegetacao na
Chapada do Araripe usando imagens de satelite do Sentinel-2 e Landsat.

**Principais funcionalidades:**
- Processamento automatizado semanal via GitHub Actions
- Indices baseados em umidade (NDMI, NBR) para deteccao confiavel em
  vegetacao sazonalmente decidua de Caatinga/Cerrado
- Deteccao de anomalias por z-score contra linhas de base mensais
- Confirmacao multi-indice para classificacao de confianca
- Limiares ajustados por seca usando dados de precipitacao SPI

**Fontes de dados:**
- Sentinel-2 L2A (resolucao 10-20m, revisita de 5 dias)
- Landsat 8/9 Collection 2 (resolucao 30m)
- NASA HLS (harmonizado 30m, revisita de 2-3 dias)

**Cobertura:** ~7-8 S, 39-40 O (Chapada do Araripe, CE/PE/PI, Brasil)
        """,
    },
    "architecture_title": {
        "en": "System Architecture",
        "pt": "Arquitetura do Sistema",
    },
    "architecture_body": {
        "en": """
**Data Pipeline:**
1. Weekly GitHub Actions cron job queries Sentinel-2 imagery
2. Cloud masking via SCL band removes clouds, shadows, cirrus
3. NDMI, NBR, EVI2 indices computed from reflectance bands
4. Z-score comparison against monthly baselines (3-5yr history)
5. Anomalous pixels vectorized into alert polygons
6. Results committed to GitHub and COGs uploaded to Cloudflare R2

**Detection Method:**
- Primary: NDMI z-score < -2.0 AND delta < -0.15
- Confirmation: Multi-index agreement (NDMI + NBR)
- Drought adjustment: SPI-based threshold widening
- Confidence levels: High (z < -3.0), Medium (z < -2.5), Low (z < -2.0)

**Technical Stack:**
- Satellite data: Element84 STAC, Planetary Computer, NASA HLS
- Processing: rasterio, xarray, dask, scipy
- Visualization: Streamlit, Leafmap, Folium, Plotly
- Hosting: Hugging Face Spaces (free tier)
- Storage: Cloudflare R2 (10 GB free, zero egress)
- Automation: GitHub Actions (weekly cron)
        """,
        "pt": """
**Pipeline de Dados:**
1. Cron job semanal do GitHub Actions consulta imagens Sentinel-2
2. Mascaramento de nuvens via banda SCL remove nuvens, sombras, cirrus
3. Indices NDMI, NBR, EVI2 calculados a partir de bandas de reflectancia
4. Comparacao de z-score com linhas de base mensais (historico de 3-5 anos)
5. Pixels anomalos vetorizados em poligonos de alerta
6. Resultados commitados no GitHub e COGs carregados no Cloudflare R2

**Metodo de Deteccao:**
- Principal: z-score NDMI < -2.0 E delta < -0.15
- Confirmacao: Concordancia multi-indice (NDMI + NBR)
- Ajuste de seca: Ampliacao de limiares baseada no SPI
- Niveis de confianca: Alta (z < -3.0), Media (z < -2.5), Baixa (z < -2.0)

**Stack Tecnico:**
- Dados de satelite: Element84 STAC, Planetary Computer, NASA HLS
- Processamento: rasterio, xarray, dask, scipy
- Visualizacao: Streamlit, Leafmap, Folium, Plotly
- Hospedagem: Hugging Face Spaces (gratuito)
- Armazenamento: Cloudflare R2 (10 GB gratuitos, zero egress)
- Automacao: GitHub Actions (cron semanal)
        """,
    },
    "last_detection": {
        "en": "Last detection run: **{date}** | {n} detection files",
        "pt": "Ultima deteccao: **{date}** | {n} arquivos de deteccao",
    },
    "footer": {
        "en": (
            "Araripe Deforestation Monitor | "
            "[GitHub](https://github.com/santibravocmcc/Araripe) | "
            "Open source | "
            "Data: ESA Sentinel-2, USGS Landsat, NASA HLS"
        ),
        "pt": (
            "Monitor de Desmatamento do Araripe | "
            "[GitHub](https://github.com/santibravocmcc/Araripe) | "
            "Codigo aberto | "
            "Dados: ESA Sentinel-2, USGS Landsat, NASA HLS"
        ),
    },
    # ── No data message ───────────────────────────────────────────────────
    "no_data": {
        "en": (
            "No alert data available yet. Run the detection pipeline first: "
            "`python scripts/run_detection.py`"
        ),
        "pt": (
            "Nenhum dado de alerta disponivel ainda. Execute o pipeline de deteccao: "
            "`python scripts/run_detection.py`"
        ),
    },
    # ── Map legend labels ─────────────────────────────────────────────────
    "legend_title": {
        "en": "Alert Confidence",
        "pt": "Confianca do Alerta",
    },
    "legend_high": {"en": "High", "pt": "Alta"},
    "legend_medium": {"en": "Medium", "pt": "Media"},
    "legend_low": {"en": "Low", "pt": "Baixa"},
}


def t(key: str) -> str:
    """Return the translated string for the current language.

    Falls back to English if the key or language is missing.
    """
    lang = st.session_state.get("language", "pt")
    entry = TRANSLATIONS.get(key, {})
    return entry.get(lang, entry.get("en", f"[{key}]"))

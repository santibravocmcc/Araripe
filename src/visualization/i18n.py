"""Internationalization — English / Brazilian Portuguese translations."""

from __future__ import annotations

import streamlit as st

# ─── All user-facing strings ──────────────────────────────────────────────────
TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── Page / header ─────────────────────────────────────────────────────
    "page_title": {
        "en": "Chapada do Araripe Deforestation Monitor",
        "pt": "Monitor de Desmatamento da Chapada do Araripe",
    },
    "main_title": {
        "en": "Chapada do Araripe Deforestation Monitor",
        "pt": "Monitor de Desmatamento da Chapada do Araripe",
    },
    "main_caption": {
        "en": (
            "Satellite-based twice-weekly deforestation monitoring for "
            "Chapada do Araripe (CE/PE/PI, Brazil)"
        ),
        "pt": (
            "Monitoramento bisemanal de desmatamento por satélite na "
            "Chapada do Araripe (CE/PE/PI, Brasil)"
        ),
    },
    # ── Latest scan ──────────────────────────────────────────────────────
    "latest_scan_btn": {
        "en": "Latest Scan Only",
        "pt": "Apenas Última Varredura",
    },
    "latest_scan_info": {
        "en": "**Last scan:** {run_date} | **Imagery from:** {image_date}",
        "pt": "**Última varredura:** {run_date} | **Imagem de:** {image_date}",
    },
    "latest_scan_help": {
        "en": "Show only alerts from the most recent detection run.",
        "pt": "Mostrar apenas alertas da detecção mais recente.",
    },
    "latest_scan_help_tooltip": {
        "en": (
            "**Last scan** — the date the automated detection job ran on "
            "GitHub Actions.\n\n"
            "**Imagery from** — the acquisition date of the satellite scene "
            "that detection job analyzed (the most recent cloud-free Sentinel-2 "
            "image available at the time the job ran). The two dates can "
            "differ by days or weeks because Sentinel-2 only revisits the "
            "area every 5 days and many passes are too cloudy to use."
        ),
        "pt": (
            "**Última varredura** — a data em que o pipeline automatizado "
            "de detecção foi executado no GitHub Actions.\n\n"
            "**Imagem de** — a data de aquisição da cena de satélite que "
            "esse pipeline analisou (a imagem Sentinel-2 mais recente sem "
            "nuvens disponível no momento da execução). As duas datas podem "
            "diferir em dias ou semanas porque o Sentinel-2 revisita a área "
            "apenas a cada 5 dias e muitas passagens estão muito nubladas "
            "para serem usadas."
        ),
    },
    # ── Sidebar ───────────────────────────────────────────────────────────
    "sidebar_title": {
        "en": "Araripe Monitor",
        "pt": "Monitoramento do Araripe",
    },
    "sidebar_caption": {
        "en": "Deforestation monitoring for Chapada do Araripe",
        "pt": "Monitoramento de desmatamento na Chapada do Araripe",
    },
    "date_range": {
        "en": "Date Range",
        "pt": "Período",
    },
    "start": {
        "en": "Start",
        "pt": "Início",
    },
    "end": {
        "en": "End",
        "pt": "Fim",
    },
    "alert_confidence": {
        "en": "Alert Confidence",
        "pt": "Confiança do Alerta",
    },
    "select_confidence": {
        "en": "Select confidence levels",
        "pt": "Selecione os níveis de confiança",
    },
    "confidence_help": {
        "en": "Choose which confidence levels to include.",
        "pt": "Escolha quais níveis de confiança incluir.",
    },
    "high": {
        "en": "High",
        "pt": "Alta",
    },
    "medium": {
        "en": "Medium",
        "pt": "Média",
    },
    "low": {
        "en": "Low",
        "pt": "Baixa",
    },
    # ── Recent activity (replaces minimum-area filter) ───────────────────
    "recent_section": {
        "en": "Recent Activity",
        "pt": "Atividade Recente",
    },
    "recent_n_label": {
        "en": "Recent runs (N)",
        "pt": "Últimas execuções (N)",
    },
    "recent_n_help": {
        "en": (
            "Alerts from the last N detection runs are highlighted on the "
            "map and table. Detection runs twice a week, so 4 ≈ 2 weeks."
        ),
        "pt": (
            "Alertas das últimas N execuções de detecção são destacados no "
            "mapa e na tabela. A detecção roda duas vezes por semana, "
            "então 4 ≈ 2 semanas."
        ),
    },
    "recent_only_label": {
        "en": "Show only recent",
        "pt": "Mostrar apenas recentes",
    },
    "recent_only_help": {
        "en": "Hide all alerts except those from the last N detection runs.",
        "pt": "Ocultar todos os alertas exceto os das últimas N execuções.",
    },
    "col_recent": {
        "en": "New",
        "pt": "Novo",
    },
    "legend_recent": {
        "en": "New (last {n} runs)",
        "pt": "Novo (últimas {n} execuções)",
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
            "Press **View on Map** to refresh the map. The full alert "
            "history is shown by default — recent runs are highlighted "
            "in magenta."
        ),
        "pt": (
            "Os filtros atualizam a tabela e métricas instantaneamente. "
            "Pressione **Ver no Mapa** para atualizar o mapa. O histórico "
            "completo de alertas é exibido por padrão — execuções recentes "
            "ficam destacadas em magenta."
        ),
    },
    # ── Metrics ───────────────────────────────────────────────────────────
    "total_alerts": {
        "en": "Total Alerts",
        "pt": "Total de Alertas",
    },
    "total_area_ha": {
        "en": "Total Area (ha)",
        "pt": "Área Total (ha)",
    },
    "high_confidence": {
        "en": "High Confidence",
        "pt": "Alta Confiança",
    },
    "medium_confidence": {
        "en": "Medium Confidence",
        "pt": "Média Confiança",
    },
    "low_confidence": {
        "en": "Low Confidence",
        "pt": "Baixa Confiança",
    },
    # ── Tabs ──────────────────────────────────────────────────────────────
    "tab_map": {
        "en": "Map",
        "pt": "Mapa",
    },
    "tab_timeseries": {
        "en": "Time Series",
        "pt": "Séries Temporais",
    },
    "tab_alerts": {
        "en": "Alert History",
        "pt": "Histórico de Alertas",
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
        "pt": "Área total: {area} ha",
    },
    # ── Table columns ─────────────────────────────────────────────────────
    "col_id": {"en": "ID", "pt": "ID"},
    "col_date": {"en": "Date", "pt": "Data"},
    "col_confidence": {"en": "Confidence", "pt": "Confiança"},
    "col_area": {"en": "Area (ha)", "pt": "Área (ha)"},
    "col_lat": {"en": "Lat", "pt": "Lat"},
    "col_lon": {"en": "Lon", "pt": "Lon"},
    # ── Time series tab ───────────────────────────────────────────────────
    "ts_title": {
        "en": "Vegetation Index Time Series",
        "pt": "Séries Temporais de Índices de Vegetação",
    },
    "ts_expander": {
        "en": "What are these indices? Which should I use?",
        "pt": "O que são esses índices? Qual devo usar?",
    },
    "ts_expander_intro": {
        "en": (
            "These spectral indices are computed from satellite bands and measure "
            "different vegetation properties. **For deforestation monitoring, enable "
            "all three** — they complement each other:"
        ),
        "pt": (
            "Estes índices espectrais são calculados a partir de bandas de satélite e medem "
            "diferentes propriedades da vegetação. **Para monitoramento de desmatamento, ative "
            "todos os três** — eles se complementam:"
        ),
    },
    "ts_select_indices": {
        "en": "Select indices to display",
        "pt": "Selecione os índices para exibir",
    },
    "ts_select_help": {
        "en": "These are the three indices computed by the detection pipeline.",
        "pt": "Estes são os três índices calculados pelo pipeline de detecção.",
    },
    "ts_select_empty": {
        "en": "Select at least one index above.",
        "pt": "Selecione pelo menos um índice acima.",
    },
    "ts_individual": {
        "en": "Individual Index Details",
        "pt": "Detalhes por Índice",
    },
    "ts_no_data": {
        "en": (
            "No time series data available. Run the detection pipeline to "
            "build up observation history."
        ),
        "pt": (
            "Sem dados de séries temporais. Execute o pipeline de detecção "
            "para acumular histórico de observações."
        ),
    },
    "ts_baselines_expander": {
        "en": "Monthly climatology baselines (per-pixel reference, 2020–2025)",
        "pt": "Climatologia mensal de referência (por pixel, 2020–2025)",
    },
    "ts_baselines_caption": {
        "en": (
            "Per-pixel monthly mean and standard deviation across multiple years "
            "of cloud-free imagery, clipped to the APA Chapada do Araripe boundary. "
            "These rasters define what \"normal\" looks like for each calendar month "
            "and are the reference against which incoming scenes are compared.\n\n"
            "**Reading the colour scales.** Negative values are physically meaningful: "
            "for NDMI and NBR they indicate dry/exposed soil, recently burned ground, "
            "rock outcrops, or water — not an artefact. EVI2 is bounded near "
            "[-0.2, 0.8] in practice; persistent zeros indicate non-vegetated surfaces. "
            "**Grey pixels** represent missing data (zero valid scenes for that "
            "month/pixel); they are now distinguished from real-zero values."
        ),
        "pt": (
            "Média e desvio-padrão mensal por pixel ao longo de vários anos de "
            "imagens sem nuvem, recortados ao limite da APA Chapada do Araripe. "
            "Estes rasters definem o que é \"normal\" para cada mês do calendário e "
            "servem de referência para comparar as cenas recém-baixadas.\n\n"
            "**Como ler as escalas de cor.** Valores negativos têm significado "
            "físico: para NDMI e NBR indicam solo seco/exposto, queimadas recentes, "
            "afloramentos rochosos ou água — não são artefatos. O EVI2 fica na "
            "prática entre [-0.2, 0.8]; zeros persistentes apontam superfícies não "
            "vegetadas. **Pixels cinzas** representam ausência de dados (zero cenas "
            "válidas para aquele mês/pixel) e agora são distinguíveis dos zeros reais."
        ),
    },
    "ts_baselines_mean": {
        "en": "Monthly mean",
        "pt": "Média mensal",
    },
    "ts_baselines_std": {
        "en": "Monthly standard deviation",
        "pt": "Desvio-padrão mensal",
    },
    "ts_baselines_missing": {
        "en": (
            "Baseline plot not found at `{path}`. Run "
            "`python scripts/plot_baselines.py` after rebuilding the baselines."
        ),
        "pt": (
            "Plot de referência não encontrado em `{path}`. Execute "
            "`python scripts/plot_baselines.py` após reconstruir as baselines."
        ),
    },
    "ts_trend": {
        "en": "Vegetation Trend",
        "pt": "Tendência da Vegetação",
    },
    "ts_decreasing": {"en": "Decreasing", "pt": "Decrescente"},
    "ts_increasing": {"en": "Increasing", "pt": "Crescente"},
    "ts_no_trend": {"en": "No trend", "pt": "Sem tendência"},
    "ts_significant": {"en": " (significant)", "pt": " (significativo)"},
    "ts_not_significant": {"en": " (not significant)", "pt": " (não significativo)"},
    # ── Index descriptions ────────────────────────────────────────────────
    "ndmi_desc": {
        "en": (
            "Sensitive to canopy water content. Best for detecting "
            "early-stage deforestation where trees are cut but stumps remain. "
            "Primary index for this monitoring system."
        ),
        "pt": (
            "Sensível ao conteúdo de água do dossel. Ideal para detectar "
            "desmatamento em estágio inicial, onde as árvores são cortadas mas os tocos permanecem. "
            "Índice principal deste sistema de monitoramento."
        ),
    },
    "ndmi_use": {
        "en": "Primary detection index",
        "pt": "Índice principal de detecção",
    },
    "nbr_desc": {
        "en": (
            "Responds to both fire damage and clearing. Strong signal for "
            "burned areas and complete canopy removal. Confirms NDMI detections."
        ),
        "pt": (
            "Responde tanto a danos por fogo quanto a desmatamento. Forte sinal para "
            "áreas queimadas e remoção completa do dossel. Confirma detecções do NDMI."
        ),
    },
    "nbr_use": {
        "en": "Confirmation index (fire + clearing)",
        "pt": "Índice de confirmação (fogo + corte)",
    },
    "evi2_desc": {
        "en": (
            "Measures green vegetation vigor with reduced soil background influence. "
            "Less affected by atmospheric conditions than NDVI. "
            "Useful for detecting gradual degradation."
        ),
        "pt": (
            "Mede o vigor da vegetação verde com menor influência do solo. "
            "Menos afetado por condições atmosféricas que o NDVI. "
            "Útil para detectar degradação gradual."
        ),
    },
    "evi2_use": {
        "en": "Degradation tracking",
        "pt": "Rastreamento de degradação",
    },
    "role_label": {
        "en": "Role",
        "pt": "Função",
    },
    # ── Alert history tab ─────────────────────────────────────────────────
    "ah_title": {
        "en": "Alert Statistics Over Time",
        "pt": "Estatísticas de Alertas ao Longo do Tempo",
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
            "(o filtro de data da barra lateral se aplica aos gráficos acima, não a esta tabela)"
        ),
    },
    "ah_no_data": {
        "en": "No alert history data available yet.",
        "pt": "Nenhum histórico de alertas disponível ainda.",
    },
    # ── About tab ─────────────────────────────────────────────────────────
    "about_expander": {
        "en": "About this monitoring system",
        "pt": "Sobre este sistema de monitoramento",
    },
    "about_body": {
        "en": """
**Chapada do Araripe Deforestation Monitor** detects vegetation loss across
Chapada do Araripe using satellite imagery from Sentinel-2 and Landsat.

**Key features:**
- Twice-weekly automated processing via GitHub Actions
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
O **Monitor de Desmatamento da Chapada do Araripe** detecta perda de vegetação na
Chapada do Araripe usando imagens de satélite do Sentinel-2 e Landsat.

**Principais funcionalidades:**
- Processamento automatizado bisemanal via GitHub Actions
- Índices baseados em umidade (NDMI, NBR) para detecção confiável em
  vegetação sazonalmente decídua de Caatinga/Cerrado
- Detecção de anomalias por z-score contra linhas de base mensais
- Confirmação multi-índice para classificação de confiança
- Limiares ajustados por seca usando dados de precipitação SPI

**Fontes de dados:**
- Sentinel-2 L2A (resolução 10-20m, revisita de 5 dias)
- Landsat 8/9 Collection 2 (resolução 30m)
- NASA HLS (harmonizado 30m, revisita de 2-3 dias)

**Cobertura:** ~7-8°S, 39-40°O (Chapada do Araripe, CE/PE/PI, Brasil)
        """,
    },
    "architecture_title": {
        "en": "System Architecture",
        "pt": "Arquitetura do Sistema",
    },
    "architecture_body": {
        "en": """
**Data Pipeline:**
1. Twice-weekly GitHub Actions cron job queries Sentinel-2 imagery
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
- Automation: GitHub Actions (twice-weekly cron)
        """,
        "pt": """
**Pipeline de Dados:**
1. Cron job bisemanal do GitHub Actions consulta imagens Sentinel-2
2. Mascaramento de nuvens via banda SCL remove nuvens, sombras, cirrus
3. Índices NDMI, NBR, EVI2 calculados a partir de bandas de reflectância
4. Comparação de z-score com linhas de base mensais (histórico de 3-5 anos)
5. Pixels anômalos vetorizados em polígonos de alerta
6. Resultados commitados no GitHub e COGs carregados no Cloudflare R2

**Método de Detecção:**
- Principal: z-score NDMI < -2.0 E delta < -0.15
- Confirmação: Concordância multi-índice (NDMI + NBR)
- Ajuste de seca: Ampliação de limiares baseada no SPI
- Níveis de confiança: Alta (z < -3.0), Média (z < -2.5), Baixa (z < -2.0)

**Stack Técnico:**
- Dados de satélite: Element84 STAC, Planetary Computer, NASA HLS
- Processamento: rasterio, xarray, dask, scipy
- Visualização: Streamlit, Leafmap, Folium, Plotly
- Hospedagem: Hugging Face Spaces (gratuito)
- Armazenamento: Cloudflare R2 (10 GB gratuitos, zero egress)
- Automação: GitHub Actions (cron bisemanal)
        """,
    },
    "last_detection": {
        "en": "Last detection run: **{date}** | {n} detection files",
        "pt": "Última detecção: **{date}** | {n} arquivos de detecção",
    },
    "footer": {
        "en": (
            "Chapada do Araripe Deforestation Monitor · "
            "Developed by [Santiago Bravo](https://santibravocmcc.github.io/portfolio/) · "
            "[GitHub](https://github.com/santibravocmcc/Araripe) · "
            "Code: Apache 2.0 | Data: CC BY 4.0 · "
            "Imagery: ESA Sentinel-2, USGS Landsat, NASA HLS"
        ),
        "pt": (
            "Monitor de Desmatamento da Chapada do Araripe · "
            "Desenvolvido por [Santiago Bravo](https://santibravocmcc.github.io/portfolio/) · "
            "[GitHub](https://github.com/santibravocmcc/Araripe) · "
            "Código: Apache 2.0 | Dados: CC BY 4.0 · "
            "Imagens: ESA Sentinel-2, USGS Landsat, NASA HLS"
        ),
    },
    "license_title": {
        "en": "License & Attribution",
        "pt": "Licença e Atribuição",
    },
    "code_license_body": {
        "en": """**Source Code**

[![Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/santibravocmcc/Araripe/blob/main/LICENSE)

[Apache License 2.0](https://github.com/santibravocmcc/Araripe/blob/main/LICENSE)

Permissive open-source license. Free to use, modify, and distribute — including commercially — provided the `NOTICE` file is retained in derivative works.""",
        "pt": """**Código-fonte**

[![Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://github.com/santibravocmcc/Araripe/blob/main/LICENSE)

[Apache License 2.0](https://github.com/santibravocmcc/Araripe/blob/main/LICENSE)

Licença permissiva. Livre para usar, modificar e distribuir — inclusive comercialmente — desde que o arquivo `NOTICE` seja mantido em obras derivadas.""",
    },
    "data_license_body": {
        "en": """**Data Products**

[![CC BY 4.0](https://img.shields.io/badge/Data-CC_BY_4.0-lightgrey.svg)](https://github.com/santibravocmcc/Araripe/blob/main/DATA_LICENSE)

[Creative Commons BY 4.0](https://github.com/santibravocmcc/Araripe/blob/main/DATA_LICENSE)

Applies to baselines, alert GeoJSONs, and time series. Share and adapt for any purpose, including commercial use, with attribution.""",
        "pt": """**Produtos de Dados**

[![CC BY 4.0](https://img.shields.io/badge/Data-CC_BY_4.0-lightgrey.svg)](https://github.com/santibravocmcc/Araripe/blob/main/DATA_LICENSE)

[Creative Commons BY 4.0](https://github.com/santibravocmcc/Araripe/blob/main/DATA_LICENSE)

Aplica-se a linhas de base, GeoJSONs de alerta e séries temporais. Compartilhe e adapte para qualquer finalidade, inclusive comercial, com atribuição.""",
    },
    "citation_title": {
        "en": "How to Cite",
        "pt": "Como Citar",
    },
    "citation_body": {
        "en": """If you use this software, baseline products, or alert outputs in your research, please cite:

> Bravo, S. (2026). *Chapada do Araripe Deforestation Monitor* (Version 1.0.0) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.19885824

[![DOI](https://zenodo.org/badge/1152379890.svg)](https://doi.org/10.5281/zenodo.19885824)

**BibTeX:**
```bibtex
@software{bravo_araripe_2026,
  author  = {Bravo, Santiago},
  title   = {Chapada do Araripe Deforestation Monitor},
  year    = {2026},
  version = {1.0.0},
  doi     = {10.5281/zenodo.19885824},
  url     = {https://github.com/santibravocmcc/Araripe}
}
```""",
        "pt": """Se você usar este software, produtos de linha de base ou saídas de alerta em sua pesquisa, por favor cite:

> Bravo, S. (2026). *Chapada do Araripe Deforestation Monitor* (Versão 1.0.0) [Software]. Zenodo. https://doi.org/10.5281/zenodo.19885824

[![DOI](https://zenodo.org/badge/1152379890.svg)](https://doi.org/10.5281/zenodo.19885824)

**BibTeX:**
```bibtex
@software{bravo_araripe_2026,
  author  = {Bravo, Santiago},
  title   = {Chapada do Araripe Deforestation Monitor},
  year    = {2026},
  version = {1.0.0},
  doi     = {10.5281/zenodo.19885824},
  url     = {https://github.com/santibravocmcc/Araripe}
}
```""",
    },
    "developer_title": {
        "en": "Developer",
        "pt": "Desenvolvedor",
    },
    "developer_body": {
        "en": """**Santiago Bravo**
Environmental monitoring software developer.

[Portfolio](https://santibravocmcc.github.io/portfolio/) · [GitHub](https://github.com/santibravocmcc)""",
        "pt": """**Santiago Bravo**
Desenvolvedor de software para monitoramento ambiental.

[Portfólio](https://santibravocmcc.github.io/portfolio/) · [GitHub](https://github.com/santibravocmcc)""",
    },
    # ── No data message ───────────────────────────────────────────────────
    "no_data": {
        "en": (
            "No alert data available yet. Run the detection pipeline first: "
            "`python scripts/run_detection.py`"
        ),
        "pt": (
            "Nenhum dado de alerta disponível ainda. Execute o pipeline de detecção: "
            "`python scripts/run_detection.py`"
        ),
    },
    # ── Map legend labels ─────────────────────────────────────────────────
    "legend_title": {
        "en": "Alert Confidence",
        "pt": "Confiança do Alerta",
    },
    "legend_high": {"en": "High", "pt": "Alta"},
    "legend_medium": {"en": "Medium", "pt": "Média"},
    "legend_low": {"en": "Low", "pt": "Baixa"},
    # ── Chart titles & axis labels ────────────────────────────────────────
    "chart_ts_title": {
        "en": "{index} Time Series",
        "pt": "Série Temporal — {index}",
    },
    "chart_multi_title": {
        "en": "Vegetation Indices Over Time",
        "pt": "Índices de Vegetação ao Longo do Tempo",
    },
    "chart_date_axis": {
        "en": "Date",
        "pt": "Data",
    },
    "chart_index_value": {
        "en": "Index Value",
        "pt": "Valor do Índice",
    },
    "chart_alerts_title": {
        "en": "Deforestation Alerts Over Time",
        "pt": "Alertas de Desmatamento ao Longo do Tempo",
    },
    "chart_num_alerts": {
        "en": "Number of Alerts",
        "pt": "Número de Alertas",
    },
    "chart_cumulative_title": {
        "en": "Cumulative Deforested Area",
        "pt": "Área Desmatada Acumulada",
    },
    "chart_area_axis": {
        "en": "Area (hectares)",
        "pt": "Área (hectares)",
    },
    "chart_cumulative_legend": {
        "en": "Cumulative Area (ha)",
        "pt": "Área Acumulada (ha)",
    },
    # ── Confidence explanation (plain language) ───────────────────────────
    "confidence_explanation_title": {
        "en": "What do the confidence levels mean?",
        "pt": "O que significam os níveis de confiança?",
    },
    "confidence_explanation": {
        "en": """
**What do the confidence levels mean?**

The system compares recent satellite images with what the area normally looks like. When the vegetation appears significantly different from normal, an alert is generated.

- **High confidence** — The change is very clear and confirmed by multiple indicators. Very likely to be a real change on the ground.
- **Medium confidence** — The change is noticeable, but could also be caused by dry season, clouds, or shadows. Worth checking.
- **Low confidence** — A small change was detected. Could be a real early-stage change, but could also be natural variation. Needs local verification.

By default, only **high confidence** alerts are shown. Use the sidebar filters to include medium and low confidence alerts.
        """,
        "pt": """
**O que significam os níveis de confiança?**

O sistema compara imagens recentes de satélite com a aparência normal da área. Quando a vegetação aparece significativamente diferente do normal, um alerta é gerado.

- **Alta confiança** — A mudança é muito clara e confirmada por múltiplos indicadores. Muito provável que seja uma mudança real no terreno.
- **Média confiança** — A mudança é perceptível, mas também pode ser causada por seca, nuvens ou sombras. Vale a pena verificar.
- **Baixa confiança** — Uma pequena mudança foi detectada. Pode ser uma mudança real em estágio inicial, mas também pode ser variação natural. Necessita verificação local.

Por padrão, apenas alertas de **alta confiança** são exibidos. Use os filtros na barra lateral para incluir alertas de média e baixa confiança.
        """,
    },
    # ── Export Mode ─────────────────────────────────────────────────────────
    "export_mode": {
        "en": "Export Mode",
        "pt": "Modo de Exportação",
    },
    "exit_export_mode": {
        "en": "Exit Export Mode",
        "pt": "Sair do Modo de Exportação",
    },
    "export_mode_instructions": {
        "en": (
            "Draw a **rectangle** or **polygon** on the map to select alerts "
            "for export. Use the drawing tools on the left side of the map."
        ),
        "pt": (
            "Desenhe um **retângulo** ou **polígono** no mapa para selecionar alertas "
            "para exportação. Use as ferramentas de desenho no lado esquerdo do mapa."
        ),
    },
    "export_selected": {
        "en": "Selected Alerts for Export",
        "pt": "Alertas Selecionados para Exportação",
    },
    "export_n_selected": {
        "en": "**{n}** alert{s} selected within the drawn area.",
        "pt": "**{n}** alerta{s} selecionado{s} dentro da área desenhada.",
    },
    "export_no_selection": {
        "en": "Draw a shape on the map above to select alerts for export.",
        "pt": "Desenhe uma forma no mapa acima para selecionar alertas para exportação.",
    },
    "export_csv": {
        "en": "Download CSV",
        "pt": "Baixar CSV",
    },
    "export_geojson": {
        "en": "Download GeoJSON",
        "pt": "Baixar GeoJSON",
    },
    "export_google_maps": {
        "en": "Open in Google Maps",
        "pt": "Abrir no Google Maps",
    },
    "col_google_maps": {
        "en": "Google Maps",
        "pt": "Google Maps",
    },
    # ── Step-by-step workflow ─────────────────────────────────────────────
    "workflow_steps": {
        "en": (
            "**How to use this dashboard:**\n"
            "1. **Filter** — In the sidebar, pick confidence levels and how many recent runs count as 'new' (default N = 1)\n"
            "2. **View on Map** — Press the button in the sidebar to update the map (full history is shown by default)\n"
            "3. **Pick a basemap** — Use the layer-control widget at the top-right of the map to switch between Esri Satellite (default), Google Hybrid, or OpenStreetMap, or to toggle the APA / FLONA contours\n"
            "4. **Spot what's new** — Alerts from the last N detection runs carry a 🆕 badge in the table and are sorted first; the **Show only recent** checkbox filters the view to just those\n"
            "5. **Explore** — Browse the Alert Explorer table below the map\n"
            "6. **Export** — Press **Export Mode** above the map to select and download alerts"
        ),
        "pt": (
            "**Como usar este painel:**\n"
            "1. **Filtrar** — Na barra lateral, escolha os níveis de confiança e quantas execuções contam como 'recentes' (padrão N = 1)\n"
            "2. **Ver no Mapa** — Pressione o botão na barra lateral para atualizar o mapa (todo o histórico é exibido por padrão)\n"
            "3. **Escolher o basemap** — Use o controle de camadas no canto superior direito do mapa para alternar entre Esri Satellite (padrão), Google Hybrid ou OpenStreetMap, ou para ligar/desligar os contornos APA / FLONA\n"
            "4. **Identificar novidades** — Alertas das últimas N execuções recebem o selo 🆕 na tabela e aparecem primeiro; o checkbox **Mostrar apenas recentes** filtra a visualização\n"
            "5. **Explorar** — Navegue pela tabela do Explorador de Alertas abaixo do mapa\n"
            "6. **Exportar** — Pressione **Modo de Exportação** acima do mapa para selecionar e baixar alertas"
        ),
    },
    # ── Guide / Instructions tab ─────────────────────────────────────────
    "tab_guide": {
        "en": "Guide",
        "pt": "Guia",
    },
    "tab_docs": {
        "en": "Documentation",
        "pt": "Documentação",
    },
    "docs_title": {
        "en": "Technical Documentation",
        "pt": "Documentação Técnica",
    },
    "docs_caption": {
        "en": (
            "Full technical review of the Araripe Deforestation Monitoring System — "
            "satellite data sources, detection methodology, validation results, and known limitations."
        ),
        "pt": (
            "Revisão técnica completa do Sistema de Monitoramento de Desmatamento do Araripe — "
            "fontes de dados satelitais, metodologia de detecção, resultados de validação e limitações conhecidas."
        ),
    },
    "docs_download": {
        "en": "Download PDF",
        "pt": "Baixar PDF",
    },
    "docs_download_caption": {
        "en": "Download the technical review as a formatted PDF document.",
        "pt": "Baixe a revisão técnica como documento PDF formatado.",
    },
    "guide_title": {
        "en": "User Guide",
        "pt": "Guia do Usuário",
    },
    "guide_body": {
        "en": """
## How to Use the Chapada do Araripe Deforestation Monitor

This dashboard lets you explore, filter, and export deforestation alerts detected by satellite imagery across Chapada do Araripe.

### Step 1: Filter Alerts

The dashboard always loads the **full alert history** so you can compare new detections with everything that came before. Use the **sidebar** (left panel) to refine the view:

- **Alert Confidence** — Choose confidence levels (High, Medium, Low). High-confidence alerts are the most reliable.
- **Recent Activity → Recent runs (N)** — Alerts from the last *N* detection runs get a 🆕 badge in the table and are sorted first. Detection runs twice a week, so N = 1 ≈ a few days, N = 4 ≈ two weeks.
- **Recent Activity → Show only recent** — Hide everything except those last *N* runs when you only care about new detections.

As you change filters, the **metrics** (top of the page) and the **Alert Explorer table** update instantly.

### Step 2: View on Map

Press the **View on Map** button in the sidebar. This refreshes the map to show only the alerts matching your current filters and zooms to fit them.

> **Why a button?** Rendering the map is expensive. Updating it on every filter change would make the app slow. The button lets you fine-tune your filters first, then update the map once.

### Step 3: Explore the Alert Table

Below the map you will find the **Alert Explorer** — a sortable table showing all filtered alerts with:
- Alert ID, detection date, confidence level
- Area in hectares
- Latitude/longitude coordinates

### Step 4: Export Mode (Select & Download)

Once you are satisfied with your filtered alerts on the map:

1. Press the **Export Mode** button (top-right corner of the map section).
2. The map reloads with **drawing tools** on the left side.
3. Use the **rectangle** or **polygon** tool to draw an area on the map.
4. All alerts **inside your drawn area** appear in a table below.
5. Download the selected alerts as **CSV** or **GeoJSON**.
6. Each alert row includes a **Google Maps link** — click it to see the exact location in Google Maps for field navigation.

### Tips

- **Start broad, then narrow down.** Use filters to remove noise first, then use Export Mode to pick a specific region.
- **Google Maps links** work on mobile too — great for field teams navigating to alert locations.
- **GeoJSON export** can be opened in QGIS, Google Earth, or any GIS software for further analysis.
- **CSV export** can be opened in Excel or Google Sheets.
""",
        "pt": """
## Como Usar o Monitor de Desmatamento da Chapada do Araripe

Este painel permite explorar, filtrar e exportar alertas de desmatamento detectados por imagens de satélite na Chapada do Araripe.

### Passo 1: Filtrar Alertas

O painel carrega sempre o **histórico completo de alertas** para que você possa comparar novas detecções com tudo o que veio antes. Use a **barra lateral** (painel esquerdo) para refinar a visualização:

- **Confiança do Alerta** — Escolha os níveis de confiança (Alta, Média, Baixa). Alertas de alta confiança são os mais confiáveis.
- **Atividade Recente → Últimas execuções (N)** — Alertas das últimas *N* execuções de detecção recebem um selo 🆕 na tabela e aparecem primeiro. A detecção roda duas vezes por semana, então N = 1 ≈ alguns dias, N = 4 ≈ duas semanas.
- **Atividade Recente → Mostrar apenas recentes** — Esconde tudo exceto essas últimas *N* execuções, quando você só quer ver as novidades.

Ao alterar os filtros, as **métricas** (topo da página) e a **tabela do Explorador de Alertas** se atualizam instantaneamente.

### Passo 2: Ver no Mapa

Pressione o botão **Ver no Mapa** na barra lateral. Isso atualiza o mapa para mostrar apenas os alertas dos filtros atuais e ajusta o zoom.

> **Por que um botão?** Renderizar o mapa é pesado. Atualizá-lo a cada mudança de filtro deixaria o app lento. O botão permite ajustar os filtros primeiro e atualizar o mapa uma só vez.

### Passo 3: Explorar a Tabela de Alertas

Abaixo do mapa você encontrará o **Explorador de Alertas** — uma tabela ordenável com todos os alertas filtrados:
- ID do alerta, data de detecção, nível de confiança
- Área em hectares
- Coordenadas de latitude/longitude

### Passo 4: Modo de Exportação (Selecionar e Baixar)

Quando estiver satisfeito com os alertas filtrados no mapa:

1. Pressione o botão **Modo de Exportação** (canto superior direito da seção do mapa).
2. O mapa recarrega com **ferramentas de desenho** no lado esquerdo.
3. Use a ferramenta de **retângulo** ou **polígono** para desenhar uma área no mapa.
4. Todos os alertas **dentro da área desenhada** aparecem em uma tabela abaixo.
5. Baixe os alertas selecionados como **CSV** ou **GeoJSON**.
6. Cada linha de alerta inclui um **link do Google Maps** — clique para ver a localização exata no Google Maps para navegação em campo.

### Dicas

- **Comece amplo, depois refine.** Use os filtros para remover ruído primeiro, depois use o Modo de Exportação para selecionar uma região específica.
- **Links do Google Maps** funcionam no celular também — ótimo para equipes de campo navegando até os locais de alerta.
- **Exportação GeoJSON** pode ser aberta no QGIS, Google Earth ou qualquer software GIS para análise adicional.
- **Exportação CSV** pode ser aberta no Excel ou Google Sheets.
""",
    },
    # ── Disclaimer ────────────────────────────────────────────────────────
    "disclaimer": {
        "en": (
            "**Important:** This platform detects vegetation changes using satellite "
            "imagery. It does **not** determine whether a change is legal or illegal — "
            "that determination is the responsibility of the competent environmental "
            "authorities (IBAMA, ICMBio, state agencies). Results may contain errors "
            "due to cloud cover, seasonal variation, or sensor limitations. "
            "**Local field validation is strongly recommended** before any conclusions "
            "are drawn."
        ),
        "pt": (
            "**Importante:** Esta plataforma detecta mudanças na vegetação usando imagens "
            "de satélite. Ela **não** determina se uma mudança é legal ou ilegal — "
            "essa atribuição é responsabilidade das autoridades ambientais competentes "
            "(IBAMA, ICMBio, órgãos estaduais). Os resultados podem conter erros "
            "devido à cobertura de nuvens, variação sazonal ou limitações dos sensores. "
            "**A validação local em campo é fortemente recomendada** antes de qualquer "
            "conclusão."
        ),
    },
}


def t(key: str) -> str:
    """Return the translated string for the current language.

    Falls back to English if the key or language is missing.
    """
    lang = st.session_state.get("language", "pt")
    entry = TRANSLATIONS.get(key, {})
    return entry.get(lang, entry.get("en", f"[{key}]"))

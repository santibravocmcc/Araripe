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
            "Monitoramento semanal de desmatamento por satélite na "
            "Chapada do Araripe (CE/PE/PI, Brasil)"
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
    "min_area_label": {
        "en": "Minimum Area",
        "pt": "Área Mínima",
    },
    "min_area_input": {
        "en": "Min area (ha)",
        "pt": "Área mín. (ha)",
    },
    "min_area_help": {
        "en": "Exclude alerts smaller than this area.",
        "pt": "Excluir alertas menores que esta área.",
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
            "Os filtros atualizam a tabela e métricas instantaneamente. "
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
O **Monitor de Desmatamento do Araripe** detecta perda de vegetação na
Chapada do Araripe usando imagens de satélite do Sentinel-2 e Landsat.

**Principais funcionalidades:**
- Processamento automatizado semanal via GitHub Actions
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
- Automação: GitHub Actions (cron semanal)
        """,
    },
    "last_detection": {
        "en": "Last detection run: **{date}** | {n} detection files",
        "pt": "Última detecção: **{date}** | {n} arquivos de detecção",
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
            "Código aberto | "
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
            "1. **Filter** — Use the sidebar to set date range, confidence, and minimum area\n"
            "2. **View on Map** — Press the button in the sidebar to update the map\n"
            "3. **Explore** — Browse the Alert Explorer table below the map\n"
            "4. **Export** — Press **Export Mode** above the map to select and download alerts"
        ),
        "pt": (
            "**Como usar este painel:**\n"
            "1. **Filtrar** — Use a barra lateral para definir período, confiança e área mínima\n"
            "2. **Ver no Mapa** — Pressione o botão na barra lateral para atualizar o mapa\n"
            "3. **Explorar** — Navegue pela tabela do Explorador de Alertas abaixo do mapa\n"
            "4. **Exportar** — Pressione **Modo de Exportação** acima do mapa para selecionar e baixar alertas"
        ),
    },
    # ── Guide / Instructions tab ─────────────────────────────────────────
    "tab_guide": {
        "en": "Guide",
        "pt": "Guia",
    },
    "guide_title": {
        "en": "User Guide",
        "pt": "Guia do Usuário",
    },
    "guide_body": {
        "en": """
## How to Use the Araripe Deforestation Monitor

This dashboard lets you explore, filter, and export deforestation alerts detected by satellite imagery across Chapada do Araripe.

### Step 1: Filter Alerts

Use the **sidebar** (left panel) to narrow down alerts:

- **Date Range** — Select the start and end dates for alerts you want to see.
- **Alert Confidence** — Choose confidence levels (High, Medium, Low). High-confidence alerts are the most reliable.
- **Minimum Area** — Exclude small alerts below a certain size in hectares.

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
## Como Usar o Monitor de Desmatamento do Araripe

Este painel permite explorar, filtrar e exportar alertas de desmatamento detectados por imagens de satélite na Chapada do Araripe.

### Passo 1: Filtrar Alertas

Use a **barra lateral** (painel esquerdo) para refinar os alertas:

- **Período** — Selecione as datas de início e fim dos alertas que deseja ver.
- **Confiança do Alerta** — Escolha os níveis de confiança (Alta, Média, Baixa). Alertas de alta confiança são os mais confiáveis.
- **Área Mínima** — Exclua alertas menores que um certo tamanho em hectares.

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

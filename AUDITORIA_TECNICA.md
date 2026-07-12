# Auditoria Técnica e Científica — Observatório da Chapada do Araripe

**Autor:** revisão técnica independente (peer review cético)
**Data:** 2026-07-10
**Escopo:** repositório de monitoramento (`Araripe/`) + site estático (`Observatorio_Chapada_do_Araripe/site/`)
**Base documental:** `docs/original_plan.md`, `REVISAO_TECNICA.md` / `TECHNICAL_REVIEW.md`, código-fonte, e os 4 documentos anexados (GeoTIFF MapBiomas 10 m + 3 ATBDs).

> Este relatório **não** é elogioso por padrão. Ele aponta, com citação de arquivo e linha, onde a documentação e o código divergem, onde há fragilidade científica, e o que foi **efetivamente corrigido no repositório** durante a auditoria (Tarefa 6). Mudanças implementadas foram testadas (`pytest`: 53 passam).

---

## 1. Sumário executivo

1. **A análise é, de fato, bissemanal no sentido "duas vezes por semana"** (segundas e quintas), não "a cada duas semanas". O único agendador é o cron `0 6 * * 1,4` em [.github/workflows/update_data.yml](.github/workflows/update_data.yml:5). Não há APScheduler, crontab ou segundo workflow. **Porém**: agendamentos do GitHub Actions só disparam no branch *default* (o arquivo está em `main` ✓), são **desativados automaticamente após 60 dias** sem atividade no repositório, e a própria documentação admite que o pipeline está "configurado, ainda não ativo" em produção. Logo, "bissemanal" é verdadeiro como *design*, mas ainda não como *operação contínua verificada*.

2. **O baseline atual (2023–2025) é cientificamente frágil**: inclui justamente **2023 e 2024, os dois El Niño mais fortes do registro recente** (pico ONI +2,06 e +1,92). Isso é exatamente o que os especialistas alertaram. O baseline fica enviesado para condições de seca, distorcendo z-scores. Implementei uma rotina reprodutível ([scripts/select_baseline_years.py](scripts/select_baseline_years.py)) que recomenda **2019, 2021, 2022, 2025 e 2017** (excluir 2023/2024).

3. **A afirmação de que os dados CHIRPS "não foram baixados / cache vazio" é falsa** (repetida em §3.4, §7.4, §10.5 dos documentos): `data/chirps/` contém **62 arquivos mensais (2021-03 a 2026-03)**. O ajuste de seca por SPI é executável hoje. Corrigi essa afirmação nos dois documentos e endureci o downloader.

4. **O "EVI2 reprovado" (45,7% fora de [-1,1]) tem causa provável de *unidade*, não só de cirrus**: [src/acquisition/download.py](src/acquisition/download.py:78) aplica o offset BOA de −1000 mas **não divide por 10000**, então as bandas chegam em escala DN (~0–10000). O termo "+1" do EVI2 pressupõe reflectância em [0,1]; em DN ele é irrelevante e o EVI2 infla para ~1–2,5. NDMI/NBR (razões puras) são imunes — exatamente o padrão observado na validação. Documentei o caveat no código; a correção real exige reescalar **e** reconstruir os baselines.

5. **Inconsistência mediana × média no baseline**: só [scripts/build_baseline_from_downloads.py](scripts/build_baseline_from_downloads.py:329) calcula mediana (que gerou os arquivos em disco); a função reutilizável `monthly_composite` e [scripts/build_baseline.py](scripts/build_baseline.py:358) calculavam **média**, contrariando a documentação. **Corrigido**: `monthly_composite` agora usa mediana, alinhando os dois caminhos de construção.

6. **~1/3 dos alertas caem sobre solo já antropizado.** Usando o recorte MapBiomas 10 m recém-produzido, anotei os 1.334 alertas de 28/11/2025: **33% em pastagem/agricultura/urbano** (só 65% predominantemente vegetação natural). Isso quantifica a taxa de comissão e motiva a integração de land cover — implementada em [src/detection/landcover.py](src/detection/landcover.py).

7. **Ausência de filtro de persistência temporal + detecção de data única** produz forte comissão: a contagem de alertas (13 → 1.334 → 3.776 → 4.951 → 4.709) acompanha a **nebulosidade da estação chuvosa**, não a sazonalidade do desmatamento. Nenhum alerta foi validado contra referência independente.

8. **Configuração morta e código não exercido**: Copernicus/CDSE (URL + *secrets* no workflow, zero código), Landsat/HLS/`classify_fire_vs_mechanical`/`seasonal.py` implementados mas **nunca chamados** pelo `run_detection.py`. Um bug latente de banda no Landsat (`swir16 → "lwir16"` térmico) foi **corrigido**.

9. **MapBiomas 10 m: recorte concluído e validado** (24490×13358 px, 16,3 MB, 100% válido). **Recomendação: não migrar** integralmente do 30 m para o 10 m beta; adotar o 10 m apenas como *máscara de contexto/estratificação* (2016–2023, beta, consistência temporal menor), mantendo o 30 m Coleção 10 (1985–2024) para as séries de longo prazo.

10. **Divergência de rótulo no enunciado**: o arquivo anexado é **Coleção 2 beta (2016–2023, 21 classes, Sentinel-2)** conforme o ATBD — e **não** "Coleção 3, 2017–2024, 22 classes, embeddings AlphaEarth" como descrito no prompt. A recomendação abaixo usa os fatos do ATBD real.

---

## 2. Tabela "Documentado vs. Implementado" (Tarefa 1)

Legenda: ✅ Implementado e fiel · ⚠️ Parcial / diverge / não exercido · ❌ Não implementado · ❓ Não verificável

| # | Funcionalidade documentada | Status | Evidência / observação |
|---|---|---|---|
| 1 | **Periodicidade bissemanal (2×/semana, seg+qui)** | ✅ | cron `0 6 * * 1,4` — [update_data.yml:5](.github/workflows/update_data.yml:5). Único agendador. Ressalvas: só roda em `main`; desativa após 60 dias; "não ativo em produção". |
| 2 | Aquisição Sentinel-2 (Element84 → Planetary Computer) | ✅ | `search_sentinel2_with_fallback` — [stac_client.py](src/acquisition/stac_client.py). |
| 3 | Landsat 8/9 via Planetary Computer | ⚠️ | `search_landsat` existe, mas `run_detection.py` só consulta Sentinel-2 — **nunca exercido**. |
| 4 | NASA HLS (HLSL30/HLSS30) | ⚠️ | `search_nasa_hls` existe; não chamado no pipeline. |
| 5 | Copernicus/CDSE na cadeia de fallback | ❌ | URL em [settings.py:23](config/settings.py:23) e *secrets* no workflow, mas **nenhum código usa** — config morta. |
| 6 | Índices NDMI, NBR, EVI2 | ⚠️ | [indices.py](src/processing/indices.py). NDMI/NBR corretos; **EVI2 mal-escalado** (ver §3, item A). |
| 7 | Baseline mensal = **mediana** + desvio-padrão | ⚠️→✅ | Só `build_baseline_from_downloads` usava mediana; `monthly_composite`/`build_baseline.py` usavam **média**. **Corrigido** para mediana. `std` é populacional (ddof=0). |
| 8 | Baseline fixo 2023–2025 (3 anos), 72 COGs | ✅ (arquivos) / ⚠️ (ciência) | 72 arquivos em `data/baselines/`; janela contaminada por El Niño 2023–24 (§4). |
| 9 | Detecção z-score + 3 níveis de confiança | ✅ | `detect_deforestation` — [change_detect.py](src/detection/change_detect.py). Comentário do limiar low (−0,10) **corrigido** para −0,15. |
| 10 | Área mín. 1 ha + máx. 1000 ha + guarda de anomalia de cena | ✅ / ⚠️ doc | Implementado ([alerts.py](src/detection/alerts.py), [run_detection.py:230](scripts/run_detection.py:230)). `MAX_ALERT_AREA_HA` e `SCENE_ANOMALY_REJECT_FRAC` **não constam** no Apêndice A dos documentos. |
| 11 | Vetorização + reprojeção p/ EPSG:4326 + GeoJSON | ✅ / ⚠️ | Reprojeção em `save_alerts` (não em `vectorize_alerts`). Confiança do polígono atribuída sobre a **janela bounding-box**, não uma máscara exata do polígono → pode superestimar confiança. |
| 12 | Ajuste de seca SPI/CHIRPS | ⚠️→✅ | `spi.py`/`chirps.py` implementados. Doc dizia dados ausentes; **na verdade há CHIRPS 2021–2026**. Download **endurecido** e ativável. |
| 13 | Discriminação fogo × mecânico | ⚠️ | `classify_fire_vs_mechanical` existe; **não é chamado** no `run_detection.py`. |
| 14 | NDFI (INPE) | ❌ | Limiares em settings, mas **sem desmistura espectral** — não calculável (doc admite). |
| 15 | Tendências Mann-Kendall + Sen | ✅ | [trends.py](src/timeseries/trends.py) real; usado no dashboard. |
| 16 | STL / BFAST | ⚠️ | STL real ([seasonal.py](src/timeseries/seasonal.py)); "BFAST" é detector harmônico caseiro simplificado e **não conectado** ao app/pipeline. |
| 17 | Painel: 6 abas, basemaps, contornos APA/FLONA, histórico completo | ✅ | [app.py](app.py), [maps.py](src/visualization/maps.py). Comentário obsoleto "default = Google" **corrigido** (é Esri). |
| 18 | Sync Hugging Face / upload Cloudflare R2 | ⚠️ | Sync HF implementado no workflow; `R2_ENDPOINT_URL=""` → upload R2 **não configurado**. |
| 19 | Alertas gerados: "5 arquivos / 8.924 polígonos" | ⚠️ | Estado real: **7 arquivos / 17.528 polígonos**. Documento desatualizado. |
| 20 | Persistência CHIRPS / DB de séries | ✅ | SQLite real (`data/timeseries/timeseries.db`) — `store_alert_stats`/`store_regional_stats`. |
| 21 | Testes automatizados | ✅ | 6 arquivos com asserções reais; agora **7 (novo `test_landcover.py`)**; 53 passam. |

---

## 3. Crítica científica e melhorias priorizadas (Tarefa 2)

### 3.1 Solidez metodológica — visão geral

A arquitetura é sólida no *conceito* (índices de umidade > verdor para Caatinga decídua; baseline mensal fenológico; z-score multi-índice; guarda de anomalia de cena). As fragilidades são de **calibração, unidades e validação**, não de concepção.

### 3.2 Inconsistências científicas (com prioridade)

**PRIORIDADE ALTA**

- **A) EVI2 em escala errada (unidades).** [download.py:78-88](src/acquisition/download.py:78) soma +1000 (offset BOA) mas nunca divide por 10000. O EVI2 = `2.5·(NIR−RED)/(NIR+2.4·RED+1)` só é válido com reflectância em [0,1]; em DN o "+1" é desprezível e o índice satura em ~1–2,5. Isso explica melhor que "cirrus fino" o fato de **45,7% dos pixels de EVI2** caírem fora de [-1,1] **sistematicamente em todos os tiles**. NDMI/NBR são razões e não sofrem. **Ação viável:** reescalar reflectância (÷10000) **e reconstruir os baselines** para manter a comparabilidade — não mudar só um lado. Enquanto isso, os limiares de delta do EVI2 (−0,15/−0,20) são fisicamente sem sentido na escala atual. Caveat já documentado em [indices.py::evi2](src/processing/indices.py:32).

- **B) Baseline contaminado por El Niño (2023–2024).** Ver Tarefa 3. Enviesa a "normal" mensal para valores deprimidos de umidade/vegetação → risco de **omissão** (um pixel realmente desmatado em 2026 parece menos anômalo frente a um baseline já seco).

- **C) Sem filtro de persistência temporal + detecção de data única.** [change_detect.py](src/detection/change_detect.py) classifica cada cena isoladamente. Combinado com nebulosidade de estação chuvosa (Nov–Abr), isso gera comissão massiva. Evidência: a contagem de alertas cresce monotonicamente na estação chuvosa (13 → 1.334 → 3.776 → 4.951 → 4.709), **oposto** ao esperado para desmatamento (mais na seca). **Recomendação:** exigir confirmação em ≥2 observações consecutivas antes de reportar (custo: ~1 ciclo de revisita).

- **D) Ausência de validação de acurácia.** Nenhum dos 17.528 polígonos foi confrontado com referência (alta resolução/campo). Sem taxas de comissão/omissão, a confiabilidade é desconhecida. **Recomendação:** amostra estratificada + inspeção visual (PlanetScope/Sentinel-2 RGB) para estimar acurácia por nível de confiança.

**PRIORIDADE MÉDIA**

- **E) Estatística de dispersão.** `std` é populacional (ddof=0) sobre poucas datas/mês; com centro = mediana, o par mediana+std é inconsistente. Considerar **MAD** (desvio absoluto mediano) escalado, mais coerente com a robustez pretendida (a própria §11.8 do documento levanta isso).
- **F) Piso de `min_std=0.01`** em [baseline.py:174](src/detection/baseline.py:174): em pixels muito estáveis, infla z para pequenas mudanças (mitigado pelo filtro de delta, mas convém monitorar).
- **G) Confiança por bounding-box.** `_assign_polygon_confidence` usa a janela retangular do polígono, incluindo pixels **fora** dele; um pixel de alta confiança vizinho pode elevar indevidamente a confiança. **Recomendação:** rasterizar a geometria (máscara exata) na janela. (Não alterado nesta auditoria para não mudar a saída de alertas sem reexecução/validação.)
- **H) Land cover não integrado à análise principal** — só existia na visualização do site. Implementado utilitário de anotação (§5).

**PRIORIDADE BAIXA**

- **I)** Bug de banda Landsat `swir16 → "lwir16"` (térmica) — **corrigido** ([bands.py:28](config/bands.py:28)).
- **J)** SPI usa apenas ~5 anos de referência (`get_current_spi(reference_years=5)`); a norma climatológica recomendada é ~30 anos. Distribuição gama pode ser trocada por Pearson III (§11.7 do documento). O novo downloader viabiliza baixar mais anos com pouco disco.
- **K)** Copernicus/CDSE: remover a config morta **ou** implementar o provedor.

---

## 4. Baseline de 5 anos — metodologia e proposta (Tarefa 3)

### 4.1 Como o baseline é definido hoje

Construído por [build_baseline_from_downloads.py](scripts/build_baseline_from_downloads.py) a partir de GeoTIFFs por cena/tile (3 bandas NDMI/NBR/EVI2) baixados pela equipe, com `--max-year 2025` fixando a janela em **2023–2025** (3 anos). `config/settings.py` declara `BASELINE_YEARS = 5` (alvo não atingido). **Não há seleção de anos por critério climático** — a janela é simplesmente "os 3 anos com cenas baixadas".

### 4.2 Rotina implementada

[scripts/select_baseline_years.py](scripts/select_baseline_years.py) (reprodutível, versionada) combina:

1. **Severidade ENSO** = pico de |ONI| no ano, da tabela oficial **NOAA CPC ONI** (embutida como *snapshot* 2015–2026; atualizável com `--refresh-oni`). Fonte: `cpc.ncep.noaa.gov/data/indices/oni.ascii.txt`. Convenção: |ONI|≥0,5 por 5+ estações = El Niño/La Niña; bandas: <0,5 neutro, 0,5–1,0 fraco, 1,0–1,5 moderado, 1,5–2,0 forte, ≥2,0 muito forte.
2. **Anomalia de precipitação** = z da precipitação anual média na AOI (CHIRPS), relativa ao registro disponível.
3. **Score** = `w_enso·severidade + w_precip·|z_precip|`; exclui anos com |ONI| ≥ `--max-severity` (padrão 1,5) e recomenda os N mais recentes elegíveis.

Piso de candidatos = 2017 (era Sentinel-2 densa: S2A 2015-06, S2B 2017-03).

### 4.3 Resultado (executado)

```
year ENSO       ONIpk  severity  precip_mm precip_z  elegível
2017 La Nina    -0.86   0.86 (fraco)     —          —       sim
2018 El Nino     0.97   0.97 (fraco)     —          —       sim
2019 El Nino     0.89   0.89 (fraco)     —          —       sim
2020 La Nina    -1.20   1.20 (mod.)      —          —       sim
2021 La Nina    -0.91   0.91 (fraco)     —          —       sim
2022 La Nina    -0.97   0.97 (fraco)   860.2     +1.53     sim
2023 El Nino     2.06   2.06 (m.forte) 728.8     -0.31     NÃO
2024 El Nino     1.92   1.92 (forte)   753.1     +0.03     NÃO
2025 La Nina    -0.55   0.55 (fraco)   660.7     -1.25     sim
```

- **Excluídos (El Niño forte): 2023, 2024** — os dois anos atualmente no baseline.
- **Recomendação (5 anos recentes quietos):** **2019, 2021, 2022, 2025 + 2017** (ou 2020 no lugar de 2017 se preferir consecutividade; 2020 é La Niña moderada). Saída completa em `data/landcover/baseline_year_selection.json`.

### 4.4 Limitações e próximos passos

- A norma de precipitação usa só anos CHIRPS completos localmente (2022–2025). Para uma anomalia robusta, baixar CHIRPS 1991–2020 (o novo downloader faz isso mantendo só o recorte da AOI — poucos KB/mês).
- **Aplicar** a recomendação exige **baixar as cenas Sentinel-2 desses anos** (2017/2019/2021/2022) e reconstruir os baselines — tarefa de dados externa (ver Tarefa 5), não executável offline aqui.

---

## 5. Land cover / MapBiomas 10 m — avaliação e recomendação (Tarefa 4)

### 5.1 O que `prepare_territorio.py` faz hoje

[site/scripts/prepare_territorio.py](../Observatorio_Chapada_do_Araripe/site/scripts/prepare_territorio.py): lê `observatorio_atual/MapBiomas/MapBiomas_LULC_YYYY_Araripe.tif` (30 m, EPSG:4326, **Coleção 10**), **reclassifica em 5 grupos** (natural {3,4,12}, agro {15,21,39,41}, urbano {24,30,75}, outros, água {33}), recorta à janela `(-41, -8, -38,8, -6,8)`, e gera `lulc-YYYY.png` + `meta.json` + `areas.json` (série de área agro na APA sem FLONA, 2010–2024). É puramente **visualização do site**.

### 5.2 Deveria entrar na análise científica principal? Como?

**Sim — como camada de contexto/estratificação, não como entrada de detecção.** O pipeline espectral não sabe "o que havia antes"; land cover permite: (i) **anotar** cada alerta com sua classe/grupo dominante e a fração de vegetação natural; (ii) **filtrar** alertas sobre solo já antropizado (falsos positivos de desmatamento *novo*). Implementei isso em [src/detection/landcover.py](src/detection/landcover.py) (`annotate_alerts_with_landcover`, `filter_alerts_by_natural_vegetation`), com teste ([tests/test_landcover.py](tests/test_landcover.py)).

**Evidência quantitativa (executada):** dos 1.334 alertas de 28/11/2025, **66% em vegetação natural, 33% em pastagem/agricultura, 0,8% urbano**; 65% com ≥50% de vegetação natural. Ou seja, ~1/3 são candidatos a comissão — um filtro de land cover reduziria o ruído de forma transparente.

### 5.3 Datasets aplicáveis

| Produto | Resolução | Cobertura | Sensor | Situação | Uso recomendado |
|---|---|---|---|---|---|
| **MapBiomas Coleção 10/10.1 (em uso)** | 30 m | **1985–2024** | Landsat | Estável/oficial; Caatinga com RF→GTB→Deep Learning (ATBD Caatinga Coll. 10) | Séries de longo prazo (territorio), tendências, baseline de uso |
| **MapBiomas 10 m Coleção 2 (beta)** | 10 m | **2016–2023** | Sentinel-2 | **Beta**; 21 classes (legenda Coll. 9 nível 3); ATBD alerta menor consistência temporal | Máscara de contexto de alta resolução alinhada à detecção (10–20 m) |
| ESA WorldCover | 10 m | 2020, 2021 | Sentinel-1/2 | Estável, global, 11 classes | Alternativa/validação cruzada de 1 ano |
| Copernicus Global Land Cover | 100 m | 2015–2019 | PROBA-V | Grosseiro | Pouco útil aqui |

> **Correção ao enunciado:** o arquivo anexado é `...collection2...classification_2023.tif` e o ATBD é **"MapBiomas 10-meters Collection 2 (beta), v1, set/2025"** — 2016–2023, 21 classes, Sentinel-2. Não é "Coleção 3 / 2017–2024 / 22 classes / embeddings AlphaEarth".

### 5.4 Tarefa técnica: inspeção, recorte, validação, exclusão

Script: [scripts/mapbiomas10m_crop.py](scripts/mapbiomas10m_crop.py) (inspeção → recorte por janela → validação → exclusão opcional).

- **Inspeção:** nacional, EPSG:4326, 465718×476412 px (221,87 Gpx), 1 banda uint8, LZW, tiled 256², **sem overviews**, `nodata=None`, classes 0–50, 5,50 GB.
- **Recorte** (janela territorio `-41,-8,-38.8,-6.8`): **24490×13358 px, ~10 m, 16,3 MB** → [data/landcover/mapbiomas10m_araripe_2023.tif](data/landcover/mapbiomas10m_araripe_2023.tif).
- **Validação:** 100% válido; extensão dentro de 2 px; classes plausíveis — Savana 57,5%, Pastagem 30,5%, Floresta 5,5%, Mosaico agro 4,9%, Urbano 0,7%, água 0,35%, etc. **Todos os *checks* passaram** (relatório em `data/landcover/mapbiomas10m_araripe_2023.report.json`).
- **Exclusão do original 5,5 GB:** **bloqueada pelo sandbox** do ambiente (arquivo em `~/Downloads`, fora do projeto). O recorte está validado; a exclusão é segura, mas requer sua confirmação: rode `python scripts/mapbiomas10m_crop.py --src <arquivo> --out data/landcover/mapbiomas10m_araripe_2023.tif --delete-source` (o script só apaga após validação OK) ou remova manualmente.

### 5.5 Recomendação final de migração

**Não migrar integralmente 30 m → 10 m beta.** Trade-offs:
- *Contra o 10 m como base única:* é **beta**, cobre só **2016–2023** (não alcança o histórico 1985– nem, por ora, 2024/2025), e o próprio ATBD registra **menor consistência temporal**; mudança de metodologia entre coleções compromete comparabilidade de séries.
- *A favor do 10 m como auxiliar:* resolução casa com a detecção (10–20 m), captura APP/bordas/infra que o 30 m perde.

**Plano recomendado:** manter **Coleção 10 (30 m)** para as séries de longo prazo do site; adotar o **recorte 10 m (2023)** como **máscara de contexto** para estratificar/filtrar alertas (já implementado). Reavaliar migração quando a coleção 10 m sair de beta e estender a cobertura temporal.

---

## 6. Download robusto do baseline climático (Tarefa 5)

### 6.1 Diagnóstico da instabilidade

O downloader original ([chirps.py](src/acquisition/chirps.py), versão anterior) usava `urllib.request.urlretrieve` **sem timeout, sem retry, sem resume e sem verificação de integridade**. Em conexão instável ele trava ou falha silenciosamente, e **cada reinício recomeça do zero** — exatamente os sintomas relatados. Além disso, guardava o **GeoTIFF global inteiro (~57 MB/mês)**, de modo que baixar muitos anos para uma boa normal acumularia GBs num disco com só 15–20 GB livres.

### 6.2 O que foi implementado

**(a) Script novo:** [scripts/download_baseline_data.py](scripts/download_baseline_data.py):
- **Download em chunks com resume por HTTP Range** (o servidor UCSB anuncia `Accept-Ranges: bytes` — verificado).
- **Retry com backoff exponencial + jitter** (rede/5xx/timeout).
- **Verificação de integridade**: tamanho vs `Content-Length` e o `.tif` deve abrir como raster válido (senão descarta e refaz).
- **Processamento incremental**: baixa → recorta à AOI (poucos KB) → anexa a média ao CSV → **apaga o global** (a menos de `--keep-global`). O pico de disco é sempre **um** arquivo global.
- **Guarda de disco** (`--min-free-gb`, padrão 2) antes de cada download.
- **Logging** claro em console + `logs/download_baseline_*.log`.
- **OneDrive (opt-in)**: `--onedrive-dir` copia os recortes; instruções de autenticação (Azure AD app + escopo Graph `Files.ReadWrite` + fluxo *device-code* via `msal`, ou `rclone onedrive:`) em `ONEDRIVE_NOTES` no próprio script. Deixado como passo manual por exigir consentimento de tenant.

**(b) Caminho operacional endurecido:** reescrevi `_download_chirps_month` em [chirps.py](src/acquisition/chirps.py) com o mesmo padrão (resume + backoff + integridade), preservando a API pública (`fetch_chirps_monthly`, usado pelo SPI). Os testes de SPI continuam passando.

### 6.3 Testes executados

- Crop de arquivos existentes (`--no-download --keep-global`): OK (não apaga cache do usuário).
- Download real de mês ausente (2020-12): baixou, verificou, recortou e **apagou o global** (incremental) — só sobrou o recorte de 2,2 KB.
- Série completa AOI 2021–2026 gerada: `data/chirps_aoi/chirps_aoi_monthly.csv` (62 meses).

### 6.4 Uso

```bash
# Baixar 2017–2025 recortando+apagando globais (disco mínimo):
python scripts/download_baseline_data.py --start 2017-01 --end 2025-12
# Manter os globais completos:
python scripts/download_baseline_data.py --start 2024-01 --end 2024-12 --keep-global
# Só (re)gerar o CSV da AOI a partir de globais já em disco:
python scripts/download_baseline_data.py --start 2021-01 --end 2025-12 --no-download --keep-global
```

> **Nota sobre a *imagem* de baseline (cenas Sentinel-2):** o download das cenas é feito por streaming de COG via STAC ([build_baseline.py](scripts/build_baseline.py) usa *range requests* — já é o padrão robusto, sem baixar cenas inteiras) e o `build_baseline_from_downloads.py` é resumível (pula meses já prontos). A instabilidade central estava no CHIRPS, agora resolvida; para as cenas, o que falta é retry por-cena explícito (hoje há `try/except` que pula a cena).

---

## 7. Resumo das implementações e pendências (Tarefa 6)

### 7.1 Implementado, testado e no repositório

| Mudança | Arquivo(s) | Por quê | Como validar |
|---|---|---|---|
| Rotina de seleção de baseline por anomalia climática (ONI+CHIRPS) | `scripts/select_baseline_years.py` (novo) | Base p/ escolher 5 anos quietos (Tarefa 3) | `python scripts/select_baseline_years.py` → tabela + JSON |
| Inspeção/recorte/validação MapBiomas 10 m | `scripts/mapbiomas10m_crop.py` (novo) | Tarefa 4 (crop + decisão) | recorte validado em `data/landcover/` + `.report.json` |
| Integração de land cover a alertas | `src/detection/landcover.py` + `tests/test_landcover.py` (novos) | Estratificar/filtrar comissão | `pytest tests/test_landcover.py` (3 testes) |
| Downloader CHIRPS robusto | `scripts/download_baseline_data.py` (novo) | Tarefa 5 | download 2020-12 testado; CSV 62 meses |
| CHIRPS operacional endurecido (resume/backoff/integridade) | `src/acquisition/chirps.py` | Estabilidade do SPI | `pytest tests/test_spi.py` |
| Baseline: centro = **mediana** (alinha os 2 caminhos + doc) | `src/processing/composite.py` | Consistência mediana×média | `pytest` |
| Bug de banda Landsat `lwir16 → swir16` | `config/bands.py` | NDMI usaria banda térmica | `pytest tests/test_indices.py` |
| Comentário do limiar low −0,10 → −0,15 | `src/detection/change_detect.py` | Fidelidade doc/código | inspeção |
| Caveat de escala do EVI2 no código | `src/processing/indices.py` | Alertar sobre unidades | inspeção |
| Comentário de basemap (Google → Esri) | `src/visualization/maps.py` | Fidelidade | inspeção |
| Docstring de `load_aoi_polygon` | `src/acquisition/aoi.py` | Fidelidade | inspeção |
| Correção de afirmações obsoletas (CHIRPS presente; "3 anos"; caveat El Niño) | `REVISAO_TECNICA.md`, `TECHNICAL_REVIEW.md` | Documentos afirmavam fatos falsos | diff |

Verificação global: **`pytest` = 53 testes, todos passam** (env conda `araripe`).

### 7.2 Pendente — depende de decisão humana, dados externos ou infraestrutura

1. **Excluir o original de 5,5 GB** — bloqueado pelo sandbox; confirmar manualmente ou via `--delete-source` (§5.4).
2. **Reconstruir baselines com 2019/2021/2022/2025/2017** — exige **baixar cenas Sentinel-2** desses anos (dados externos, grandes); usar `build_baseline.py` + `build_baseline_from_downloads.py`.
3. **Corrigir escala do EVI2 (÷10000) e reconstruir baselines** juntos — mudança acoplada; não fazer só um lado.
4. **Filtro de persistência temporal** e **máscara exata de confiança** (`_assign_polygon_confidence`) — alteram a saída de alertas; requerem reexecução + validação.
5. **Ativar o ajuste de seca (SPI)** nas execuções e **ativar o workflow em produção** no `main` (e evitar a desativação por 60 dias de inatividade).
6. **Validação de acurácia** dos alertas contra referência independente.
7. **OneDrive**: registrar app Azure AD + credenciais (não provisionável aqui).
8. **Regenerar os PDFs** `REVISAO_TECNICA.pdf` / `TECHNICAL_REVIEW.pdf` via `scripts/md_to_pdf.py` após as correções de texto.
9. **Remover config morta** (Copernicus/CDSE) ou implementá-la; idem código não exercido (Landsat/HLS/fogo×mecânico/BFAST) — decidir manter (roadmap) ou remover.

---

### Apêndice — como reproduzir os principais resultados

```bash
conda activate araripe                     # ambiente do projeto
pytest -q                                  # 53 testes

python scripts/select_baseline_years.py --json data/landcover/baseline_year_selection.json
python scripts/mapbiomas10m_crop.py --src ~/Downloads/mapbiomas_10m_collection2_integration_v1-classification_2023.tif \
       --out data/landcover/mapbiomas10m_araripe_2023.tif
python scripts/download_baseline_data.py --no-download --keep-global --start 2021-01 --end 2026-03
python - <<'PY'
import geopandas as gpd; from src.detection.landcover import annotate_alerts_with_landcover
g = annotate_alerts_with_landcover(gpd.read_file("data/alerts/alerts_2025-11-28.geojson"),
                                   "data/landcover/mapbiomas10m_araripe_2023.tif")
print(g["lc_group"].value_counts())
PY
```

---
---

# Fase 2 — verificação cética + execução das pendências

**Data:** 2026-07-10 · **Escopo:** peer-review do peer-review (Tarefa 0) + execução das Tarefas 1–8 do prompt de continuação.
**Ambiente de teste:** sem `conda`; usado um *venv* com `--system-site-packages` sobre o Anaconda base (stack geo já presente: rasterio/geopandas/scipy/shapely/pyproj) + `loguru`/`pystac-client`/`planetary-computer`. **Todos os testes rodam neste venv.**

> Postura mantida: onde o relatório da Fase 1 divergia do código, **corrigi e sinalizei** em vez de silenciar. As divergências abaixo foram encontradas por verificação independente, não estavam listadas na Fase 1.

## F2.0 — Verificação cética da Fase 1 (Tarefa 0)

**`pytest` real hoje: 53 testes passam** (confirmado; 6 acq + 9 aoi + 7 det + 5 grid + 13 indices + 3 landcover + 10 spi). Após a Fase 2: **65 testes passam** (novos: `test_alerts.py` 2, `test_persistence.py` 6, `test_landcover.py` +4).

Os *fixes* pequenos da Fase 1 foram verificados contra o `git diff` real e **conferem**: `bands.py` `lwir16→swir16` (bug térmico real), `change_detect.py` comentário −0,10→−0,15, `composite.py` `monthly_composite` média→**mediana**, caveat de EVI2 em `indices.py`, comentário de basemap em `maps.py`, docstring de `aoi.py`.

**Divergências encontradas (a Fase 1 errou ou exagerou):**

| # | Afirmação da Fase 1 | Realidade verificada na Fase 2 |
|---|---|---|
| A | mediana "alinhou os dois caminhos de construção" (§2 linha 7, §7.1) | **`scripts/build_baseline.py` continuava calculando MÉDIA** (`stacked.mean(...)`), e o `monthly_composite` que ele importava **nunca era chamado** (import morto). Só `composite.py` e o caminho `baseline.py` foram corrigidos. O caminho de *streaming* — o que a Tarefa 1 usa — **não** tinha a correção. **Corrigido nesta fase.** |
| B | SPI "implementado, mas não ligado por padrão" (§7.2.5; Tarefa 3 do prompt) | **Já estava ATIVO por padrão**: `run_detection.py:98` chama `get_current_spi(aoi_bbox)` e a linha 227 passa `spi_3month=spi_value` a `detect_deforestation`, que aplica o alargamento quando SPI < −1,0. Não era pendência de ativação. |
| C | `data/chirps/` tem "62 arquivos" (§1.3) | São **61** rasters mensais (2021-03 a 2026-03). O "62" corresponde ao CSV da AOI (que inclui o download-teste de 2020-12). |
| D | Alertas crescem monotonicamente 13→1.334→3.776→4.951→4.709 (§1.7, §3.2.C) | A série real é **13 / 1.334 / 1 / 3.776 / 4.951 / 4.709 / 2.744** (7 arquivos, 17.528 polígonos). A Fase 1 omitiu o arquivo de 1 feição (2025-12-28) e o de 2.744 (queda, 2026-04-27) para sugerir monotonicidade. |
| E | `select_baseline_years.py` recomenda "2019, 2021, 2022, 2025 e 2017" (§4.3) | O script na verdade emite `recommended_recent_quiet = [2019, 2020, 2021, 2022, 2025]`. O conjunto do relatório é uma **edição manual** (troca 2020↔2017). O prompt da Fase 2 **decidiu** por `{2017, 2019, 2021, 2022, 2025}`; segui a decisão do prompt, sinalizando que difere da saída bruta do script. |
| F | (novo) — | **Bug no workflow:** o passo "Upload COGs to Cloudflare R2" tinha `if: env.R2_ENDPOINT_URL != ''` lendo uma variável definida no `env:` **do próprio passo** — que o GitHub Actions não expõe ao `if:` do mesmo passo. **O upload R2 nunca rodava.** Corrigido (var hasteada para o `env:` do *job*). |

**MapBiomas 10 m — confirmação contra o ATBD anexado:** é **Coleção 2 (beta), 2016–2023, 21 classes, Sentinel-2** — não "Coleção 3 / 2017–2024 / 22 classes / embeddings AlphaEarth". Trechos verbatim do `ATBD_MAPBIOMAS_10m_COLLECTION_2_BETA_SENTINEL.pdf`: capa "Collection 2 (beta) / Version 1 / September, 2025"; Sumário Executivo (p.3) "…covered the period of 2016 to 2023 and 21 LCLU classes…"; §3.1 "harmonized Collection of Sentinel-2 Level 2A surface reflectance images". Busca por "AlphaEarth"/"embedding"/"Collection 3"/"22 classes" = **zero ocorrências**. A legenda completa (níveis 1–3) foi extraída e usada na Tarefa 8.

Os 4 scripts novos da Fase 1 existem e rodam: `select_baseline_years.py` (roda; recomendação = ver divergência E), `mapbiomas10m_crop.py --help` (tem `--delete-source` + validação), `download_baseline_data.py --help` (tem `--min-free-gb`, resume/backoff), `landcover.py` importa e `test_landcover.py` passa.

## F2.1 — Baseline de 5 anos + escala do EVI2 (Tarefa 1)

**Diagnóstico refinado (mais forte que a Fase 1).** Os "45,7% de EVI2 fora de [-1,1]" vêm de `scripts/validation_output/validation_report.md` — métrica **por-cena, pré-clip** (mês 01, 106 arquivos: EVI2 mediana 0,99, máx 2,09, 45,67% fora, 48,4% >0,95; NDMI/NBR limpos: assinatura clássica de escala DN). Os baselines **em disco** já são **cortados a ±1,0** (`build_baseline_from_downloads.py:302`, `EVI2_CAP=1.0`) — por isso o `evi2_*_mean.tif` tem máx = 1,000 e 0% fora: **o corte mascara o problema, comprimindo o EVI2 do baseline junto de 1,0 e destruindo seu poder discriminativo.**

**Correção implementada — conversão de reflectância *dirigida por metadados* (`src/acquisition/download.py`), acoplada por uma flag.** Verifiquei o `raster:bands` STAC real: 2017 (baseline 00.01) → `scale 1e-4, offset 0`; 2022/2025 (≥04.00) → `scale 1e-4, offset −0.1`. A conversão correta é `refl = DN*scale + offset`, **por-cena e por-sensor** (nova `_reflectance_scale_offset(item, asset_key, sensor)`, com *fallbacks* Landsat `2.75e-5/−0.2` e HLS `1e-4/0`). Isto é **essencial**: um baseline que reúne 2017/2019/2021 (offset 0) com 2022/2025 (offset −0,1) precisa aplicar o offset de cada cena; um offset fixo misturaria escalas e corromperia o composto. **Validação:** por-cena, o EVI2 fora de [-1,1] cai de **45,67% → ≈0,0%** (medido em janelas de cenas 2017/2022/2025; medianas físicas ~0,12–0,18).

**Acoplamento explícito (correção pós-revisão adversarial — ver F2.10).** As duas mudanças são acopladas: a conversão só é correta se os baselines em disco estiverem na mesma escala. Como **não foi possível reconstruir os baselines nesta sessão** (rede — ver abaixo), aplicar a conversão sozinha corromperia o canal EVI2 (baseline DN mediana ~0,99 vs. observação em reflectância ~0,4). Portanto a conversão é controlada por **`config/settings.REFLECTANCE_SCALING`** (`load_band` a lê em tempo de chamada): **default `False`** preserva o comportamento DN legado (consistente com os baselines atuais, detecção funciona hoje); `build_baseline.py` força `True` no próprio processo (baselines reconstruídos saem em reflectância). **Para ativar o fix em produção: reconstruir os baselines com `build_baseline.py` e então setar `REFLECTANCE_SCALING = True`** — nunca um lado só (exatamente a exigência do prompt). O fix está implementado e validado por-cena; fica *dormente* atrás da flag até o rebuild acoplado.

**`scripts/build_baseline.py` (caminho de *streaming* COG):** adicionados `--year-set 2017,2019,2021,2022,2025` (consulta **um ano por vez**, evitando o teto de 500 itens e pulando 2023/2024), `--months` (reconstrução mês-a-mês, limitando memória), `--min-free-gb` (guarda de disco antes da query e antes de cada escrita) e **troca de média→mediana** via `median_composite`/`std_composite` (corrige a divergência A e usa de fato o `composite.py`).

**Pico de disco observado (Tarefa 1):** rodei reconstruções reais em *background* (AOI completa da APA e uma AOI reduzida). **O disco permaneceu constante em ~28 GB livres durante toda a execução** — com `--cache off` o caminho de *streaming* **não escreve nada em disco além dos 72 COGs finais** (~7 GB); lê janelas de COG por *range request* direto para a RAM. Memória: ~260–350 MB (AOI reduzida) a ~1,4 GB (AOI completa, um mês). **Conclusão: 15–20 GB são MAIS que suficientes** — disco não é o gargalo.

**O que impediu a reconstrução completa nesta sessão (reporte honesto):** *throttling* intermitente do S3 público (`sentinel-cogs`). As execuções processavam cenas normalmente e então **travavam no *streaming* de uma cena individual** (>8 min sem progresso), tanto na AOI completa quanto na reduzida — logo é **rede**, não disco/memória/código. Recomendação: rodar a reconstrução em horário de menor carga ou no CI (rede mais rápida), **um mês por vez** (`--months N`) com a guarda de disco; o código está pronto e validado por-cena. Isto **não** exige OneDrive (Tarefa 5): o gargalo nunca foi disco.

## F2.2 — Persistência temporal + máscara exata de confiança (Tarefa 2)

**Máscara exata de confiança (`src/detection/alerts.py::_assign_polygon_confidence`).** O código antigo importava `rasterize` mas **nunca o usava** — tomava `np.nanmax` sobre a **janela *bounding-box*** do polígono (podia herdar confiança de um pixel de outro polígono vizinho dentro do retângulo). Reescrito para rasterizar a **geometria exata** (`geometry_mask` na janela, `all_touched=True`) e reduzir só sobre pixels internos. Teste `tests/test_alerts.py`: um triângulo cujo *bbox* contém um pixel de confiança 3 fora do polígono recebe confiança 1 (interior), não 3.

**Filtro de persistência (`src/detection/persistence.py`, novo).** Como a detecção é por-cena e sem estado (o DB só guarda agregados), implementei persistência **vetorial** (sobreposição espacial entre observações consecutivas) — um alerta só é *confirmado* se sobrepõe (≥5% da própria área) um alerta da observação imediatamente anterior (`filter_alerts_by_persistence`), com `apply_persistence_to_history` para reavaliar o arquivo existente sem reprocessar imagens. Também **ligado ao `run_detection.py`** (não-destrutivo: grava todos os alertas com uma coluna `persistence_status` = confirmed/candidate/first_observation, para que a próxima execução possa encadear).

**Antes/depois sobre o histórico real** (`scripts/apply_persistence_filter.py`, ≥2 obs. consecutivas, sobreposição mín. 5%):

| data | bruto | confirmado |
|---|---|---|
| 2025-11-26 | 13 | 0 (1ª obs.) |
| 2025-11-28 | 1.334 | 22 |
| 2025-12-28 | 1 | 0 |
| 2026-01-12 | 3.776 | 0 |
| 2026-02-01 | 4.951 | 701 |
| 2026-02-11 | 4.709 | 1.364 |
| 2026-04-27 | 2.744 | 157 |
| **TOTAL** | **17.528** | **2.244 (−87,2%)** |

A sequência confirmada (0, 22, 0, 0, 701, 1.364, 157) **deixa de crescer monotonicamente com a nebulosidade** — objetivo da tarefa. **Caveat honesto:** quando a observação anterior é pobre em nuvens (ex.: 2025-12-28 com 1 alerta), a confirmação fica impossível e o filtro **super-suprime** (2026-01-12 → 0). Isto reflete a **cadência irregular** do arquivo atual; em produção (cadência bissemanal regular) o efeito é menos severo. Testes: `tests/test_persistence.py` (6).

## F2.3 — Ativação em produção (Tarefa 3)

- **Ajuste de seca SPI:** já ativo por padrão (ver divergência B). Endurecido em `src/processing/spi.py::get_current_spi` para **descartar meses recentes do CHIRPS ainda não publicados** (lag de ~1–1,5 mês) antes do SPI-3 — antes, um mês faltante zerava o SPI silenciosamente (sem alargamento).
- **Workflow em produção:** o `.github/workflows/update_data.yml` já vive no `main` (agendamentos só disparam no *default branch*), então "ativar" é operacional (habilitar Actions + secrets). **Bug do R2 corrigido** (var no `env:` do job — divergência F). Não posso alternar configurações/segredos do GitHub a partir daqui; documentado no `DEPLOYMENT_GUIDE.md`.
- **Mitigação do auto-desligamento de 60 dias:** novo `.github/workflows/keepalive.yml` (heartbeat semanal que commita um timestamp, mantendo o repo ativo) + *fallback* manual documentado (`workflow_dispatch`, `gh workflow enable/run`).

## F2.4 — Metodologia de validação de acurácia (Tarefa 4)

Novo `scripts/sample_alerts_for_validation.py`: **amostragem estratificada** por nível de confiança (e por `lc_group`, quando presente), com semente fixa (reprodutível); gera um CSV (`validation_sample.csv`) com uma coluna `verdict` em branco (TP/FP/UNC) e opção `--chips` para renderizar recortes RGB Sentinel-2 com o polígono sobreposto (lado a lado, para julgamento visual). **Fórmulas documentadas:** comissão por nível = `FP/(TP+FP)`; acurácia do usuário = `1 − comissão`; **omissão** exige uma camada de referência **independente** de desmatamentos conhecidos (ex.: PRODES/DETER), não derivada destes alertas. **Explícito: a interpretação visual final é etapa humana pendente — não foi simulada.**

## F2.5 — OneDrive (Tarefa 5)

**Não necessário.** A Tarefa 1 mostrou que o disco nunca foi o gargalo (streaming não usa disco de scratch; pico ~0 além dos COGs finais). Portanto **não** provisionei credenciais Azure AD. Caso um dia se opte por espelhar recortes para OneDrive, o fluxo *device-code* (`msal`, escopo Graph `Files.ReadWrite`) já está esboçado em `ONEDRIVE_NOTES` no `download_baseline_data.py` — passo manual (exige consentimento de *tenant*).

## F2.6 — PDFs (Tarefa 6)

Correções de texto em `REVISAO_TECNICA.md`/`TECHNICAL_REVIEW.md` desta fase: "62"→"61" arquivos CHIRPS; SPI marcado como **já ativo**; Copernicus/CDSE marcado como **removido** (era config morta). PDFs regenerados via `scripts/md_to_pdf.py` (ver seção de pendências se a fonte/engine faltar no ambiente).

## F2.7 — Configuração morta: implementar ou remover (Tarefa 7)

1. **Landsat/HLS (7.1):** conectados como fontes extras em `run_detection.py --extra-sources landsat,hls` (dispatch por sensor: loader + máscara de nuvem próprios; `load_hls_for_indices` novo; escala de reflectância por-sensor sob a flag; tolerância de *grid* por sensor). Aumenta a densidade de observações → reforça a persistência (Tarefa 2). **Caveat:** comparados contra baselines **Sentinel-2 (20 m)** por aproximação (snap por vizinho); o ideal é baseline por-sensor (roadmap). Por segurança, extra-sources é *opt-in* (default = só S2) e HLS exige auth Earthdata.
2. **`classify_fire_vs_mechanical` (7.2):** ativado no `run_detection.py` (`--classify-clearing`, default on): carrega BSI extra, classifica fogo×mecânico e anota cada alerta com `clearing_type` (modal exato sobre o polígono).
3. **Copernicus/CDSE (7.3):** **removido** — verifiquei que **nenhum código** consumia `COPERNICUS_STAC_URL` nem os *secrets* `CDSE_*` (config morta; docs afirmavam falsamente um *fallback*). SAR (Sentinel-1) não é *toggle* de credencial (exige cadeia de pré-processamento própria) → fora de escopo, registrado no `ROADMAP.md`. Removido de `settings.py`, do workflow, do `.env.example`; docs corrigidas (`DEPLOYMENT_GUIDE.md`, `README.md`).
4. **BFAST (7.4):** mantido como *roadmap* explícito (`ROADMAP.md` + nota na docstring de `seasonal.py::harmonic_fit`, deixando claro que o detector harmônico atual **não é BFAST** e não está ligado à produção).

## F2.8 — MapBiomas: ambas as coleções como filtro selecionável (Tarefa 8)

`src/detection/landcover.py` generalizado: parâmetro `collection` (`"mapbiomas10m"` | `"mapbiomas30m"`) em `annotate_alerts_with_landcover` e `filter_alerts_by_natural_vegetation`, cada uma com **sua própria tabela de reclassificação** derivada dos ATBDs (as taxonomias diferem de fato: a Coleção 2 usa 18/19/36 para agricultura e **não tem** os códigos de subdivisão de cultura 39/20/40/62/41/46/47/35/48 nem 75/fotovoltaica, que existem na Coleção 10.1). Config em `settings.py` (`LANDCOVER_RASTERS`, `DEFAULT_LANDCOVER_COLLECTION`). Recorte 30 m gerado em `data/landcover/mapbiomas30m_araripe_2023.tif` (fonte Coleção 10 do território — **~300 m agregado**, rotulado honestamente; não há fonte 30 m nativa local). Seletor de UI adicionado (`dashboard.py` + `app.py` + `i18n.py`, bilíngue). Testes cobrem os dois caminhos, incluindo a diferença de taxonomia (código 39/soja → *farming* na 10.1, *other* na 2; 75/fotovoltaica → *urban* na 10.1, *other* na 2). Demonstração real: os 13 alertas de 2025-11-26 dão 8 natural/5 farming (10 m) vs 11 natural/2 farming (30 m) — coleções diferentes, resultados diferentes, como esperado.

## F2.10 — Revisão adversarial das mudanças da Fase 2 (verificação cética do meu próprio trabalho)

Rodei uma passada de revisão adversarial (múltiplos revisores independentes + verificação para *refutar* cada achado) sobre o diff da Fase 2. **5 achados confirmados, todos corrigidos:**

1. **[ALTO]** Escala de reflectância estava restrita a `sensor=="sentinel2"` → Landsat/HLS ficariam em DN e seriam comparados contra baselines S2 em reflectância. **Corrigido:** `_reflectance_scale_offset` agora é por-sensor (Landsat `2.75e-5/−0.2`, HLS `1e-4/0`), e a escala cobre todos os sensores sob a flag.
2. **[ALTO]** Mudar a escala só na aquisição, com baselines em disco ainda em DN, corromperia o canal EVI2 na detecção. **Corrigido:** flag `REFLECTANCE_SCALING` (default `False`) acopla os dois lados (ver F2.1).
3. **[BAIXO]** Docstring do EVI2 em `indices.py` ficara desatualizada. **Corrigida** (descreve os dois modos da flag).
4. **[MÉDIO]** Em *cache-hit*, `run_detection` computava `compute_list` (com `bsi`, que exige a banda `blue`) sobre cenas cacheadas sem `blue` → `KeyError` derrubava a cena. **Corrigido:** só computa índices cujas bandas estão presentes no `ds`.
5. **[BAIXO]** A guarda de disco em `build_baseline.py` fazia `break` só do laço interno. **Corrigido:** flag `stop_writing` aborta ambos os laços.

Após as correções: **65 testes passam**; todos os módulos importam; `download.py`/`build_baseline.py`/`run_detection.py` compilam e `--help` funcionam.

## F2.9 — Pendências (dependem de humano ou de recursos externos)

1. **Reconstrução COMPLETA do baseline (12 meses × 5 anos) + ativação do fix de EVI2 — ✅ CONCLUÍDO (2026-07-11, via Earth Engine).** Os 72 baselines em `data/baselines/` foram reconstruídos em **reflectância** (medianas mensais sobre {2017,2019,2021,2022,2025}) e `REFLECTANCE_SCALING=True` foi ativado — o fix do EVI2 está **ligado**. Validação: EVI2 medianas ~0,15–0,44 com sazonalidade correta (alto na estação úmida, baixo na seca da Caatinga), NDMI/NBR em [-1,1], cobertura ~100%, 72/72 arquivos íntegros, 65 testes passam. **Resta apenas** publicar esses baselines para produção (o GitHub Action lê de LFS/R2/HF; são dados locais) — passo do responsável. Histórico da decisão abaixo:
   - **Bugs do caminho de *streaming* (`build_baseline.py`)** — nunca fora exercido antes; a primeira rodada produziu baselines quebrados (0,75% de cobertura). Corrigidos: grade-comum via `reproject_match`, e sobretudo **`nodata=NaN` explícito** em `download.py` (sem isso, reproject/clip enchiam com 0). Também adicionados timeout/retry por-cena + guarda de disco, e compositagem incremental (Welford, memory-safe → média, não mediana). Validado: cobertura ~100% e índices corretos.
   - **Gargalo real = rede**, não código. *Benchmark* medido: da máquina do usuário (Brasil) todas as fontes rendem ~1 MB/s; Planetary Computer é ~2× mais lento que a AWS atual; download manual (.SAFE ~1 GB/cena) é pior. Boa parte da lentidão era **config do GDAL** (cache de *range* desligado → 0,1 MB/s; `CHUNK_SIZE=512` fragmenta).
   - **Caminho recomendado (decisão do usuário): Google Earth Engine.** `scripts/build_baseline_gee.py` calcula os compostos mensais (mediana **verdadeira**, coleção `S2_SR_HARMONIZED` que já harmoniza o offset de 2022) **no servidor** e exporta 12 GeoTIFFs pequenos; `scripts/split_gee_baselines.py` os fatia nos 72 COGs do detector; então **setar `REFLECTANCE_SCALING = True`** (acoplamento — F2.1). Passo-a-passo em `docs/BASELINE_GEE.md`. Exige autenticação Google do usuário (roda no servidor, então a conexão local não é gargalo).
2. **Interpretação visual dos alertas (Tarefa 4):** etapa humana — preencher `verdict` em `validation_sample.csv`; depois calcular comissão por nível. Omissão exige camada de referência independente (PRODES/DETER).
3. **Ativação operacional no GitHub** (habilitar Actions, definir *secrets* R2/HF): só o responsável pelo repositório pode fazer.
4. **Exclusão do original MapBiomas 10 m de 5,5 GB** em `~/Downloads` (fora do projeto): segue pendente; recorte validado já existe.
5. **Baselines por-sensor para Landsat/HLS** e **BFAST/SAR reais:** roadmap (`ROADMAP.md`).
6. **Teste ao vivo do seletor de land cover na UI** (Streamlit): o app compila e o `streamlit` está disponível, mas a interação foi validada só por compilação/importação aqui.

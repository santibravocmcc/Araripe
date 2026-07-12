# Revisão Técnica: Sistema de Monitoramento de Desmatamento da Chapada do Araripe

**Versão:** 2.0
**Data:** 12/07/2026
**Preparado para:** Revisão por pares especialistas (sensoriamento remoto, monitoramento ambiental)

---

## 0. O que mudou na versão 2.0 (após a auditoria técnica)

Esta versão incorpora as correções e melhorias da auditoria técnica (detalhes e
justificativas em `AUDITORIA_TECNICA.md`; explicação em linguagem simples em
`COMO_FUNCIONA.md`). As mudanças de maior impacto científico:

1. **Baseline reconstruído em refletância, sobre 5 anos climaticamente "calmos"
   {2017, 2019, 2021, 2022, 2025}** — substituindo a janela 2023–2025, que estava
   contaminada pelos dois El Niño mais fortes do período (2023/2024). Calculado no
   **Google Earth Engine** (mediana verdadeira por mês, coleção `S2_SR_HARMONIZED`).
2. **Correção de escala do EVI2** (refletância `DN·scale + offset`, por-cena/sensor)
   acoplada ao rebuild do baseline via a flag `REFLECTANCE_SCALING` (agora `True`).
   Elimina os ~45,7% de EVI2 fora de [-1,1] que motivavam o *cap* artificial em 1,0.
3. **Filtro de persistência temporal** (≥2 observações consecutivas com sobreposição
   espacial) — reduz a comissão da estação chuvosa (~-87% no histórico).
4. **Máscara de confiança por geometria exata** do polígono (não mais pela janela
   *bounding-box*), evitando herança de confiança de polígonos vizinhos.
5. **Integração de land cover (MapBiomas)** à análise: anotação de cada alerta por
   classe/grupo dominante, com **as duas coleções selecionáveis** (10 m Coleção 2 e
   30 m Coleção 10), cada uma com sua tabela de reclassificação.
6. **Ajuste de seca (SPI/CHIRPS) confirmado ativo** por padrão e endurecido
   (descarte de meses ainda não publicados).
7. **Configuração morta removida** (Copernicus/CDSE) e **código antes não exercido
   ligado** (Landsat/HLS como fontes extras opcionais; discriminação fogo×mecânico).
8. **Caminho de produção via Google Earth Engine + Cloudflare R2**: baselines
   publicados no R2 e baixados sob demanda pelo CI; detecção de 2026 reprocessada
   via GEE (ver §9.3). Painel público migrado do Streamlit para **site estático**.

O restante deste documento foi atualizado para refletir esse estado. Onde uma
afirmação da v1.1 se tornou obsoleta, o texto foi corrigido no lugar.

---

## 1. Resumo Executivo

O Sistema de Monitoramento de Desmatamento da Chapada do Araripe é um pipeline de detecção de mudanças em tempo quase real, projetado para gerar alertas bissemanais (duas vezes por semana) de desmatamento e degradação para a região da Chapada do Araripe, no nordeste do Brasil. O sistema ingere imagens multiespectrais de satélite (Sentinel-2 L2A como fonte primária; Landsat 8/9 Collection 2 e NASA HLS como fontes extras opcionais) via APIs STAC abertas, calcula índices espectrais sensíveis à umidade e à vegetação (NDMI, NBR, EVI2) e detecta perda anômala de vegetação por meio de desvio z-score em relação a baselines mensais. Os baselines são construídos a partir de uma janela de referência de **5 anos climaticamente "calmos" — {2017, 2019, 2021, 2022, 2025}** — em **refletância de superfície**. O calendário 2026 em diante é reservado exclusivamente para a etapa de detecção, garantindo uma comparação clara contra um baseline congelado.

O sistema foi projetado para operar com custo recorrente zero. A automação bissemanal usa **GitHub Actions**; os baselines são armazenados como Cloud Optimized GeoTIFF (COG) no **Cloudflare R2** e baixados sob demanda pelo CI antes da detecção; o **painel público é um site estático** (Cloudflare Pages), tendo substituído o painel Streamlit/Hugging Face original. As saídas de detecção são polígonos de alerta vetorizados em formato GeoJSON, classificados em três níveis de confiança (alto, médio, baixo) com unidade mínima de mapeamento de 1 hectare, anotados com a classe de uso do solo (MapBiomas) e com um estado de persistência temporal.

**Status operacional atual:** O código-fonte completo está implementado e funcional. Os baselines mensais (**72 arquivos COG, em refletância**) foram reconstruídos via Google Earth Engine para todos os 12 meses em três índices espectrais e publicados no R2. O histórico de detecção acumulava **7 arquivos de alerta / 17.528 polígonos** (nov/2025 a abr/2026); a detecção de **2026 está sendo reprocessada via GEE** com o baseline novo (ver §9.3). Os dados de precipitação CHIRPS **estão presentes** (2021-03 a 2026-03) e o ajuste de seca por SPI **está ativo**. O pipeline de automação bissemanal foi endurecido (busca os baselines no R2, correção do gate de R2) e depende apenas de habilitar os Actions e definir os *secrets* no repositório.

---

## 2. Área de Estudo

### 2.1 Contexto Geográfico

A Chapada do Araripe é um planalto sedimentar no nordeste do Brasil, situado nas divisas dos estados do Ceará, Pernambuco e Piauí. Eleva-se a aproximadamente 800--1.000 m de altitude acima das terras baixas semiáridas do Sertão. A área de interesse (AOI) é definida pela caixa delimitadora:

- **Oeste:** -40,0°
- **Sul:** -8,0°
- **Leste:** -39,0°
- **Norte:** -7,0°

Isso corresponde a uma área de aproximadamente 111 km x 111 km (cerca de 12.321 km²), projetada em **EPSG:32724** (WGS 84 / UTM zona 24S). O polígono da AOI está armazenado em `data/aoi/chapada_araripe.gpkg`.

### 2.2 Significância Ecológica

A Chapada do Araripe ocupa uma zona de transição biogeográfica onde três grandes biomas brasileiros convergem:

- **Cerrado** (savana brasileira) no topo do planalto, com formações de cerrado sentido restrito denso e campo cerrado.
- **Caatinga** (floresta/arbustal tropical sazonalmente seco) nas encostas inferiores e terras baixas circundantes, caracterizada por vegetação decídua e semidecídua com comportamento extremo de perda foliar sazonal.
- **Mata Atlântica** relictual em enclaves úmidos nas encostas orientais, sustentada por precipitação orográfica.

A região abriga duas unidades de conservação importantes:

- **FLONA Araripe** (Floresta Nacional do Araripe) -- uma das primeiras florestas nacionais estabelecidas no Brasil (1946), cobrindo aproximadamente 38.600 ha.
- **APA Chapada do Araripe** (Área de Proteção Ambiental) -- uma área de proteção ambiental de aproximadamente 1.063.000 ha que abrange o planalto mais amplo e seus arredores.

### 2.3 Justificativa do Monitoramento

A Chapada do Araripe enfrenta múltiplas ameaças que justificam o monitoramento contínuo por satélite:

1. **Desmatamento para expansão agrícola e de pastagens**, particularmente ao longo das bordas do planalto e nas terras baixas da Caatinga.
2. **Extração seletiva ilegal de madeira** para produção de carvão vegetal e materiais de construção.
3. **Incêndios florestais**, que são frequentes durante a estação seca (agosto--outubro) e exacerbados por eventos de El Niño.
4. **Expansão urbana**, particularmente nas proximidades das cidades de Crato, Juazeiro do Norte e Barbalha.
5. **Degradação dos recursos hídricos** -- o planalto do Araripe é uma zona crítica de recarga para nascentes que abastecem mais de 1 milhão de pessoas.

A fenologia decídua da vegetação da Caatinga representa um desafio particular para o sensoriamento remoto óptico: a perda foliar sazonal natural pode imitar sinais de desmatamento quando se utilizam índices baseados em verdor, como o NDVI. Esta foi uma consideração primária de projeto do sistema de monitoramento.

---

## 3. Fontes de Dados e Aquisição

### 3.1 Imagens de Satélite

O sistema foi projetado para ingerir imagens de três programas de satélite complementares, proporcionando redundância espacial e temporal.

#### 3.1.1 Sentinel-2 L2A (Fonte Primária)

- **Satélites:** Sentinel-2A, 2B e 2C (ESA Copernicus)
- **Nível de processamento:** Level-2A (reflectância de superfície / fundo de atmosfera)
- **Resolução espacial:** 10 m (B2, B3, B4, B8), 20 m (B5, B6, B7, B8A, B11, B12)
- **Tempo de revisita:** ~5 dias no equador (com 3 satélites)
- **Bandas utilizadas para cálculo de índices:**
  - B4 (Vermelho, 665 nm) -- para EVI2
  - B8 (NIR amplo, 842 nm) -- para EVI2
  - B8A (NIR estreito, 865 nm) -- para NDMI, NBR
  - B11 (SWIR1, 1610 nm) -- para NDMI
  - B12 (SWIR2, 2190 nm) -- para NBR
  - SCL (Scene Classification Layer) -- para máscara de nuvens
- **Collection ID:** `sentinel-2-l2a` (Element84), `sentinel-2-c1-l2a` (Copernicus)

O sistema opera na resolução de 20 m para o pipeline de detecção, compatível com a resolução nativa das bandas SWIR utilizadas pelos índices primários (NDMI, NBR).

#### 3.1.2 Landsat 8/9 Collection 2

- **Nível de processamento:** Collection 2, Level 2 (reflectância de superfície)
- **Resolução espacial:** 30 m (todas as bandas de reflectância)
- **Tempo de revisita:** ~8 dias (Landsat 8 + 9 combinados)
- **Máscara de nuvens:** Banda QA_PIXEL (flags bit a bit, Bit 3 = nuvem, Bit 4 = sombra de nuvem)
- **Collection ID:** `landsat-c2-l2`

#### 3.1.3 NASA HLS (Harmonized Landsat Sentinel)

- **Produtos:** HLSL30 v2.0 (derivado do Landsat) e HLSS30 v2.0 (derivado do Sentinel-2)
- **Resolução espacial:** 30 m (harmonizado em grade comum)
- **Máscara de nuvens:** Banda Fmask (Bit 1 = nuvem, Bit 2 = nuvem adjacente/sombra, Bit 3 = sombra de nuvem)
- **Autenticação:** Requer credenciais NASA Earthdata (via biblioteca `earthaccess`)

### 3.2 Endpoints da API STAC e Cadeia de Fallback

A aquisição de dados é implementada em `src/acquisition/stac_client.py` utilizando a biblioteca `pystac-client`. O sistema consulta múltiplos endpoints de API STAC com uma estratégia de fallback automática:

| Prioridade | Provedor | URL | Autenticação |
|------------|----------|-----|--------------|
| 1 | Element84 Earth Search | `https://earth-search.aws.element84.com/v1` | Não requerida |
| 2 | Microsoft Planetary Computer | `https://planetarycomputer.microsoft.com/api/stac/v1` | Assinatura de token SAS via pacote `planetary-computer` |
| 3 | NASA CMR STAC | `https://cmr.earthdata.nasa.gov/stac/LPCLOUD` | Login NASA Earthdata |
| 4 | ~~Copernicus Data Space~~ | ~~`https://stac.dataspace.copernicus.eu/v1`~~ | **Removido na Fase 2** — era config morta (nenhum código o consumia; não havia fallback real, apesar de docs antigas afirmarem o contrário). Sentinel-1 SAR via CDSE é *roadmap* (ver ROADMAP.md) |

A lógica de fallback para consultas Sentinel-2 é: Element84 primeiro; se zero resultados, Planetary Computer. Consultas Landsat e HLS podem ser adicionadas como fontes extras de observação via `run_detection.py --extra-sources landsat,hls` (Fase 2, Tarefa 7.1).

### 3.3 Parâmetros de Consulta

- **Cobertura máxima de nuvens:** 20% (`MAX_CLOUD_COVER`)
- **Janela de busca:** 16 dias (`SEARCH_DAYS_BACK`)
- **Máximo de itens por consulta:** 50 (`MAX_ITEMS_PER_SEARCH`)
- **Porcentagem mínima de pixels claros para cenas do baseline:** 10% (`MIN_CLEAR_PERCENTAGE_BASELINE`)

### 3.4 Dados de Precipitação CHIRPS

O ajuste de seca depende de estimativas mensais de precipitação do **Climate Hazards Group InfraRed Precipitation with Station data (CHIRPS)** versão 2.0:

- **URL de origem:** `https://data.chc.ucsb.edu/products/CHIRPS-2.0/global_monthly/tifs`
- **Resolução:** 0,05° (~5,5 km)
- **Cobertura temporal:** 1981--presente
- **Diretório de cache:** `data/chirps/`
- **Status atual (atualizado na auditoria 2026-07, revisado na Fase 2):** O cache local `data/chirps/` contém **61 arquivos globais** mensais de CHIRPS, de 2021-03 a 2026-03 (contagem verificada na Fase 2; a Fase 1 dizia "~62"). Não são versionados no Git, portanto ausentes do repositório remoto. O download foi tornado robusto na auditoria (retry com backoff, retomada por *range* e verificação de integridade) em `src/acquisition/chirps.py` e no novo `scripts/download_baseline_data.py`. **O ajuste de seca por SPI já está ATIVO por padrão** em `scripts/run_detection.py` (chama `get_current_spi` e o passa a `detect_deforestation`) — a Fase 2 confirmou que não era um item "a ativar", e reforçou a robustez descartando meses recentes ainda não publicados do CHIRPS.

---

## 4. Índices Espectrais

Três índices espectrais formam o núcleo do pipeline de detecção. A seleção prioriza índices sensíveis à umidade em vez de índices puramente baseados em verdor, especificamente para enfrentar o desafio da deciduidade da Caatinga.

### 4.1 NDMI -- Normalized Difference Moisture Index (Primário)

**Fórmula:**

    NDMI = (NIR - SWIR1) / (NIR + SWIR1)

**Mapeamento de bandas:**
- Sentinel-2: (B8A - B11) / (B8A + B11) a 20 m
- Landsat: (B5 - B6) / (B5 + B6) a 30 m

**Significado físico:** O NDMI quantifica o conteúdo de água nos dosséis vegetais explorando o contraste entre a reflectância no NIR (alta para vegetação saudável) e a reflectância no SWIR1 (absorvida pela água foliar). Valores típicos variam de -0,5 (solo exposto/rocha) a +0,6 (vegetação densa e bem hidratada).

**Justificativa para Caatinga/Cerrado:** O NDMI é sensível ao estresse hídrico do dossel independentemente do verdor. Espécies decíduas da Caatinga perdem suas folhas durante a estação seca, mas a estrutura lenhosa retém uma assinatura de umidade diferente da de áreas desmatadas ou queimadas. O NDVI, em contraste, cai drasticamente durante a queda foliar natural, gerando falsos sinais de desmatamento. O NDMI apresenta menor amplitude sazonal em vegetação intacta, tornando-o mais confiável para distinguir desmatamento antrópico de mudanças fenológicas.

**Papel no pipeline:** Índice primário de detecção. Necessário para alertas de confiança média e alta. Validado como limpo nos dados do baseline (valores dentro de [-0,56; 0,55], média 0,058).

**Implementação:** `src/processing/indices.py::ndmi()`

### 4.2 NBR -- Normalized Burn Ratio (Primário)

**Fórmula:**

    NBR = (NIR - SWIR2) / (NIR + SWIR2)

**Mapeamento de bandas:**
- Sentinel-2: (B8A - B12) / (B8A + B12) a 20 m
- Landsat: (B5 - B7) / (B5 + B7) a 30 m

**Significado físico:** O NBR é estruturalmente similar ao NDMI, mas utiliza a banda SWIR2 de comprimento de onda mais longo (2190 nm), que é mais sensível à umidade do solo e às assinaturas de carvão/cinza. É o índice padrão para mapeamento de severidade de queimada (dNBR).

**Justificativa:** O NBR complementa o NDMI fornecendo sensibilidade ao desmatamento relacionado a incêndios, que é um importante vetor de perda de vegetação na região do Araripe. A banda SWIR2 também penetra camadas finas de fumaça melhor do que as bandas visíveis, tornando o NBR mais robusto durante as estações de incêndios ativos.

**Papel no pipeline:** Índice primário de detecção junto com o NDMI. Ambos devem sinalizar um pixel para classificação de alta confiança. Também utilizado para discriminação entre incêndio e desmatamento mecânico via dNBR (delta NBR). Validado como limpo nos dados do baseline (valores dentro de [-0,58; 0,75], média 0,279).

**Limiares adicionais para detecção de incêndios:**
- dNBR > 0,27: Queimada de baixa severidade (`DNBR_LOW_SEVERITY`)
- dNBR > 0,66: Queimada de alta severidade (`DNBR_HIGH_SEVERITY`)
- NBR pós-incêndio < 0,1: Confirma assinatura de incêndio (`NBR_POST_FIRE_THRESHOLD`)

**Implementação:** `src/processing/indices.py::nbr()`, `src/processing/indices.py::dnbr()`

### 4.3 EVI2 -- Enhanced Vegetation Index 2 (Confirmatório)

**Fórmula:**

    EVI2 = 2.5 * (NIR - RED) / (NIR + 2.4 * RED + 1)

**Mapeamento de bandas:**
- Sentinel-2: 2.5 * (B8 - B4) / (B8 + 2.4 * B4 + 1) a 10 m
- Landsat: 2.5 * (B5 - B4) / (B5 + 2.4 * B4 + 1) a 30 m

**Significado físico:** O EVI2 é uma simplificação de duas bandas do EVI completo (que requer a banda azul). O fator de escala 2,5 amplifica o sinal de vegetação, enquanto o termo de ajuste de solo (2,4 * RED + 1) reduz os efeitos da reflectância de fundo do solo. Diferentemente do NDVI, o EVI2 não satura em dosséis de alta biomassa. Note que o EVI2 NÃO é limitado ao intervalo [-1, 1] devido ao multiplicador 2,5; no entanto, valores acima de ~1,0 são fisicamente irrealistas para vegetação natural.

**Justificativa:** O EVI2 fornece um complemento sensível ao verdor em relação ao NDMI e NBR, baseados em umidade. Embora compartilhe parte da sensibilidade à deciduidade do NDVI, é menos afetado pela dispersão atmosférica e pelo fundo de solo. Pode detectar desmatamento que envolve remoção de dossel sem alterar a umidade do solo (por exemplo, extração seletiva de madeira).

**Limitação (revisada na v2.0):** A validação da v1.1 encontrou 45,7% dos pixels de EVI2 fora de [-1, 1] (P99 = 1,74) e atribuiu isso a cirrus finos. A auditoria mostrou que a **causa dominante era de unidade/escala**: a aquisição somava o *offset* BOA mas **não dividia por 10000**, deixando as bandas em escala DN (~0–10000); como o termo "+1" da fórmula do EVI2 pressupõe refletância em [0,1], o índice inflava para ~1–2,5. NDMI e NBR, sendo razões puras, são imunes — exatamente o padrão observado. **Correção (v2.0):** conversão para refletância dirigida por metadados (`DN·scale + offset`, por-cena/sensor), acoplada ao rebuild do baseline via `REFLECTANCE_SCALING = True`. Após a correção, o EVI2 por-cena fica em ~0% fora de [-1, 1], **sem** o *cap* artificial em 1,0 da v1.1. Contaminação por cirrus fino ainda pode elevar marginalmente valores individuais, mas deixou de ser sistemática.

**Papel no pipeline:** Índice confirmatório. Pode disparar alertas de baixa confiança independentemente, mas não pode elevar para confiança média ou alta sem concordância do NDMI ou NBR.

**Implementação:** `src/processing/indices.py::evi2()`

### 4.4 Por que o NDVI Foi Despriorizado

Embora o NDVI esteja implementado no código-fonte (`src/processing/indices.py::ndvi()`), ele não é utilizado no pipeline de detecção. Na vegetação da Caatinga, o NDVI cai de 0,3 a 0,5 unidades durante a estação seca (agosto--outubro) devido à deciduidade completa, o que produziria alertas falso-positivos generalizados. Os meses de queda foliar da Caatinga são explicitamente definidos na configuração (`CAATINGA_LEAFOFF_MONTHS = [8, 9, 10]`).

### 4.5 Índices Adicionais Disponíveis

Os seguintes índices estão implementados, mas são utilizados apenas para análise complementar, não para detecção primária:

- **SAVI** (Soil-Adjusted Vegetation Index): `1.5 * (NIR - RED) / (NIR + RED + 0.5)`. Útil em áreas de Caatinga esparsa onde o solo exposto contribui para a reflectância do pixel.
- **BSI** (Bare Soil Index): `((SWIR1 + RED) - (NIR + BLUE)) / ((SWIR1 + RED) + (NIR + BLUE))`. Utilizado para confirmar desmatamento quando combinado com quedas nos índices de vegetação, e no módulo de discriminação entre incêndio e desmatamento mecânico.

---

## 5. Construção do Baseline

### 5.1 Abordagem de Projeto

O sistema de detecção utiliza uma abordagem de baseline por mês: para cada um dos 12 meses do calendário, um resumo estatístico pixel a pixel (tendência central e variabilidade) é calculado a partir de múltiplos anos de observações históricas. Isso captura o ciclo fenológico da vegetação, de modo que uma observação de janeiro é comparada com a distribuição histórica de janeiro em vez de uma média anual.

### 5.2 Dados de Origem

Os baselines atuais (v2.0) foram construídos no **Google Earth Engine (GEE)** a partir da coleção `COPERNICUS/S2_SR_HARMONIZED`, que harmoniza automaticamente o *offset* de refletância introduzido na *Processing Baseline* 04.00 (2022). A janela de referência é o conjunto de **5 anos climaticamente "calmos": {2017, 2019, 2021, 2022, 2025}**, selecionado para excluir 2023 e 2024 — os dois El Niño mais fortes do registro recente (ver §5.5 e `AUDITORIA_TECNICA.md`, Tarefa 3). O ano de 2026 em diante é usado apenas para detecção. Os dados de origem:

- **Fonte:** Sentinel-2 L2A (`S2_SR_HARMONIZED`), **refletância de superfície** (as bandas são divididas por 10000 no servidor, de modo que os índices ficam na escala física correta).
- **Máscara de nuvens:** classes claras da SCL {2, 4, 5, 6, 7, 11}, aplicada por-pixel antes da composição.
- **Cobertura espacial:** toda a AOI da APA (mosaico das tiles UTM feito server-side).
- **SRC:** EPSG:32724 (UTM zona 24S), **Resolução:** 20 m.
- **Bandas exportadas:** os 3 índices de detecção (NDMI, NBR, EVI2), cada um com mediana e desvio-padrão mensais.

> **Por que GEE.** A construção por *streaming* de COG a partir do S3 público (`scripts/build_baseline.py`) está implementada e validada, mas o gargalo real era a **rede** (throttling do S3 a partir do Brasil, ~1 MB/s), que inviabilizava reconstruir os 60 compostos localmente. O GEE executa a mediana no servidor e exporta apenas 12 GeoTIFFs pequenos, contornando esse gargalo. Scripts: `scripts/build_baseline_gee.py` / `docs/gee_baseline_cloudshell.py` (cálculo) e `scripts/split_gee_baselines.py` (fatiamento nos 72 COGs do detector). Passo-a-passo em `docs/BASELINE_GEE.md`.

### 5.3 Pipeline de Processamento

Para cada mês, a construção do baseline (no GEE) procede da seguinte forma:

1. **Filtro temporal e espacial** -- A coleção é filtrada pela AOI e pelos meses-calendário correspondentes ao longo dos 5 anos selecionados.
2. **Máscara de nuvens + refletância + índices** -- Cada cena é mascarada pela SCL, convertida para refletância e transformada em NDMI/NBR/EVI2 (a mesma preparação `prep()` usada na detecção via GEE, garantindo que baseline e observação fiquem na mesma escala).
3. **Composição temporal** -- Para cada mês, calcula-se a **mediana** e o **desvio padrão** pixel a pixel sobre todas as cenas dos 5 anos. A mediana é preferida à média por robustez a outliers (nuvens residuais, sombras). A mediana verdadeira é viável no GEE (todo o *stack* fica no servidor).
4. **Exportação** -- Os compostos mensais são exportados para o Google Drive e, na máquina local, fatiados em 72 arquivos `{index}_month{MM}_{mean,std}.tif` por `split_gee_baselines.py`, que restaura o sentinela de no-data e grava `nodata=NaN`.

> **Sem *cap* de EVI2.** Ao contrário da v1.1 — que aplicava `EVI2_CAP = 1.0` para conter a cauda irreal do EVI2 em escala DN — a v2.0 não precisa desse corte: com a refletância correta, o EVI2 já cai na faixa física esperada (medianas ~0,15–0,44, com a sazonalidade correta). O *cap* mascarava o problema de unidade e comprimia artificialmente o sinal (ver §4.3 e §8.2).

> **Nota sobre o *streaming* como *fallback*.** O caminho `scripts/build_baseline.py` (streaming COG, mediana, `nodata=NaN`, guarda de disco, retry por-cena) permanece disponível e corrigido — útil no CI (rede rápida) ou como alternativa ao GEE.

### 5.4 Saída

A construção do baseline produz **72 arquivos COG**:

    3 índices (NDMI, NBR, EVI2) x 12 meses x 2 estatísticas (média/mediana, std) = 72 arquivos

Convenção de nomenclatura: `{index}_month{MM}_mean.tif` e `{index}_month{MM}_std.tif`

Todos os 72 arquivos de baseline foram reconstruídos com sucesso (via GEE) e estão armazenados em `data/baselines/` (e publicados no R2). Nota: embora os nomes de arquivo utilizem o sufixo `_mean`, a estatística realmente calculada é a **mediana**. Esta convenção de nomenclatura foi herdada do projeto original do pipeline e mantida por compatibilidade com o carregador (`load_baseline_pair`).

### 5.5 Profundidade Temporal

A configuração especifica um objetivo de 5 anos de histórico (`BASELINE_YEARS = 5`), agora **atingido**: os baselines v2.0 usam **{2017, 2019, 2021, 2022, 2025}**, com 2026 reservado para detecção. **[Auditoria 2026-07]** A janela anterior (2023--2025) incluía justamente 2023 e 2024 — os dois anos de El Niño mais fortes do registro recente (pico ONI +2,06 e +1,92) —, o que enviesava o baseline em direção a condições de seca e aumentava o risco de **omissão** (um pixel realmente desmatado em 2026 parece menos anômalo frente a um "normal" já seco). O script `scripts/select_baseline_years.py` seleciona, de forma reprodutível, os anos recentes com menor anomalia climática (combinando severidade ENSO/ONI e anomalia de precipitação CHIRPS na AOI); a decisão adotada foi {2017, 2019, 2021, 2022, 2025}, excluindo 2023 e 2024. Ver `AUDITORIA_TECNICA.md`, Tarefa 3. Ressalva remanescente: 5 anos ainda podem não cobrir toda a variabilidade interanual extrema; estender a janela conforme mais cenas quietas sejam adquiridas segue recomendado.

### 5.6 Inspeção Visual dos Baselines

Para verificação rápida da cobertura espacial e do ciclo fenológico, o script `scripts/plot_baselines.py` gera figuras 4×3 (uma por índice e estatística) em `data/baselines/plots/`. Cada painel mostra a distribuição mensal do índice com os contornos da APA Chapada do Araripe (amarelo) e da FLONA Araripe-Apodi (verde) sobrepostos, além do percentual de pixels válidos no título. Esses arquivos não vão para a Hugging Face Space (a pasta `data/baselines/` é ignorada na sincronização) e servem somente para auditoria interna do baseline.

---

## 6. Método de Detecção de Mudanças

### 6.1 Visão Geral

O método de detecção é uma abordagem de **detecção de anomalias por z-score** com confirmação multi-índice. Uma nova observação de satélite é comparada pixel a pixel com o baseline mensal, e os pixels que apresentam diminuições estatisticamente significativas nos índices de vegetação/umidade são sinalizados como alertas potenciais de desmatamento.

A lógica de detecção está implementada em `src/detection/change_detect.py::detect_deforestation()`.

### 6.2 Cálculo do Z-Score

Para cada índice, o z-score mede quantos desvios padrão a observação atual se desvia do baseline histórico para o mês correspondente:

    z = (atual - baseline_mean) / baseline_std

Z-scores negativos indicam uma diminuição no valor do índice (perda de vegetação). O baseline_std é limitado inferiormente a um valor pequeno para prevenir divisão por zero.

### 6.3 Delta (Mudança Absoluta)

Além do z-score, um delta absoluto é calculado:

    delta = atual - baseline_mean

Isso fornece um filtro secundário para evitar que alertas sejam disparados por pequenas mudanças absolutas que possuem um z-score elevado (por exemplo, pixels com variabilidade de baseline muito baixa).

### 6.4 Classificação de Confiança

Os alertas são classificados em três níveis de confiança com base na concordância entre limiares de z-score, limiares de delta e o número de índices confirmatórios. A classificação segue uma abordagem hierárquica em que os níveis de confiança mais altos têm precedência.

#### Alta Confiança (confiança = 3)

Requisitos (TODOS devem ser atendidos):
- z-score < -3,0 (`Z_THRESHOLD_HIGH`) em **ambos** NDMI e NBR
- delta < -0,20 (`DELTA_THRESHOLD_HIGH`) em **ambos** NDMI e NBR

Este é o nível mais conservador, exigindo concordância entre dois índices de umidade independentes com grande desvio estatístico e mudança absoluta substancial.

#### Confiança Média (confiança = 2)

Requisitos (TODOS devem ser atendidos):
- z-score < -2,5 (`Z_THRESHOLD_MEDIUM`) em **pelo menos um** índice de umidade (NDMI ou NBR)
- delta < -0,15 (`DELTA_THRESHOLD_MEDIUM`) no mesmo índice

Ambas as condições são necessárias para evitar a sinalização de variação interanual normal que possa cruzar um único limiar.

#### Baixa Confiança (confiança = 1)

Requisitos (TODOS devem ser atendidos):
- z-score < -2,0 (`Z_THRESHOLD_LOW`) em **qualquer** índice individual (NDMI, NBR ou EVI2)
- delta < -0,15 (`DELTA_THRESHOLD_LOW`) no mesmo índice

### 6.5 Área Mínima de Alerta

Os pixels detectados são vetorizados em polígonos de componentes conexos, e polígonos com área inferior a **1,0 hectare** (`MIN_ALERT_AREA_HA`) são descartados. Na resolução de 20 m, 1 ha corresponde a 25 pixels, o que fornece um filtro espacial razoável contra ruído.

### 6.6 Vetorização e Saída

O processo de vetorização está implementado em `src/detection/alerts.py::vectorize_alerts()`:

1. O raster de confiança é binarizado no nível mínimo de confiança.
2. Componentes conexos são extraídos usando `rasterio.features.shapes()`.
3. A área de cada polígono é calculada em hectares (assumindo que o SRC projetado está em metros).
4. Polígonos abaixo da área mínima são descartados.
5. A cada polígono sobrevivente é atribuído o valor **máximo de confiança** encontrado **dentro da sua geometria exata**. *(Correção v2.0: antes o cálculo usava a janela retangular — *bounding-box* — do polígono, podendo herdar a confiança de um pixel de outro polígono vizinho dentro do retângulo; agora rasteriza a geometria com `geometry_mask` e reduz só sobre pixels internos.)*
6. Os polígonos são reprojetados de EPSG:32724 (UTM) para EPSG:4326 (WGS 84) para saída em GeoJSON.
7. Metadados (data de detecção, timestamp de criação, rótulo de confiança) são anexados.
8. A saída é salva como `data/alerts/alerts_{YYYY-MM-DD}.geojson`.

### 6.7 Discriminação entre Incêndio e Desmatamento Mecânico

Um módulo auxiliar de classificação (`src/detection/change_detect.py::classify_fire_vs_mechanical()`) distingue a causa do desmatamento detectado:

- **Incêndio:** dNBR > 0,27 E NBR pós-incêndio < 0,1
- **Desmatamento mecânico:** BSI elevado sem assinatura de carvão (BSI > 0,1, dNBR > 0,05, sem máscara de incêndio)
- **Incerto:** Alguma mudança detectada (dNBR > 0,1) mas não corresponde claramente a nenhum dos padrões

*(v2.0: este módulo, antes implementado mas nunca chamado, foi **ligado ao pipeline** — cada alerta recebe um campo `clearing_type` = fogo/mecânico/incerto/nenhum, atribuído pela classe modal sobre a geometria exata do polígono.)*

### 6.8 Persistência Temporal (novo na v2.0)

A detecção é por-cena e sem estado. Para conter a comissão de fenômenos
transitórios (nuvem/sombra/água temporária), a v2.0 adiciona um **filtro de
persistência vetorial** (`src/detection/persistence.py`): um alerta só é marcado
`confirmed` se **sobrepõe espacialmente** (≥5% da própria área, `min_overlap_frac`)
um alerta da observação imediatamente anterior; caso contrário fica `candidate`
(ou `first_observation` na primeira data). O filtro é **não-destrutivo** — grava
todos os alertas com o campo `persistence_status`, permitindo encadear
observações sucessivas sem reprocessar imagens.

**Antes/depois no histórico real** (≥2 obs. consecutivas, sobreposição mín. 5%):
a sequência bruta 13 / 1.334 / 1 / 3.776 / 4.951 / 4.709 / 2.744 (17.528 no total)
cai para 0 / 22 / 0 / 0 / 701 / 1.364 / 157 confirmados (**2.244; −87,2%**), e
**deixa de crescer monotonicamente com a nebulosidade**. Ressalva honesta: quando
a observação anterior é pobre (ex.: cena muito nublada, 1 alerta), a confirmação
fica impossível e o filtro super-suprime — efeito atenuado por uma cadência
bissemanal regular. Testes: `tests/test_persistence.py`.

---

## 7. Ajuste de Seca

### 7.1 Justificativa

No bioma Caatinga, secas prolongadas causam morte natural da vegetação e perda foliar que podem imitar sinais de desmatamento nos índices espectrais. Sem ajuste de seca, um sistema de monitoramento produziria extensos alertas falso-positivos durante anos secos. O sistema aborda isso calculando o Índice de Precipitação Padronizado (SPI) e relaxando os limiares de detecção quando condições de seca são identificadas.

### 7.2 Cálculo do SPI

O cálculo do SPI está implementado em `src/processing/spi.py`. O SPI de 3 meses (SPI-3) é utilizado para detectar seca sazonal:

1. **Fonte de dados:** Precipitação mensal CHIRPS v2.0 (global, resolução de 0,05°)
2. **Agregação:** Valores de precipitação mensal são somados em uma janela móvel de 3 meses para produzir o SPI-3.
3. **Ajuste de distribuição:** Uma distribuição gama é ajustada ao período de referência histórico de somas de precipitação de 3 meses não nulas (usando `scipy.stats.gamma.fit` com localização fixada em zero).
4. **Transformação integral de probabilidade:** A soma de 3 meses alvo é transformada pela CDF gama ajustada, considerando a distribuição mista (probabilidade de precipitação zero + distribuição gama para valores positivos).
5. **Padronização:** O valor da CDF é mapeado para um desvio normal padrão via a CDF normal inversa (`scipy.stats.norm.ppf`), produzindo o valor do SPI.
6. **Limitação das caudas:** Os valores da CDF são limitados ao intervalo [0,001; 0,999] para evitar valores infinitos de SPI nas caudas da distribuição.

Interpretação do SPI:
- SPI > 0: Mais úmido que o normal
- SPI < -1,0: Seca moderada
- SPI < -1,5: Seca severa
- SPI < -2,0: Seca extrema

Comportamento de fallback: Se menos de 10 valores de precipitação não nulos estão disponíveis para o ajuste gama, o sistema recorre a um z-score simples (alvo menos média, dividido pelo desvio padrão).

### 7.3 Ajuste de Limiares

Quando o SPI de 3 meses cai abaixo de -1,0 (`SPI_DROUGHT_THRESHOLD`), todos os limiares de z-score são alargados subtraindo 0,5 desvios padrão (`DROUGHT_Z_ADJUSTMENT`):

| Confiança | Limiar normal | Limiar em seca |
|-----------|---------------|----------------|
| Alta | z < -3,0 | z < -3,5 |
| Média | z < -2,5 | z < -3,0 |
| Baixa | z < -2,0 | z < -2,5 |

Isso efetivamente exige um desvio maior do baseline para disparar um alerta durante a seca, reduzindo os falso-positivos do estresse natural da vegetação.

### 7.4 Status Atual

**[Atualizado na v2.0]** O cache `data/chirps/` contém **61 rasters** mensais CHIRPS de 2021-03 a 2026-03 (locais, não versionados). O ajuste de seca por SPI **está ATIVO por padrão** — `scripts/run_detection.py` (e `run_detection_from_gee.py`) chamam `get_current_spi(aoi_bbox)` e passam o valor a `detect_deforestation`, que alarga os limiares quando SPI-3 < −1,0. A auditoria da Fase 1 supunha que era um item "a ativar"; na verdade já estava ligado. O cálculo foi **endurecido** (`get_current_spi`) para descartar meses recentes ainda não publicados pelo CHIRPS (lag de ~1–1,5 mês), evitando que um mês faltante zere o SPI silenciosamente. Uma série de precipitação média na AOI (2021--2026) foi extraída para `data/chirps_aoi/chirps_aoi_monthly.csv`.

---

## 8. Resultados da Validação de Dados

### 8.1 Metodologia de Validação

Um script de validação (`scripts/validate_baseline_data.py`) analisou todos os 106 arquivos GeoTIFF baixados para janeiro (mês 01), produzindo histogramas por banda, estatísticas resumidas por tile e uma avaliação quantitativa de sinais de contaminação por nuvens. As saídas de validação estão armazenadas em `scripts/validation_output/`.

### 8.2 Resultados por Índice

#### NDMI: APROVADO

- **Faixa de valores:** [-0,56; 0,55] -- totalmente dentro dos limites teóricos [-1, 1]
- **Média:** 0,058, **Mediana:** 0,065, **Desvio padrão:** 0,125
- **Distribuição:** Unimodal, suave, sem sinal bimodal de contaminação por nuvens
- **P1/P99:** -0,22 / 0,30
- **Fração fora da faixa:** 0,00%
- **Variação interanual:** Cenas de 2025--2026 apresentam NDMI ligeiramente menor que 2023, consistente com variabilidade interanual da precipitação
- **Avaliação:** Limpo e adequado para composição de baseline sem modificação

#### NBR: APROVADO

- **Faixa de valores:** [-0,58; 0,75] -- dentro dos limites teóricos
- **Média:** 0,279, **Mediana:** 0,291, **Desvio padrão:** 0,168
- **Distribuição:** Unimodal, assimétrica à direita em direção a valores vegetados, sem sinal de contaminação
- **P1/P99:** -0,12 / 0,59
- **Fração fora da faixa:** 0,00%
- **Avaliação:** Limpo e adequado para composição de baseline sem modificação

#### EVI2: REPROVADO (com mitigação aplicada)

- **Faixa de valores:** [-0,41; 2,09] -- valores acima de ~1,0 são fisicamente irrealistas
- **Média:** 0,974, **Mediana:** 0,990, **Desvio padrão:** 0,404
- **P1/P99:** 0,20 / 1,74
- **Fração fora da faixa (fora de [-1, 1]):** 45,7%
- **Suspeito alto (> 0,95):** 48,4%
- **Causa provável:** Cirrus finos ou névoa não detectados pela máscara de nuvens SCL. Nuvens possuem alta reflectância NIR em relação ao RED, o que infla o EVI2 (devido ao multiplicador 2,5) muito mais do que o NDMI ou NBR (que utilizam bandas SWIR absorvidas pelas nuvens).
- **Mitigação aplicada:** Valores de EVI2 são limitados a 1,0 durante a construção do baseline (`EVI2_CAP = 1.0` em `build_baseline_from_downloads.py`). Isso remove a cauda fisicamente irrealista preservando sinais válidos de vegetação.
- **Avaliação:** Utilizável com limitação. No entanto, a contaminação sistemática significa que os baselines de EVI2 possuem maior incerteza do que os de NDMI ou NBR. Isso é aceitável porque o EVI2 desempenha um papel confirmatório, não de detecção primária.
- **[Revisão v2.0]** Esta análise refere-se aos dados **em escala DN** da v1.1. Como explicado em §4.3, a maior parte dos "45,7% fora de faixa" era **erro de unidade**, não cirrus. Com a conversão de refletância (`REFLECTANCE_SCALING=True`) e o rebuild do baseline, o EVI2 passa a ~0% fora de [-1, 1] **sem** o *cap* em 1,0. Este bloco é mantido como registro do diagnóstico original.

### 8.3 Verificação da Máscara de Nuvens

A validação resolveu uma incerteza-chave sobre os dados baixados:

- **Máscara de nuvens foi aplicada:** Pixels utilizam NaN para áreas mascaradas/sem dados, não o valor declarado de nodata 0. Frações de NaN de 11--90% por cena (média de ~69%) são consistentes com mascaramento pixel a pixel baseado em SCL tendo sido aplicado antes do download.
- **Codificação de NoData:** Os metadados do arquivo declaram `nodata=0`, mas a codificação real de no-data é NaN (Float32). Muito poucos pixels são exatamente 0, portanto essa discrepância nos metadados não causa perda de dados na prática.
- **Contaminação residual:** O mascaramento de nuvens é eficaz para NDMI e NBR, mas incompleto para EVI2 (vazamento de cirrus finos). Esta é uma limitação conhecida da máscara SCL para os limites da classe de cirrus.

### 8.4 Consistência entre Tiles

A análise entre os 7 tiles UTM mostra:
- As distribuições de NDMI e NBR são consistentes entre todos os tiles.
- A contaminação do EVI2 é sistemática (presente em todos os tiles), não específica de tile.
- Os tiles 24MVS e 24MVT apresentam valores ligeiramente mais altos de NDMI/NBR, consistente com vegetação mais densa no planalto do Araripe devido ao aumento de precipitação orográfica.

---

## 9. Resultados dos Alertas e Status Atual

### 9.1 Alertas Gerados

O histórico de detecção (v1.1) acumulava **7 arquivos de alerta / 17.528 polígonos**, cobrindo nov/2025 a abr/2026. *(A v1.1 relatava "5 arquivos / 8.924 polígonos" — desatualizado: omitia o arquivo de 1 feição de 28/12 e os arquivos de fev/abr, e trazia contagens per-arquivo incorretas.)*

| Arquivo | Data | Polígonos (bruto) | Confirmados (persistência) |
|---------|------|---------------------|---------------------|
| `alerts_2025-11-26.geojson` | 26/11/2025 | 13 | 0 (1ª obs.) |
| `alerts_2025-11-28.geojson` | 28/11/2025 | 1.334 | 22 |
| `alerts_2025-12-28.geojson` | 28/12/2025 | 1 | 0 |
| `alerts_2026-01-12.geojson` | 12/01/2026 | 3.776 | 0 |
| `alerts_2026-02-01.geojson` | 01/02/2026 | 4.951 | 701 |
| `alerts_2026-02-11.geojson` | 11/02/2026 | 4.709 | 1.364 |
| `alerts_2026-04-27.geojson` | 27/04/2026 | 2.744 | 157 |
| **Total** | | **17.528** | **2.244 (−87,2%)** |

> **Reprocessamento 2026 (v2.0).** Estes números vêm do baseline DN antigo. A
> detecção de 2026 está sendo **reprocessada via GEE** contra o baseline novo em
> refletância (§9.3), o que substituirá as contagens acima por valores
> consistentes na escala correta e com um passo de aquisição regular (as ~30 datas
> bissemanais de 2026, em vez das 7 datas esparsas geradas por execuções manuais).

### 9.2 Observações

A contagem de alertas aumenta substancialmente de novembro a fevereiro. Esta tendência merece análise:

- O período novembro--dezembro marca o início da estação chuvosa nesta região, portanto desmatamento natural generalizado seria inesperado.
- A contagem crescente de alertas pode refletir: (a) atividade genuína de desmatamento, (b) erros de comissão por artefatos de nuvens/sombras durante a estação chuvosa, (c) mudanças na disponibilidade ou qualidade das cenas, ou (d) problemas com a representatividade do baseline nos meses iniciais do sistema.
- A contagem de alertas quase zero em 28/12/2025 (apenas 1 polígono) pode indicar uma cena fortemente coberta por nuvens onde poucos pixels passaram pelo filtro de céu limpo.

Esses alertas ainda não foram validados contra dados de referência independentes (por exemplo, imagens de alta resolução, verificação em campo).

### 9.3 Automação e Implantação

| Componente | Configuração | Status (v2.0) |
|------------|-------------|--------|
| Cron bissemanal do GitHub Actions | `.github/workflows/update_data.yml`, seg+qui 06:00 UTC | Endurecido; falta habilitar Actions + *secrets* R2 no repo |
| Fetch de baselines do R2 (novo) | `scripts/fetch_baselines_from_r2.py`, passo do workflow antes da detecção | Adicionado — é o que faz o CI ter baselines |
| Armazenamento no Cloudflare R2 | Bucket `araripe-cogs`, prefixo `baselines/`, upload via `scripts/upload_to_r2.py` | Baselines em refletância **publicados** |
| Site público estático | Vite MPA → Cloudflare Pages; dados via `prepare_data.py` (lê `data/alerts` + `timeseries.db`) | Em produção (substitui o Streamlit/HF) |
| Painel Streamlit / Hugging Face (legado) | `app.py`; sync HF ao fim do workflow | Legado, não mais o frontend em uso |

**Por que a operação anterior capturava poucas datas (e por que o GEE captura ~30).**
O workflow antigo **nunca detectava de fato no CI**: a checagem baixava o repositório,
mas os baselines são dados locais *git-ignored* (não estavam no repo nem no R2 de
forma consumível), então o passo de detecção encontrava "sem baselines" e pulava.
Os 7 arquivos de alerta esparsos (§9.1) foram gerados por **execuções manuais
locais**, cada uma olhando só `--days-back 16` — daí a cadência irregular. Não era
uma operação bissemanal contínua. Com os baselines agora no R2 e o **novo passo de
fetch** no workflow, o CI passa a ter baselines e a detecção via *streaming* roda no
*runner* (rede rápida, ao contrário da conexão doméstica). Já o **caminho GEE**
(§abaixo) processa **todas** as datas de aquisição de um intervalo — por isso
enumera as ~30 datas bissemanais reais de 2026, expondo que a lacuna anterior era de
**operação**, não de disponibilidade de imagens.

**Caminho de detecção via Google Earth Engine (adotado para 2026).** Espelha o
rebuild do baseline: `scripts/build_detection_gee.py` (Cloud Shell) computa **um
composto por data** (NDMI/NBR/EVI2/BSI em refletância, com a mesma `prep()` do
baseline) e exporta GeoTIFFs pequenos; `scripts/run_detection_from_gee.py` (local)
roda a **lógica de detecção inalterada** contra os baselines em refletância
(z-score → guarda de cena → vetorização → fogo×mecânico → land cover →
persistência). Como o GEE mosaica todas as tiles de uma data num único composto da
AOI, este caminho também **corrige** o bug latente do *streaming* em que tiles da
mesma data sobrescreviam o arquivo de alerta uma da outra. Passo-a-passo em
`docs/DETECTION_GEE.md`. *(A automação totalmente headless do GEE no CI — via conta
de serviço — é roadmap; hoje o passo GEE é manual via Cloud Shell.)*

### 9.4 Painel Web — Camada de Visualização

> **[v2.0] Esta seção descreve o painel Streamlit legado (`app.py`), que não é mais o frontend em uso.** O frontend atual é um **site estático** (Vite MPA → Cloudflare Pages), que consome os mesmos `data/alerts/*.geojson` via um script de preparação (`prepare_data.py`) e serve páginas prontas. O conteúdo abaixo é mantido como registro do painel original.

A interface web (`app.py` + `src/visualization/`) foi atualizada na versão 1.1 para refletir a forma como o sistema é usado em campo:

- **Basemaps configuráveis** — todas as visualizações de mapa (modo normal e modo de exportação) oferecem três camadas selecionáveis no widget de controle de camadas no canto superior direito do mapa: Esri Satellite (padrão), Google Satellite Hybrid e OpenStreetMap. O mesmo widget também permite ligar/desligar os contornos APA, FLONA e a camada de alertas.
- **Contornos de áreas protegidas** — os limites da APA Chapada do Araripe (linha amarela) e da FLONA Araripe-Apodi (linha verde) são sobrepostos automaticamente em todos os mapas, lidos de `data/aoi/APA_chapada_araripe.gpkg` e `data/aoi/FLONA_araripe.gpkg` (ambos em EPSG:4326).
- **Histórico completo de alertas por padrão** — o filtro de intervalo de datas e o filtro de área mínima foram removidos. Todo o histórico de detecção é exibido no mapa e na tabela, evitando que detecções antigas se tornem invisíveis ao usuário.
- **Atividade Recente** — bloco único na barra lateral que combina (a) a linha "Última varredura | Imagem de" com um ícone "?" explicando a diferença entre a data em que o pipeline rodou e a data de aquisição da cena Sentinel-2 analisada; (b) o seletor *Últimas execuções (N)* (padrão N = 1, configurável de 1 a 20); e (c) o checkbox **Mostrar apenas recentes**, que filtra a visualização para alertas das últimas *N* execuções. Alertas recentes mantêm o selo 🆕 na tabela e são listados primeiro; o destaque visual com contorno magenta foi removido por inconsistência entre versões do Folium.
- **Identificação de "recente"** — definido como o conjunto das últimas *N* datas de execução, derivadas dos nomes dos arquivos `data/alerts/alerts_YYYY-MM-DD.geojson` ordenados lexicograficamente. Cada feature é marcada como recente quando seu campo `detection_date` pertence a esse conjunto.
- **Aba Documentação bilíngue** — expõe `REVISAO_TECNICA.md` (PT) e `TECHNICAL_REVIEW.md` (EN); o botão de download entrega o PDF correspondente ao idioma ativo (`REVISAO_TECNICA.pdf` ou `TECHNICAL_REVIEW.pdf`), gerados por `scripts/md_to_pdf.py`.

---

## 10. Limitações Conhecidas e Incertezas

### 10.1 Confundimento Fenológico

A fenologia decídua da vegetação da Caatinga permanece como a fonte mais significativa de erro potencial de comissão. Durante a estação seca (agosto--outubro, definida como `CAATINGA_LEAFOFF_MONTHS = [8, 9, 10]`), a queda foliar natural pode produzir assinaturas espectrais que se sobrepõem aos sinais de desmatamento, mesmo em índices baseados em umidade como o NDMI. A abordagem de baseline mensal mitiga isso comparando com distribuições históricas do mesmo mês, mas o baseline pode não capturar toda a faixa de variabilidade fenológica interanual, especialmente com apenas 3 anos de dados de referência.

### 10.2 Cobertura de Nuvens

A cobertura de nuvens da estação chuvosa (novembro--abril) reduz o número de observações utilizáveis. O sistema aplica um filtro de cobertura máxima de nuvens de 20% no nível da cena, mas contaminação parcial por nuvens dentro das cenas ainda pode afetar os valores dos índices. A máscara de nuvens SCL lida eficazmente com nuvens espessas, mas possui limitações documentadas com cirrus finos (especialmente para o EVI2).

### 10.3 Sensibilidade do EVI2 a Cirrus Finos

Conforme documentado na Seção 8, o EVI2 é mais sensível à contaminação residual por cirrus finos do que o NDMI ou NBR. A mitigação por limitação (valores > 1,0 definidos como 1,0) aborda casos extremos, mas não corrige valores moderadamente elevados na faixa de 0,8--1,0 que ainda podem estar contaminados. Isso aumenta a incerteza das estatísticas do baseline do EVI2 (tanto mediana quanto desvio padrão).

### 10.4 Profundidade Temporal do Baseline

Os baselines da v2.0 abrangem **5 anos {2017, 2019, 2021, 2022, 2025}**, atingindo o objetivo e **excluindo 2023/2024** (El Niño forte). O ano de 2026 foi deliberadamente excluído para servir como ano de detecção contra uma referência fixa. Ressalva remanescente: 5 anos ainda podem não capturar toda a variabilidade interanual extrema; eventos raros futuros (ex.: El Niño extremo) podem gerar falso-positivos, mitigados pelo ajuste de seca (SPI) e pela persistência.

### 10.5 Ajuste de Seca — **agora operacional (v2.0)**

Os dados CHIRPS **estão presentes** (61 rasters, 2021-03 a 2026-03) e o ajuste de seca por SPI **está ativo por padrão** (alargamento dos limiares quando SPI-3 < −1,0). Ressalva: a norma climatológica usa poucos anos (~5) em vez dos ~30 recomendados, e a distribuição gama poderia ser trocada por Pearson III (ver §11.7). Historicamente (antes da auditoria) o sistema operou sem esse ajuste.

### 10.6 Persistência Temporal — **agora implementada (v2.0)**

A v2.0 adiciona um filtro de persistência vetorial (≥2 observações consecutivas com sobreposição espacial ≥5%; ver §6.8), reduzindo fortemente a comissão de fenômenos transitórios (−87% no histórico). Cada alerta carrega `persistence_status` (confirmed/candidate/first_observation), de forma não-destrutiva. Ressalva: com cadência irregular ou observação anterior muito nublada, o filtro pode super-suprimir; uma cadência bissemanal regular atenua isso.

### 10.7 Unidade Mínima de Mapeamento

A área mínima de alerta de 1 ha pode ser muito grosseira para detectar extração seletiva de madeira em pequena escala ou muito fina para priorização de resposta operacional. Na resolução de 20 m, 1 ha = 25 pixels, o que fornece coerência espacial razoável, mas ainda pode incluir padrões fragmentados de ruído.

### 10.8 Lacuna na Validação dos Alertas

Os alertas gerados (8.924 polígonos) não foram validados contra dados de referência independentes. Sem avaliação de acurácia (taxas de erro de comissão e omissão), a confiabilidade do sistema não pode ser quantificada.

---

## 11. Recomendações para Especialistas

Esta seção apresenta questões específicas para revisores com expertise em monitoramento de desmatamento baseado em sensoriamento remoto, ecologia da Caatinga/Cerrado e sistemas operacionais de alerta.

### 11.1 Calibração dos Limiares de Z-Score

Os limiares de z-score atuais (-2,0 / -2,5 / -3,0) foram definidos com base em práticas padrão de detecção de anomalias. Esses valores são apropriados para a variabilidade espectral observada em zonas de transição Caatinga/Cerrado? Os limiares deveriam ser diferenciados por estação (por exemplo, mais conservadores durante os meses secos) ou por tipo de vegetação (por exemplo, sub-regiões de Cerrado vs. Caatinga)?

### 11.2 Inclusão do NDVI

O NDVI foi excluído do pipeline de detecção devido a preocupações com a deciduidade. No entanto, alguns sistemas (por exemplo, PRODES) utilizam o NDVI em combinação com outros índices. O NDVI deveria ser reintroduzido como um índice confirmatório adicional, talvez com um esquema de ponderação sazonal? Alternativamente, um baseline de NDVI ajustado pela fenologia (por exemplo, usando regressão harmônica para modelar o ciclo sazonal) poderia dar conta adequadamente da deciduidade?

### 11.3 Unidade Mínima de Mapeamento

A área mínima de alerta de 1 ha é apropriada para esta região? Considerando:
- Tamanhos típicos de manchas de desmatamento na Chapada do Araripe
- A resolução de pixel de 20 m (1 ha = 25 pixels)
- Capacidade de resposta operacional das agências de fiscalização (IBAMA, ICMBio)
- O compromisso entre sensibilidade de detecção e taxa de falsos alarmes

### 11.4 Persistência Temporal

O sistema deveria exigir que os alertas sejam confirmados em 2 ou mais observações consecutivas antes de serem reportados? Isso reduziria a tempestividade (em um ciclo de revisita, aproximadamente 5--10 dias), mas poderia reduzir substancialmente os falso-positivos de fenômenos transitórios (nuvens, sombras, água temporária).

### 11.5 Protocolo para a Estação Seca

Os meses da estação seca (agosto--outubro) são identificados como problemáticos (`CAATINGA_LEAFOFF_MONTHS`). Como o sistema deveria lidar com esses meses de forma diferente? As opções incluem:
- Aumento dos limiares de z-score durante os meses secos
- Exclusão total do EVI2 durante os meses secos (dependendo apenas do NDMI e NBR)
- Uso de um baseline corrigido pela fenologia que modele o ciclo intra-anual em vez de compósitos mensais discretos
- Suspensão dos alertas de baixa confiança durante os meses secos

### 11.6 Índices Adicionais

Existem outros índices que deveriam ser considerados para esta transição de biomas?

- **NDFI** (Normalized Difference Fraction Index): Utilizado pelos sistemas DETER e PRODES do INPE para detecção de degradação florestal. O NDFI utiliza análise de mistura espectral para decompor pixels em frações de vegetação verde, vegetação não fotossintética e solo/sombra. O sistema já define limiares de NDFI (`NDFI_INTACT_FOREST = 0.75`, `NDFI_DEGRADED_MIN = 0.0`), mas não implementa a desmistura espectral necessária para calculá-lo.
- **MSI** (Moisture Stress Index): Razão SWIR/NIR, inverso do NDMI, às vezes preferido para terras secas.
- **NDWI** (Normalized Difference Water Index): Poderia ajudar a distinguir mudanças em corpos d'água do desmatamento.
- **Índices baseados em SAR** (por exemplo, do Sentinel-1): O radar é independente das condições climáticas e poderia complementar a detecção óptica durante a estação chuvosa com cobertura de nuvens.

### 11.7 Questões Adicionais

7. A computação do SPI baseada na distribuição gama é apropriada para esta região semiárida, ou uma distribuição alternativa (por exemplo, Pearson Tipo III) se ajustaria melhor à climatologia da precipitação?
8. A construção do baseline deveria utilizar uma medida robusta de dispersão (por exemplo, desvio absoluto mediano) em vez do desvio padrão, dada a contaminação documentada por outliers no EVI2?
9. Como o sistema deveria lidar com áreas que já estavam desmatadas antes do período do baseline? Atualmente, estas apresentariam valores de índice consistentemente baixos e não disparariam alertas (z-scores baixos), mas também podem mascarar degradação contínua de remanescentes de vegetação.

---

## 12. Módulo de Análise de Tendências

Além do sistema de alertas em tempo quase real, o código-fonte inclui um módulo de análise de tendências (`src/timeseries/trends.py`) para avaliação de mudanças de vegetação em longo prazo:

- **Teste de Mann-Kendall:** Teste não paramétrico para tendências monotônicas em séries temporais de índices de vegetação. Reporta o tau de Kendall, p-valor (significância em alfa = 0,05) e direção da tendência (crescente / decrescente / sem tendência). Corrigido para valores empatados.
- **Estimador de declividade de Sen** (Theil-Sen): Estimativa robusta de declividade (mediana de todas as declividades par a par), reportada como mudança por ano com intervalos de confiança de 95%.

Essas ferramentas suportam a análise retrospectiva de tendências graduais de degradação que podem não acionar o sistema de detecção de mudanças agudas.

---

## 13. Referências

1. Gao, B.-C. (1996). NDWI -- A normalized difference water index for remote sensing of vegetation liquid water from space. *Remote Sensing of Environment*, 58(3), 257--266. (O NDMI é às vezes referido como NDWI na literatura; a fórmula usando SWIR1 é comumente atribuída a Gao.)

2. Key, C. H., & Benson, N. C. (2006). Landscape Assessment: Sampling and analysis methods. In D. C. Lutes et al. (Eds.), *FIREMON: Fire Effects Monitoring and Inventory System* (Gen. Tech. Rep. RMRS-GTR-164-CD). USDA Forest Service. (Classificação de severidade de queimada por NBR e dNBR.)

3. Jiang, Z., Huete, A. R., Didan, K., & Miura, T. (2008). Development of a two-band enhanced vegetation index without a blue band. *Remote Sensing of Environment*, 112(10), 3833--3845. (Formulação e validação do EVI2.)

4. McKee, T. B., Doesken, N. J., & Kleist, J. (1993). The relationship of drought frequency and duration to time scales. *Proceedings of the 8th Conference on Applied Climatology*. American Meteorological Society. (Índice de Precipitação Padronizado.)

5. Funk, C., Peterson, P., Landsfeld, M., et al. (2015). The climate hazards infrared precipitation with stations -- a new environmental record for monitoring extremes. *Scientific Data*, 2, 150066. (Conjunto de dados de precipitação CHIRPS.)

6. Souza Jr., C. M., Roberts, D. A., & Cochrane, M. A. (2005). Combining spectral and spatial information to map canopy damage from selective logging and forest fires. *Remote Sensing of Environment*, 98(2--3), 329--343. (NDFI e análise de mistura espectral para degradação florestal tropical.)

7. Hamed, K. H., & Rao, A. R. (1998). A modified Mann-Kendall trend test for autocorrelated data. *Journal of Hydrology*, 204(1--4), 182--196. (Teste de tendência de Mann-Kendall.)

8. Sen, P. K. (1968). Estimates of the regression coefficient based on Kendall's tau. *Journal of the American Statistical Association*, 63(324), 1379--1389. (Estimador de declividade de Sen / regressão de Theil-Sen.)

9. Diniz, J. M. F. S., Gama, F. F., & Adami, M. (2022). Evaluation of the performance of vegetation indices for detecting deforestation in the Caatinga biome. *Remote Sensing Applications: Society and Environment*, 26, 100753. (Desempenho de índices de vegetação na Caatinga, suportando NDMI sobre NDVI.)

10. Lamchin, M., Lee, W.-K., Jeon, S. W., et al. (2018). Long-term land cover change and deforestation in Southeast Asia using remote sensing. *Remote Sensing*, 10(11), 1663. (Detecção de anomalias por z-score para mudança de cobertura do solo.)

---

## Apêndice A: Resumo dos Parâmetros de Configuração

Todos os parâmetros configuráveis são definidos em `config/settings.py`. A tabela a seguir resume os valores utilizados no sistema atual:

| Parâmetro | Valor | Descrição |
|-----------|-------|-----------|
| `AOI_BBOX` | [-40.0, -8.0, -39.0, -7.0] | Caixa delimitadora [O, S, L, N] em graus |
| `TARGET_CRS` | EPSG:32724 | UTM zona 24S |
| `SENTINEL2_20M_RESOLUTION` | 20 m | Resolução de trabalho para detecção |
| `LANDSAT_RESOLUTION` | 30 m | Resolução nativa do Landsat |
| `MAX_CLOUD_COVER` | 20% | Filtro de cobertura de nuvens no nível da cena |
| `SEARCH_DAYS_BACK` | 16 dias | Janela temporal de busca |
| `MIN_CLEAR_PERCENTAGE_BASELINE` | 10% | Mínimo de pixels claros para incluir uma cena |
| `BASELINE_YEARS` | 5 | Anos-alvo para o baseline (atingido: {2017, 2019, 2021, 2022, 2025} — ver §5.5) |
| `REFLECTANCE_SCALING` | True (v2.0) | Converte DN→refletância (`DN·scale + offset`) na aquisição; acoplado ao baseline em refletância |
| `Z_THRESHOLD_HIGH` | -3,0 | Z-score para alertas de alta confiança |
| `Z_THRESHOLD_MEDIUM` | -2,5 | Z-score para alertas de confiança média |
| `Z_THRESHOLD_LOW` | -2,0 | Z-score para alertas de baixa confiança |
| `DELTA_THRESHOLD_HIGH` | -0,20 | Mudança absoluta para alta confiança |
| `DELTA_THRESHOLD_MEDIUM` | -0,15 | Mudança absoluta para confiança média |
| `DELTA_THRESHOLD_LOW` | -0,15 | Mudança absoluta para baixa confiança |
| `MIN_ALERT_AREA_HA` | 1,0 ha | Área mínima do polígono |
| `MAX_ALERT_AREA_HA` | 1000 ha | Área máxima do polígono (guarda contra artefatos) |
| `SCENE_ANOMALY_REJECT_FRAC` | 0,30 | Fração de pixels sinalizados acima da qual a cena inteira é rejeitada |
| `SPI_DROUGHT_THRESHOLD` | -1,0 | SPI-3 abaixo deste valor aciona o ajuste |
| `DROUGHT_Z_ADJUSTMENT` | 0,5 sigma | Alargamento do limiar de z-score durante seca |
| `DNBR_LOW_SEVERITY` | 0,27 | Limiar de dNBR para queimada de baixa severidade |
| `DNBR_HIGH_SEVERITY` | 0,66 | Limiar de dNBR para queimada de alta severidade |
| `NBR_POST_FIRE_THRESHOLD` | 0,1 | NBR pós-incêndio confirmando assinatura de fogo |
| `CAATINGA_LEAFOFF_MONTHS` | [8, 9, 10] | Meses da estação seca ago--out |
| `NDFI_INTACT_FOREST` | 0,75 | Limiar de NDFI para floresta intacta |

---

## Apêndice B: Referência de Módulos

| Caminho do Módulo | Finalidade |
|-------------------|-----------|
| `config/settings.py` | Todos os parâmetros globais de configuração |
| `src/acquisition/stac_client.py` | Consultas à API STAC com fallback de provedor |
| `src/acquisition/chirps.py` | Download de dados de precipitação CHIRPS |
| `src/processing/indices.py` | Cálculo de índices espectrais (NDMI, NBR, EVI2, NDVI, SAVI, BSI, dNBR) |
| `src/processing/cloud_mask.py` | Máscara de nuvens para Sentinel-2 (SCL), Landsat (QA_PIXEL), HLS (Fmask) |
| `src/processing/spi.py` | Cálculo do SPI (ajuste de distribuição gama) |
| `src/detection/change_detect.py` | Detecção de anomalias por z-score e classificação de confiança |
| `src/detection/alerts.py` | Vetorização de alertas (máscara de geometria exata), armazenamento e estatísticas |
| `src/detection/baseline.py` | Primitivas de cálculo de z-score e delta; `load_baseline_pair` |
| `src/detection/persistence.py` | **(v2.0)** Filtro de persistência temporal (sobreposição entre observações) |
| `src/detection/landcover.py` | **(v2.0)** Anotação/filtro por MapBiomas (10 m e 30 m, tabelas por-coleção) |
| `src/timeseries/trends.py` | Teste de Mann-Kendall e estimador de declividade de Sen |
| `scripts/build_baseline_gee.py` · `docs/gee_baseline_cloudshell.py` | **(v2.0)** Baseline mensal em refletância via Google Earth Engine |
| `scripts/split_gee_baselines.py` | **(v2.0)** Fatia os compostos do GEE nos 72 COGs do detector |
| `scripts/build_baseline.py` | Construção de baseline por *streaming* de COG (fallback; corrigido) |
| `scripts/run_detection.py` | Execução de detecção por *streaming* (usada no CI) |
| `scripts/build_detection_gee.py` · `scripts/run_detection_from_gee.py` | **(v2.0)** Detecção por composto-por-data via GEE (Cloud Shell + ingestão local) |
| `scripts/select_baseline_years.py` | **(v2.0)** Seleção reprodutível dos anos "calmos" (ONI + CHIRPS) |
| `scripts/upload_to_r2.py` · `scripts/fetch_baselines_from_r2.py` | Publicar / baixar baselines no Cloudflare R2 |
| `app.py` | Painel Streamlit (**legado**; frontend atual é o site estático) |

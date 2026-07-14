# Como funciona o Observatório da Chapada do Araripe

*Explicação simples do sistema de monitoramento de desmatamento. Para os detalhes
técnicos completos, veja `REVISAO_TECNICA.md`; para o histórico das mudanças e da
auditoria, `AUDITORIA_TECNICA.md`.*

---

## Em uma frase

O sistema olha imagens de satélite da Chapada do Araripe duas vezes por semana,
compara cada área com "como aquele lugar normalmente é naquela época do ano", e
avisa (gera um **alerta**) quando algo muda de forma anormal — indício de
desmatamento, corte ou queimada.

## A ideia central, em 4 passos

1. **O "normal" (baseline).** Para cada mês do ano, o sistema sabe como a
   vegetação normalmente aparece nos satélites — a partir de vários anos de
   imagens. É a régua de comparação.
2. **A imagem nova.** Chega uma imagem recente do satélite Sentinel-2.
3. **A comparação.** Pixel a pixel, ele mede o quanto a imagem nova se afastou do
   normal daquele mês. Uma queda forte e incomum na vegetação/umidade é suspeita.
4. **O alerta.** As áreas suspeitas viram polígonos no mapa, com um nível de
   confiança, e aparecem no site.

---

## O "normal" — o baseline

- É calculado **por mês** (um "janeiro típico", um "julho típico", etc.), porque a
  Caatinga muda muito com as estações.
- Usa **5 anos** de imagens: **2017, 2019, 2021, 2022 e 2025**. Escolhemos anos de
  clima "calmo" e **excluímos 2023 e 2024**, que foram os dois El Niño mais fortes
  do período (muito secos) — se entrassem, o "normal" ficaria distorcido para seco
  e o sistema deixaria de perceber desmatamentos reais.
- Para cada mês, pega o valor **mediano** de cada pixel nesses anos (a mediana
  ignora bem valores esquisitos, como nuvens residuais).
- **Como é calculado:** no **Google Earth Engine** (servidores do Google), que faz
  a conta pesada e devolve só o resultado pronto. Isso resolveu um gargalo de
  internet que tornava esse cálculo inviável de baixar localmente.

## Os 3 "índices" que o sistema olha

Em vez de olhar a cor crua, o sistema calcula três indicadores a partir das bandas
do satélite:

| Índice | O que mede (em linguagem simples) | Por que é útil aqui |
|---|---|---|
| **NDMI** | **Umidade** da vegetação | Principal. A Caatinga perde as folhas na seca, mas a estrutura ainda retém umidade — então umidade distingue melhor "seca natural" de "desmatamento" do que o verde. |
| **NBR** | Sensível a **queimadas** e corte raso | Confirma o NDMI e capta fogo. |
| **EVI2** | **Verdor**/vigor da vegetação | Papel de apoio; ajuda a confirmar. |

**Por que não usar só o "verde" (NDVI)?** Porque na Caatinga o verde despenca
naturalmente na estação seca (as árvores perdem as folhas), o que geraria milhares
de alertas falsos. Por isso o sistema prioriza **umidade**, não verde.

> **Uma correção importante que fizemos:** o EVI2 estava sendo calculado numa
> escala errada (números "crus" do satélite em vez de refletância de 0 a 1),
> inflando os valores. Corrigimos e reconstruímos o baseline na escala certa — o
> EVI2 agora fica na faixa física esperada.

## Níveis de confiança do alerta

Cada alerta recebe **alta**, **média** ou **baixa** confiança:
- **Alta:** os dois índices de umidade (NDMI e NBR) caem muito e ao mesmo tempo.
- **Média:** um deles cai bastante.
- **Baixa:** qualquer índice (incluindo o EVI2) cai o suficiente.

E há uma **área mínima de 1 hectare** — manchas menores são descartadas como
ruído.

## Nuvens e o filtro de persistência

- Nuvens e sombras podem imitar desmatamento. O sistema usa a máscara de nuvens do
  próprio satélite, mas nuvens finas às vezes escapam.
- Por isso adicionamos um **filtro de persistência**: um alerta só é "confirmado"
  se aparecer no **mesmo lugar em duas observações seguidas**. Isso derruba muito
  ruído passageiro (nuvem, sombra) — no histórico existente reduziu os alertas em
  ~87%. Um desmatamento de verdade permanece; uma nuvem, não.

## Comparação com o MapBiomas (o que havia antes)

O satélite vê que "algo mudou", mas não sabe **o que havia ali antes**. O MapBiomas
(mapa oficial de uso do solo do Brasil) preenche essa lacuna. Cada alerta é
**anotado** com o tipo de cobertura embaixo dele (vegetação natural, pasto,
agricultura, urbano…) e com a fração que é vegetação natural.

- Isso permite **separar** um provável desmatamento novo (sobre vegetação natural)
  de uma variação sobre área **já** antropizada (pasto/agricultura) — que
  normalmente não é desmatamento novo. Na análise da auditoria, ~1/3 dos alertas
  caíam sobre solo já usado.
- O sistema aceita **duas versões** do MapBiomas, selecionáveis:
  - **Coleção 2 (10 m, Sentinel-2, 2016–2023):** resolução fina, casa melhor com a
    escala da detecção.
  - **Coleção 10 (Landsat, série longa 1985–2024):** para contexto histórico.
  - As duas têm **tabelas de classes diferentes** (a de 10 m não tem, por exemplo,
    as subdivisões de cultura da de 30 m), então cada uma usa sua própria
    correspondência classe→grupo.

## Ajuste de seca (SPI)

Em anos anormalmente secos, a vegetação sofre naturalmente e pode parecer
desmatada. O sistema calcula um índice de seca (SPI, a partir de dados de chuva
CHIRPS) e, quando detecta seca, **afrouxa um pouco os limiares** para não gerar
falsos alertas por estresse hídrico natural.

## Como os alertas chegam ao site

1. A detecção gera arquivos de alerta (`.geojson`) no repositório do projeto.
2. Um script do site (`prepare_data.py`) lê esses arquivos e os traduz para um
   formato leve.
3. O site (hospedado na **Cloudflare**) publica tudo como páginas estáticas — o
   navegador só lê arquivos prontos, sem cálculo em tempo real.

Duas vezes por semana (segundas e quintas) isso pode rodar de forma automática.

## O que ainda é limitação (honestamente)

- **Validação de acurácia pendente:** ninguém ainda conferiu visualmente, um a um,
  uma amostra de alertas contra imagem de alta resolução para medir a taxa de
  acerto/erro. Há um script que monta essa amostra; a conferência é uma etapa
  humana.
- **Não é prova jurídica:** um alerta é um *indício* que merece verificação, não
  uma confirmação de crime ambiental.
- **Estação chuvosa (nov–abr)** tem mais nuvens → menos imagens boas e mais ruído
  (mitigado pelo filtro de persistência).
- **Roadmap:** radar Sentinel-1 (enxerga através de nuvens) e um detector de
  tendência mais sofisticado (BFAST) são melhorias futuras, ainda não implementadas.

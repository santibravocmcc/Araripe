# Phase 8 — a aba Clima (registro de 2026-10-27)

Pedido do dono em 2026-10-14: uma aba **Clima** separada de Território, com a
chuva que estava lá, a temperatura, uma seção dedicada ao El Niño de 2026–27 e
previsões; projeções até 2100 mais tarde. Regra do dono: **nada nos
repositórios antes de a virada da Phase 6 terminar** — o plano, os dados, as
análises e um protótipo da página foram feitos na pasta `clima/` do workspace,
fora dos dois repositórios. Depois do C5 (`PHASE_6_CUTOVER_2026-10-27.md`) o
dono pediu para levar ao site.

## Onde está

| o quê | onde |
| --- | --- |
| a PR do site (página, dados e robôs) | `observatorio-site#56`, branch `claude/clima-aba`, commit `f64e988` |
| o plano e as decisões | `clima/PLANO.md` (workspace, fora do git) |
| os números | `clima/resultados/RELATORIO_F2.md` (idem) |
| este registro e a Phase 8 no `ROADMAP.md` | esta PR de documentação |

## Decisões do dono (2026-10-15 e 2026-10-16)

| # | decisão |
| --- | --- |
| previsão | até **6 meses**; mostrar a **combinada e cada sistema**; sistemas **ECMWF, CMCC e NCEP** (indicação de um meteorologista), pesados pela habilidade medida |
| temperatura | **não** baixar os ~41 GB do SAMeT diário; a semana contra a normal diária oficial do CPTEC; dias quentes calculados no Earth Engine com o BR-DWGD diário |
| normal | 2001–2025 para MERGE e SAMeT (muda −0,2 % a chuva anual do site); 1991–2020 para o BR-DWGD |
| El Niño | manchete em RONI, com o ONI ao lado; "típica" = mediana (explicada na página) |
| chave do CDS | vira segredo do repositório do site (`CDSAPI_KEY`) |
| nomes | "Território" + "Clima", mantendo `territorio.html` |
| roadmap | Phase 8 (a Phase 7 já é "Final hardening") |

## Medido no caminho (o que muda código ou texto)

- **O SAMeT republica cada dia ~6 dias depois, revisado.** A mínima média da
  AOI de 2026-10-12 era 17,71 °C no arquivo de 14/10 e é 22,14 °C no de 18/10.
  A semana é refeita inteira a cada rodada e a página diz quantos dias são
  provisórios.
- O SAMeT publica arquivos de **0 byte** (`SAMeT_CPTEC_TMAX_20261006.nc` em
  14/10): contam como "não publicado".
- O **CMCC SPS3.5** (`system 35`) não tem 2026 no CDS; o **SPS4** (`4`) tem,
  com retroprevisões 1993–2016.
- O **IRI Data Library** passou a exigir login; o NMME segue público no FTP da CPC.
- O GRIB antigo do NMME (2011–2018) começa no lead 1 (banda *i* = lead *i*),
  medido pela correlação 0,978 com o netCDF do mesmo mês.
- O **SAMeT tem um salto por volta de 2012–13** que o BR-DWGD não tem: a
  tendência da temperatura usa só o BR-DWGD; as duas bases não são emendadas.
- O asset do autor do BR-DWGD no Earth Engine é uma `ImageCollection` (23 741
  imagens): os dias quentes de 1961–2025 saem de uma redução no servidor.

## Resultados que vão para a página

- El Niño forte (6 estações: 1973, 1983, 1992, 1998, 2016, 2024): chuva de
  fev–mai **típica de 75 %** do normal (La Niña 114 %, neutro 98 %); com 6
  casos a diferença não é estatisticamente firme (permutação p = 0,23).
- O Atlântico decide junto: El Niño com o Atlântico Norte mais quente, 93 %;
  com o Sul mais quente, 116 % (o caso de 2024).
- Temperatura: **+0,29 °C/década** na máxima e +0,22 na mínima (1961–2025);
  dias quentes de **10 por ano (1961–90) para 45 (1996–2025)**, recorde 2016 (131).
- Previsão emitida em out/2026 (ECMWF + CMCC SPS4 + NCEP): chuva de **fev/2027
  67 %** no terço seco (mês com habilidade medida) e mar/2027 70 % (sem
  habilidade comprovada nesse prazo).
- Habilidade (retroprevisões 1993–2016 contra o BR-DWGD): ECMWF o melhor
  sozinho, a combinada igual ou melhor a partir do 2º mês, NCEP o mais fraco.

## O que falta, com dono

1. **Dono:** cadastrar `CDSAPI_KEY` no repositório do site; mesclar a #56
   (deploy de produção). Recomendação: depois da leitura do C6, como as PRs do
   monitor CAR; a #56 e a #53 conflitam só nas linhas do menu.
2. **Mensal, à mão:** `scripts/clima-src/cpc_discussao.json` com a discussão da
   NOAA (o robô avisa depois de 40 dias).
3. **Depois:** veranicos, mapas de composto, pesos da combinada em validação
   cruzada, projeções CLIMBra até 2100.

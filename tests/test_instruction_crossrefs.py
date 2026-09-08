"""Uma referência a `<arquivo> §N` tem de resolver para uma seção que existe.

Escrito em 2026-09-08, depois de um erro meu. O landing do Package 2A.6 trocou
o que `ROADMAP.md` é na `main`: passou a ser o plano, e o rastreador que estava
ali foi para `docs/implementation/PENDING_CAPABILITIES.md`. Os dois documentos
têm numeração própria, então **quatro** arquivos de instrução que diziam
"`ROADMAP.md` §6" passaram a apontar para a seção errada, sem uma palavra ter
mudado neles:

    ROADMAP.md            §6 = "Usage-limit strategy"
    PENDING_CAPABILITIES  §6 = "Time-series publication lane (2026-08-17 incident)"

Uma referência quebrada assim é pior que uma ausente, porque ela resolve — para
outra coisa — e quem seguir lê um documento plausível e errado.

**E a primeira versão deste arquivo não pegava o defeito.** Ela checava se a
seção `§N` existia no arquivo referido — e `§6` existe nos DOIS documentos, com
assuntos diferentes. A mutação (voltar a referência para `ROADMAP.md §6`) passou.
Foi o próprio caso de "um teste pode passar pelo motivo errado", num teste
escrito para pegar um erro parecido. Corrigido fixando o **assunto** esperado de
cada referência que importa, e não só o número.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).parents[1]

#: Onde procurar referências. Os arquivos de instrução governam o trabalho, então
#: uma referência quebrada aqui desorienta toda sessão futura.
ARQUIVOS_DE_INSTRUCAO = ("AGENTS.md", "CLAUDE.md")

#: `path/to/file.md` seguido, em até ~40 caracteres, de `§N`.
REFERENCIA = re.compile(
    r"`(?P<arquivo>[\w./-]+\.md)`[^\n]{0,40}?§\s*(?P<secao>\d+)", re.MULTILINE
)

SECAO = re.compile(r"^#{1,4}\s+(?P<numero>\d+)\.\s", re.MULTILINE)


def referencias() -> list[tuple[str, str, int]]:
    """`(arquivo_de_origem, caminho_referido, numero_da_secao)` de cada referência."""

    achadas = []
    for nome in ARQUIVOS_DE_INSTRUCAO:
        origem = RAIZ / nome
        if not origem.is_file():
            continue
        for m in REFERENCIA.finditer(origem.read_text(encoding="utf-8")):
            achadas.append((nome, m.group("arquivo"), int(m.group("secao"))))
    return achadas


def test_existe_referencia_para_conferir():
    """Guarda o arquivo: uma varredura vazia tornaria o teste abaixo vácuo."""

    assert referencias(), (
        "nenhuma referência `<arquivo>.md §N` encontrada nos arquivos de "
        "instrução — se o formato mudou, este teste precisa mudar com ele"
    )


@pytest.mark.parametrize(
    "origem,referido,secao",
    referencias(),
    ids=lambda v: str(v).replace("/", "_"),
)
def test_a_secao_referida_existe(origem, referido, secao):
    alvo = RAIZ / referido
    if not alvo.is_file():  # pode ser do outro repositório do workspace
        pytest.skip(f"{referido} não está neste repositório")
    numeros = {int(m.group("numero")) for m in SECAO.finditer(alvo.read_text("utf-8"))}
    assert numeros, f"{referido} não tem seção numerada nenhuma"
    assert secao in numeros, (
        f"{origem} aponta para {referido} §{secao}, e aquele arquivo tem as "
        f"seções {sorted(numeros)}. Uma referência que resolve para a seção "
        "errada é pior que uma ausente: quem seguir lê um documento plausível."
    )


#: As referências que importam, com o ASSUNTO esperado — não só o número.
#: Fixar o assunto é o que separa "a seção existe" de "a seção é aquela".
#: `(arquivo_de_origem, caminho_referido, secao, trecho_esperado_no_titulo)`
REFERENCIAS_FIXADAS = (
    (
        "AGENTS.md",
        "docs/implementation/PENDING_CAPABILITIES.md",
        6,
        "Time-series publication lane",
    ),
    (
        "CLAUDE.md",
        "docs/implementation/PENDING_CAPABILITIES.md",
        6,
        "Time-series publication lane",
    ),
)


@pytest.mark.parametrize(
    "origem,referido,secao,titulo_esperado",
    REFERENCIAS_FIXADAS,
    ids=lambda v: str(v).replace("/", "_"),
)
def test_a_referencia_fixada_aponta_para_o_ASSUNTO_certo(
    origem, referido, secao, titulo_esperado
):
    """O que a primeira versão deste arquivo não pegava.

    A `main` teve dois documentos com o nome `ROADMAP.md`, e a §6 de cada um
    tratava de outra coisa. Uma referência ao número certo no arquivo errado
    resolve em silêncio. Este teste exige que o **título** da seção referida
    contenha o assunto, e exige também que a referência ainda esteja escrita no
    arquivo de origem — senão alguém a removeria e o teste continuaria verde.
    """

    texto_origem = (RAIZ / origem).read_text(encoding="utf-8")
    assert f"`{referido}` §{secao}" in texto_origem, (
        f"{origem} não contém mais a referência a `{referido}` §{secao}. Se ela "
        "mudou de propósito, atualize REFERENCIAS_FIXADAS no mesmo commit."
    )

    alvo = RAIZ / referido
    assert alvo.is_file(), f"{referido} não existe"
    titulos = {
        int(m.group("numero")): m.group(0).strip()
        for m in re.finditer(
            r"^#{1,4}\s+(?P<numero>\d+)\.\s+.*$",
            alvo.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
    }
    assert secao in titulos, f"{referido} não tem §{secao}; tem {sorted(titulos)}"
    assert titulo_esperado.lower() in titulos[secao].lower(), (
        f"{origem} aponta para {referido} §{secao}, esperando "
        f"{titulo_esperado!r}, mas aquela seção é {titulos[secao]!r}. "
        "O número resolve e o assunto não — é o defeito de 2026-09-08."
    )

"""O driver do replay: a preparação é a mesma, e ele não alcança produção.

Determinístico: sem Earth Engine, sem rede, sem credencial. O driver é
importado por caminho, como o shell do operador o roda.

O que estes testes existem para impedir é uma coisa só: que o replay componha
uma observação numa escala diferente da que construiu a baseline. Se a
preparação divergir, o z-score compara duas coisas que não são comparáveis, e
o candidato fica **plausível** em vez de obviamente errado — que é o modo de
falha que esta fase inteira foi desenhada para evitar.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts" / "replay_2026.py"
EXPORT = ROOT / "scripts" / "build_detection_gee.py"
BLUE_CI = ROOT / "scripts" / "run_detection_gee.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


driver = load(DRIVER, "replay_2026")
export = load(EXPORT, "build_detection_gee")


def _function_body(path: Path, function: str, *, nested_in: str | None = None):
    """The normalized source of one function, for comparing two copies.

    Compares the parsed body rather than the text so indentation, the
    surrounding scope and the ``ee`` parameter do not make three identical
    implementations look different.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    scope = tree
    if nested_in is not None:
        scope = next(
            node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == nested_in
        )
    node = next(
        item for item in ast.walk(scope)
        if isinstance(item, ast.FunctionDef) and item.name == function
    )
    return [ast.dump(statement) for statement in node.body
            if not isinstance(statement, ast.Expr)
            or not isinstance(statement.value, ast.Constant)]


def test_a_preparacao_do_driver_e_a_do_export():
    """**A asserção que importa.** Derruba: mexer no cloud-mask, na divisão por
    10000, ou na escolha de banda de um índice em um dos dois lugares.

    O export e o driver calculam NDMI/NBR sobre B8A e EVI2/BSI sobre B8, com o
    allowlist SCL [2,4,5,6,7,11]. A baseline foi construída na mesma escala.
    Uma divergência aqui não quebra nada visivelmente — ela desloca todos os
    z-scores de 2026.
    """

    assert _function_body(DRIVER, "_prep") == _function_body(
        EXPORT, "prep", nested_in="main"
    )


def test_a_preparacao_do_driver_e_a_do_caminho_azul_de_ci():
    """O terceiro exemplar da mesma preparação, que roda em produção."""

    assert _function_body(DRIVER, "_prep") == _function_body(BLUE_CI, "_prep")


def test_o_allowlist_scl_e_as_bandas_sao_os_mesmos_objetos_de_valor():
    assert driver.SCL_CLEAR == export.SCL_CLEAR == [2, 4, 5, 6, 7, 11]
    assert driver.BANDS == ["ndmi", "nbr", "evi2", "bsi"]


def test_o_driver_nao_alcanca_producao():
    """Derruba: um caminho de escrita em produção acrescentado ao driver.

    O replay escreve só em `--out-dir` e `--state-path`. Nomear o bucket de
    produção, o Worker, um workflow azul ou um ponteiro canônico aqui é o que
    este teste recusa — e ele lê o texto executável, ignorando comentário e
    docstring, porque a §7 dos insumos registra que uma varredura ingênua já
    se enganou nos dois sentidos.
    """

    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    executable = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parent_is_docstring = False
            executable.append(node.value)
    # docstrings are Expr(Constant); drop those, keep real string literals
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)):
            text = ast.get_docstring(node, clean=False)
            if text is not None:
                docstrings.add(text)
    literals = [value for value in executable if value not in docstrings]
    haystack = "\n".join(literals).lower()

    for forbidden in (
        "araripe-cogs",
        "observatorio-chapada",
        "pointers/green/current.json",
        "detect_gee.yml",
        "update_data.yml",
        "cloudflare",
        "r2_staging",
        "aws_access_key",
    ):
        assert forbidden not in haystack, (
            f"the replay driver names {forbidden!r} in executable code"
        )


def test_o_driver_nao_importa_o_carregador_de_dotenv_no_topo():
    """Derruba: mover `from config.settings import ...` para o topo.

    O driver PRECISA de `config.settings` (é o caminho azul da ciência, não uma
    lane verde), mas importá-lo no topo faria `plan` — que não processa nada —
    carregar o `.env` de produção só para enumerar. O import fica dentro de
    `command_run`.
    """

    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    top_level = [
        node for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    named = {
        (node.module or "") for node in top_level if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in top_level if isinstance(node, ast.Import)
         for alias in node.names}
    assert not any(name.startswith("config") for name in named), named


def test_o_modo_de_persistencia_do_replay_e_rebuild_e_nao_e_configuravel():
    """Derruba: expor `--persistence-mode live` no replay.

    O modo live recusa datas mais antigas, que é exatamente o que um replay
    faz; e um replay que rodasse em live contra o estado vivo escreveria em
    cima da persistência de produção.

    A primeira versão deste teste procurava a string no arquivo inteiro e caiu
    no **docstring** do módulo, que menciona `--persistence-mode` para explicar
    que ele não existe. É a armadilha que a §7 dos insumos registra, e ela
    pegou o teste que foi escrito para evitá-la. Agora ele lê as chamadas de
    `add_argument` e o argumento nomeado `mode=`, que é a pergunta de verdade.
    """

    tree = ast.parse(DRIVER.read_text(encoding="utf-8"))
    flags = {
        argument.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "add_argument"
        for argument in node.args
        if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
    }
    assert "--persistence-mode" not in flags, flags
    assert "--state-path" in flags

    modes = {
        keyword.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg == "mode"
        and isinstance(keyword.value, ast.Constant)
    }
    assert modes == {"rebuild"}, modes


def test_o_filtro_so_pode_rejeitar_e_nunca_aceitar():
    """Derruba: o driver aceitando uma aquisição pelo número do filtro.

    `assess_scene_quality` é a única coisa que aceita. O driver só chama
    `screen_rejection` — nunca um `screen_acceptance`, que não existe.
    """

    from src.replay import enumeration

    assert hasattr(enumeration, "screen_rejection")
    assert not hasattr(enumeration, "screen_acceptance")
    source = DRIVER.read_text(encoding="utf-8")
    assert "assess_scene_quality" in source
    assert 'status="complete_with_alerts" if observation_ids' in source


@pytest.mark.parametrize("command", ["plan", "run"])
def test_out_dir_e_obrigatorio_nos_dois_comandos(command, capsys):
    """Derruba: um default que escreveria na árvore do repositório."""

    with pytest.raises(SystemExit):
        driver.main([command, "--start", "2026-01-01", "--end", "2026-01-02"])


def test_run_exige_state_path_e_os_limites_do_lote():
    with pytest.raises(SystemExit):
        driver.main(["run", "--start", "2026-01-01", "--end", "2026-01-02",
                     "--out-dir", "/tmp/nope"])

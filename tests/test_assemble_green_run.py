"""O ponto de entrada do operador, e o que uma rodada quebrada ou concorrente
não pode estragar.

Exit gate P2B, itens 1 e 3 do escopo. `src/publication/run_assembler.py` sabia
montar um prefixo de rodada e `scripts/publish_green_release.py` sabia
publicá-lo; entre os dois faltava **quem deposita** `runs/<run-id>/` a partir de
uma execução de detecção real. `scripts/assemble_green_run.py` é essa peça, e
estes testes fixam as três coisas que ela decide e a biblioteca não:

* **o ledger decide quais datas existem, o diretório não.** A primeira versão
  desta função recusava um arquivo de uma data que o ledger não reconcilia — o
  que parece uma boa checagem até se medir quem enche o diretório: no CI é a
  própria rodada, e localmente `fetch_alerts_from_r2.py` baixa **o arquivo
  inteiro**. Encodar isso seria afirmar invariante que o produtor não promete,
  que é exatamente a armadilha de 2026-09-07;
* **uma data de zero alertas não tem arquivo nenhum**, medido do produtor:
  `run_detection.py` só põe a data em `alerts_by_date` dentro do galho que
  achou alertas. O contrato exige duas coleções vazias, e o ledger é quem diz
  que alguém olhou;
* **uma data de zero alertas COM feições é contradição**, e a biblioteca não a
  pega — ela checa o caso espelho.

E a cláusula do gate — *"a deliberately failed or racing green run cannot
corrupt blue or expose a partial release"* — tem as duas metades executadas
aqui contra um store que impõe as precondições do R2, além das execuções contra
o R2 real registradas em `docs/implementation/PHASE_2B_GATE_2026-09-08.md`.

Tudo determinístico: sem rede, sem relógio real, sem object store, sem
credencial.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path

import pytest

from src.publication import conditional_store as cs
from src.publication import run_assembler as ra
from src.publication import run_inputs as ri
from src.publication.atomic_publish import (
    promote,
    publish_release,
    read_pointer,
    verify_release,
)
from src.publication.conditional_store import (
    ConditionalStore,
    ImmutableObjectConflict,
    PreconditionFailed,
)
from src.publication.findings import Rejected
from src.publication.green_release import POINTER_KEY
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, FAILED, REJECTED, ZERO, build_ledger
from tests.test_atomic_publish import CI, NOW
from tests.test_run_assembler import ALERTING_FEATURES, areal

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "assemble_green_run.py"

#: The four green scripts that must stay clear of the repository `.env`.
GREEN_SCRIPTS = (
    "assemble_green_run.py",
    "stage_green_run.py",
    "publish_green_release.py",
    "check_site_artifact.py",
    "plan_retention.py",
)


def load_entry_point():
    """Import the script by path, as an operator's shell would run it."""

    spec = importlib.util.spec_from_file_location("assemble_green_run", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


aggr = load_entry_point()


# ── the detection run on disk ────────────────────────────────────────────────


def write_run(tmp_path, features_by_date, *, state=b'{"type":"FeatureCollection"}\n'):
    """Lay out what a detection run leaves behind, with the producer's names."""

    alerts = tmp_path / "data" / "alerts"
    alerts.mkdir(parents=True)
    for observed_on, features in features_by_date.items():
        document = {"type": "FeatureCollection", "features": list(features)}
        (alerts / f"alerts_{observed_on}.geojson").write_text(
            json.dumps(document), encoding="utf-8"
        )
    (tmp_path / "data" / aggr.PERSISTENCE_STATE_NAME).write_bytes(state)
    return alerts


class Args:
    def __init__(self, run, ledger, alerts_dir, state):
        self.run, self.ledger = run, ledger
        self.alerts_dir, self.state = alerts_dir, state


def args_for(tmp_path, spec, features_by_date, *, run="entry-1", state=None):
    document, _ = build_ledger(spec)
    alerts = write_run(tmp_path, features_by_date, **({"state": state} if state else {}))
    ledger_path = tmp_path / "ledger.json"
    ledger_path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return Args(run, ledger_path, alerts, tmp_path / "data" / aggr.PERSISTENCE_STATE_NAME)


def codes(excinfo):
    return sorted(excinfo.value.codes)


# ── o ledger decide as datas, e o disco não ─────────────────────────────────


def test_o_ledger_decide_as_datas_e_um_arquivo_a_mais_e_ignorado(tmp_path):
    """A armadilha central: o diretório de alertas é um ARQUIVO, não a saída de
    uma rodada.

    Localmente `fetch_alerts_from_r2.py` (sem `--latest`) baixa a história
    inteira para o mesmo diretório, então "todo arquivo aqui é desta rodada" é
    propriedade de um dos dois usos documentados, não promessa do produtor.
    Recusar por causa dele derrubaria toda rodada real.
    """

    args = args_for(
        tmp_path,
        {"2026-04-07": [ALERTS]},
        {"2026-04-07": ALERTING_FEATURES, "2026-04-10": [areal()], "2026-04-13": [areal()]},
    )
    run = aggr.assemble(args)
    assert sorted(item["observed_on"] for item in run.document["objects"]) == [
        "2026-04-07",
        "2026-04-07",
    ]
    assert aggr.ignored_dates(args.alerts_dir, {"2026-04-07": "alerts"}) == [
        "2026-04-10",
        "2026-04-13",
    ]


def test_o_numero_de_datas_ignoradas_e_reportado_e_nao_engolido(tmp_path):
    """Ignorar em silêncio e ignorar reportando são coisas diferentes: com 37
    datas na pasta, o operador tem de conseguir ver que 37 foram ignoradas.
    """

    args = args_for(
        tmp_path,
        {"2026-04-07": [ALERTS]},
        {"2026-04-07": ALERTING_FEATURES, "2026-04-10": [], "2026-04-13": []},
    )
    assert len(aggr.ignored_dates(args.alerts_dir, {"2026-04-07": "alerts"})) == 2
    assert aggr.ignored_dates(args.alerts_dir, {}) == [
        "2026-04-07",
        "2026-04-10",
        "2026-04-13",
    ]


# ── as três traduções entre o disco do produtor e o contrato ────────────────


def test_uma_data_de_zero_alertas_sem_arquivo_publica_duas_colecoes_vazias(tmp_path):
    """Medido do produtor: `run_detection.py` só registra a data no galho que
    achou alertas, e loga *"Scene {}: no alerts"* no outro — logo uma data
    observada e quieta **não escreve arquivo**. O contrato exige as duas
    coleções vazias, como observação positiva de ausência.
    """

    args = args_for(tmp_path, {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]},
                    {"2026-04-07": ALERTING_FEATURES})
    run = aggr.assemble(args)
    quiet = [
        item["path"] for item in run.document["objects"]
        if item["observed_on"] == "2026-04-10"
    ]
    assert len(quiet) == 2
    for path in quiet:
        assert json.loads(run.bodies[path])["features"] == []


def test_uma_data_com_alertas_e_sem_arquivo_e_recusada(tmp_path):
    """E aqui `[]` seria uma MENTIRA: o ledger diz que houve observação, e um
    arquivo ausente é uma detecção que não escreveu, não um dia quieto.
    """

    args = args_for(tmp_path, {"2026-04-07": [ALERTS]}, {})
    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        aggr.assemble(args)
    assert codes(excinfo) == ["date_without_detection_output"]


def test_uma_data_de_zero_alertas_com_feicoes_e_contradicao(tmp_path):
    """A biblioteca não pega este caso — ela checa o espelho
    (`features_for_an_unobserved_date`). O ledger diz que toda aquisição
    reportou nada; a detecção escreveu feições. Publicar qualquer das duas
    versões faria a release contradizer o ledger que ela embarca.
    """

    args = args_for(
        tmp_path,
        {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]},
        {"2026-04-07": ALERTING_FEATURES, "2026-04-10": [areal()]},
    )
    with pytest.raises(aggr.DetectionOutputRejected) as excinfo:
        aggr.assemble(args)
    assert codes(excinfo) == ["zero_alert_date_with_detection_features"]


def test_a_biblioteca_sozinha_publicaria_essa_contradicao(tmp_path):
    """A mutação que o teste acima derruba, dita por extenso.

    Se a checagem saísse do ponto de entrada, a montagem passaria e a release
    publicaria feições numa data que o ledger declara vazia. Este teste é o que
    impede alguém de "simplificar" removendo a checagem.
    """

    document, _ = build_ledger({"2026-04-07": [ALERTS], "2026-04-10": [ZERO]})
    run = ra.assemble_run(
        "library-only",
        document,
        {"2026-04-07": ALERTING_FEATURES, "2026-04-10": [areal()]},
        persistence_state_sha256="a" * 64,
        persistence_state_bytes=1,
    )
    quiet = [
        item["path"] for item in run.document["objects"]
        if item["observed_on"] == "2026-04-10"
    ]
    assert any(json.loads(run.bodies[path])["features"] for path in quiet)


def test_feicoes_numa_data_sem_cobertura_chegam_a_biblioteca_para_ela_recusar(tmp_path):
    """Uma data sem cobertura com arquivo é passada adiante de propósito: quem
    a nomeia é a biblioteca, e engolir aqui esconderia o desacordo.
    """

    args = args_for(
        tmp_path,
        {"2026-04-07": [ALERTS], "2026-04-10": [FAILED, REJECTED]},
        {"2026-04-07": ALERTING_FEATURES, "2026-04-10": [areal()]},
    )
    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        aggr.assemble(args)
    assert codes(excinfo) == ["features_for_an_unobserved_date"]


# ── o estado de persistência: medido, nunca afirmado ───────────────────────


def test_o_digest_do_estado_de_persistencia_e_calculado_do_arquivo(tmp_path):
    body = b'{"type":"FeatureCollection","features":[]}\n'
    args = args_for(tmp_path, {"2026-04-07": [ALERTS]},
                    {"2026-04-07": ALERTING_FEATURES}, state=body)
    run = aggr.assemble(args)
    import hashlib

    assert run.document["persistence_state"] == {
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
    }


def test_um_estado_de_persistencia_ausente_e_recusado(tmp_path):
    args = args_for(tmp_path, {"2026-04-07": [ALERTS]}, {"2026-04-07": ALERTING_FEATURES})
    args.state.unlink()
    with pytest.raises(aggr.DetectionOutputRejected) as excinfo:
        aggr.assemble(args)
    assert codes(excinfo) == ["persistence_state_unreadable"]


@pytest.mark.parametrize(
    "body,expected",
    [
        (b"{", "alert_file_unreadable"),
        (b'{"type":"Feature"}', "alert_file_not_a_feature_collection"),
        (b'{"type":"FeatureCollection"}', "alert_file_without_features"),
    ],
)
def test_um_arquivo_de_alerta_quebrado_e_recusado_nomeando_o_arquivo(
    tmp_path, body, expected
):
    """Um arquivo truncado é o que uma detecção morta no meio deixa. Recusar
    nomeando o caminho é a diferença entre um erro e uma release curta.
    """

    args = args_for(tmp_path, {"2026-04-07": [ALERTS]}, {"2026-04-07": ALERTING_FEATURES})
    aggr.alert_path(args.alerts_dir, "2026-04-07").write_bytes(body)
    with pytest.raises(aggr.DetectionOutputRejected) as excinfo:
        aggr.assemble(args)
    assert codes(excinfo) == [expected]


@pytest.mark.parametrize("bad", ["a/b", "..", "a b", "", "x\\y"])
def test_um_run_id_que_alcancaria_outro_prefixo_e_recusado(tmp_path, bad):
    args = args_for(tmp_path, {"2026-04-07": [ALERTS]},
                    {"2026-04-07": ALERTING_FEATURES}, run=bad)
    with pytest.raises(ri.RunRejected):
        aggr.assemble(args)


# ── os nomes vêm do produtor, não deste arquivo ────────────────────────────


def _assigned_fstring(source: str, function: str, target: str) -> str | None:
    """The f-string a function assigns to ``target``, as a format template."""

    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.FunctionDef) and node.name == function):
            continue
        for statement in ast.walk(node):
            if not isinstance(statement, ast.Assign):
                continue
            names = [t.id for t in statement.targets if isinstance(t, ast.Name)]
            if target not in names or not isinstance(statement.value, ast.JoinedStr):
                continue
            out = ""
            for part in statement.value.values:
                if isinstance(part, ast.Constant):
                    out += str(part.value)
                else:
                    out += "{}"
            return out
    return None


def test_o_nome_do_arquivo_de_alerta_e_o_do_produtor():
    """Lido do produtor por `ast`, não do comentário.

    `save_alerts` monta `filename = f"alerts_{detection_date}.geojson"`. Se
    alguém renomear lá, este teste cai aqui em vez de toda data parecer
    ausente na próxima rodada real.
    """

    template = _assigned_fstring(
        (ROOT / "src" / "detection" / "alerts.py").read_text(encoding="utf-8"),
        "save_alerts",
        "filename",
    )
    assert template is not None, "save_alerts no longer assigns `filename`"
    assert template == aggr.ALERT_FILENAME.replace("{observed_on}", "{}")


def test_o_diretorio_de_alertas_e_o_do_produtor():
    """`config/settings.py` define `ALERTS_DIR = DATA_DIR / "alerts"`, e a
    leitura é por texto porque IMPORTAR `config.settings` carregaria o `.env`
    de produção — ver o teste seguinte.
    """

    source = (ROOT / "config" / "settings.py").read_text(encoding="utf-8")
    assert 'DATA_DIR = ROOT_DIR / "data"' in source
    assert 'ALERTS_DIR = DATA_DIR / "alerts"' in source
    assert aggr.DEFAULT_ALERTS_DIR == Path("data/alerts")


def test_o_caminho_do_estado_de_persistencia_e_o_do_produtor():
    """`run_detection.py`: `state_path = ALERTS_DIR.parent / "persistence_state.geojson"`."""

    source = (ROOT / "scripts" / "run_detection.py").read_text(encoding="utf-8")
    assert f'ALERTS_DIR.parent / "{aggr.PERSISTENCE_STATE_NAME}"' in source


def test_nenhum_script_verde_importa_o_carregador_de_dotenv():
    """`config/settings.py` chama `load_dotenv(ROOT_DIR / ".env")` no import, e
    o `.env` do repositório guarda as credenciais de PRODUÇÃO.

    Um script verde que importasse `config.settings` para alcançar `ALERTS_DIR`
    colocaria esses valores no ambiente de um lane cujo princípio é não
    alcançar produção — o mesmo defeito medido no site, onde `wrangler dev`
    injetou cinco bindings de credencial do `.env`. Por `ast`, e não por texto:
    a docstring deste arquivo cita `config.settings` e não é um import.
    """

    for name in GREEN_SCRIPTS:
        tree = ast.parse((ROOT / "scripts" / name).read_text(encoding="utf-8"))
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [item for item in imported if item.split(".")[0] in {"config", "dotenv"}]
        assert offenders == [], f"{name} imports {offenders}"


def _first_party_module_path(module: str) -> Path | None:
    """Where a dotted first-party module lives, or ``None`` if it is external."""

    if module.split(".")[0] not in {"src", "config", "scripts", "tests"}:
        return None
    candidate = ROOT / Path(*module.split("."))
    if (candidate / "__init__.py").exists():
        return candidate / "__init__.py"
    if candidate.with_suffix(".py").exists():
        return candidate.with_suffix(".py")
    return None


def _reachable_imports(entry: Path) -> dict[str, list[str]]:
    """Every first-party module reachable from ``entry``, and who imported it.

    Follows `import`/`from ... import` through first-party files only, so an
    external package ends the walk. Sibling imports inside ``scripts/`` are
    resolved as ``scripts.<name>`` because the scripts insert their own
    directory on ``sys.path`` — ``run_detection_gee.py`` imports
    ``run_detection_from_gee`` exactly that way.
    """

    reached: dict[str, list[str]] = {}
    pending = [(entry, entry.name)]
    seen = {entry.resolve()}
    while pending:
        path, importer = pending.pop()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            else:
                continue
            for module in names:
                reached.setdefault(module, []).append(importer)
                target = _first_party_module_path(module)
                if target is None and (ROOT / "scripts" / f"{module}.py").exists():
                    module = f"scripts.{module}"
                    reached.setdefault(module, []).append(importer)
                    target = ROOT / "scripts" / f"{module.split('.')[1]}.py"
                if target is None or target.resolve() in seen:
                    continue
                seen.add(target.resolve())
                pending.append((target, module))
    return reached


def test_nenhum_script_verde_alcanca_o_carregador_de_dotenv_transitivamente():
    """O teste acima olha só os imports do PRÓPRIO script, e isso não basta.

    Um script verde que importasse `src.detection.baseline_selection` — que
    importa `config.settings` — carregaria o `.env` de produção e **passaria**
    no teste direto, porque `config` não aparece no seu próprio AST. A Phase 3
    acrescentou exatamente esse tipo de módulo: um resolvedor de baseline no
    lado azul, que o lane verde não pode alcançar nem por dois saltos.

    Mutação que este teste derruba, e que o direto não derruba: acrescentar
    `from src.detection.baseline_selection import resolve_baseline` a qualquer
    um dos cinco scripts verdes. Verificado por edição temporária.
    """

    for name in GREEN_SCRIPTS:
        reached = _reachable_imports(ROOT / "scripts" / name)
        offenders = {
            module: sorted(set(importers))
            for module, importers in reached.items()
            if module.split(".")[0] in {"config", "dotenv"}
        }
        assert offenders == {}, f"{name} reaches {offenders}"


# ── as fronteiras do lane 2, lidas deste arquivo ───────────────────────────


def test_o_ponto_de_entrada_nao_nomeia_a_identidade_de_promocao():
    """Espelho de `test_the_candidate_identity_is_not_read_by_the_cli`: se as
    duas metades lessem a mesma chave, qualquer rodada candidata poderia mover
    o ponteiro.
    """

    source = SCRIPT.read_text(encoding="utf-8")
    executable = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    tree = ast.parse(source)
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert not any("R2_PROMOTION" in value for value in literals)
    assert aggr.ACCESS_KEY_VAR == "R2_STAGING_ACCESS_KEY_ID"
    assert "R2_PROMOTION" not in executable


def test_nenhuma_escrita_de_ponteiro_e_expressavel_no_ponto_de_entrada():
    """Lane 2 escreve prefixos imutáveis e **nenhum ponteiro**. Por `ast`: nem
    o nome do ponteiro nem um `put_if_match` aparecem como código.
    """

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }
    assert POINTER_KEY not in literals
    attributes = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert "put_if_match" not in attributes
    assert "put_if_pointer_absent" not in attributes
    assert "put_if_absent" not in attributes  # it is the library that writes


def test_o_deposito_e_write_once_e_so_sob_o_prefixo_da_rodada(tmp_path):
    args = args_for(tmp_path, {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]},
                    {"2026-04-07": ALERTING_FEATURES})
    run = aggr.assemble(args)
    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    ra.upload(store, run)
    assert fake.writes
    assert all(key.startswith(run.prefix) for key, _ in fake.writes)
    assert POINTER_KEY not in fake.reads


def test_montar_nao_toca_o_store(tmp_path):
    """`plan` existe para rodar em qualquer lugar: nada é escrito e nenhuma
    credencial é lida até `apply`.
    """

    args = args_for(tmp_path, {"2026-04-07": [ALERTS]}, {"2026-04-07": ALERTING_FEATURES})
    fake = FakeS3()
    aggr.assemble(args)
    assert fake.writes == [] and fake.reads == []


# ── a cláusula do gate: rodada falhada ─────────────────────────────────────


def published_release(store, spec, features, run_id):
    """Assemble, deposit, read back and publish one run."""

    document, _ = build_ledger(spec)
    run = ra.assemble_run(
        run_id, document, features,
        persistence_state_sha256="a" * 64, persistence_state_bytes=126469137,
    )
    ra.upload(store, run)
    staged = ri.load_run(store, run_id)
    publish_release(store, staged.release, staged.ledger_document, staged.bodies)
    verify_release(store, staged.release)
    return staged


SPEC_A = {"2026-04-07": [ALERTS], "2026-04-10": [ZERO]}
SPEC_B = {"2026-04-07": [ALERTS], "2026-04-10": [ZERO], "2026-04-13": [ALERTS]}
SPEC_C = dict(SPEC_B, **{"2026-04-16": [ALERTS]})
FEAT_A = {"2026-04-07": ALERTING_FEATURES, "2026-04-10": []}
FEAT_B = {"2026-04-07": ALERTING_FEATURES, "2026-04-10": [], "2026-04-13": [areal()]}
FEAT_C = dict(FEAT_B, **{"2026-04-16": [areal()]})


def test_uma_rodada_que_morre_antes_do_manifesto_nao_e_publicavel():
    """Deliberadamente falhada: o manifesto vai por último, então uma rodada
    interrompida não tem `run.json` e as duas lanes a recusam pelo mesmo
    achado — em vez de publicarem meia rodada.
    """

    fake = FakeS3(interrupt_after=2)
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    document, _ = build_ledger(SPEC_A)
    run = ra.assemble_run(
        "dies-early", document, FEAT_A,
        persistence_state_sha256="a" * 64, persistence_state_bytes=1,
    )
    with pytest.raises(Exception):
        ra.upload(store, run)
    assert ri.RUN_MANIFEST_PATH not in {key.split("/")[-1] for key, _ in fake.writes}

    with pytest.raises(ri.RunRejected) as excinfo:
        ri.load_run(store, "dies-early")
    assert codes(excinfo) == ["run_manifest_absent"]


def test_uma_rodada_falhada_deixa_a_release_anterior_viva_e_completa():
    """A metade que importa do gate: nada de corromper, nada de expor parcial.

    A releituura é do store, com `rollback` recusando um alvo incompleto — logo
    "viva e completa" é verificado, não afirmado.
    """

    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    staged_a = published_release(store, SPEC_A, FEAT_A, "alive-a")
    first = promote(store, staged_a.release, staged_a.ledger_document, now=NOW, promoted_by=CI)
    live_before, etag_before = read_pointer(store)

    # A segunda rodada morre no meio do depósito.
    document, _ = build_ledger(SPEC_B)
    run_b = ra.assemble_run(
        "dies-b", document, FEAT_B,
        persistence_state_sha256="a" * 64, persistence_state_bytes=1,
    )
    fake.interrupt_after = len(fake.writes) + 2
    with pytest.raises(Exception):
        ra.upload(store, run_b)

    live_after, etag_after = read_pointer(store)
    assert (live_after, etag_after) == (live_before, etag_before)
    assert live_after["release_id"] == staged_a.release_id == first.release_id
    verify_release(store, staged_a.release)          # still complete
    assert not any(
        key.startswith("releases/") and key.endswith("release.json")
        and staged_a.release_id not in key
        for key, _ in fake.writes
    )


# ── a cláusula do gate: rodada concorrente ─────────────────────────────────


class StalePointerView:
    """The store as a racing job sees it: the pointer it read is no longer live.

    Exactly the shape of a real race — read, someone else moves it, write —
    and the only way to make that interleaving deterministic without a clock
    or a thread.  Everything but the pointer read is the real store.
    """

    def __init__(self, inner, stale):
        self.inner, self.stale = inner, stale
        self.bucket = inner.bucket

    def get(self, key):
        return self.stale if key == POINTER_KEY else self.inner.get(key)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def test_uma_rodada_concorrente_com_visao_velha_do_ponteiro_perde_o_cas():
    """"an older or racing job cannot replace a newer release" — a metade
    concorrente, e é o compare-and-swap que a decide, **porque a política não
    pode**.

    A montagem é a que mostra por quê, e a primeira tentativa deste teste
    errou de forma instrutiva: um corredor que re-promove a release que a sua
    visão velha já diz viva sai pelo galho ``unchanged`` de ``promote`` e não
    escreve nada — seguro, mas não é o compare-and-swap.

    Aqui o corredor promove B, que a sua visão velha (A viva, até 04-10) aceita
    como avanço legítimo. Enquanto isso o ponteiro real já está em C, até
    04-16. **A comparação de cobertura de ``promote`` diz sim**, porque ela
    compara com o que o corredor leu; se a escrita passasse, uma release de
    04-13 substituiria uma de 04-16 — a regressão exata que a política existe
    para impedir, invisível a ela. O ``If-Match`` é o que fecha isso.
    """

    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    staged_a = published_release(store, SPEC_A, FEAT_A, "race-a")
    staged_b = published_release(store, SPEC_B, FEAT_B, "race-b")
    staged_c = published_release(store, SPEC_C, FEAT_C, "race-c")

    promote(store, staged_a.release, staged_a.ledger_document, now=NOW, promoted_by=CI)
    stale = store.require(POINTER_KEY)                  # what the racer read
    promote(store, staged_c.release, staged_c.ledger_document, now=NOW, promoted_by=CI)
    live_before = store.require(POINTER_KEY)
    assert live_before.etag != stale.etag
    assert json.loads(stale.body)["release_id"] == staged_a.release_id

    # The racer's own policy check passes against its stale view …
    assert (
        staged_b.release["coverage"]["last_observed_on"]
        > json.loads(stale.body)["coverage"]["last_observed_on"]
    )
    # … while the live release is in fact NEWER than the racer's candidate.
    assert (
        staged_b.release["coverage"]["last_observed_on"]
        < json.loads(live_before.body)["coverage"]["last_observed_on"]
    )

    racer = StalePointerView(store, stale)
    with pytest.raises(PreconditionFailed):
        promote(racer, staged_b.release, staged_b.ledger_document, now=NOW, promoted_by=CI)

    after = store.require(POINTER_KEY)
    assert (after.body, after.etag) == (live_before.body, live_before.etag)
    assert json.loads(after.body)["release_id"] == staged_c.release_id


def test_um_corredor_que_re_promove_a_release_que_ja_viu_viva_nao_escreve():
    """O galho que o teste acima descobriu, fixado de propósito: é seguro, e
    saber que ele existe é o que impede alguém de "provar" o CAS com ele.
    """

    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    staged_a = published_release(store, SPEC_A, FEAT_A, "noop-a")
    staged_c = published_release(store, SPEC_C, FEAT_C, "noop-c")
    promote(store, staged_a.release, staged_a.ledger_document, now=NOW, promoted_by=CI)
    stale = store.require(POINTER_KEY)
    promote(store, staged_c.release, staged_c.ledger_document, now=NOW, promoted_by=CI)
    live_before = store.require(POINTER_KEY)

    racer = StalePointerView(store, stale)
    outcome = promote(
        racer, staged_a.release, staged_a.ledger_document, now=NOW, promoted_by=CI
    )
    assert outcome.action == "unchanged"
    after = store.require(POINTER_KEY)
    assert (after.body, after.etag) == (live_before.body, live_before.etag)


def test_uma_rodada_mais_velha_nao_substitui_uma_release_mais_nova():
    """A outra metade, e é *dado* que decide, não ordem de escrita: um replay
    de uma janela velha é uma escrita posterior de dado anterior.
    """

    from src.publication.atomic_publish import PromotionRefused

    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    staged_a = published_release(store, SPEC_A, FEAT_A, "old-a")
    staged_b = published_release(store, SPEC_B, FEAT_B, "old-b")
    promote(store, staged_b.release, staged_b.ledger_document, now=NOW, promoted_by=CI)
    live_before = store.require(POINTER_KEY)

    with pytest.raises(PromotionRefused) as excinfo:
        promote(store, staged_a.release, staged_a.ledger_document, now=NOW, promoted_by=CI)
    assert codes(excinfo) == ["coverage_regression"]

    after = store.require(POINTER_KEY)
    assert (after.body, after.etag) == (live_before.body, live_before.etag)


def test_duas_rodadas_diferentes_com_um_id_falham_fechado_e_a_release_nao_muda():
    """Duas rodadas reivindicando uma identidade. A recusa cai no `ledger.json`
    — não nos objetos — porque `put_if_absent` é por chave e as datas da
    segunda rodada são outras.

    Medido contra o R2 real em 2026-09-08: a rodada em conflito **acrescentou**
    dois objetos ao prefixo antes de colidir, e a rodada continuou lendo como a
    MESMA release, porque `run.json` é quem declara e vai por último. O
    prefixo é imutável no que decide a release, e não é à prova de acréscimo.
    """

    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    staged = published_release(store, SPEC_A, FEAT_A, "one-id")

    other, _ = build_ledger({"2026-04-13": [ALERTS]})
    clash = ra.assemble_run(
        "one-id", other, {"2026-04-13": [areal()]},
        persistence_state_sha256="b" * 64, persistence_state_bytes=2,
    )
    with pytest.raises(ImmutableObjectConflict):
        ra.upload(store, clash)

    again = ri.load_run(store, "one-id")
    assert again.release_id == staged.release_id
    assert again.document == staged.document
    stray = [
        key for key in fake.objects
        if key.startswith("runs/one-id/") and "2026-04-13" in key
    ]
    assert stray, "the measured nuance changed: nothing was appended"
    assert all(
        item["path"] not in {Path(key).name for key in stray}
        for item in again.document["objects"]
    )

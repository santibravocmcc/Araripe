"""O montador da rodada: a peça que faltava desde o Package 2B.2C.

Exit gate P2B. O caminho de publicação já sabia ler um prefixo de rodada,
publicá-lo, verificá-lo e mover o ponteiro; o prefixo era montado à mão, por um
andaime que vivia fora do repositório. Estes testes fixam o que o montador tem
de garantir, e as três propriedades que carregam o peso são:

* **o subconjunto forte é exatamente `strong_features`** — propriedade E
  geometria. Filtrar só pela propriedade publica um objeto com mais feições que
  o número exibido ao lado dele, que é o defeito que o 2B.4B achou por fixture;
* **exatamente um objeto cheio e um forte por data que publica**, e a
  classificação não pode depender da ordem de declaração, porque
  `run-<data>.strong.geojson` também termina em `.geojson`;
* **montar duas vezes dá bytes idênticos** — o prefixo da release é função do
  ledger, então a segunda publicação da mesma rodada compara bytes e falha
  fechado se eles diferirem.

Tudo determinístico: sem rede, sem relógio, sem object store, sem credencial.
"""

from __future__ import annotations

import json

import pytest

from src.publication import conditional_store as cs
from src.publication import run_assembler as ra
from src.publication import run_inputs as ri
from src.publication import site_artifact
from src.publication.atomic_publish import promote, publish_release, rollback, verify_release
from src.publication.conditional_store import ConditionalStore, ImmutableObjectConflict
from src.publication.green_release import LEDGER_PATH, schema_validator, sha256_bytes
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, FAILED, REJECTED, ZERO, build_ledger
from tests.test_atomic_publish import CI, NOW

STATE_SHA = "a" * 64
STATE_BYTES = 126469137
RUN_ID = "gate-p2b-2026-09-08"


# ── fixtures de feição, com a armadilha de geometria explícita ──────────────


def areal(**properties):
    """Uma feição areal — Polygon — que o site conta e desenha."""

    base = {
        "confidence_label": "high",
        "persistence_count": 30,
        "lc_natural_frac_10m": 0.9,
    }
    base.update(properties)
    return {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
        "properties": base,
    }


def point(**properties):
    """Uma feição de PONTO com propriedades fortes.

    É a armadilha: `is_strong` diria sim, e `run_statistics` não a conta. O
    subconjunto forte tem de excluí-la.
    """

    base = {
        "confidence_label": "high",
        "persistence_count": 30,
        "lc_natural_frac_10m": 0.9,
    }
    base.update(properties)
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [0, 0]}, "properties": base}


#: Uma data com alertas, montada para exercitar cada conjunto de `is_strong`
#: separadamente, mais a armadilha de geometria:
#:   0  areal forte
#:   1  areal com confiança média      -> fora (confidence_label)
#:   2  PONTO com propriedades fortes  -> fora (geometria)
#:   3  areal com fração natural baixa -> fora (lc_natural_frac_10m)
#:   4  areal com uma observação só    -> fora (persistence_count)
#:   5  areal forte, para o subconjunto ser uma LISTA e a ordem importar
ALERTING_FEATURES = [
    areal(),
    areal(confidence_label="medium"),
    point(),
    areal(lc_natural_frac_10m=0.1),
    areal(persistence_count=1),
    areal(lc_natural_frac_10m=0.75),
]

SPEC = {"2026-04-07": [ALERTS, REJECTED], "2026-04-10": [ZERO]}


def assemble(spec=None, features=None, run_id=RUN_ID, **kwargs):
    document, _ = build_ledger(spec or SPEC)
    if features is None:
        features = {"2026-04-07": ALERTING_FEATURES, "2026-04-10": []}
    return ra.assemble_run(
        run_id,
        document,
        features,
        persistence_state_sha256=kwargs.pop("state_sha", STATE_SHA),
        persistence_state_bytes=kwargs.pop("state_bytes", STATE_BYTES),
    ), document


def codes(excinfo):
    return sorted(excinfo.value.codes)


# ── a propriedade central: o subconjunto forte ──────────────────────────────


def test_o_subconjunto_forte_e_exatamente_o_que_a_autoridade_diz():
    """Não uma reimplementação: a mesma função que o site usa para contar.

    Duas fortes areais entre quatro feições. O ponto tem propriedades fortes e
    fica fora, porque não tem geometria contável.
    """

    run, _ = assemble()
    body = run.bodies[ra.strong_object_path("2026-04-07")]
    features = json.loads(body)["features"]
    assert features == site_artifact.strong_features(ALERTING_FEATURES)
    assert len(features) == 2
    assert all(f["geometry"]["type"] == "Polygon" for f in features)


def test_a_feicao_de_ponto_com_propriedades_fortes_fica_fora_do_forte():
    """O defeito exato que o 2B.4B achou, pinado do lado do produtor.

    Um Point com `confidence_label: high` e 30 observações passa em `is_strong`
    e não passa em `is_counted`. Se ele entrasse no objeto, o arquivo teria mais
    feições do que o número `strong` que a página imprime ao lado.
    """

    run, _ = assemble()
    strong = json.loads(run.bodies[ra.strong_object_path("2026-04-07")])["features"]
    assert not any(f["geometry"]["type"] == "Point" for f in strong)
    # E a contagem que o site publicaria bate com o objeto.
    stats = site_artifact.run_statistics(ALERTING_FEATURES)
    assert stats["strong"] == len(strong)


def test_o_objeto_cheio_carrega_todas_as_feicoes_inclusive_a_de_ponto():
    """Cheio é cheio: o subconjunto é o forte, não o contável."""

    run, _ = assemble()
    full = json.loads(run.bodies[ra.full_object_path("2026-04-07")])["features"]
    assert full == list(ALERTING_FEATURES)
    assert any(f["geometry"]["type"] == "Point" for f in full)


# ── exatamente um de cada, e a ordem dos sufixos ────────────────────────────


def test_cada_data_que_publica_declara_exatamente_um_cheio_e_um_forte():
    run, _ = assemble()
    by_date: dict[str, list[str]] = {}
    for item in run.document["objects"]:
        by_date.setdefault(item["observed_on"], []).append(item["path"])
    assert sorted(by_date) == ["2026-04-07", "2026-04-10"]
    for observed_on, paths in by_date.items():
        full, strong = site_artifact.classify_run_objects(paths)
        assert full == ra.full_object_path(observed_on)
        assert strong == ra.strong_object_path(observed_on)


def test_a_classificacao_nao_depende_da_ordem_em_que_o_montador_declara():
    """`run-<data>.strong.geojson` também termina em `.geojson`.

    Testar o sufixo cheio primeiro classificaria o subconjunto como a rodada
    inteira, em silêncio, e a visão default da página passaria a carregar todos
    os candidatos. O montador não pode depender de sorte na ordem.
    """

    run, _ = assemble()
    paths = [item["path"] for item in run.document["objects"] if item["observed_on"] == "2026-04-07"]
    assert site_artifact.classify_run_objects(paths) == site_artifact.classify_run_objects(
        list(reversed(paths))
    )


def test_o_sufixo_forte_e_lido_da_autoridade_e_nao_redigitado():
    assert ra.FULL_SUFFIX is site_artifact.FULL_OBJECT_SUFFIX
    assert ra.STRONG_SUFFIX is site_artifact.STRONG_OBJECT_SUFFIX
    assert ra.strong_object_path("2026-04-07").endswith(site_artifact.FULL_OBJECT_SUFFIX)


# ── quais datas publicam, medido no consumidor ──────────────────────────────


def test_uma_data_de_zero_alertas_publica_duas_colecoes_vazias():
    """Observação positiva de ausência, não omissão.

    Uma data que não publicasse nada seria indistinguível de uma que ninguém
    olhou — e o consumidor exige exatamente um de cada para toda data que não
    seja `no_valid_coverage`.
    """

    run, _ = assemble()
    for path in (ra.full_object_path("2026-04-10"), ra.strong_object_path("2026-04-10")):
        assert json.loads(run.bodies[path]) == {"type": "FeatureCollection", "features": []}


def test_uma_data_sem_cobertura_nao_publica_objeto_nenhum():
    """`no_valid_coverage` não foi uma execução; a página lista execuções.

    Medido no consumidor: `site/scripts/site_artifact.py:444` a pula antes de
    exigir os dois objetos.
    """

    spec = {"2026-04-07": [ALERTS], "2026-04-09": [REJECTED, FAILED]}
    run, _ = assemble(spec=spec, features={"2026-04-07": ALERTING_FEATURES})
    states = ra.dates_by_state(run.acceptance)
    assert states["2026-04-09"] == ra.UNOBSERVED_STATE
    assert not any(item["observed_on"] == "2026-04-09" for item in run.document["objects"])


def test_feicoes_para_uma_data_sem_cobertura_sao_recusadas():
    """Uma data sem cobertura não pode ter alertas; uma das entradas está errada."""

    spec = {"2026-04-07": [ALERTS], "2026-04-09": [REJECTED, FAILED]}
    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        assemble(spec=spec, features={"2026-04-07": ALERTING_FEATURES, "2026-04-09": [areal()]})
    assert codes(excinfo) == ["features_for_an_unobserved_date"]


def test_uma_data_que_o_ledger_reconcilia_e_nao_tem_saida_e_recusada():
    """Zero alertas é uma lista vazia, não uma chave ausente.

    A diferença é se alguém olhou — e é exatamente a distinção que o contrato da
    release existe para preservar.
    """

    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        assemble(features={"2026-04-07": ALERTING_FEATURES})
    assert codes(excinfo) == ["date_without_detection_output"]


def test_uma_data_com_alertas_e_sem_feicoes_e_recusada():
    """O ledger diz que houve observações; publicar vazio contradiria o ledger."""

    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        assemble(features={"2026-04-07": [], "2026-04-10": []})
    assert codes(excinfo) == ["alerting_date_without_features"]


def test_feicoes_para_uma_data_que_o_ledger_nao_reconhece_sao_recusadas():
    """O ledger decide quais datas existem, não a saída da detecção."""

    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        assemble(
            features={
                "2026-04-07": ALERTING_FEATURES,
                "2026-04-10": [],
                "2026-04-30": [areal()],
            }
        )
    assert codes(excinfo) == ["features_for_an_unreconciled_date"]


def test_todos_os_achados_sao_coletados_antes_de_levantar():
    """`findings.py`: o operador aprende a escala na primeira linha."""

    with pytest.raises(ra.RunAssemblyRejected) as excinfo:
        assemble(features={"2026-04-99": [areal()], "2026-04-98": [areal()]})
    assert len(excinfo.value.findings) >= 3  # duas datas estranhas + duas ausentes


# ── o documento da rodada ───────────────────────────────────────────────────


def test_o_documento_valida_contra_o_schema_da_rodada():
    run, _ = assemble()
    errors = list(schema_validator("green-run-v1").iter_errors(run.document))
    assert errors == [], [error.message for error in errors]


def test_os_objetos_sao_date_product_e_nao_declaram_acquisition_id():
    """Eles são compostos pelo publicador, não selados por uma linha do ledger.

    E o schema proíbe `acquisition_id` num `date_product`, então declará-lo
    seria recusado — mas a razão vem antes do schema: o ledger não faz promessa
    nenhuma sobre estes bytes.
    """

    run, _ = assemble()
    for item in run.document["objects"]:
        assert item["kind"] == "date_product"
        assert "acquisition_id" not in item
        assert item["content_type"] == ra.GEOJSON_CONTENT_TYPE
        assert item["source"] == item["path"]


def test_o_documento_nomeia_a_propria_rodada_e_o_ledger_no_lugar_fixo():
    run, _ = assemble()
    assert run.document["run_id"] == RUN_ID
    assert run.document["ledger"] == LEDGER_PATH
    assert run.document["schema"] == ri.RUN_SCHEMA
    assert run.document["persistence_state"] == {"sha256": STATE_SHA, "bytes": STATE_BYTES}


@pytest.mark.parametrize("bad", ["../escape", "a/b", "..", "", "with space", "back\\slash"])
def test_um_run_id_que_alcancaria_outro_prefixo_e_recusado(bad):
    """A mesma regra de `run_inputs.validate_run_id`, aplicada na produção.

    Um run id é um segmento de caminho; um que carregue `/` ou `..` escreveria
    fora do próprio prefixo.
    """

    with pytest.raises(ri.RunRejected):
        assemble(run_id=bad)


# ── determinismo, que é o que a imutabilidade cobra ─────────────────────────


def test_montar_duas_vezes_da_bytes_identicos():
    """O prefixo é função do ledger; a segunda publicação compara BYTES.

    Se a montagem não fosse determinística, republicar a mesma rodada falharia
    como `ImmutableObjectConflict` em vez de ser um no-op — e o operador veria
    um conflito de identidade onde não há nenhum.
    """

    first, _ = assemble()
    second, _ = assemble()
    assert first.bodies == second.bodies
    assert first.document == second.document


def test_a_ordem_das_feicoes_de_entrada_e_preservada():
    """`strong_features` documenta "in input order", e o objeto o respeita.

    Reordenar aqui mudaria os bytes sem mudar o ledger, o que é exatamente a
    forma de quebrar o determinismo acima.
    """

    run, _ = assemble()
    strong = json.loads(run.bodies[ra.strong_object_path("2026-04-07")])["features"]
    assert strong == [f for f in ALERTING_FEATURES if f in strong]


def test_o_ledger_viaja_como_o_produtor_o_escreveu_e_nao_reencodado():
    """Não-requisito 4 do binding: um ledger não precisa chegar canônico.

    Reencodar aqui faria este módulo autor de bytes cujos digests o produtor
    selou. O que importa é que o documento parseado seja o mesmo.
    """

    run, ledger = assemble()
    assert json.loads(run.bodies[LEDGER_PATH]) == ledger


# ── ponta a ponta: o que o gate realmente pede ──────────────────────────────


def store():
    fake = FakeS3()
    return ConditionalStore(fake, cs.STAGING_BUCKET), fake


def stage(conditional, fake, run_id, spec, features):
    """Montar, enviar, e ler de volta uma rodada — o caminho do operador."""

    run, _ = assemble(spec=spec, features=features, run_id=run_id)
    ra.upload(conditional, run)
    return run, ri.load_run(ri.ReadOnlyStore(fake, cs.STAGING_BUCKET), run_id)


def test_a_rodada_montada_e_lida_de_volta_publicada_promovida_e_revertida():
    """A cadeia inteira, do montador ao ponteiro, sobre um store que impõe as
    precondições do R2 — e com DUAS rodadas, porque a cláusula do gate fala de
    mover *e* reverter.

    Reverter para a release que já está no ar não prova nada: o ponteiro já a
    nomeia. Então a segunda rodada cobre uma data a mais, é promovida, e a
    reversão traz a primeira de volta — a mesma forma dos cinco movimentos
    provados contra o R2 real em 2026-09-07.
    """

    conditional, fake = store()

    run_a, staged_a = stage(
        conditional, fake, "gate-a", SPEC,
        {"2026-04-07": ALERTING_FEATURES, "2026-04-10": []},
    )
    spec_b = dict(SPEC, **{"2026-04-13": [ALERTS]})
    run_b, staged_b = stage(
        conditional, fake, "gate-b", spec_b,
        {"2026-04-07": ALERTING_FEATURES, "2026-04-10": [], "2026-04-13": [areal()]},
    )
    assert staged_a.release_id != staged_b.release_id

    # A: publicar, verificar, promover.
    publish_release(conditional, staged_a.release, staged_a.ledger_document, staged_a.bodies)
    verify_release(conditional, staged_a.release)
    first = promote(
        conditional, staged_a.release, staged_a.ledger_document, now=NOW, promoted_by=CI
    )
    assert first.pointer["sequence"] == 1
    assert first.pointer["release_id"] == staged_a.release_id

    # B: cobertura mais nova, então `promote` aceita e registra o supersede.
    publish_release(conditional, staged_b.release, staged_b.ledger_document, staged_b.bodies)
    verify_release(conditional, staged_b.release)
    second = promote(
        conditional, staged_b.release, staged_b.ledger_document, now=NOW, promoted_by=CI
    )
    assert second.pointer["sequence"] == 2
    assert second.pointer["release_id"] == staged_b.release_id
    assert second.pointer["supersedes"]["release_id"] == staged_a.release_id

    # E a reversão: a sequência sobe, a cobertura volta.
    back = rollback(conditional, staged_a.release_id, now=NOW, promoted_by=CI)
    assert back.pointer["sequence"] == 3
    assert back.pointer["action"] == "rollback"
    assert back.pointer["release_id"] == staged_a.release_id
    assert back.pointer["rolled_back_from"]["release_id"] == staged_b.release_id
    assert (
        back.pointer["coverage"]["last_observed_on"]
        < second.pointer["coverage"]["last_observed_on"]
    )


def test_reenviar_a_mesma_rodada_e_um_no_op_idempotente():
    run, _ = assemble()
    conditional, fake = store()
    ra.upload(conditional, run)
    before = list(fake.writes)
    again = ra.upload(conditional, run)
    assert fake.writes == before
    assert all(line.startswith("unchanged ") for line in again)


def test_bytes_diferentes_sob_o_mesmo_run_id_falham_fechado():
    """Um prefixo de rodada é imutável, e duas montagens diferentes com o mesmo
    id são duas rodadas reivindicando uma identidade.
    """

    run, _ = assemble()
    conditional, _ = store()
    ra.upload(conditional, run)
    other, _ = assemble(features={"2026-04-07": [areal()], "2026-04-10": []})
    with pytest.raises(ImmutableObjectConflict):
        ra.upload(conditional, other)


def test_o_montador_nao_escreve_nada_por_conta_propria():
    """Montar é puro: nada é enviado até `upload` ser chamado.

    O que separa "montei" de "publiquei" é uma chamada, e é ela que o operador
    decide fazer.
    """

    _, fake = store()
    assemble()
    assert fake.writes == []


def test_o_upload_e_write_once_em_todo_objeto():
    """Nenhuma escrita incondicional, e nenhum `If-Match` num prefixo imutável."""

    run, _ = assemble()
    conditional, fake = store()
    ra.upload(conditional, run)
    assert len(fake.writes) == len(run.bodies)
    assert all(key.startswith(run.prefix) for key, _ in fake.writes)


def test_o_resumo_do_operador_conta_feicoes_e_nao_so_bytes():
    run, _ = assemble()
    text = ra.describe(run)
    assert RUN_ID in text
    assert "feature(s)" in text
    assert ra.strong_object_path("2026-04-07") in text
    assert sha256_bytes(run.bodies[ra.full_object_path("2026-04-07")])[:12] in text


def test_a_ordem_DAS_CHAVES_da_entrada_nao_muda_os_bytes():
    """`sort_keys` é o que torna isso verdade, e a mutação revelou a lacuna.

    O teste de determinismo anterior comparava duas montagens da MESMA entrada,
    e dicionários em Python preservam ordem de inserção — então tirar
    `sort_keys` não quebrava nada. Mas a detecção não promete ordem de chave: se
    ela montar as propriedades de uma feição por comprehension sobre um conjunto,
    duas execuções semanticamente idênticas dariam bytes diferentes, e a segunda
    publicação da mesma rodada falharia como conflito de imutabilidade.

    Duas feições iguais, com as chaves inseridas em ordem oposta.
    """

    ordered = {
        "type": "Feature",
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
        "properties": {
            "confidence_label": "high",
            "persistence_count": 30,
            "lc_natural_frac_10m": 0.9,
        },
    }
    shuffled = {
        "properties": {
            "lc_natural_frac_10m": 0.9,
            "persistence_count": 30,
            "confidence_label": "high",
        },
        "geometry": {"coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]], "type": "Polygon"},
        "type": "Feature",
    }
    assert ordered == shuffled  # semanticamente a mesma feição
    assert list(ordered) != list(shuffled)  # e com ordem de chave diferente
    assert ra.feature_collection([ordered]) == ra.feature_collection([shuffled])


def test_o_manifesto_da_rodada_e_enviado_por_ultimo():
    """Uma rodada meio enviada não tem `run.json`, e `load_run` a recusa.

    Espelha a ordem da publicação de release — manifesto por último — para que a
    presença do manifesto seja evidência de que os corpos chegaram. A mutação
    que o punha primeiro não derrubava nada, porque a asserção tinha ficado num
    teste que eu reescrevi.
    """

    run, _ = assemble()
    conditional, fake = store()
    written = ra.upload(conditional, run)
    assert written[-1].endswith(ri.RUN_MANIFEST_PATH)
    assert [key for key, _ in fake.writes][-1] == run.prefix + ri.RUN_MANIFEST_PATH
    # E todo o resto foi escrito antes dele.
    assert len(written) == len(run.bodies)

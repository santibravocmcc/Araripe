"""O ensaio limitado do replay, executado — não descrito.

Phase 3, item 4 do escopo, e a cláusula em que o exit gate P3 pega: *"The small
rehearsal is reproducible, completeness checks pass, rollback works, and the
full replay can run without mutating the live release."*

Os quatro passos que o roadmap nomeia são **rodados** aqui, contra um store que
impõe as precondições do R2 (`tests/fake_object_store.FakeS3`) e que pode ser
mandado falhar numa chave nomeada. Isso importa: um store que nunca falha não
exercita o galho de recuperação, e um ensaio que não pode falhar não prova nada
sobre falhar. `run_rehearsal` levanta `RehearsalError` se a publicação
interrompida tiver sucesso, exatamente por isso.

O que cada passo prova, e o que cai se ele quebrar:

1. **staging** — um intervalo pequeno publica sob prefixo imutável e o ponteiro
   anda uma vez;
2. **recuperação de falha** — a publicação cortada ao meio deixa a release
   anterior viva E completa, e a retentativa converge no MESMO `release_id`,
   porque a identidade é derivada do ledger e não cunhada;
3. **reversão de ponteiro** — o ponteiro volta, e a `sequence` ainda só cresce
   (ela conta escritas, não recência de dado — conflatar as duas é a armadilha
   que `atomic_publish` documenta);
4. **recuperação de data enfileirada** — a data que o corte deixou de fora
   entra numa release posterior sem tocar um byte da anterior.

E a quinta, que é propriedade das quatro: **nenhuma chave de produção é
escrita**, medido do log de escritas do store e não afirmado.

Determinístico: sem rede, sem relógio real, sem object store, sem credencial.
"""

from __future__ import annotations

import pytest

from src.publication import conditional_store as cs
from src.publication.atomic_publish import publish_release, read_pointer
from src.publication.conditional_store import ConditionalStore
from src.publication.green_release import POINTER_KEY, build_release
from src.publication.ledger_gate import check_processing_ledger
from src.replay import rehearsal as rh
from tests.fake_object_store import FakeS3
from tests.green_release_fixtures import ALERTS, ZERO, build_ledger
from tests.test_atomic_publish import CI, LATER, NOW
from tests.test_green_release import STATE_BYTES, STATE_SHA, objects_for

#: A deliberately small bounded range: three pre-cutoff dates, one of them a
#: quiet observed day, plus one post-cutoff date to queue.
PRE_CUTOFF = {
    "2026-08-22": [ALERTS],
    "2026-08-25": [ZERO],
    "2026-08-30": [ALERTS, ALERTS],
}
QUEUED_DATE = "2026-09-02"
CUTOFF = "2026-08-30"


def _release(spec):
    document, bodies = build_ledger(spec)
    acceptance = check_processing_ledger(document)
    objects = objects_for(document, bodies)
    release = build_release(
        acceptance,
        document,
        objects,
        persistence_state_sha256=STATE_SHA,
        persistence_state_bytes=STATE_BYTES,
    )
    return release, document, {item.path: item.body for item in objects}


def _input(label, spec):
    release, document, bodies = _release(spec)
    return rh.ReleaseInput(
        label=label, release=release, ledger_document=document, bodies=bodies
    )


def _inputs():
    """The three releases the rehearsal needs, and the key to fail on.

    ``interrupted`` adds one date to the pre-cutoff set, so it declares an
    object the earlier release does not — which is the object the store is
    told to refuse, cutting the publication in half.
    """

    pre = _input("pre_cutoff", PRE_CUTOFF)
    with_extra = dict(PRE_CUTOFF)
    with_extra["2026-08-31"] = [ALERTS]
    interrupted = _input("interrupted", with_extra)
    drained_spec = dict(with_extra)
    drained_spec[QUEUED_DATE] = [ALERTS]
    drained = _input("drained", drained_spec)

    new_paths = sorted(
        {item["path"] for item in interrupted.release["objects"]}
        - {item["path"] for item in pre.release["objects"]}
    )
    assert new_paths, "the interrupted release must declare something new"
    fail_key = f"{interrupted.prefix}{new_paths[-1]}"
    return pre, interrupted, drained, fail_key


def _run(*, seed_objects=None):
    pre, interrupted, drained, fail_key = _inputs()
    fake = FakeS3(objects=seed_objects, fail_on={fail_key})
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    rh.staging_bucket_only(store)
    # The retry store must share the SAME objects dict, so it is literally the
    # same store without the injected failure. `FakeS3.__init__` COPIES what it
    # is given, so passing `fake.objects` there would hand the retry a snapshot
    # taken before anything was published — a fresh, empty store, which proves
    # nothing about recovering from a half-written prefix. (Measured: it made
    # the first promotion fail with "release.json is absent".)
    retry_fake = FakeS3()
    retry_fake.objects = fake.objects
    retry_store = ConditionalStore(retry_fake, cs.STAGING_BUCKET)
    record = rh.run_rehearsal(
        store=store,
        pre_cutoff=pre,
        interrupted=interrupted,
        drained=drained,
        now=NOW,
        later=LATER,
        promoted_by=CI,
        interrupt_on=fail_key,
        retry_store=retry_store,
        queued_dates=[QUEUED_DATE],
    )
    return record, store, retry_store, pre, interrupted, drained, fail_key


# ── o ensaio roda, e o registro cobre os quatro passos ───────────────────────


def test_o_ensaio_completa_os_quatro_passos():
    record, *_ = _run()
    document = record.to_dict()
    rh.validate_rehearsal(document)
    assert set(document["steps"]) == set(rh.REHEARSAL_STEPS)


def test_um_registro_sem_um_dos_passos_e_recusado():
    record, *_ = _run()
    document = record.to_dict()
    document["steps"].pop("pointer_rollback")
    document["rehearsal_sha256"] = rh.canonical_sha256(
        {key: value for key, value in document.items() if key != "rehearsal_sha256"}
    )
    with pytest.raises(rh.RehearsalError, match="pointer_rollback"):
        rh.validate_rehearsal(document)


# ── 1. staging ───────────────────────────────────────────────────────────────


def test_o_intervalo_limitado_publica_e_o_ponteiro_anda_uma_vez():
    record, store, _retry, pre, *_ = _run()
    step = record.steps["staging"]
    assert step["pointer_sequence"] == 1
    assert step["pointer_action"] == "promote"
    assert step["completeness"]["complete"] is True
    assert step["prefix"] == pre.prefix
    assert step["declared_objects"] == len(pre.release["objects"])


def test_o_intervalo_do_ensaio_e_pequeno_e_inclui_um_dia_quieto():
    """Um dia observado sem alertas não tem arquivo nenhum, e o contrato exige
    que ele exista como data. Se o ensaio só tivesse datas com alerta, o galho
    de zero alertas nunca seria exercitado.
    """

    pre, *_ = _inputs()
    dates = {row["observed_on"] for row in pre.ledger_document["terminal_rows"]}
    assert dates == set(PRE_CUTOFF)
    assert len(dates) == 3
    statuses = {row["status"] for row in pre.ledger_document["terminal_rows"]}
    assert "complete_zero_alerts" in statuses


# ── 2. recuperação de falha ──────────────────────────────────────────────────


def test_uma_publicacao_cortada_ao_meio_deixa_a_anterior_viva_e_completa():
    record, *_ = _run()
    step = record.steps["failure_recovery"]
    assert step["raised"] in {"ObjectStoreError", "ReleaseIncomplete"}
    assert step["pointer_survived_at"]["sequence"] == 1
    assert step["completeness"]["complete"] is True


def test_a_retentativa_converge_na_mesma_identidade_de_release():
    """A identidade é função do ledger, então republicar não é conflito: é
    no-op para os objetos que já saíram, e criação para os que faltavam.
    """

    record, store, retry_store, _pre, interrupted, *_ = _run()
    step = record.steps["failure_recovery"]
    assert step["retry_release_id"] == interrupted.release_id
    assert step["retry_created"] >= 1, "a retentativa tinha de criar o que faltou"
    assert step["retry_unchanged"] >= 1, (
        "e tinha de reencontrar, byte a byte, o que a tentativa interrompida "
        "já havia escrito"
    )
    assert step["pointer_sequence"] == 2


def test_um_ensaio_cujo_passo_de_falha_nao_falha_e_recusado():
    """A armadilha que este teste fecha: se o store deixasse de falhar, o
    ensaio passaria a "provar" recuperação sem nunca ter falhado. Medido
    rodando o ensaio com um store que aceita tudo.
    """

    pre, interrupted, drained, _fail_key = _inputs()
    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    with pytest.raises(rh.RehearsalError, match="never exercised"):
        rh.run_rehearsal(
            store=store,
            pre_cutoff=pre,
            interrupted=interrupted,
            drained=drained,
            now=NOW,
            later=LATER,
            queued_dates=[QUEUED_DATE],
        )


# ── 3. reversão de ponteiro ──────────────────────────────────────────────────


def test_a_reversao_devolve_o_ponteiro_e_a_sequence_ainda_cresce():
    record, _store, retry_store, pre, *_ = _run()
    step = record.steps["pointer_rollback"]
    assert step["pointer_action"] == "rollback"
    assert step["target_release_id"] == pre.release_id
    assert step["pointer_sequence"] == 3
    assert step["pointer"]["release_id"] == pre.release_id
    assert step["completeness_of_target"]["complete"] is True


def test_a_reversao_revalida_o_alvo_antes_de_mover():
    """`rollback` carrega a release do store e a verifica inteira. O ensaio
    grava a completude do alvo DEPOIS da reversão, então uma reversão para uma
    release incompleta apareceria aqui — e `atomic_publish` a recusaria antes.
    """

    record, *_ = _run()
    assert record.steps["pointer_rollback"]["completeness_of_target"] == {
        "complete": True,
        "findings": [],
    }


# ── 4. recuperação de data enfileirada ───────────────────────────────────────


def test_a_data_enfileirada_e_drenada_sem_tocar_a_release_anterior():
    record, _store, retry_store, pre, _interrupted, drained, _key = _run()
    step = record.steps["queued_date_recovery"]
    assert step["queued_dates"] == [QUEUED_DATE]
    assert step["drained_release_id"] == drained.release_id
    assert step["pointer_sequence"] == 4
    assert step["pointer"]["release_id"] == drained.release_id
    assert step["earlier_release_still_complete"] is True
    assert step["earlier_release_objects_unchanged"] == len(
        pre.release["objects"]
    )


def test_a_data_drenada_esta_depois_do_corte_e_a_do_lote_nao():
    """O ensaio só é um ensaio do corte se a data drenada estiver do lado
    certo dele. Medido contra o próprio divisor.
    """

    from src.replay.cutoff import split_at_cutoff

    in_batch, after = split_at_cutoff(CUTOFF, [*PRE_CUTOFF, QUEUED_DATE])
    assert set(in_batch) == set(PRE_CUTOFF)
    assert after == (QUEUED_DATE,)


def test_nada_e_sobrescrito_em_lugar_nenhum():
    """A propriedade que sustenta "nada é apagado", e ela é do store, não do
    log: cada objeto sai com `If-None-Match: *`, então uma segunda escrita da
    MESMA chave com bytes DIFERENTES é recusada.

    Provado derrubando a mutação em vez de inspecionar o log: o ensaio inteiro
    completa (logo nenhuma recusa aconteceu, logo os objetos reencontrados
    eram idênticos), e uma tentativa deliberada de escrever bytes diferentes
    na mesma chave levanta `ImmutableObjectConflict`.
    """

    from src.publication.conditional_store import ImmutableObjectConflict

    record, store, retry_store, pre, *_ = _run()
    # O ensaio completou, e a retentativa reencontrou objetos byte a byte.
    assert record.steps["failure_recovery"]["retry_unchanged"] >= 1

    existing = f"{pre.prefix}{pre.release['objects'][0]['path']}"
    assert existing in retry_store._client.objects
    with pytest.raises(ImmutableObjectConflict):
        retry_store.put_if_absent(
            existing, b"different bytes", "application/geo+json"
        )


# ── 5. a release viva não é tocada, e nada de produção é escrito ────────────


def test_o_ensaio_so_escreve_no_bucket_de_staging():
    record, store, retry_store, *_ = _run()
    assert store.bucket == cs.STAGING_BUCKET == "araripe-v2-staging"
    assert retry_store.bucket == cs.STAGING_BUCKET
    assert cs.PRODUCTION_BUCKET == "araripe-cogs"
    assert rh.blue_keys_touched(record) == ()


def test_um_store_de_producao_e_recusado_antes_de_qualquer_escrita():
    """O ensaio ESCREVE, então é o único lugar da Phase 3 que precisa dizer em
    voz alta em que bucket pode escrever — e recusar o congelado.
    """

    store = ConditionalStore(FakeS3(), cs.PRODUCTION_BUCKET)
    with pytest.raises(rh.RehearsalError, match="araripe-v2-staging"):
        rh.staging_bucket_only(store)


def test_uma_chave_que_parece_de_producao_derruba_a_validacao():
    """Mutação derrubada: se o ensaio algum dia escrevesse sob `alerts/`,
    `baselines/` ou `data/timeseries/`, o registro seria recusado.
    """

    record, *_ = _run()
    document = record.to_dict()
    document["written_keys"] = sorted(
        set(document["written_keys"]) | {"alerts/alerts_2026-08-30.geojson"}
    )
    document["rehearsal_sha256"] = rh.canonical_sha256(
        {key: value for key, value in document.items() if key != "rehearsal_sha256"}
    )
    with pytest.raises(rh.RehearsalError, match="blue production"):
        rh.validate_rehearsal(document)


def test_a_release_viva_do_azul_nao_participa_do_ensaio():
    """O ponteiro verde é `pointers/green/current.json`, e é a única chave de
    ponteiro que o ensaio escreve. O `/data/…` estático do site — o rollback
    do azul — não é alcançável por este store nem por este bucket.
    """

    record, store, *_ = _run()
    pointer_writes = [
        key for key, _ in store._client.writes if key.startswith("pointers/")
    ]
    assert set(pointer_writes) <= {POINTER_KEY}
    assert POINTER_KEY == "pointers/green/current.json"


# ── reprodutibilidade ────────────────────────────────────────────────────────


def test_dois_ensaios_independentes_dao_a_mesma_impressao_digital():
    """"Reprodutível" checado como comparação de bytes, não como afirmação.
    Duas execuções em stores separados, e o digest do que o código decidiu.
    """

    first, *_ = _run()
    second, *_ = _run()
    assert rh.rehearsal_fingerprint(first) == rh.rehearsal_fingerprint(second)
    assert first.to_dict()["rehearsal_sha256"] == second.to_dict()["rehearsal_sha256"]


def test_a_impressao_digital_muda_quando_o_ensaio_muda():
    """Se o digest fosse constante, ele não mediria nada. Um passo alterado
    muda a impressão.
    """

    first, *_ = _run()
    mutated = rh.RehearsalRecord(
        steps={**first.steps, "staging": {**first.steps["staging"], "pointer_sequence": 9}},
        writes=list(first.writes),
    )
    assert rh.rehearsal_fingerprint(first) != rh.rehearsal_fingerprint(mutated)


def test_o_ensaio_e_reproduzivel_a_partir_de_um_prefixo_ja_meio_escrito():
    """O caso operacional real: alguém repete o ensaio depois de uma falha, e
    o prefixo já tem parte dos objetos. A republicação é no-op nos que existem
    e criação nos que faltam, e a identidade não muda.
    """

    pre, interrupted, _drained, _key = _inputs()
    fake = FakeS3()
    store = ConditionalStore(fake, cs.STAGING_BUCKET)
    publish_release(store, pre.release, pre.ledger_document, dict(pre.bodies))
    first_keys = {key for key, _ in fake.writes}

    record, *_ = _run(seed_objects=dict(fake.objects))
    assert record.steps["staging"]["completeness"]["complete"] is True
    assert record.steps["staging"]["pointer_sequence"] == 1
    assert first_keys, "the seeding publication has to have written something"

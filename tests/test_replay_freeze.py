"""O congelamento, o corte e a fotografia — medidos, não escritos em prosa.

Phase 3, itens 2, 3 e 5 do escopo. O briefing é explícito: *"Um congelamento
que não é verificável por teste não é congelamento: prefira um pin medido a uma
lista em prosa."*

É isso que este arquivo faz. `build_freeze` lê cada versão **do módulo que a
possui**, e `validate_freeze` relê e falha fechado em qualquer divergência —
então mudar uma constante congelada derruba um teste que NOMEIA o grupo. Duas
mutações foram derrubadas de propósito antes de este arquivo ficar definitivo:
`DETECTION_ALGORITHM_VERSION` e `Z_THRESHOLD_HIGH`.

Três coisas ficam deliberadamente FORA do congelamento, e cada uma tem teste:

* **a data de corte**, que é regra resolvida na consulta da Phase 4 e não
  depende de nenhum dos dez grupos;
* **qual baseline o replay usa**, que é decisão científica do dono — registrar
  um default aqui decidiria por omissão;
* **a release viva do azul**, que é fotografia e não pin: o azul publica seg/qui
  por desenho, então um teste que caísse com a publicação de produção seria
  ruído.

Determinístico: sem rede, sem relógio, sem object store, sem credencial.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from config import settings
from src.detection.identity import canonical_sha256
from src.replay import cutoff as cut
from src.replay import freeze as fz
from src.replay import snapshot as snap

ROOT = Path(__file__).resolve().parents[1]


# ── o congelamento é um pin medido ───────────────────────────────────────────


def test_o_congelamento_cobre_os_dez_grupos_que_o_roadmap_nomeia():
    """O bullet nomeia dez coisas. Uma chave faltando passa desapercebida; um
    nome faltando na lista de grupos não.
    """

    document = fz.build_freeze()
    assert set(fz.FROZEN_GROUPS) <= set(document)
    assert len(fz.FROZEN_GROUPS) == 10
    assert fz.FROZEN_GROUPS == (
        "monitoring_extent",
        "algorithm",
        "baseline",
        "cloud_and_mosaic",
        "drought",
        "mapbiomas",
        "label",
        "schema",
        "environment",
        "release",
    )


def test_o_congelamento_e_uma_funcao_da_arvore_e_nao_da_execucao():
    first = fz.build_freeze()
    again = fz.build_freeze()
    assert first == again
    body = {k: v for k, v in first.items() if k != "freeze_sha256"}
    assert canonical_sha256(body) == first["freeze_sha256"]


def test_o_congelamento_checado_no_repo_ainda_bate_com_os_produtores():
    """O teste que dá sentido ao documento: se alguém mudar uma constante
    congelada e não regravar o documento, isto cai.
    """

    document = fz.load_freeze()
    assert document["replay_freeze_version"] == fz.REPLAY_FREEZE_VERSION
    fz.validate_freeze(document)


def test_um_digest_adulterado_e_recusado():
    document = fz.build_freeze()
    document["freeze_sha256"] = "0" * 64
    with pytest.raises(fz.FreezeError, match="freeze_sha256"):
        fz.validate_freeze(document)


def test_um_grupo_divergente_e_nomeado_na_recusa():
    document = fz.build_freeze()
    document["algorithm"] = dict(document["algorithm"])
    document["algorithm"]["detection_algorithm_version"] = "9.9.9"
    body = {k: v for k, v in document.items() if k != "freeze_sha256"}
    document["freeze_sha256"] = canonical_sha256(body)
    with pytest.raises(fz.FreezeError, match="algorithm"):
        fz.validate_freeze(document)


def test_o_congelamento_nao_carrega_float():
    """Os bytes canônicos do digest não podem depender de quem serializou.
    Todo número é `int` ou decimal em texto — a mesma disciplina do export.
    """

    def walk(value, path="$"):
        assert not isinstance(value, float), f"{path} is a float"
        if isinstance(value, dict):
            for key, item in value.items():
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]")

    walk(fz.build_freeze())


def test_o_congelamento_nao_tem_caminho_absoluto():
    """`AGENTS.md` proíbe caminho específico de máquina, e um documento
    commitado com `/Users/...` também faria duas fotografias da mesma árvore
    diferirem por quem as tirou.
    """

    blob = json.dumps(fz.build_freeze())
    assert "/Users/" not in blob
    assert str(settings.ROOT_DIR) not in blob


# ── o que o congelamento deliberadamente NÃO decide ──────────────────────────


def test_o_congelamento_le_a_decisao_da_baseline_e_nao_a_reafirma():
    """A decisão mais consequente da fase é do dono, e o congelamento a LÊ do
    arquivo em que ela foi registrada — não a repete.

    Registrada em 2026-09-09: o dono respondeu "a nova", ou seja a `2.1.0`.
    Enquanto o arquivo não existia, o congelamento dizia `decided: false`, e
    é isso que `test_sem_o_arquivo_de_decisao_o_congelamento_diz_nao_decidido`
    ainda prova.
    """

    baseline = fz.build_freeze()["baseline"]
    decision = baseline["replay_generation"]
    assert decision["decided"] is True
    assert decision["decided_by"] == "project_owner"
    assert decision["version"] == "2.1.0"
    assert decision["version"] in baseline["registered_generations"]
    assert decision["decision_path"] == (
        "config/phase3_replay_baseline_decision_v1.json"
    )
    assert len(decision["decision_sha256"]) == 64
    assert decision["authorized_on"] == "2026-09-09"
    assert sorted(baseline["registered_generations"]) == ["1.0.0", "2.1.0"]
    assert baseline["superseded_generations"] == {"2.0.0": "2.1.0"}


def test_decidir_o_replay_nao_move_o_default_do_azul():
    """A propriedade que a fase inteira existiu para preservar.

    O dono escolheu a `2.1.0` para o REPLAY. `config/settings.py` continua em
    `1.0.0`, e o congelamento grava os dois valores lado a lado — porque a
    produção está congelada até a Phase 5 e o replay nomeia a geração dele.
    """

    baseline = fz.build_freeze()["baseline"]
    assert baseline["runtime_default"] == "1.0.0" == settings.BASELINE_VERSION
    assert baseline["replay_generation"]["version"] == "2.1.0"
    assert baseline["runtime_default"] != baseline["replay_generation"]["version"]
    decision = json.loads(
        (ROOT / "config" / "phase3_replay_baseline_decision_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert decision["authorization"]["blue_default_change_permitted"] is False
    assert decision["does_not_change"]["blue_runtime_default"] == "1.0.0"


def test_sem_o_arquivo_de_decisao_o_congelamento_diz_nao_decidido(monkeypatch, tmp_path):
    """A propriedade original, preservada: sem decisão registrada, o
    congelamento NÃO escolhe. Um default aqui decidiria por omissão.
    """

    monkeypatch.setattr(fz, "BASELINE_DECISION_PATH", tmp_path / "ausente.json")
    decision = fz.build_freeze()["baseline"]["replay_generation"]
    assert decision["decided"] is False
    assert "version" not in decision
    assert decision["decided_by"] == "project_owner"


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ({"baseline_version": "2.0.0"}, "not a registered generation"),
        ({"baseline_version": "3.0.0"}, "not a registered generation"),
        ({"baseline_version": None}, "not a registered generation"),
        ({"decision_id": "outra-coisa"}, "declares decision_id"),
    ],
)
def test_uma_decisao_mal_formada_falha_fechado(monkeypatch, tmp_path, mutation, expected):
    """A decisão é VALIDADA e não confiada. Um erro de digitação, um nome
    retirado, ou a `2.0.0` superada falham aqui — em vez de produzirem um
    replay contra algo que ninguém escolheu.
    """

    document = json.loads(
        (ROOT / "config" / "phase3_replay_baseline_decision_v1.json").read_text(
            encoding="utf-8"
        )
    )
    document.update(mutation)
    path = tmp_path / "decisao.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(fz, "BASELINE_DECISION_PATH", path)
    with pytest.raises(fz.FreezeError, match=expected):
        fz.build_freeze()


@pytest.mark.parametrize(
    "field,value,expected",
    [
        ("authorized_by", "an_agent", "no project_owner authorization"),
        ("authorized_by", None, "no project_owner authorization"),
        ("authorized_on", None, "no authorization date"),
        ("blue_default_change_permitted", True, "does not permit changing"),
    ],
)
def test_uma_decisao_sem_autorizacao_do_dono_falha_fechado(
    monkeypatch, tmp_path, field, value, expected
):
    """"O dono disse" tem de ser fato num arquivo, não memória de conversa —
    a mesma disciplina das emendas de regime sazonal. E a decisão não pode
    autorizar mexer no default do azul.
    """

    document = json.loads(
        (ROOT / "config" / "phase3_replay_baseline_decision_v1.json").read_text(
            encoding="utf-8"
        )
    )
    if value is None:
        document["authorization"].pop(field, None)
    else:
        document["authorization"][field] = value
    path = tmp_path / "decisao.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(fz, "BASELINE_DECISION_PATH", path)
    with pytest.raises(fz.FreezeError, match=expected):
        fz.build_freeze()


def test_a_decisao_carrega_o_custo_que_o_dono_aceitou():
    """A recomendação vinha com um preço; a decisão tem de carregá-lo, senão
    dentro de três meses ninguém sabe se ele foi considerado.
    """

    decision = json.loads(
        (ROOT / "config" / "phase3_replay_baseline_decision_v1.json").read_text(
            encoding="utf-8"
        )
    )
    cost = decision["accepted_cost"]
    assert "January through April" in cost["consequence"]
    assert cost["watch"] == "scripts/check_esa_reprocessing.py"
    assert "mixed_lineage_pending_esa_reprocessing" in cost["wet_season_lineage"]
    # E o congelamento carrega a consequência, não só o ponteiro para ela.
    assert (
        fz.build_freeze()["baseline"]["replay_generation"]["accepted_cost"]
        == cost["consequence"]
    )


def test_o_checksum_do_manifest_na_decisao_e_o_medido_e_nao_um_plausivel():
    """Este arquivo nasceu com um `sha256` INVENTADO — 64 caracteres hex,
    plausível, e falso. `AGENTS.md`: *"um identificador plausível é pior que um
    obviamente ausente, porque a revisão não o pega"*.

    O teste compara o valor gravado na decisão com o que o congelamento lê do
    MESMO arquivo, então os dois não podem divergir em silêncio.
    """

    decision = json.loads(
        (ROOT / "config" / "phase3_replay_baseline_decision_v1.json").read_text(
            encoding="utf-8"
        )
    )
    version = decision["baseline_version"]
    generation = fz.build_freeze()["baseline"]["registered_generations"][version]
    assert decision["evidence"]["manifest_path"] == generation["manifest_path"]
    assert decision["evidence"]["manifest_sha256"] == generation["manifest_sha256"]


def test_a_decisao_nao_autoriza_rodar_a_phase_4():
    """Escolher a referência e autorizar o reprocessamento são coisas
    diferentes, e o arquivo diz qual das duas ele é.
    """

    decision = json.loads(
        (ROOT / "config" / "phase3_replay_baseline_decision_v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert (
        decision["authorization"]["phase_4_execution_authorized_by_this_decision"]
        is False
    )
    assert decision["authorization"]["production_mutation_permitted"] is False


def test_as_duas_geracoes_registradas_trazem_a_identidade_do_inventario():
    """Sem baixar 13 GB: o SHA-256 do manifest e o `inventory_sha256` são o
    checksum do inventário inteiro.
    """

    generations = fz.build_freeze()["baseline"]["registered_generations"]
    for version, entry in generations.items():
        assert entry["object_count"] == 72, version
        assert len(entry["inventory_sha256"]) == 64, version
        assert len(entry["manifest_sha256"]) == 64, version
        assert entry["manifest_path"].startswith("config/"), version


def test_o_congelamento_nao_carrega_a_data_de_corte():
    """A regra do corte vive em `src/replay/cutoff.py` e resolve na consulta da
    Phase 4. Nenhum dos dez grupos depende dela — que é justamente por que o
    congelamento pode ficar de pé com a data aberta.
    """

    document = fz.build_freeze()
    for group in fz.FROZEN_GROUPS:
        assert "cutoff" not in json.dumps(document[group]).lower(), group


def test_a_release_viva_e_fotografia_e_nao_pin():
    document = fz.build_freeze()
    assert document["release"]["is_a_photograph_not_a_pin"] is True
    # E a prova de que é fotografia: validar contra uma release DIFERENTE não
    # levanta nada, porque `validate_freeze` não compara este grupo.
    other = fz.build_freeze()
    other["release"] = dict(other["release"])
    other["release"]["latest_observation"] = "2026-01-01"
    body = {k: v for k, v in other.items() if k != "freeze_sha256"}
    other["freeze_sha256"] = canonical_sha256(body)
    fz.validate_freeze(other)


def test_a_seca_e_registrada_como_nao_aplicada():
    """As constantes de SPI existem e o ajuste NÃO é aplicado: os dois pontos
    de entrada passam `spi_3month=None`. Um congelamento que listasse só os
    limiares implicaria o contrário.
    """

    drought = fz.build_freeze()["drought"]
    assert drought["operationally_applied"] is False
    for script in ("run_detection.py", "run_detection_from_gee.py"):
        source = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert "spi_3month=None" in source, script


def test_a_janela_incremental_congelada_e_a_do_produtor():
    """Medido nesta sessão: `SEARCH_DAYS_BACK` é 5, e duas docstrings ainda
    dizem 16 — a estimativa de custo dos insumos usou 16. O congelamento grava
    o valor do produtor, então a próxima estimativa parte do número certo.
    """

    assert fz.build_freeze()["algorithm"]["incremental_search_days_back"] == 5
    assert settings.SEARCH_DAYS_BACK == 5


def test_o_grupo_de_rotulos_nao_congela_a_taxonomia_da_phase_5():
    label = fz.build_freeze()["label"]
    assert label["qualified_validation_labels"]["frozen"] is False
    assert label["persistence_tiers"] == [
        "first_observation",
        "candidate",
        "confirmed",
    ]
    assert len(label["terminal_ledger_statuses"]) == 7


# ── o corte e a fila ─────────────────────────────────────────────────────────


def test_o_corte_provisorio_e_lido_do_produtor_e_nao_adivinhado():
    provisional = cut.read_provisional_cutoff()
    release = json.loads(
        (Path(settings.TIMESERIES_DIR) / "RELEASE.json").read_text(encoding="utf-8")
    )
    assert provisional.date == release["latest_observation"]
    assert provisional.source_field == "latest_observation"
    assert provisional.source_run_id == str(release["run_id"])


def test_um_sinal_de_release_de_schema_desconhecido_e_recusado(tmp_path):
    path = tmp_path / "RELEASE.json"
    path.write_text(
        json.dumps(
            {
                "latest_observation": "2026-08-30",
                "published_utc": "2026-09-07T15:52:37Z",
                "run_id": "1",
                "schema": "araripe.timeseries.release/9",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(cut.CutoffError, match="schema"):
        cut.read_provisional_cutoff(path)


def test_o_corte_e_inclusivo_do_lado_do_lote():
    """Phase 4 consulta *"from January 1 through the recorded cutoff"*, então a
    própria data do corte é replayada. Um off-by-one aqui é uma data inteira
    processada duas vezes ou nenhuma.
    """

    in_batch, after = cut.split_at_cutoff(
        "2026-08-30", ["2026-08-29", "2026-08-30", "2026-08-31"]
    )
    assert in_batch == ("2026-08-29", "2026-08-30")
    assert after == ("2026-08-31",)


def test_a_fila_nomeia_a_fonte_que_declarou_as_datas():
    """A diferença entre "estas datas existem" e "alguém olhou"."""

    document = cut.build_queue(
        cutoff="2026-08-30",
        observed_dates=["2026-08-30", "2026-09-02"],
        observation_source="a medição desta sessão",
        cutoff_is_provisional=True,
    )
    cut.validate_queue(document)
    assert document["observation_source"] == "a medição desta sessão"
    assert document["queued"]["dates"] == ["2026-09-02"]
    assert document["queued"]["disposition"] == cut.QUEUED


def test_uma_fila_vazia_ainda_registra_que_a_medicao_foi_feita():
    document = cut.build_queue(
        cutoff="2026-08-30",
        observed_dates=["2026-08-30"],
        observation_source="a medição desta sessão",
        cutoff_is_provisional=True,
    )
    cut.validate_queue(document)
    assert document["queued"]["count"] == 0
    assert document["queued"]["dates"] == []
    assert document["queued"]["disposition"] == cut.QUEUED


def test_a_fila_nao_e_um_calendario():
    """Ela nunca inventa datas entre o corte e hoje: revisita do Sentinel-2,
    recusa por nuvem e terminalidade fazem do conjunto observado uma medição e
    não uma aritmética.
    """

    document = cut.build_queue(
        cutoff="2026-08-30",
        observed_dates=["2026-09-02", "2026-09-15"],
        observation_source="a medição desta sessão",
        cutoff_is_provisional=True,
    )
    assert document["queued"]["dates"] == ["2026-09-02", "2026-09-15"]
    assert "2026-09-03" not in document["queued"]["dates"]


def test_o_lote_da_fila_declara_que_nao_e_a_enumeracao_da_phase_4():
    """A armadilha que este campo fecha: a fonte de observação sem credencial é
    o banco de série temporal, que é o produto AZUL e só conhece as datas que o
    azul processou. A Phase 4 enumera do GEE e verá mais.
    """

    document = cut.build_queue(
        cutoff="2026-08-30",
        observed_dates=["2026-08-30"],
        observation_source="a medição desta sessão",
        cutoff_is_provisional=True,
    )
    assert document["in_batch"]["is_authoritative_for_phase_4"] is False
    mutated = json.loads(json.dumps(document))
    mutated["in_batch"]["is_authoritative_for_phase_4"] = True
    mutated["queue_sha256"] = canonical_sha256(
        {k: v for k, v in mutated.items() if k != "queue_sha256"}
    )
    with pytest.raises(cut.CutoffError, match="non-authoritative"):
        cut.validate_queue(mutated)


@pytest.mark.parametrize(
    "mutation",
    [
        ("in_batch", "dates", ["2026-09-05"]),
        ("queued", "dates", ["2026-08-01"]),
    ],
)
def test_uma_data_do_lado_errado_do_corte_e_recusada(mutation):
    group, field, value = mutation
    document = cut.build_queue(
        cutoff="2026-08-30",
        observed_dates=["2026-08-30", "2026-09-02"],
        observation_source="a medição desta sessão",
        cutoff_is_provisional=True,
    )
    document[group] = dict(document[group])
    document[group][field] = value
    document[group]["count"] = len(value)
    document["queue_sha256"] = canonical_sha256(
        {k: v for k, v in document.items() if k != "queue_sha256"}
    )
    with pytest.raises(cut.CutoffError, match="cutoff"):
        cut.validate_queue(document)


def test_a_regra_do_corte_resolve_para_a_ultima_data_terminal():
    resolved = cut.resolve_recorded_cutoff(
        terminal_dates=["2026-01-02", "2026-08-30", "2026-08-25"],
        asked_at_utc="2026-09-08T12:00:00Z",
    )
    assert resolved["date"] == "2026-08-30"
    assert resolved["date_is_provisional"] is False
    assert resolved["rule_id"] == cut.CUTOFF_RULE_ID
    assert resolved["terminal_date_count"] == 3


def test_a_regra_do_corte_falha_fechado_sem_data_terminal():
    """"Nenhuma data é terminal" não é um corte, e cair para hoje colocaria no
    lote datas em que o gate P4 não pode fechar.
    """

    with pytest.raises(cut.CutoffError, match="not be defaulted"):
        cut.resolve_recorded_cutoff(
            terminal_dates=[], asked_at_utc="2026-09-08T12:00:00Z"
        )


# ── a fotografia ─────────────────────────────────────────────────────────────


def test_a_fotografia_cobre_os_sete_assuntos_do_roadmap():
    assert snap.SNAPSHOT_SUBJECTS == (
        "r2_alerts",
        "baseline_objects",
        "persistence_state",
        "timeseries_database",
        "site_manifest",
        "public_products",
        "repository_commits",
    )


def test_todo_assunto_diz_se_foi_medido_e_por_que_nao():
    """A disciplina que faz a fotografia ser evidência: uma entrada que omite
    o inventário do R2 por falta de credencial é indistinguível de uma tirada
    de um bucket vazio.
    """

    document = snap.build_snapshot(
        backend_root=ROOT,
        site_root=None,
        baseline_generations=[],
    )
    snap.validate_snapshot(document)
    assert document["r2_alerts"]["measured"] is False
    assert "no R2 credential" in document["r2_alerts"]["reason"]
    assert document["site_manifest"]["measured"] is False
    assert snap.unmeasured_subjects(document)


def test_um_assunto_nao_medido_sem_razao_e_recusado():
    document = snap.build_snapshot(
        backend_root=ROOT, site_root=None, baseline_generations=[]
    )
    document["site_manifest"] = {"measured": False}
    document["snapshot_sha256"] = canonical_sha256(
        {k: v for k, v in document.items() if k != "snapshot_sha256"}
    )
    with pytest.raises(snap.SnapshotError, match="gives no reason"):
        snap.validate_snapshot(document)


def test_um_assunto_sem_a_flag_de_medicao_e_recusado():
    document = snap.build_snapshot(
        backend_root=ROOT, site_root=None, baseline_generations=[]
    )
    document["persistence_state"] = {"path": "data/persistence_state.geojson"}
    document["snapshot_sha256"] = canonical_sha256(
        {k: v for k, v in document.items() if k != "snapshot_sha256"}
    )
    with pytest.raises(snap.SnapshotError, match="not say whether it was measured"):
        snap.validate_snapshot(document)


def test_a_fotografia_grava_caminhos_relativos_ao_repositorio():
    document = snap.build_snapshot(
        backend_root=ROOT, site_root=None, baseline_generations=[]
    )
    blob = json.dumps(document)
    assert "/Users/" not in blob
    assert str(ROOT) not in blob


def test_o_banco_de_serie_temporal_e_medido_e_auditado():
    document = snap.build_snapshot(
        backend_root=ROOT, site_root=None, baseline_generations=[]
    )
    entry = document["timeseries_database"]
    assert entry["measured"] is True
    assert entry["path"] == "data/timeseries/timeseries.db"
    assert len(entry["sha256"]) == 64
    assert entry["audit"]["measured"] is True
    assert entry["audit"]["publishable"] is False
    assert entry["audit"]["disposition"] == "quarantined_mixed_generation_audit"


def test_as_datas_observadas_unem_as_duas_tabelas():
    """`alert_stats` só tem datas que produziram alerta; um dia observado e
    quieto existe apenas em `regional_stats`. Tomar uma tabela só derrubaria
    uma classe inteira de data.
    """

    import sqlite3

    db = ROOT / "data" / "timeseries" / "timeseries.db"
    dates = snap.observed_dates_from_timeseries(db)
    connection = sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True)
    try:
        regional = {r[0] for r in connection.execute(
            "SELECT DISTINCT date FROM regional_stats"
        )}
        alerts = {r[0] for r in connection.execute(
            "SELECT DISTINCT date FROM alert_stats"
        )}
    finally:
        connection.close()
    assert set(dates) == regional | alerts
    assert len(alerts) < len(regional), (
        "se as duas tabelas tivessem as mesmas datas, este teste não mediria "
        "nada — a diferença é o dia quieto"
    )


def test_os_dois_commits_de_repositorio_sao_lidos_do_git():
    """Copiado da ferramenta que produz o valor, nunca completado de memória."""

    document = snap.build_snapshot(
        backend_root=ROOT, site_root=None, baseline_generations=[]
    )
    backend = document["repository_commits"]["backend"]
    assert backend["measured"] is True
    assert len(backend["head"]) == 40
    assert document["repository_commits"]["site"]["measured"] is False


def test_a_deriva_da_release_e_reportada_e_nunca_afirmada():
    """O azul publica seg/qui por desenho, então a deriva é esperada. Um teste
    que caísse nela quebraria em toda rodada bem-sucedida de produção.
    """

    document = snap.build_snapshot(
        backend_root=ROOT, site_root=None, baseline_generations=[]
    )
    same = snap.release_drift(
        document,
        frozen_release={
            "timeseries_db_sha256": document["timeseries_database"]["sha256"],
            "latest_observation": "2026-08-30",
        },
    )
    assert same["drifted"] is False
    moved = snap.release_drift(
        document,
        frozen_release={
            "timeseries_db_sha256": "0" * 64,
            "latest_observation": "2026-09-14",
        },
    )
    assert moved["drifted"] is True


def test_a_geracao_2_1_0_esta_presente_e_verificada_byte_a_byte():
    """A medição que só esta máquina podia fazer: os 72 rasters de 13 GB da
    2.1.0 estão em disco e casam com o manifest. Se eles não estiverem, o teste
    diz isso em vez de falhar — a fotografia é do que existe.
    """

    from src.detection.baseline_selection import resolve_baseline

    generation = resolve_baseline("2.1.0")
    entry = snap.baseline_generation_entry(
        version=generation.version,
        manifest_path=generation.manifest_path,
        directory=generation.directory,
        key_prefix=generation.key_prefix,
        root=ROOT,
    )
    assert entry["measured"] is True
    assert entry["object_count"] == 72
    local = entry["rasters_local"]
    assert local["expected"] == 72
    assert local["mismatched"] == []
    assert local["verified"] == local["present"]


# ── o runbook nomeia os alvos que o código resolve ──────────────────────────

RUNBOOK = ROOT / "docs" / "operations" / "PHASE_3_REPLAY_RUNBOOK.md"


def test_o_runbook_declara_a_revisao_pre_cutover_ainda_aberta():
    """O bullet pede revisão explícita do dono **antes do cutover**, e o runbook
    não pode declarar-se revisado por conta própria.

    Em 2026-09-09 dois itens fecharam — a baseline e a cota — e os outros
    quatro continuam abertos. O teste exige que ainda haja item aberto e que o
    documento diga que o cutover não começa sem ela; se algum dia todos
    fecharem, este teste cai e a linha tem de mudar deliberadamente.
    """

    text = RUNBOOK.read_text(encoding="utf-8")
    assert "Revisão pré-cutover do dono" in text
    assert "PENDENTE" in text
    assert "- [ ]" in text, "a revisão pré-cutover ainda tem item aberto"
    assert "- [x]" in text, "e tem item já fechado, que é o estado real"
    assert "cutover não" in text and "começa" in text


def test_o_runbook_registra_a_decisao_da_baseline_que_o_congelamento_le():
    """As duas metades têm de dizer a mesma coisa: se o runbook nomeasse uma
    geração e o congelamento lesse outra, a Phase 4 seguiria a errada.
    """

    text = RUNBOOK.read_text(encoding="utf-8")
    decided = fz.build_freeze()["baseline"]["replay_generation"]
    assert decided["decided"] is True
    assert f"DECIDIDA em {decided['authorized_on']}" in text
    assert decided["version"] in text
    assert decided["decision_path"] in text
    # E TODA ocorrência de `--baseline-version` no runbook nomeia a geração
    # decidida. Verificar só que a decidida aparece em algum lugar não bastava:
    # medido, com o comando do procedimento trocado para `1.0.0` o teste passava,
    # porque a §2.1 menciona `--baseline-version 2.1.0` noutra linha.
    import re

    named = set(re.findall(r"--baseline-version\s+`?(\d+\.\d+\.\d+)", text))
    assert named == {decided["version"]}, named


def test_o_runbook_nao_diz_que_a_decisao_bloqueia_a_phase_4():
    """`pre-cutover` é literal no bullet: a revisão é portão da Phase 6. Um
    runbook que dissesse o contrário travaria o reprocessamento sem motivo.
    """

    text = RUNBOOK.read_text(encoding="utf-8")
    assert "não** bloqueia" in text or "não bloqueia" in text
    assert "a Phase 4 pode começar" in text


def test_o_runbook_nomeia_os_alvos_resolvidos_lidos_do_codigo():
    """Se um destes nomes mudar no código e não no runbook, isto cai — que é a
    única coisa que impede um runbook de descrever um sistema que já não
    existe.
    """

    from src.publication import conditional_store as cs
    from src.publication.green_release import POINTER_KEY

    text = RUNBOOK.read_text(encoding="utf-8")
    for value in (
        cs.STAGING_BUCKET,
        cs.PRODUCTION_BUCKET,
        POINTER_KEY,
        "v2_candidate_replay.yml",
        "phase3_replay_freeze_v1.json",
        f"SEARCH_DAYS_BACK = {settings.SEARCH_DAYS_BACK}",
    ):
        assert value in text, value


def test_o_runbook_nomeia_os_documentos_que_esta_fase_gravou():
    """Um runbook que apontasse para uma fotografia inexistente não seria
    seguível. Os nomes são construídos da data provisória do corte.
    """

    stamp = cut.read_provisional_cutoff().date
    text = RUNBOOK.read_text(encoding="utf-8")
    for name in (
        f"PHASE_3_SNAPSHOT_{stamp}.json",
        f"PHASE_3_POST_CUTOFF_QUEUE_{stamp}.json",
    ):
        assert name in text, name
        assert (ROOT / "docs" / "implementation" / name).is_file(), name


def test_o_runbook_nao_finge_ter_a_lista_do_broker_maior():
    """A lista allowlistada do broker é exatamente três operações. Um runbook
    que nomeasse uma quarta convidaria a tentativa.
    """

    text = RUNBOOK.read_text(encoding="utf-8")
    broker = (
        ROOT / ".github" / "workflows" / "cloudflare_green_control.yml"
    ).read_text(encoding="utf-8")
    for operation in ("audit", "enforce-worker-isolation", "disable-site-branch-deploy"):
        assert operation in text, operation
        assert operation in broker, operation


def test_a_recomendacao_de_baseline_carrega_o_custo_dela():
    """A 2.1.0 admite produtos pré-Collection-1 nos meses 1-4, e a ESA está
    reprocessando — então um replay contra ela pode ter de ser refeito para
    janeiro-abril. Uma recomendação sem o custo não é uma recomendação.
    """

    text = RUNBOOK.read_text(encoding="utf-8")
    assert "pré-Collection-1" in text
    assert "check_esa_reprocessing.py" in text
    amendment = json.loads(
        (
            ROOT / "config" / "phase2a6c1_seasonal_source_regime_amendment_v2.json"
        ).read_text(encoding="utf-8")
    )
    wet = next(
        regime
        for regime in amendment["source_regime_contract"]["regimes"]
        if regime["regime_id"] == "wet-season-mixed-lineage-v1"
    )
    assert wet["months"] == [1, 2, 3, 4]
    assert wet["provenance_state"] == "mixed_lineage_pending_esa_reprocessing"
    assert wet["watch"] == "scripts/check_esa_reprocessing.py"

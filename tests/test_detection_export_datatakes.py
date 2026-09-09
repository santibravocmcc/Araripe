"""O export de detecção passa a carregar o datatake físico, e a cópia é checada.

Phase 3, item 1b do escopo. Medido antes: `scripts/build_baseline_v2_gee.py`
menciona `DATATAKE_IDENTIFIER`/`SPACECRAFT_NAME`/`platform` **80** vezes e
`scripts/build_detection_gee.py` **zero** — então o ledger v3, que existe na
`main` (`ProcessingLedgerV3`, `CompositionRunV3`) e exige `platform`,
`datatake_id` e `acquisition_timestamp_utc` por aquisição, só podia ser
preparado à mão.

O script roda em Cloud Shell com `earthengine-api` e nada do repositório, então
a derivação **é** uma segunda cópia da biblioteca. Este arquivo é o que impede
as duas de divergirem: cada função pura do script é rodada contra a sua
contraparte na biblioteca e comparada, e o manifest de execução gerado é
consumido por `CompositionRunV3` de verdade.

Mutações que estes testes derrubam, e as três foram derrubadas de propósito:

* usar `system:time_start` (o instante do grânulo) em vez do instante embutido
  no identificador do datatake;
* deixar um `float` no corpo assinado — as duas canonicalizações discordam em
  `1.0`/`1` e `1e-07`/`1e-7`, então o digest sairia diferente do da biblioteca;
* compor um datatake com cenas de outro, ou declarar o mesmo datatake duas
  vezes.

Determinístico: sem rede, sem relógio, sem Earth Engine, sem credencial. O
script é importável exatamente porque `import ee` e `ee.Initialize` foram para
dentro de `main()`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from src.detection.composition_run_v3 import CompositionRunV3, DatatakeRunInputV3
from src.detection.identity import canonical_json_bytes
from src.detection.identity_v3 import create_acquisition_v3
from src.processing.composition_v2 import create_scene_input_v2, normalize_platform
from src.processing.scl_mask_v2 import REVIEWED_PROCESSING_BASELINES

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_detection_gee.py"
BASELINE_SCRIPT = ROOT / "scripts" / "build_baseline_v2_gee.py"


def load_script():
    """Import the Cloud Shell script by path, as the operator's shell runs it.

    Importing it at all is the first assertion: before Phase 3 the module body
    called ``ee.Initialize`` and could not be imported without live Earth
    Engine credentials, which is why its derivation had never been tested.
    """

    spec = importlib.util.spec_from_file_location("build_detection_gee", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


export = load_script()


def _rows(*specs):
    """Scene-property rows shaped like ``reduceColumns`` returns them."""

    return [
        {
            "system:index": scene_id,
            "PRODUCT_ID": f"S2X_MSIL2A_{scene_id}",
            "DATATAKE_IDENTIFIER": datatake_id,
            "SPACECRAFT_NAME": spacecraft,
            "PROCESSING_BASELINE": baseline,
            "MGRS_TILE": scene_id[-5:],
            "CLOUDY_PIXEL_PERCENTAGE": cloud,
        }
        for scene_id, datatake_id, spacecraft, baseline, cloud in specs
    ]


TWO_DATATAKES_ONE_DATE = _rows(
    ("20260830T130251_20260830T130842_T24MTV", "GS2A_20260830T130251_012345_N05.11",
     "Sentinel-2A", "05.11", 4.2),
    ("20260830T130251_20260830T130842_T24MUV", "GS2A_20260830T130251_012345_N05.11",
     "Sentinel-2A", "05.11", 7.5),
    ("20260830T131241_20260830T131802_T24MTV", "GS2C_20260830T131241_054321_N05.11",
     "Sentinel-2C", "05.11", 1.0),
)


# ── a derivação concorda com a biblioteca ────────────────────────────────────


@pytest.mark.parametrize(
    "provider,expected",
    [
        ("Sentinel-2A", "S2A"),
        ("Sentinel-2B", "S2B"),
        ("Sentinel-2C", "S2C"),
        ("sentinel-2c", "S2C"),
        ("S2C", "S2C"),
        ("s2b", "S2B"),
    ],
)
def test_normalize_platform_concorda_com_a_biblioteca(provider, expected):
    assert export.normalize_platform(provider) == expected
    assert normalize_platform(provider) == expected


@pytest.mark.parametrize(
    "provider", ["", "   ", "Landsat-8", "Sentinel-1A", "S2", "S2E", "sentinel-3a"]
)
def test_normalize_platform_falha_fechado_como_a_biblioteca(provider):
    with pytest.raises(ValueError):
        export.normalize_platform(provider)
    with pytest.raises(ValueError):
        normalize_platform(provider)


def test_o_instante_vem_do_identificador_e_nao_do_granulo():
    """A armadilha que o lado da baseline registra: `system:time_start` é o
    instante do grânulo e discorda do instante do datatake em toda cena.

    O `system:index` desta cena começa em `20260830T130251` e o segundo campo
    dele — o instante do grânulo — é `T130842`, nove minutos depois. O valor
    derivado tem de ser o do datatake.
    """

    row = TWO_DATATAKES_ONE_DATE[0]
    assert "T130842" in row["system:index"]
    assert export.datatake_instant(row["DATATAKE_IDENTIFIER"]) == (
        "2026-08-30T13:02:51Z"
    )


@pytest.mark.parametrize("value", ["", "   ", "GS2A", "GS2Anounderscore", None, 42])
def test_um_identificador_sem_instante_falha_fechado(value):
    with pytest.raises(ValueError):
        export.datatake_instant(value)


def test_as_propriedades_de_cena_sao_as_mesmas_dos_dois_scripts():
    """Se alguém acrescentar uma propriedade no lado da baseline, este teste cai
    aqui em vez de o export de detecção ficar silenciosamente sem ela.

    Lido do texto do outro script porque importá-lo executaria o seu próprio
    `ee`; a tupla é literal nos dois arquivos.
    """

    source = BASELINE_SCRIPT.read_text(encoding="utf-8")
    block = source[source.index("SCENE_PROPERTIES = ("):]
    block = block[: block.index(")")]
    named = {
        line.strip().strip(",").strip('"')
        for line in block.splitlines()[1:]
        if line.strip()
    }
    assert named == set(export.SCENE_PROPERTIES)


# ── o agrupamento é por datatake físico ──────────────────────────────────────


def test_uma_data_com_dois_datatakes_da_duas_aquisicoes():
    """O ledger contabiliza aquisições e **resume** por data. Se o agrupamento
    fosse por data, as duas passagens de 30/08 virariam uma linha e o gate P4
    — uma linha terminal por aquisição esperada — não teria como fechar.
    """

    datatakes = export.group_into_datatakes(TWO_DATATAKES_ONE_DATE)
    assert len(datatakes) == 2
    assert {item["observed_on"] for item in datatakes} == {"2026-08-30"}
    assert [item["platform"] for item in datatakes] == ["S2A", "S2C"]
    assert [item["scene_count"] for item in datatakes] == [2, 1]


def test_as_cenas_de_um_datatake_saem_em_ordem_de_bytes():
    datatakes = export.group_into_datatakes(list(reversed(TWO_DATATAKES_ONE_DATE)))
    scenes = [scene["scene_id"] for scene in datatakes[0]["scenes"]]
    assert scenes == sorted(scenes, key=lambda text: text.encode("utf-8"))


def test_o_agrupamento_nao_depende_da_ordem_que_o_gee_devolveu():
    forward = export.group_into_datatakes(TWO_DATATAKES_ONE_DATE)
    backward = export.group_into_datatakes(list(reversed(TWO_DATATAKES_ONE_DATE)))
    assert forward == backward


def test_uma_cena_duplicada_nao_duplica_a_contagem():
    """`reduceColumns` pode devolver a mesma cena duas vezes se a consulta se
    sobrepuser; o `scene_count` é o de cenas distintas.
    """

    doubled = TWO_DATATAKES_ONE_DATE + [TWO_DATATAKES_ONE_DATE[0]]
    datatakes = export.group_into_datatakes(doubled)
    assert [item["scene_count"] for item in datatakes] == [2, 1]


def test_uma_plataforma_nao_sentinel2_derruba_a_enumeracao():
    rows = _rows(
        ("x", "GS2A_20260830T130251_012345_N05.11", "Landsat-8", "05.11", 1.0)
    )
    with pytest.raises(ValueError):
        export.group_into_datatakes(rows)


# ── os bytes canônicos concordam com os da biblioteca ────────────────────────


def test_os_bytes_canonicos_do_manifest_batem_com_os_da_biblioteca():
    """A propriedade que sustenta o `run_manifest_sha256`: a canonicalização do
    Cloud Shell e a RFC 8785 da biblioteca dão os MESMOS bytes.
    """

    manifest = export.build_run_manifest(
        start="2026-08-25",
        end="2026-09-01",
        max_cloud=60,
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE),
        exported_dates=["2026-08-30"],
    )
    assert export.canonical_bytes(manifest) == canonical_json_bytes(manifest)


def test_um_float_no_corpo_assinado_e_recusado():
    """A razão medida: `json.dumps` escreve `1.0` e `1e-07` onde a RFC 8785
    escreve `1` e `1e-7`. Sem float nenhum as duas formas concordam para
    QUALQUER documento, e não só para os que foram tentados.
    """

    assert export.canonical_bytes({"a": 1}) == canonical_json_bytes({"a": 1})
    with pytest.raises(ValueError, match=r"\$\.a\[0\]\.b is a float"):
        export.canonical_bytes({"a": [{"b": 1.0}]})


def test_o_percentual_de_nuvem_viaja_como_decimal_que_volta_ao_mesmo_float():
    datatakes = export.group_into_datatakes(TWO_DATATAKES_ONE_DATE)
    recorded = datatakes[0]["scenes"][0]["cloudy_pixel_percentage"]
    assert isinstance(recorded, str)
    assert float(recorded) == 4.2


def test_o_manifest_e_uma_funcao_da_consulta_e_nao_da_execucao():
    """Sem relógio, sem run id, sem ator: a mesma consulta dá o mesmo binding,
    e uma mudança nos datatakes dá outro. É a disciplina de
    `run_manifest_binding_from_plan`.
    """

    kwargs = dict(
        start="2026-08-25",
        end="2026-09-01",
        max_cloud=60,
        exported_dates=["2026-08-30"],
    )
    first = export.build_run_manifest(
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE), **kwargs
    )
    again = export.build_run_manifest(
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE), **kwargs
    )
    fewer = export.build_run_manifest(
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE[:2]), **kwargs
    )
    assert first["run_manifest_id"] == again["run_manifest_id"]
    assert first["run_manifest_id"] != fewer["run_manifest_id"]
    assert first["run_manifest_id"] == "run-v3-" + first["run_manifest_sha256"]
    body = {
        key: value
        for key, value in first.items()
        if key
        not in {"run_manifest_id", "run_manifest_sha256", "expected_acquisitions"}
    }
    assert export.canonical_sha256(body) == first["run_manifest_sha256"]


# ── quem cunha a identidade, e por que não é o export ───────────────────────


def test_o_export_nao_cunha_acquisition_id():
    """MEDIDO, e é o achado desta ativação.

    Um primeiro rascunho pré-computava cada `acquisition_id` no manifest. Os
    valores **não** batiam com os que `CompositionRunV3` deriva, porque aquela
    classe amarra `composite_method_id` a `coverage-ranked-first-valid-v1` —
    a composição escopada por datatake — enquanto este export mosaica a data
    inteira sob `daily_mosaic-v1`. Um ID plausível que não casa é pior que
    nenhum ID: a Phase 4 reconciliaria contra a identidade errada e o
    resultado pareceria válido.
    """

    manifest = export.build_run_manifest(
        start="2026-08-25",
        end="2026-09-01",
        max_cloud=60,
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE),
        exported_dates=["2026-08-30"],
    )
    assert "expected_acquisitions" not in manifest
    assert not any("acquisition_id" in item for item in manifest["datatakes"])
    assert manifest["acquisition_identity"]["minted_by"].endswith(
        "CompositionRunV3"
    )


def test_a_divergencia_de_metodo_de_composicao_esta_medida_e_nao_suposta():
    """A divergência que a Phase 3 mediu, e a Phase 4 RESOLVEU por decisão.

    Este teste dizia que cairia "se o export passar a compor por datatake". Em
    2026-09-09 o export passou a compor por datatake e **ele não caiu** — a
    asserção era `export.COMPOSITE_METHOD_ID == "daily_mosaic-v1"`, e a mudança
    acrescentou uma segunda constante em vez de mexer nessa. É a quarta vez que
    o padrão "o teste passa pelo motivo errado" aparece nesta linha de
    trabalho, e a primeira em que o próprio docstring do teste nomeava a
    mutação que ele deixou passar.

    O que ele fixa agora é a resolução, e cada asserção tem uma mutação:
    o export expõe as DUAS unidades; a do azul continua `daily_mosaic-v1`; a
    da Phase 4 é um ID novo; e nenhuma das duas é a da biblioteca, porque um
    `mosaic()` do Earth Engine não está provado igual à seleção ranqueada.
    """

    from src.processing.composition_v2 import COMPOSITION_METHOD_ID

    assert export.COMPOSITION_UNITS == ("date", "datatake")
    assert export.composite_method_for("date") == "daily_mosaic-v1"
    assert export.composite_method_for("datatake") == "datatake_mosaic-v1"
    assert COMPOSITION_METHOD_ID == "coverage-ranked-first-valid-v1"
    minted = {export.composite_method_for(unit) for unit in export.COMPOSITION_UNITS}
    assert COMPOSITION_METHOD_ID not in minted
    with pytest.raises(ValueError):
        export.composite_method_for("scene")
    source = (ROOT / "src" / "detection" / "composition_run_v3.py").read_text(
        encoding="utf-8"
    )
    assert "composite_method_id=COMPOSITION_METHOD_ID," in source


def test_o_manifest_declara_a_unidade_que_ele_descreve():
    """Derruba: deixar o leitor inferir a unidade a partir do método.

    Inferir foi exatamente como as duas metades do sistema discordaram. Os dois
    manifests também têm de ter identidades distintas: se a unidade não
    entrasse nos bytes selados, uma consulta idêntica produziria o mesmo
    `run_manifest_id` para dois runs que compõem coisas diferentes.
    """

    common = dict(
        start="2026-08-25",
        end="2026-09-01",
        max_cloud=60,
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE),
        exported_dates=["2026-08-30"],
    )
    by_date = export.build_run_manifest(**common, composition_unit="date")
    by_datatake = export.build_run_manifest(**common, composition_unit="datatake")

    assert by_date["composition_unit"] == "date"
    assert by_datatake["composition_unit"] == "datatake"
    assert by_date["composite_method_id"] == "daily_mosaic-v1"
    assert by_datatake["composite_method_id"] == "datatake_mosaic-v1"
    assert by_date["run_manifest_id"] != by_datatake["run_manifest_id"]
    assert export.build_run_manifest(**common)["composition_unit"] == "date"
    with pytest.raises(ValueError):
        export.build_run_manifest(**common, composition_unit="scene")


def test_o_nome_do_composto_por_datatake_nao_colide_numa_data_com_dois():
    """Derruba: reaproveitar o nome por data na unidade por datatake.

    `TWO_DATATAKES_ONE_DATE` é o caso: dois datatakes, uma data. Com o nome
    antigo os dois arquivos teriam o mesmo caminho e o segundo sobrescreveria
    o primeiro — a mesma classe de bug que o mosaico por data foi criado para
    resolver no caminho de streaming.
    """

    # the consumer's own regex, not a copy of it: a name the export can write
    # and run_detection_from_gee cannot parse is the failure worth catching.
    import importlib

    consumer = importlib.import_module("scripts.run_detection_from_gee")

    datatakes = export.group_into_datatakes(TWO_DATATAKES_ONE_DATE)
    assert len({item["observed_on"] for item in datatakes}) == 1
    names = {
        export.composite_name(
            "datatake",
            observed_on=item["observed_on"],
            datatake_id=item["datatake_id"],
        )
        for item in datatakes
    }
    assert len(names) == len(datatakes) == 2
    # the date is still the first thing a reader (and _DATE_RE) finds
    for name in names:
        assert consumer._DATE_RE.search(name).group(1) == datatakes[0]["observed_on"]
    assert export.composite_name("date", observed_on="2026-08-30") == (
        "araripe_detect_2026-08-30"
    )


def test_os_campos_fisicos_bastam_para_a_biblioteca_cunhar_a_identidade():
    """O que o export deve entregar: `platform`, `datatake_id`,
    `acquisition_timestamp_utc` e as cenas nativas. Provado passando SÓ esses
    campos para o contrato v3 e obtendo uma identidade válida.
    """

    manifest = export.build_run_manifest(
        start="2026-08-25",
        end="2026-09-01",
        max_cloud=60,
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE),
        exported_dates=["2026-08-30"],
    )
    for datatake in manifest["datatakes"]:
        minted = create_acquisition_v3(
            run_manifest_id=manifest["run_manifest_id"],
            run_manifest_sha256=manifest["run_manifest_sha256"],
            collection_id=manifest["collection_id"],
            platform=datatake["platform"],
            datatake_id=datatake["datatake_id"],
            acquisition_timestamp_utc=datatake["acquisition_timestamp_utc"],
            scene_ids=datatake["scene_ids"],
            monitoring_extent_id=manifest["monitoring_extent_id"],
            composite_method_id="coverage-ranked-first-valid-v1",
            grid_id=manifest["grid_id"],
        )
        assert minted.observed_on == datatake["observed_on"]
        assert list(minted.scene_ids) == sorted(set(datatake["scene_ids"]))
        assert minted.acquisition_timestamp_utc == (
            datatake["acquisition_timestamp_utc"]
        )


def test_o_grid_declarado_nao_finge_ser_o_da_baseline():
    """O export pede só `crs` e `scale`, então a origem é escolha do GEE.
    Declarar a grade da baseline seria afirmar invariante que o produtor não
    promete — e `run_detection_from_gee.py` reindexa com tolerância de 15 m,
    que é a evidência de que ninguém assumiu alinhamento.
    """

    assert export.GRID_ID != "araripe-baseline-epsg32724-20m-grid-v1"
    source = (ROOT / "scripts" / "run_detection_from_gee.py").read_text(
        encoding="utf-8"
    )
    assert 'method="nearest", tolerance=15' in source
    manifest = export.build_run_manifest(
        start="2026-08-25",
        end="2026-09-01",
        max_cloud=60,
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE),
        exported_dates=["2026-08-30"],
    )
    assert manifest["grid_request"]["crs_transform_pinned"] is False


# ── o manifest gerado é aceito pelo produtor de ledger que já existe ─────────


def test_o_manifest_gerado_alimenta_um_composition_run_v3_de_verdade():
    """O ponto inteiro da ativação: com estes campos, o ledger passa a ser
    **produzido por execução**. Aqui o run é construído com o manifest do
    script e o ledger sai com duas aquisições esperadas na mesma data.
    """

    manifest = export.build_run_manifest(
        start="2026-08-25",
        end="2026-09-01",
        max_cloud=60,
        datatakes=export.group_into_datatakes(TWO_DATATAKES_ONE_DATE),
        exported_dates=["2026-08-30"],
    )
    run = CompositionRunV3(
        run_manifest_id=manifest["run_manifest_id"],
        run_manifest_sha256=manifest["run_manifest_sha256"],
        collection_id=manifest["collection_id"],
        monitoring_extent_id=manifest["monitoring_extent_id"],
        grid_id=manifest["grid_id"],
        algorithm_version="1.0.0",
        created_at="2026-09-08T00:00:00Z",
        datatakes=tuple(
            DatatakeRunInputV3(
                platform=item["platform"],
                datatake_id=item["datatake_id"],
                acquisition_timestamp_utc=item["acquisition_timestamp_utc"],
                scenes=tuple(
                    create_scene_input_v2(
                        scene_id=scene["scene_id"],
                        platform=item["platform"],
                        datatake_id=item["datatake_id"],
                        properties={
                            "PROCESSING_BASELINE": scene["processing_baseline"]
                        },
                        scl=None,
                        bands={"B8A": np.zeros((2, 2), dtype="float32")},
                    )
                    for scene in item["scenes"]
                ),
            )
            for item in manifest["datatakes"]
        ),
    )
    assert len(run.ledger.expected_acquisitions) == 2
    assert {
        entry["observed_on"] for entry in run.ledger.expected_acquisitions
    } == {"2026-08-30"}
    # Every expected row carries the three physical fields the export supplied.
    supplied = {
        (item["platform"], item["datatake_id"], item["acquisition_timestamp_utc"])
        for item in manifest["datatakes"]
    }
    assert {
        (
            entry["platform"],
            entry["datatake_id"],
            entry["acquisition_timestamp_utc"],
        )
        for entry in run.ledger.expected_acquisitions
    } == supplied
    assert run.ledger.expected_acquisitions[0]["run_manifest_id"] == (
        manifest["run_manifest_id"]
    )


def test_as_baselines_de_processamento_observadas_ficam_registradas():
    """O registro revisado é a política de reprodutibilidade do lado da
    baseline; o export de detecção não decide nada sobre ele, mas grava o que
    observou para que a Phase 4 possa decidir com dado e não com suposição.
    """

    datatakes = export.group_into_datatakes(TWO_DATATAKES_ONE_DATE)
    assert datatakes[0]["observed_processing_baselines"] == ["05.11"]
    assert "05.11" in REVIEWED_PROCESSING_BASELINES


def test_o_manifest_de_aquisicao_v1_nao_mudou_de_forma():
    """`load_composite_acquisition` lê este documento por data e constrói um
    `AcquisitionIdentity`. A forma é contrato de quem consome, então a
    ativação é **aditiva**: um segundo arquivo, e este intacto.
    """

    from src.detection.identity import AcquisitionIdentity

    record = export.acquisition_v1_identity(
        "2026-08-30",
        [
            "COPERNICUS/S2_SR_HARMONIZED/20260830T130251_20260830T130842_T24MTV",
            "COPERNICUS/S2_SR_HARMONIZED/20260830T131241_20260830T131802_T24MTV",
        ],
    )
    identity = AcquisitionIdentity.from_dict(record)
    assert identity.observed_on == "2026-08-30"
    assert identity.acquisition_id == record["acquisition_id"]
    assert record["acquisition_id"].startswith("acq-v1-")


def test_o_script_nao_toca_earth_engine_ao_ser_importado():
    """A propriedade que tornou este arquivo possível, fixada: `import ee` e
    `ee.Initialize` estão dentro de `main()`. Uma mutação que os devolvesse ao
    corpo do módulo faria `load_script()` exigir credencial.
    """

    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
            )
            assert "ee" not in names
    module_level_calls = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
    ]
    assert module_level_calls == []

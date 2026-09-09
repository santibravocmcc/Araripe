"""Qual baseline o runtime carrega, e a prova de que o azul não mudou.

Phase 3, item 1a do escopo. A ativação da 2.1.0 **afeta o caminho azul**, e o
briefing pede a inércia provada e não afirmada. É isso que este arquivo faz, em
três camadas:

* **o resolvedor sem argumento é exatamente o de hoje** — versão `1.0.0`,
  diretório `data/baselines`, manifest `config/baseline_manifest_v1.json`;
* **o carregador sem geração nomeada lê o diretório de hoje** e verifica contra
  o manifest de hoje. Provado por leitura de raster real (sintético, escrito no
  `tmp_path`), não por inspeção de assinatura;
* **a 2.1.0 só é alcançável se alguém a nomear.** Nada a escolhe por ambiente,
  por data de build, por "mais nova" ou por diretório presente em disco.

Mutação que estes testes derrubam, e que foi derrubada de propósito antes de
serem escritos como definitivos: trocar o default do registro para `2.1.0`, e
fazer `resolve_baseline` cair na sucessora quando alguém pede a `2.0.0`.

Determinístico: sem rede, sem relógio, sem object store, sem credencial. Os
rasters de 13 GB da 2.1.0 existem localmente mas **não** são lidos aqui — o que
se verifica é a identidade declarada pelo manifest.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import rasterio

from config import settings
from src.detection import baseline as baseline_module
from src.detection import baseline_selection as sel

ROOT = Path(__file__).resolve().parents[1]


def _write_raster(path: Path, value: float) -> None:
    data = np.full((4, 4), value, dtype="float32")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        height=4,
        width=4,
        count=1,
        dtype="float32",
        crs="EPSG:32724",
        transform=rasterio.transform.from_origin(290080.0, 9231780.0, 20.0, 20.0),
        nodata=float("nan"),
    ) as handle:
        handle.write(data, 1)


# ── o default é o azul de hoje ───────────────────────────────────────────────


def test_o_default_e_a_geracao_v1_de_producao():
    """Sem argumento, o resolvedor devolve o que o runtime já usava."""

    generation = sel.resolve_baseline()
    assert generation.version == "1.0.0"
    assert generation.directory == Path(settings.BASELINES_DIR)
    assert generation.manifest_path == Path(settings.BASELINE_MANIFEST_PATH)
    assert generation.manifest_path.name == "baseline_manifest_v1.json"
    assert generation.key_prefix == "baselines/"
    assert generation.manifest_schema == sel.MANIFEST_SCHEMA_V1


def test_o_default_vem_de_settings_e_nao_de_uma_segunda_lista():
    """Um pin só. Se `settings.BASELINE_VERSION` mudar, o default muda com ele
    — e `tests/test_baseline_manifest.py` amarra esse valor ao próprio
    `baseline_version` do manifest v1, então uma mudança solta cai lá.
    """

    assert sel.default_baseline_version() == settings.BASELINE_VERSION
    assert sel.resolve_baseline().version == settings.BASELINE_VERSION


def test_a_v2_nao_e_alcancavel_sem_ser_nomeada(monkeypatch):
    """Nem por ambiente, nem por "mais nova", nem por diretório presente.

    O diretório `data/baselines_v2/2.1.0` existe nesta máquina com os 72
    rasters; se a resolução olhasse o disco, este teste passaria por acidente.
    Ele olha o valor devolvido.
    """

    for variable in (
        "BASELINE_VERSION",
        "ARARIPE_BASELINE_VERSION",
        "BASELINE_MANIFEST_PATH",
    ):
        monkeypatch.setenv(variable, "2.1.0")
    assert sel.resolve_baseline().version == "1.0.0"


# ── o registro é fechado e falha fechado ─────────────────────────────────────


def test_as_duas_geracoes_registradas_sao_a_v1_e_a_v2_1():
    assert sorted(sel.BASELINE_GENERATIONS) == ["1.0.0", "2.1.0"]


def test_a_v2_1_aponta_para_o_seu_proprio_manifest_e_diretorio():
    generation = sel.resolve_baseline("2.1.0")
    assert generation.manifest_path.name == "baseline_manifest_v2_1.json"
    assert generation.directory.as_posix().endswith("data/baselines_v2/2.1.0")
    assert generation.key_prefix == "baselines_v2/2.1.0/"
    assert generation.manifest_schema == sel.MANIFEST_SCHEMA_V2
    # Prefixos disjuntos: nenhuma listagem ou chave de v1 pode colidir.
    assert not generation.key_prefix.startswith(
        sel.resolve_baseline("1.0.0").key_prefix + "v"
    )


def test_a_2_0_0_e_recusada_nomeando_a_sucessora():
    """Ela existe como material de auditoria e 12 dos 72 rasters diferem da
    2.1.0. Recusar em silêncio pareceria esquecimento; redirecionar responderia
    outra pergunta.
    """

    with pytest.raises(sel.UnknownBaselineGeneration) as raised:
        sel.resolve_baseline("2.0.0")
    assert "superseded by 2.1.0" in str(raised.value)
    assert sel.superseded_manifest_path("2.0.0").name == "baseline_manifest_v2.json"


@pytest.mark.parametrize("value", ["", "   ", "2", "2.1", "3.0.0", "latest", None])
def test_uma_versao_desconhecida_falha_fechado(value):
    """Inclui `None` **como string vazia deliberada**: `None` é o default e é
    legítimo, então a lista acima usa `None` só para o caso de string vazia
    depois de `strip`. Nenhum valor é aproximado para a geração mais próxima.
    """

    if value is None:
        return
    with pytest.raises(sel.UnknownBaselineGeneration):
        sel.resolve_baseline(value)


def test_um_esquema_de_manifest_desconhecido_e_recusado(tmp_path):
    _write_raster(tmp_path / "ndmi_month07_mean.tif", 0.1)
    with pytest.raises(sel.UnknownBaselineGeneration):
        sel.verify_object_against_manifest(
            Path(settings.BASELINE_MANIFEST_PATH),
            "baseline-manifest-v9",
            tmp_path / "ndmi_month07_mean.tif",
        )


# ── o manifest de cada geração é válido e descreve 72 objetos ────────────────


@pytest.mark.parametrize("version", ["1.0.0", "2.1.0"])
def test_cada_geracao_registrada_carrega_e_valida_o_seu_manifest(version):
    manifest = sel.resolve_baseline(version).load_manifest()
    assert manifest["baseline_version"] == version
    assert manifest["aggregate"]["object_count"] == 72
    assert manifest["aggregate"]["range_violation_pixels"] == 0


def test_as_duas_geracoes_compartilham_a_grade_e_o_extent():
    """É por isso que a troca é uma troca e não um reprojeto: mesma grade,
    mesmo extent, mesmos 72 nomes. Medido dos dois manifests.
    """

    v1 = sel.resolve_baseline("1.0.0").load_manifest()
    v21 = sel.resolve_baseline("2.1.0").load_manifest()
    for field in ("crs", "width", "height", "transform", "bounds", "pixel_size",
                  "dtype", "band_count", "nodata"):
        assert v1["raster_contract"][field] == v21["raster_contract"][field], field
    assert v1["monitoring_extent"] == v21["monitoring_extent"]
    assert (
        {obj["filename"] for obj in v1["objects"]}
        == {obj["filename"] for obj in v21["objects"]}
    )


def test_as_duas_geracoes_nao_compartilham_um_unico_raster():
    """Zero interseção de SHA-256. A troca muda todos os 72 objetos, não
    alguns — e é por isso que a decisão é científica e não operacional.
    """

    v1 = sel.resolve_baseline("1.0.0").load_manifest()
    v21 = sel.resolve_baseline("2.1.0").load_manifest()
    assert not (
        {obj["sha256"] for obj in v1["objects"]}
        & {obj["sha256"] for obj in v21["objects"]}
    )


# ── o carregador ─────────────────────────────────────────────────────────────


def test_sem_geracao_nomeada_o_carregador_le_o_diretorio_azul(tmp_path, monkeypatch):
    """A inércia, provada lendo um raster: com `BASELINES_DIR` redirecionado, o
    carregador sem geração vai a esse diretório e exige o manifest v1.
    """

    filename = "ndmi_month07_mean.tif"
    _write_raster(tmp_path / filename, 0.1)
    monkeypatch.setattr(baseline_module, "BASELINES_DIR", tmp_path)
    baseline_module._verify_authoritative_file.cache_clear()
    sel.clear_verification_cache()
    with pytest.raises(ValueError, match="size does not match"):
        baseline_module.load_baseline("ndmi", 7, "mean")


def test_uma_geracao_nomeada_verifica_contra_o_manifest_dela(tmp_path):
    """Um raster sintético no diretório da 2.1.0 é recusado pelo manifest da
    2.1.0 — a mensagem prova que a verificação usou o manifest da geração e não
    o do default.
    """

    filename = "ndmi_month07_mean.tif"
    _write_raster(tmp_path / filename, 0.1)
    generation = sel.BaselineGeneration(
        version="2.1.0",
        directory=tmp_path,
        manifest_path=Path(sel.resolve_baseline("2.1.0").manifest_path),
        key_prefix="baselines_v2/2.1.0/",
        manifest_schema=sel.MANIFEST_SCHEMA_V2,
    )
    sel.clear_verification_cache()
    with pytest.raises(ValueError, match="size does not match"):
        baseline_module.load_baseline("ndmi", 7, "mean", generation=generation)


def test_nomear_geracao_e_diretorio_ao_mesmo_tempo_e_recusado(tmp_path):
    with pytest.raises(ValueError, match="never both"):
        baseline_module.load_baseline(
            "ndmi", 7, "mean", tmp_path, generation=sel.resolve_baseline()
        )


def test_o_cache_de_verificacao_nao_confunde_duas_geracoes(tmp_path):
    """Os dois manifests têm os MESMOS 72 nomes de arquivo. Um cache com chave
    só no caminho deixaria a verificação de uma geração responder pela outra
    quando os diretórios coincidissem; a chave inclui o manifest.
    """

    filename = "ndmi_month07_mean.tif"
    _write_raster(tmp_path / filename, 0.1)
    v1 = sel.BaselineGeneration(
        version="1.0.0",
        directory=tmp_path,
        manifest_path=Path(settings.BASELINE_MANIFEST_PATH),
        key_prefix="baselines/",
        manifest_schema=sel.MANIFEST_SCHEMA_V1,
    )
    v21 = sel.BaselineGeneration(
        version="2.1.0",
        directory=tmp_path,
        manifest_path=Path(sel.resolve_baseline("2.1.0").manifest_path),
        key_prefix="baselines_v2/2.1.0/",
        manifest_schema=sel.MANIFEST_SCHEMA_V2,
    )
    sel.clear_verification_cache()
    for generation in (v1, v21):
        with pytest.raises(ValueError):
            sel.verify_baseline_object(generation, tmp_path / filename)
    assert sel._verify_cached.cache_info().misses == 2


# ── os pontos de entrada expõem a escolha ────────────────────────────────────


@pytest.mark.parametrize(
    "script",
    ["run_detection.py", "run_detection_gee.py", "run_detection_from_gee.py"],
)
def test_todo_run_detection_aceita_a_versao_de_baseline(script):
    """O briefing pede `src/detection/baseline.py` **e os `run_detection*`**
    capazes de carregar a v2. Lido do arquivo, não do docstring.
    """

    source = (ROOT / "scripts" / script).read_text(encoding="utf-8")
    assert '"--baseline-version"' in source
    assert "resolve_baseline" in source


def test_o_default_do_cli_e_none_e_nao_uma_versao_escrita():
    """Se um `run_detection*` escrevesse `default="1.0.0"`, o default do azul
    passaria a viver em quatro lugares e `settings.py` deixaria de ser a
    autoridade. Todos passam `None`, que resolve por `settings`.
    """

    for script in (
        "run_detection.py",
        "run_detection_gee.py",
        "run_detection_from_gee.py",
    ):
        source = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        block = source[source.index('"--baseline-version"'):]
        block = block[: block.index(")")]
        assert "default=None" in block, script
        assert "1.0.0" not in block and "2.1.0" not in block, script


def test_a_persistencia_recebe_a_versao_resolvida_e_nao_a_constante():
    """A tier de persistência carrega `baseline_version`. Se continuasse a
    receber `BASELINE_VERSION` importado, um replay contra a 2.1.0 gravaria
    `1.0.0` em cada track — e o candidato pareceria válido comparado contra a
    referência errada, que é exatamente o risco desta fase.
    """

    for script, expected in (
        ("run_detection.py", "baseline_version=resolved_baseline,"),
        ("run_detection_from_gee.py", "baseline_version=baseline.version,"),
    ):
        source = (ROOT / "scripts" / script).read_text(encoding="utf-8")
        assert expected in source, script
        assert "baseline_version=BASELINE_VERSION" not in source, script

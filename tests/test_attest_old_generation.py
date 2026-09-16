"""The cross-check that makes the attestation evidence, and what drops it.

The attestation's whole claim to being evidence rather than a directory listing
is that the producer's own sealed digest is recomputed from the tracked bytes.
If that check were absent, or non-fatal, the document would still look
complete — it would just be asserting the producer's number back at itself.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "attest_old_generation.py"


def _load():
    spec = importlib.util.spec_from_file_location("attest_old_generation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


attest = _load()

BODY = b'{"schema":"araripe.timeseries.release/1","x":1}'
DIGEST = hashlib.sha256(BODY).hexdigest()


def _rows(sha=DIGEST, size=len(BODY)):
    return [{
        "path": "data/timeseries/timeseries.db",
        "git_blob_id": "0" * 40,
        "bytes": size,
        "sha256": sha,
    }]


def _release(sha=DIGEST, size=len(BODY), path="data/timeseries/timeseries.db"):
    return json.dumps({
        "schema": "araripe.timeseries.release/1",
        "latest_observation": "2026-08-30",
        "published_utc": "2026-09-07T15:52:37Z",
        "run_id": "34137318406",
        "timeseries": {"path": path, "sha256": sha, "bytes": size},
    }).encode("utf-8")


def test_a_reivindicacao_do_produtor_confere_com_os_bytes_rastreados():
    """O caminho honesto: os dois concordam e a atestação registra a origem."""

    verified = attest.verify_release_claim(_rows(), _release())
    assert verified["verified"] is True
    assert verified["timeseries_sha256"] == DIGEST
    assert verified["producer_run_id"] == "34137318406"
    assert verified["declared_by"] == "data/timeseries/RELEASE.json"


def test_um_digest_divergente_e_um_achado_e_nao_um_numero_mais_novo():
    """Derruba: pular a conferência, ou torná-la um aviso.

    Esta é a mutação que importa. Sem ela, a atestação selaria os bytes que
    encontrou e repetiria o número do produtor sem nunca compará-los — e um
    banco reescrito por fora passaria como a mesma geração.
    """

    with pytest.raises(attest.AttestationError, match="disagree"):
        attest.verify_release_claim(_rows(sha="f" * 64), _release())


def test_um_tamanho_divergente_tambem_falha_fechado():
    """Derruba: conferir só o digest.

    Um digest igual com tamanho diferente é impossível na prática, mas a
    reivindicação tem dois campos e aceitar um documento que erra um deles é
    aceitar um documento que não foi lido.
    """

    with pytest.raises(attest.AttestationError, match="bytes"):
        attest.verify_release_claim(_rows(size=99), _release())


def test_uma_reivindicacao_sobre_um_objeto_fora_do_inventario_falha_fechado():
    """Derruba: ignorar uma reivindicação que não casa com nada.

    Se o RELEASE.json nomeasse um caminho que o inventário não contém, uma
    implementação permissiva não teria nada para comparar e diria "verificado".
    """

    with pytest.raises(attest.AttestationError, match="not in the sealed inventory"):
        attest.verify_release_claim(_rows(), _release(path="data/other.db"))


def test_a_atestacao_real_esta_gravada_e_confere():
    """A atestação desta sessão, relida do documento commitado.

    Derruba: um documento gravado sem a verificação, ou com um inventário
    vazio. O `inventory_sha256` é recomputado a partir do próprio inventário
    do documento, então um documento editado à mão deixa de casar.
    """

    from src.detection.identity import canonical_sha256

    path = REPO / "docs" / "implementation" / "OLD_GENERATION_ATTESTATION_2026-09-09.json"
    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["schema"] == attest.ATTESTATION_SCHEMA
    assert document["producer_release_claim"]["verified"] is True
    assert document["site"]["object_count"] > 0
    assert document["totals"]["object_count"] == (
        len(document["backend"]["objects"]) + len(document["site"]["objects"])
    )
    recomputed = canonical_sha256({
        "backend": {
            "commit": document["backend"]["commit"],
            "objects": document["backend"]["objects"],
        },
        "site": {
            "commit": document["site"]["commit"],
            "objects": document["site"]["objects"],
        },
    })
    assert recomputed == document["inventory_sha256"], (
        "the recorded inventory digest does not match the recorded inventory"
    )

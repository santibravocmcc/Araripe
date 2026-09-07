#!/usr/bin/env python3
"""Get/put the gap-tolerant persistence-state GeoJSON in Cloudflare R2.

The persistence state is a single object (`persistence_state.geojson`) holding
the running alert "tracks" (n_sightings, first_seen, last_seen, geometry). The
scheduled detection fetches it before running (so streaks chain across runs,
tolerating gaps) and pushes the updated version afterwards.

Usage:
    python scripts/r2_state.py get data/persistence_state.geojson
    python scripts/r2_state.py get data/persistence_state.geojson --require-existing
    python scripts/r2_state.py put data/persistence_state.geojson

Needs R2_ENDPOINT_URL / R2_ACCESS_KEY / R2_SECRET_KEY in the environment.

Fail-closed contract (Package 2B.1)
-----------------------------------
This helper used to wrap the download in a bare `except Exception` that printed
"primeira execução?" and continued. An authentication failure, a network error,
a truncated download or a corrupt object was therefore indistinguishable from a
genuine first run, and the pipeline proceeded with an EMPTY state — silently
resetting `n_sightings`, `first_seen` and `last_seen` for every track. Those
counters are the scientific product (they drive first_observation / candidate /
confirmed), and the loss is unrecoverable without a full replay.

So `get` now distinguishes exactly one benign case from every other outcome:

  * the object is genuinely absent (HTTP 404 / NoSuchKey) -> start fresh, say so
    loudly, and exit 0 — unless `--require-existing` is passed, which is how a
    deployment whose state is known to exist refuses a silent deletion too;
  * anything else — bad credentials, denied access, missing bucket, network or
    endpoint failure, a truncated body, unparseable JSON, a payload that is not
    a track FeatureCollection -> fail closed, exit non-zero, write no file.

`put` is fail-closed in the same spirit: a missing local file used to print a
warning and exit 0, which turned "detection produced no state" into a silent
no-op that left the previous state live. It is now an error, and the payload is
validated before upload so a corrupt state is never published.

Escopo da validação (corrigido em 2026-09-07)
---------------------------------------------
A primeira versão desta validação afirmou um invariante que o código NUNCA
garantiu — `first_seen <= last_seen` — e derrubou a rodada de produção de
2026-09-07 (`feature 101684: first_seen 2026-07-13 is after last_seen
2026-07-11`). O estado estava íntegro; a checagem estava errada.

Em `update_tracks`, `w_last[t] = date` sobrescreve `last_seen` com a data em
processamento, enquanto `w_first[t]` é preservado. Como cada rodada reprocessa
uma janela de `SEARCH_DAYS_BACK = 16` dias, uma rodada posterior pode casar uma
track numa data MAIS ANTIGA do que a que já estava registrada — e aí
`last_seen` anda para trás. `last_seen` significa "data do casamento processado
mais recentemente", não "data mais recente já vista".

Daí a divisão, agora baseada em evidência e não em suposição:

- **fatal** — o objeto não serve como estado: corpo truncado, vazio, não-JSON,
  não é FeatureCollection, sem `features`, feature que não é objeto, sem
  `properties`, sem as três colunas, sem geometria, ou `last_seen` ilegível
  (`update_tracks` chama `_days_between` nele e estouraria depois);
- **anomalia contada** — o pipeline lida com ela, então avisa e segue:
  `first_seen > last_seen` (normal, acima), `first_seen` ilegível (só é
  carregado como string, nunca parseado) e `n_sightings` não-inteiro ou < 1
  (`pd.to_numeric(errors="coerce").fillna(1)` resolve).

A lição: uma validação fail-closed só pode exigir o que o produtor realmente
promete. Exigir mais transforma a proteção na própria falha.
"""
import json
import os
import sys

KEY = "persistence_state.geojson"

# Properties every track carries; see `src/detection/persistence.py`.
REQUIRED_PROPERTIES = ("n_sightings", "first_seen", "last_seen")

# R2/S3 error codes that mean "the object is not there", as opposed to "we could
# not find out". Only these may be read as a genuine first run.
ABSENT_CODES = frozenset({"404", "NoSuchKey"})

_ENV_VARS = ("R2_ENDPOINT_URL", "R2_ACCESS_KEY", "R2_SECRET_KEY")


class StateError(RuntimeError):
    """The state could not be trusted — never treat this as a first run."""


def _annotate(msg):
    """Error text, annotated for the Actions log when running in CI."""
    return f"::error::{msg}" if os.environ.get("GITHUB_ACTIONS") else f"erro: {msg}"


def _client():
    missing = [v for v in _ENV_VARS if not os.environ.get(v)]
    if missing:
        raise StateError(f"missing R2 credentials in the environment: {', '.join(missing)}")
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_KEY"],
    )


def _error_code(exc):
    """Best-effort S3 error code for a botocore ClientError, else None."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return None
    code = (response.get("Error") or {}).get("Code")
    if code is not None:
        return str(code)
    status = (response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
    return str(status) if status is not None else None


def is_absent(exc):
    """True only for "the object does not exist".

    Deliberately narrow: a 403 hides existence rather than denying it, and a
    missing bucket is a misconfiguration. Both must fail closed, because reading
    either as a first run is what silently wipes the tracks.
    """
    return _error_code(exc) in ABSENT_CODES


def validate_state(raw, *, expected_bytes=None):
    """Validate a persistence-state payload; return a summary dict.

    Raises `StateError` on anything that is not a complete, parseable track
    FeatureCollection. An EMPTY FeatureCollection is valid: a run that has never
    seen an alert legitimately stores zero tracks.
    """
    if expected_bytes is not None and len(raw) != expected_bytes:
        raise StateError(
            f"truncated download: got {len(raw)} bytes, R2 reports {expected_bytes}"
        )
    if not raw.strip():
        raise StateError("empty payload (0 bytes of content)")
    try:
        doc = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as e:
        raise StateError(f"payload is not valid JSON: {e}") from e
    if not isinstance(doc, dict):
        raise StateError(f"payload is a {type(doc).__name__}, expected a GeoJSON object")
    if doc.get("type") != "FeatureCollection":
        raise StateError(f"expected a FeatureCollection, got type={doc.get('type')!r}")
    features = doc.get("features")
    if not isinstance(features, list):
        raise StateError("FeatureCollection has no 'features' list")

    anomalies = {}
    for i, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise StateError(f"feature {i} is a {type(feature).__name__}, expected an object")
        props = feature.get("properties")
        if not isinstance(props, dict):
            raise StateError(f"feature {i} has no properties object")
        missing = [p for p in REQUIRED_PROPERTIES if p not in props]
        if missing:
            raise StateError(f"feature {i} is missing {', '.join(missing)}")
        if feature.get("geometry") is None:
            raise StateError(f"feature {i} has no geometry — it could never match an alert")
        _check_track(i, props, anomalies)

    summary = {"tracks": len(features), "bytes": len(raw), "anomalies": anomalies}
    _report_anomalies(summary)
    return summary


# Anomalias que NÃO impedem o pipeline de rodar. Contadas e avisadas, nunca
# fatais — ver a nota "Escopo da validação" no topo do módulo.
_ODD_BACKWARDS = "first_seen_after_last_seen"
_ODD_FIRST_DATE = "first_seen_not_iso"
_ODD_COUNT = "n_sightings_not_a_positive_int"


def _check_track(i, props, anomalies):
    """Fatal só no que quebra o pipeline; o resto é anomalia contada."""
    # FATAL: update_tracks chama _days_between(date, last_seen), que estoura
    # com uma data ilegível — o run morreria depois, com traceback pior.
    _iso_date(i, props, "last_seen")

    # Contadas: nenhuma destas impede a próxima detecção de rodar.
    first = _iso_date_or_none(props, "first_seen")
    if first is None:
        _note(anomalies, _ODD_FIRST_DATE, i, props.get("first_seen"))
    elif str(first) > str(props["last_seen"]):
        _note(anomalies, _ODD_BACKWARDS, i,
              f"{props['first_seen']} > {props['last_seen']}")
    try:
        if int(props["n_sightings"]) < 1:
            _note(anomalies, _ODD_COUNT, i, props["n_sightings"])
    except (TypeError, ValueError):
        _note(anomalies, _ODD_COUNT, i, props["n_sightings"])


def _note(anomalies, kind, i, detail):
    """Registra a contagem e o primeiro exemplo de cada tipo de anomalia."""
    entry = anomalies.setdefault(kind, {"count": 0, "first_example": None})
    entry["count"] += 1
    if entry["first_example"] is None:
        entry["first_example"] = f"feature {i}: {detail}"


def _report_anomalies(summary):
    """Um aviso por tipo, com contagem e exemplo — nunca uma falha."""
    marker = "::warning::" if os.environ.get("GITHUB_ACTIONS") else "aviso: "
    for kind, entry in sorted(summary["anomalies"].items()):
        print(f"{marker}{summary['tracks']} tracks, {entry['count']} com "
              f"{kind} ({entry['first_example']})", flush=True)


def _iso_date(i, props, key):
    from datetime import date
    try:
        return date.fromisoformat(str(props[key]))
    except ValueError as e:
        raise StateError(f"feature {i}: {key}={props[key]!r} is not a YYYY-MM-DD date") from e


def _iso_date_or_none(props, key):
    from datetime import date
    try:
        return date.fromisoformat(str(props[key]))
    except ValueError:
        return None


def get(client, bucket, path, *, require_existing=False):
    """Download and validate the state. Returns True if a file was written."""
    from botocore.exceptions import ClientError

    try:
        head = client.head_object(Bucket=bucket, Key=KEY)
    except ClientError as e:
        if is_absent(e) and not require_existing:
            # The one benign path: no state yet, every alert is a 1ª observação.
            print(f"{KEY} não existe em {bucket} — primeira execução, começando do zero")
            return False
        if is_absent(e):
            raise StateError(
                f"{KEY} is absent from {bucket} but --require-existing was given: "
                "the state was deleted or the bucket/endpoint is wrong. Refusing to "
                "reset every track's n_sightings/first_seen/last_seen."
            ) from e
        raise StateError(f"cannot read {KEY} from {bucket} ({_error_code(e) or 'unknown'}): {e}") from e
    except Exception as e:  # network, endpoint, TLS, credential shape…
        raise StateError(f"cannot reach R2 to read {KEY} from {bucket}: {e}") from e

    expected = head.get("ContentLength")
    tmp = f"{path}.part"
    try:
        client.download_file(bucket, KEY, tmp)
        with open(tmp, "rb") as f:
            raw = f.read()
        summary = validate_state(raw, expected_bytes=expected)
    except StateError:
        _unlink(tmp)
        raise
    except Exception as e:
        _unlink(tmp)
        raise StateError(f"download of {KEY} from {bucket} failed: {e}") from e

    # Only a fully validated payload replaces whatever is on disk.
    os.replace(tmp, path)
    print(f"fetched {KEY} -> {path} ({summary['tracks']} tracks, {summary['bytes']} bytes)")
    return True


def put(client, bucket, path):
    """Validate the local state, upload it, and confirm the stored size."""
    if not os.path.exists(path):
        raise StateError(
            f"{path} does not exist — detection produced no persistence state. "
            "Refusing to exit clean: that would leave the previous state live "
            "while reporting success."
        )
    with open(path, "rb") as f:
        raw = f.read()
    summary = validate_state(raw)

    try:
        client.upload_file(
            path, bucket, KEY, ExtraArgs={"ContentType": "application/geo+json"}
        )
    except Exception as e:
        raise StateError(f"upload of {path} to {bucket}/{KEY} failed: {e}") from e

    try:
        stored = client.head_object(Bucket=bucket, Key=KEY).get("ContentLength")
    except Exception as e:
        raise StateError(f"uploaded {KEY} but could not confirm it in {bucket}: {e}") from e
    if stored != summary["bytes"]:
        raise StateError(
            f"{KEY} stored as {stored} bytes but {summary['bytes']} were sent — "
            "the upload is incomplete"
        )
    print(f"put {path} -> {KEY} ({summary['tracks']} tracks, {summary['bytes']} bytes)")


def _unlink(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    require_existing = False
    if "--require-existing" in argv:
        argv.remove("--require-existing")
        require_existing = True
    if len(argv) < 2 or argv[0] not in ("get", "put"):
        sys.exit("usage: r2_state.py {get|put} <local_path> [--require-existing]")
    action, path = argv[0], argv[1]
    bucket = os.environ.get("R2_BUCKET_NAME", "araripe-cogs")
    try:
        client = _client()
        if action == "get":
            get(client, bucket, path, require_existing=require_existing)
        else:
            put(client, bucket, path)
    except StateError as e:
        sys.exit(_annotate(str(e)))


if __name__ == "__main__":
    main()

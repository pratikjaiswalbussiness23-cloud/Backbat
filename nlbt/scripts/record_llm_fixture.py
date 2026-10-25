"""Record ONE real LLM response into tests/fixtures/llm/ — P6-T1 dev tooling.

NEVER runs in CI: this is a script under scripts/ (not collected by pytest),
it needs a live key, and its outputs are reviewed before staging. Owner
authorization ("source .env for the probe", 2026-10-25) covers exactly this
script and the step-2 probe for gitignored-.env key loading.

Key handling (strict): the key is read via scripts/envfile.py into a LOCAL
variable, used only for the Authorization header, and the serialized record
is byte-checked before any write — if the key would land in the file,
``write_fixture`` RAISES and nothing is written (R13).

Usage:
    NLBT_LLM_MODEL=<chosen id> uv run python scripts/record_llm_fixture.py \
        --name smoke_envelope
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

try:
    from envfile import find_key
except ImportError:  # loaded via importlib from tests (scripts/ not on sys.path)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from envfile import find_key

from nlbt.config import Config
from nlbt.nl import OpenAICompatibleClient, envelope_schema, schema_sha256

#: A tiny envelope-shaped request (P6-T1 smoke recording).
DEFAULT_SYSTEM = (
    "You translate English into the nlbt envelope JSON. Output JSON only, "
    "matching the provided schema."
)
DEFAULT_USER = (
    'Respond with JSON only: {"status": "ok", "spec": null, "questions": [], '
    '"assumptions": [], "unsupported": []}'
)

__all__ = ["build_record", "main", "write_fixture"]


def write_fixture(path: Path, record: dict[str, Any], *, key: str) -> None:
    """Serialize and write; RAISES (writing nothing) if the key would appear."""
    text = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=True)
    if key and key in text:
        raise RuntimeError("refusing to write fixture: the API key would appear in the file")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def build_record(
    *,
    name: str,
    model: str,
    structured_mode: str,
    temperature: float,
    system: str,
    user: str,
    schema: dict[str, Any],
    response: dict[str, Any],
    host: str,
    request_hash: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "request_hash": request_hash,
        "request": {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "schema_sha256": schema_sha256(schema),
            "temperature": temperature,
            "structured_mode": structured_mode,
        },
        "response": response,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "host": host,
        "source": "recorded",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record one live LLM fixture (dev-only).")
    parser.add_argument("--name", default="smoke_envelope", help="fixture file stem")
    parser.add_argument("--model", default=None, help="model id (default: NLBT_LLM_MODEL)")
    parser.add_argument(
        "--mode",
        default="json_schema",
        choices=["json_schema", "nvext_guided_json"],
        help="structured output transport",
    )
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "llm"),
        help="fixture directory",
    )
    args = parser.parse_args(argv)

    # Key: env var first (Config reads it), else the authorized .env helper.
    config = Config()
    if not config.nvidia_api_key:
        key = find_key(Path(__file__).resolve().parents[1] / ".env")
        if not key:
            print("KEY MISSING IN .env")
            return 2
        config = Config(nvidia_api_key=key)  # local; never printed, never written

    model = args.model if args.model else config.llm_model
    client = OpenAICompatibleClient(config=config, structured_mode=args.mode)
    schema = envelope_schema()
    resp = client.complete_structured(DEFAULT_SYSTEM, DEFAULT_USER, schema, model=model)

    record = build_record(
        name=args.name,
        model=model,
        structured_mode=args.mode,
        temperature=0.0,
        system=DEFAULT_SYSTEM,
        user=DEFAULT_USER,
        schema=schema,
        response=resp.payload,
        host=config.llm_base_url,
        request_hash=client.fingerprint(DEFAULT_SYSTEM, DEFAULT_USER, schema, model=model),
    )
    target = Path(args.out) / f"{args.name}.json"
    assert_key = config.nvidia_api_key or ""
    write_fixture(target, record, key=assert_key)
    print(f"wrote {target} (source={resp.source}, status={resp.payload.get('status')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

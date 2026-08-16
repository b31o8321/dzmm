from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from . import CONTRACT_VERSION


def contracts_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "contracts"


def load_contracts() -> dict[str, dict]:
    contracts: dict[str, dict] = {}
    for path in sorted(contracts_dir().glob("*.schema.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(payload)
        contracts[path.name] = payload
    if not contracts:
        raise RuntimeError("no vNext contracts found")
    return contracts


def contract_manifest() -> dict[str, object]:
    return {"version": CONTRACT_VERSION, "contracts": sorted(load_contracts())}


def contract_validator(name: str) -> Draft202012Validator:
    try:
        contract = load_contracts()[name]
    except KeyError as error:
        raise ValueError(f"unknown vNext contract: {name}") from error
    return Draft202012Validator(contract)

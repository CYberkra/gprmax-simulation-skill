from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml
from jsonschema import Draft202012Validator


class ContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _schema_path() -> Path:
    return Path(__file__).resolve().parents[1] / "schemas" / "simulation_contract.schema.json"


def validate_contract(value: Mapping[str, Any]) -> None:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(value), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.path) or "<root>"
        raise ContractError("BLOCK_CONTRACT_SCHEMA", f"{location}: {error.message}")


def load_contract(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ContractError("BLOCK_CONTRACT_SCHEMA", "<root>: contract must be a mapping")
    validate_contract(value)
    return value

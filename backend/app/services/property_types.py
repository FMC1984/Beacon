"""Property (client/site) type vocabulary + config loader.

This is the client/site TYPE of a Property - multifamily_apartment vs
housing_authority - which drives terminology, Content Intelligence knowledge
bases, available connectors, and Nora framing. It is deliberately SEPARATE from
PropertyProfile.property_type (the operator-asserted regulatory/marketing type
like affordable/senior). Vocabulary lives in reference_data/property_types.json.
"""

import json
from functools import lru_cache
from pathlib import Path

_REFERENCE = (
    Path(__file__).resolve().parent.parent / "reference_data" / "property_types.json"
)


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(_REFERENCE.read_text())


def default_type() -> str:
    return config()["default"]


def type_keys() -> list[str]:
    return list(config()["types"].keys())


def type_config(property_type: str) -> dict:
    return config()["types"].get(property_type, config()["types"][default_type()])


def label(property_type: str) -> str:
    return type_config(property_type).get("label", property_type)


def allowed_connectors(property_type: str) -> list[str]:
    return list(type_config(property_type).get("allowed_connectors", []))


def connector_allowed(property_type: str, connector: str) -> bool:
    return connector in allowed_connectors(property_type)


class InvalidPropertyTypeError(ValueError):
    """property_type not in the controlled vocabulary."""


def validate_property_type(value: str | None) -> str:
    key = (value or "").strip()
    if not key:
        return default_type()
    if key not in config()["types"]:
        raise InvalidPropertyTypeError(
            "Unknown property_type '" + str(value) + "'. Allowed: "
            + ", ".join(type_keys())
        )
    return key

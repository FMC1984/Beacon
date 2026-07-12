from app.adapters.crm_base import CRMAdapter, NormalizedLead, SkippedRecord
from app.adapters.yardi_adapter import YardiAdapter

ADAPTERS: dict[str, CRMAdapter] = {
    YardiAdapter.key: YardiAdapter(),
}


def get_adapter(key: str) -> CRMAdapter | None:
    return ADAPTERS.get(key)


__all__ = [
    "ADAPTERS",
    "CRMAdapter",
    "NormalizedLead",
    "SkippedRecord",
    "YardiAdapter",
    "get_adapter",
]

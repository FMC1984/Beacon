"""The request's principal, reachable from code that has no request handle.

current_principal (async, so it runs on the request task) sets it; sync
handlers and the services they call run in a thread that inherits a copy of
the task's context, so they can read it. Background loops and CLI code never
set it, so they see None and behave as they always did.
"""

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.auth.deps import Principal

principal_var: ContextVar["Principal | None"] = ContextVar("beacon_principal", default=None)


def set_current(principal: "Principal | None") -> None:
    principal_var.set(principal)


def get_current() -> "Principal | None":
    return principal_var.get()

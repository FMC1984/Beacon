"""Every API route declares an auth dependency unless it is on the explicit
public allowlist. This is the guard against an endpoint shipping open."""

from fastapi.routing import APIRoute

from app.auth.deps import current_principal, require_platform_admin, require_role, role_gate
from app.main import app
from app.routers.auth import PUBLIC_ROUTES

PUBLIC = set(PUBLIC_ROUTES) | {
    ("GET", "/api/health"),
    ("GET", "/api/briefing/shared/{token}"),
    ("GET", "/api/google/callback"),
    ("POST", "/api/billing/webhook"),
}

AUTH_CALLS = {current_principal, role_gate, require_platform_admin}


def api_routes():
    """(methods, full path, dependant) for every route, including those FastAPI
    keeps inside included routers (0.139+ wraps them; router-level dependencies
    live on the effective route context, not the inner APIRoute)."""
    for route in app.routes:
        if isinstance(route, APIRoute):
            yield route.methods or set(), route.path, route.dependant
        elif hasattr(route, "effective_route_contexts"):
            for ctx in route.effective_route_contexts():
                yield ctx.methods or set(), ctx.path, ctx.dependant


def _dependency_calls(dependant) -> set:
    calls = set()
    stack = [dependant]
    while stack:
        d = stack.pop()
        if d.call is not None:
            calls.add(d.call)
        stack.extend(d.dependencies)
    return calls


def _is_gated(dependant) -> bool:
    calls = _dependency_calls(dependant)
    if calls & AUTH_CALLS:
        return True
    return any(getattr(c, "__qualname__", "").startswith("require_role.<locals>.dep") for c in calls)


def test_the_walk_sees_the_real_routes():
    paths = {path for _, path, _ in api_routes()}
    assert "/api/companies" in paths and "/api/auth/login" in paths and "/api/admin/status" in paths


def test_every_route_is_gated_or_explicitly_public():
    open_routes = []
    for methods, path, dependant in api_routes():
        if not path.startswith("/api"):
            continue
        for method in methods:
            if method in ("HEAD", "OPTIONS") or (method, path) in PUBLIC:
                continue
            if not _is_gated(dependant):
                open_routes.append(f"{method} {path}")
    assert not open_routes, "Routes without an auth dependency: " + ", ".join(sorted(open_routes))


def test_public_routes_are_really_open():
    """The allowlist names routes that exist and carry no auth dependency."""
    present = {(m, path): dependant for methods, path, dependant in api_routes() for m in methods}
    for method, path in PUBLIC:
        assert (method, path) in present, f"{method} {path} is on the public allowlist but does not exist"
        assert not _is_gated(present[(method, path)]), f"{method} {path} is public but gated"


def test_require_role_closure_is_recognised():
    dep = require_role("owner")
    assert dep.__qualname__.startswith("require_role.<locals>.dep")

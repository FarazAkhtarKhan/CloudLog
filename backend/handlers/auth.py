"""
Identity and role-based access control.

API Gateway's JWT authorizer verifies the Cognito token (signature, expiry,
audience) before the request reaches Lambda, then passes the claims through.
This module only maps those claims to a role and a set of permissions.
"""
from dataclasses import dataclass
from typing import Any

from backend.config import local_mode

ADMIN, ANALYST, VIEWER = "Admin", "Analyst", "Viewer"
ROLES = (ADMIN, ANALYST, VIEWER)  # highest privilege first

PERMISSIONS = {
    ADMIN: {"read", "triage", "simulate", "reset"},
    ANALYST: {"read", "triage", "simulate"},
    VIEWER: {"read"},
}


@dataclass
class User:
    user_id: str
    email: str
    role: str

    def can(self, permission: str) -> bool:
        return permission in PERMISSIONS[self.role]


def _groups(raw: Any) -> list[str]:
    # API Gateway flattens list claims to a string like "[Admin Analyst]"
    if isinstance(raw, list):
        return [str(g) for g in raw]
    if isinstance(raw, str):
        return [g for g in raw.strip("[]").replace(",", " ").split() if g]
    return []


def user_from_event(event: dict[str, Any]) -> User:
    claims = event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    if claims:
        groups = _groups(claims.get("cognito:groups"))
        role = next((r for r in ROLES if r in groups), VIEWER)
        return User(user_id=str(claims.get("sub", "unknown")), email=str(claims.get("email", "unknown")), role=role)

    # Offline emulator only: the dashboard sends its chosen demo role in a header.
    # In AWS this branch is unreachable because the JWT authorizer rejects tokenless calls.
    if local_mode():
        headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
        role = headers.get("x-user-role", VIEWER)
        if role in ROLES:
            return User(user_id=f"local-{role.lower()}", email=f"{role.lower()}@cloudlog.local", role=role)

    return User(user_id="anonymous", email="anonymous", role=VIEWER)

"""
Authentication and Role-Based Access Control (RBAC) helpers for CloudLog API.
Extracts user identity and role from Cognito JWT claims in API Gateway HTTP API proxy events.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

ROLE_ADMIN = "Admin"
ROLE_ANALYST = "Analyst"
ROLE_VIEWER = "Viewer"

ALL_ROLES = {ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER}
CAN_MODIFY_INCIDENTS = {ROLE_ADMIN, ROLE_ANALYST}


@dataclass
class UserContext:
    """User security context parsed from API Gateway JWT claims."""
    user_id: str
    email: str
    role: str
    groups: List[str]

    @property
    def can_modify_incidents(self) -> bool:
        """Only Admin and Analyst roles may resolve/update incidents."""
        return self.role in CAN_MODIFY_INCIDENTS


def extract_user_context(event: Dict[str, Any]) -> UserContext:
    """
    Extract authenticated user context from API Gateway v2 HTTP event.
    Reads Cognito JWT claims injected by API Gateway's native JWT Authorizer.
    Falls back gracefully for local testing when authorizer is mocked.

    Args:
        event: API Gateway 2.0 proxy event dictionary.

    Returns:
        UserContext dataclass instance with user_id, email, role, and groups.
    """
    req_context = event.get("requestContext", {})
    authorizer = req_context.get("authorizer", {})
    jwt_data = authorizer.get("jwt", {})
    claims = jwt_data.get("claims", {})

    headers = event.get("headers", {}) or {}

    # 1. Read claims from API Gateway JWT authorizer
    if claims:
        user_id = str(claims.get("sub", claims.get("username", "anonymous")))
        email = str(claims.get("email", user_id))

        # cognito:groups can be a list or a string
        raw_groups = claims.get("cognito:groups", [])
        if isinstance(raw_groups, str):
            groups = [g.strip(" []\"'") for g in raw_groups.split(",") if g.strip(" []\"'")]
        elif isinstance(raw_groups, list):
            groups = [str(g) for g in raw_groups]
        else:
            groups = []

        # Determine dominant role
        if ROLE_ADMIN in groups:
            role = ROLE_ADMIN
        elif ROLE_ANALYST in groups:
            role = ROLE_ANALYST
        elif ROLE_VIEWER in groups:
            role = ROLE_VIEWER
        else:
            role = ROLE_VIEWER

        return UserContext(user_id=user_id, email=email, role=role, groups=groups)

    # 2. Local testing / dev fallback header: x-user-role
    override_role = headers.get("x-user-role", headers.get("X-User-Role"))
    if override_role and override_role in ALL_ROLES:
        return UserContext(
            user_id="mock-user-id",
            email=f"{override_role.lower()}@cloudlog.local",
            role=override_role,
            groups=[override_role],
        )

    # 3. Default unauthenticated / viewer fallback
    return UserContext(
        user_id="anonymous",
        email="anonymous@cloudlog.local",
        role=ROLE_VIEWER,
        groups=[ROLE_VIEWER],
    )

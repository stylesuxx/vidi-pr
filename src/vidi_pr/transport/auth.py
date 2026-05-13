from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt


def make_app_jwt(app_id: int, private_key: str, *, ttl_seconds: int = 540) -> str:
    now = datetime.now(UTC)
    payload = {
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        "iss": str(app_id),
    }

    return jwt.encode(payload, private_key, algorithm="RS256")

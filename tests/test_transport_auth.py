from __future__ import annotations

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from vidi_pr.transport.auth import make_app_jwt


def _keypair() -> tuple[str, str]:
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    return private_pem, public_pem


def test_jwt_carries_expected_claims() -> None:
    private_pem, public_pem = _keypair()
    token = make_app_jwt(app_id=12345, private_key=private_pem)
    claims = jwt.decode(token, public_pem, algorithms=["RS256"])

    assert claims["iss"] == "12345"
    assert "iat" in claims
    assert "exp" in claims


def test_jwt_uses_rs256() -> None:
    private_pem, _ = _keypair()
    token = make_app_jwt(app_id=1, private_key=private_pem)
    header = jwt.get_unverified_header(token)

    assert header["alg"] == "RS256"


def test_default_ttl_is_540_seconds() -> None:
    private_pem, public_pem = _keypair()
    token = make_app_jwt(app_id=1, private_key=private_pem)
    claims = jwt.decode(token, public_pem, algorithms=["RS256"])

    assert claims["exp"] - claims["iat"] == 540


def test_custom_ttl_is_respected() -> None:
    private_pem, public_pem = _keypair()
    token = make_app_jwt(app_id=1, private_key=private_pem, ttl_seconds=60)
    claims = jwt.decode(token, public_pem, algorithms=["RS256"])

    assert claims["exp"] - claims["iat"] == 60

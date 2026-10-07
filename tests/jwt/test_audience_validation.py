import time

import jwt
import pytest

from fence.jwt.errors import JWTError
from fence.jwt.validate import validate_jwt


def test_fence_rejects_a_signed_token_for_another_audience(
    rsa_private_key, rsa_public_key
):
    now = int(time.time())
    token = jwt.encode(
        {
            "iss": "https://fence.example.org/user",
            "aud": "unrelated-service",
            "iat": now,
            "exp": now + 300,
        },
        rsa_private_key,
        algorithm="RS256",
    )

    with pytest.raises(JWTError, match="Audience"):
        validate_jwt(
            encoded_token=token,
            aud="gen3",
            scope=None,
            purpose=None,
            require_purpose=False,
            public_key=rsa_public_key,
            issuers=["https://fence.example.org/user"],
        )

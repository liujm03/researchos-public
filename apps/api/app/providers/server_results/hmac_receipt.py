"""A configured key signature is separate from scientific verification."""

import hashlib
import hmac
import re

from pydantic import SecretStr

from app.domain.server_results import ServerReceiptAuthenticationResult


class HMACServerReceiptAuthentication:
    provider_key = "hmac_sha256"

    def __init__(self, *, server_id: str | None = None, key: SecretStr | str | None = None):
        secret = key.get_secret_value() if isinstance(key, SecretStr) else key
        if secret is not None and len(secret.encode("utf-8")) < 32:
            raise ValueError("Server receipt signing key needs at least 32 UTF-8 bytes")
        if server_id is not None and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", server_id) is None:
            raise ValueError("Invalid configured server identity")
        self._server_id = server_id
        self._key = secret.encode("utf-8") if secret is not None else None

    @property
    def configured_server_id(self) -> str | None:
        return self._server_id

    @property
    def configured(self) -> bool:
        return self._key is not None and self._server_id is not None

    def verify(
        self, *, canonical_receipt: bytes, server_id: str | None, signature: str | None
    ) -> ServerReceiptAuthenticationResult:
        if self._key is None or self._server_id is None:
            return ServerReceiptAuthenticationResult(
                "OWNER_UPLOADED_UNVERIFIED", ("SERVER_SIGNATURE_NOT_CONFIGURED",)
            )
        if server_id != self._server_id:
            return ServerReceiptAuthenticationResult(
                "OWNER_UPLOADED_UNVERIFIED", ("SERVER_ID_NOT_CONFIGURED",)
            )
        if signature is None:
            return ServerReceiptAuthenticationResult(
                "OWNER_UPLOADED_UNVERIFIED", ("SERVER_SIGNATURE_MISSING",)
            )
        expected = hmac.new(self._key, canonical_receipt, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return ServerReceiptAuthenticationResult("INVALID_SIGNATURE", ("INVALID_SIGNATURE",))
        return ServerReceiptAuthenticationResult("CONFIGURED_KEY_SIGNATURE", ())

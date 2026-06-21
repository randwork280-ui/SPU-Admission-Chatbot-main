import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Services" / "Data_Loader"))

if "fastapi" not in sys.modules:
    fastapi_stub = types.ModuleType("fastapi")

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi_stub.HTTPException = HTTPException
    fastapi_stub.Header = lambda default=None: default
    fastapi_stub.status = types.SimpleNamespace(
        HTTP_401_UNAUTHORIZED=401,
        HTTP_503_SERVICE_UNAVAILABLE=503,
    )
    sys.modules["fastapi"] = fastapi_stub

if "pydantic" not in sys.modules:
    pydantic_stub = types.ModuleType("pydantic")
    pydantic_stub.BaseModel = object
    sys.modules["pydantic"] = pydantic_stub

import admin_security


class AdminSecurityTests(unittest.TestCase):
    def test_hash_and_verify_password(self):
        password_hash = admin_security.hash_password("strong-password", salt_hex="00" * 16)
        with patch.dict(os.environ, {"ADMIN_PASSWORD_HASH": password_hash}, clear=False):
            self.assertTrue(admin_security.verify_password("strong-password"))
            self.assertFalse(admin_security.verify_password("wrong-password"))

    def test_admin_token_round_trip(self):
        with patch.dict(os.environ, {"ADMIN_TOKEN_SECRET": "unit-test-secret" * 4}, clear=False):
            token = admin_security.create_admin_token(ttl_seconds=60)
            payload = admin_security.verify_admin_token(token)
            self.assertEqual(payload["sub"], "admin")

    def test_expired_admin_token_is_rejected(self):
        with patch.dict(os.environ, {"ADMIN_TOKEN_SECRET": "unit-test-secret" * 4}, clear=False):
            token = admin_security.create_admin_token(ttl_seconds=-1)
            with self.assertRaises(admin_security.HTTPException):
                admin_security.verify_admin_token(token)

    def test_require_admin_rejects_missing_bearer_token(self):
        with self.assertRaises(admin_security.HTTPException):
            admin_security.require_admin(None)


if __name__ == "__main__":
    unittest.main()

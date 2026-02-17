"""Tests for app/mfa.py — TOTP, backup codes, encryption utilities."""
import pytest
import re

from mfa import (
    encrypt_totp_secret,
    decrypt_totp_secret,
    generate_totp_secret,
    get_totp_uri,
    verify_totp,
    generate_qr_code_base64,
    generate_backup_codes,
    hash_backup_code,
    verify_backup_code,
    BACKUP_CODE_COUNT,
    BACKUP_CODE_LENGTH,
)


class TestTOTPSecret:
    def test_generate_returns_base32_string(self):
        secret = generate_totp_secret()
        assert isinstance(secret, str)
        assert len(secret) > 0
        # Base32 chars only
        assert re.match(r'^[A-Z2-7]+=*$', secret)

    def test_generate_produces_unique_secrets(self):
        secrets = {generate_totp_secret() for _ in range(10)}
        assert len(secrets) == 10


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self, db_session):
        secret = generate_totp_secret()
        encrypted = encrypt_totp_secret(secret)
        assert encrypted != secret
        decrypted = decrypt_totp_secret(encrypted)
        assert decrypted == secret

    def test_encrypted_output_is_string(self, db_session):
        encrypted = encrypt_totp_secret("JBSWY3DPEHPK3PXP")
        assert isinstance(encrypted, str)

    def test_different_encryptions_differ(self, db_session):
        """Fernet includes a timestamp, so same plaintext produces different ciphertext."""
        secret = "JBSWY3DPEHPK3PXP"
        e1 = encrypt_totp_secret(secret)
        e2 = encrypt_totp_secret(secret)
        assert e1 != e2
        # Both decrypt to the same value
        assert decrypt_totp_secret(e1) == decrypt_totp_secret(e2) == secret


class TestTOTPVerification:
    def test_verify_current_code(self):
        import pyotp
        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        code = totp.now()
        assert verify_totp(secret, code) is True

    def test_verify_wrong_code(self):
        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False

    def test_verify_non_numeric_code(self):
        secret = generate_totp_secret()
        assert verify_totp(secret, "abcdef") is False


class TestTOTPUri:
    def test_uri_format(self):
        uri = get_totp_uri("JBSWY3DPEHPK3PXP", "testuser")
        assert uri.startswith("otpauth://totp/")
        assert "testuser" in uri
        assert "CloudLab" in uri
        assert "secret=JBSWY3DPEHPK3PXP" in uri

    def test_custom_issuer(self):
        uri = get_totp_uri("JBSWY3DPEHPK3PXP", "testuser", issuer="CustomApp")
        assert "CustomApp" in uri


class TestQRCode:
    def test_generates_base64_png(self):
        import base64
        uri = get_totp_uri("JBSWY3DPEHPK3PXP", "testuser")
        b64 = generate_qr_code_base64(uri)
        assert isinstance(b64, str)
        # Should be valid base64
        raw = base64.b64decode(b64)
        # PNG magic bytes
        assert raw[:4] == b'\x89PNG'


class TestBackupCodes:
    def test_generates_correct_count(self):
        codes = generate_backup_codes()
        assert len(codes) == BACKUP_CODE_COUNT

    def test_codes_are_uppercase_hex(self):
        codes = generate_backup_codes()
        for code in codes:
            assert len(code) == BACKUP_CODE_LENGTH
            assert re.match(r'^[0-9A-F]+$', code)

    def test_codes_are_unique(self):
        codes = generate_backup_codes()
        assert len(set(codes)) == len(codes)


class TestBackupCodeHashing:
    def test_hash_and_verify_roundtrip(self):
        code = "ABCD1234"
        hashed = hash_backup_code(code)
        assert hashed != code
        assert verify_backup_code(code, hashed) is True

    def test_wrong_code_fails(self):
        hashed = hash_backup_code("ABCD1234")
        assert verify_backup_code("WRONG123", hashed) is False

    def test_case_insensitive_verification(self):
        code = "ABCD1234"
        hashed = hash_backup_code(code)
        assert verify_backup_code("abcd1234", hashed) is True
        assert verify_backup_code("Abcd1234", hashed) is True

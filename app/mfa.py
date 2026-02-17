import secrets
import pyotp
import qrcode
import io
import base64
from cryptography.fernet import Fernet
from passlib.context import CryptContext
from auth import get_secret_key

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

BACKUP_CODE_COUNT = 8
BACKUP_CODE_LENGTH = 8  # 8 alphanumeric chars per code


def _get_fernet() -> Fernet:
    """Derive a Fernet key from the app's secret_key (32-byte hex -> 32 bytes -> base64)."""
    secret = get_secret_key()
    # secret_key is 64 hex chars = 32 bytes. Fernet needs 32 bytes base64-encoded.
    key_bytes = bytes.fromhex(secret)[:32]
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_totp_secret(secret: str) -> str:
    """Encrypt a TOTP secret for storage."""
    f = _get_fernet()
    return f.encrypt(secret.encode()).decode()


def decrypt_totp_secret(encrypted: str) -> str:
    """Decrypt a TOTP secret from storage."""
    f = _get_fernet()
    return f.decrypt(encrypted.encode()).decode()


def generate_totp_secret() -> str:
    """Generate a new random TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, username: str, issuer: str = "CloudLab") -> str:
    """Generate the otpauth:// URI for QR code scanning."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def verify_totp(secret: str, code: str) -> bool:
    """Verify a TOTP code against a secret. Allows 1 window of drift."""
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def generate_qr_code_base64(uri: str) -> str:
    """Generate a QR code as a base64-encoded PNG string."""
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def generate_backup_codes() -> list[str]:
    """Generate a set of plaintext backup codes."""
    return [
        secrets.token_hex(BACKUP_CODE_LENGTH // 2).upper()
        for _ in range(BACKUP_CODE_COUNT)
    ]


def hash_backup_code(code: str) -> str:
    """Hash a backup code for storage."""
    return pwd_context.hash(code.upper())


def verify_backup_code(plain: str, hashed: str) -> bool:
    """Verify a backup code against its hash."""
    return pwd_context.verify(plain.upper(), hashed)

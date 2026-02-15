import os
import httpx
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SENDAMATIC_API_URL = "https://send.api.sendamatic.net/send"
SENDAMATIC_API_KEY = os.environ.get("SENDAMATIC_API_KEY", "")
SENDAMATIC_SENDER_EMAIL = os.environ.get("SENDAMATIC_SENDER_EMAIL", "")
SENDAMATIC_SENDER_NAME = os.environ.get("SENDAMATIC_SENDER_NAME", "CloudLab Manager")

SMTP_HOST = os.environ.get("SMTP_HOST", "")
try:
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
except (ValueError, TypeError):
    SMTP_PORT = 587
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_USE_TLS = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"
SMTP_SENDER_EMAIL = os.environ.get("SMTP_SENDER_EMAIL", "")
SMTP_SENDER_NAME = os.environ.get("SMTP_SENDER_NAME", "CloudLab Manager")


def _get_sender():
    if SENDAMATIC_SENDER_NAME:
        return f"{SENDAMATIC_SENDER_NAME} <{SENDAMATIC_SENDER_EMAIL}>"
    return SENDAMATIC_SENDER_EMAIL


def _get_smtp_sender():
    name = SMTP_SENDER_NAME or SENDAMATIC_SENDER_NAME
    email = SMTP_SENDER_EMAIL or SENDAMATIC_SENDER_EMAIL
    if name:
        return f"{name} <{email}>"
    return email


async def _send_email_smtp(to_email: str, subject: str, html_body: str, text_body: str):
    """Send email via SMTP with STARTTLS."""
    sender_email = SMTP_SENDER_EMAIL or SENDAMATIC_SENDER_EMAIL
    if not sender_email:
        print(f"WARN: SMTP sender email not configured. Would send to {to_email}: {subject}")
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = _get_smtp_sender()
    msg["To"] = to_email
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        smtp = aiosmtplib.SMTP(hostname=SMTP_HOST, port=SMTP_PORT, timeout=15.0)
        await smtp.connect()
        if SMTP_USE_TLS:
            await smtp.starttls()
        if SMTP_USERNAME and SMTP_PASSWORD:
            await smtp.login(SMTP_USERNAME, SMTP_PASSWORD)
        await smtp.send_message(msg)
        await smtp.quit()
        print(f"Email sent via SMTP to {to_email}: {subject}")
        return True
    except Exception as e:
        print(f"SMTP send failed to {to_email}: {e}")
        return False


async def _send_email(to_email: str, subject: str, html_body: str, text_body: str):
    """Send email via SMTP if configured, otherwise via Sendamatic API."""
    if SMTP_HOST:
        return await _send_email_smtp(to_email, subject, html_body, text_body)

    if not SENDAMATIC_API_KEY or not SENDAMATIC_SENDER_EMAIL:
        print(f"WARN: Email not configured. Would send to {to_email}: {subject}")
        return False

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(
            SENDAMATIC_API_URL,
            headers={"x-api-key": SENDAMATIC_API_KEY, "Content-Type": "application/json"},
            json={
                "to": [to_email],
                "sender": _get_sender(),
                "subject": subject,
                "html_body": html_body,
                "text_body": text_body,
            },
        )
        if resp.status_code == 200:
            print(f"Email sent to {to_email}: {subject}")
            return True
        else:
            print(f"Email send failed ({resp.status_code}): {resp.text}")
            return False


async def send_invite(to_email: str, invite_token: str, inviter_name: str, base_url: str):
    """Send invite email with link to accept."""
    accept_url = f"{base_url}/#accept-invite-{invite_token}"

    html_body = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #0a0c10; color: #e8edf5; padding: 2rem; border: 1px solid #1e2738; border-radius: 8px;">
        <div style="border-bottom: 2px solid #f0a030; padding-bottom: 1rem; margin-bottom: 1.5rem;">
            <h1 style="margin: 0; font-size: 1.2rem; color: #f0a030; letter-spacing: 0.1em;">CLOUDLAB MANAGER</h1>
        </div>
        <h2 style="margin: 0 0 0.5rem; font-size: 1.1rem; color: #e8edf5;">You've been invited</h2>
        <p style="color: #8899b0; font-size: 0.9rem; line-height: 1.6;">
            <strong>{inviter_name}</strong> has invited you to join CloudLab Manager.
            Click below to set your password and activate your account.
        </p>
        <div style="text-align: center; margin: 1.5rem 0;">
            <a href="{accept_url}" style="display: inline-block; background: #f0a030; color: #0a0c10; font-weight: 700; padding: 0.75rem 2rem; border-radius: 4px; text-decoration: none; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 0.05em;">Accept Invite</a>
        </div>
        <p style="color: #4a5a70; font-size: 0.75rem;">This link expires in 72 hours. If you didn't expect this, ignore this email.</p>
    </div>
    """

    text_body = f"""{inviter_name} has invited you to CloudLab Manager.

Accept your invite: {accept_url}

This link expires in 72 hours."""

    return await _send_email(to_email, "You're invited to CloudLab Manager", html_body, text_body)


async def send_password_reset(to_email: str, reset_token: str, base_url: str):
    """Send password reset email."""
    reset_url = f"{base_url}/#reset-password-{reset_token}"

    html_body = f"""
    <div style="font-family: 'Segoe UI', Arial, sans-serif; max-width: 520px; margin: 0 auto; background: #0a0c10; color: #e8edf5; padding: 2rem; border: 1px solid #1e2738; border-radius: 8px;">
        <div style="border-bottom: 2px solid #f0a030; padding-bottom: 1rem; margin-bottom: 1.5rem;">
            <h1 style="margin: 0; font-size: 1.2rem; color: #f0a030; letter-spacing: 0.1em;">CLOUDLAB MANAGER</h1>
        </div>
        <h2 style="margin: 0 0 0.5rem; font-size: 1.1rem; color: #e8edf5;">Password Reset</h2>
        <p style="color: #8899b0; font-size: 0.9rem; line-height: 1.6;">
            A password reset was requested for your account.
            Click below to set a new password.
        </p>
        <div style="text-align: center; margin: 1.5rem 0;">
            <a href="{reset_url}" style="display: inline-block; background: #f0a030; color: #0a0c10; font-weight: 700; padding: 0.75rem 2rem; border-radius: 4px; text-decoration: none; text-transform: uppercase; font-size: 0.85rem; letter-spacing: 0.05em;">Reset Password</a>
        </div>
        <p style="color: #4a5a70; font-size: 0.75rem;">This link expires in 1 hour. If you didn't request this, ignore this email.</p>
    </div>
    """

    text_body = f"""A password reset was requested for your CloudLab Manager account.

Reset your password: {reset_url}

This link expires in 1 hour. If you didn't request this, ignore this email."""

    return await _send_email(to_email, "CloudLab Manager — Password Reset", html_body, text_body)


def get_email_transport_status():
    """Return the active email transport and whether it is configured."""
    if SMTP_HOST:
        sender = SMTP_SENDER_EMAIL or SENDAMATIC_SENDER_EMAIL
        return {
            "transport": "smtp",
            "configured": bool(sender),
            "host": SMTP_HOST,
            "port": SMTP_PORT,
            "tls": SMTP_USE_TLS,
        }
    configured = bool(SENDAMATIC_API_KEY and SENDAMATIC_SENDER_EMAIL)
    return {"transport": "sendamatic", "configured": configured}

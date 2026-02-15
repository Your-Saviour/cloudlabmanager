"""Tests for app/email_service.py — email sending via Sendamatic API and SMTP."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


class TestGetSender:
    def test_with_name(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_NAME", "CloudLab")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "noreply@example.com")

        result = email_service._get_sender()
        assert result == "CloudLab <noreply@example.com>"

    def test_without_name(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_NAME", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "noreply@example.com")

        result = email_service._get_sender()
        assert result == "noreply@example.com"


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_returns_false_when_not_configured(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "noreply@example.com")

        result = await email_service._send_email("to@example.com", "Subject", "<p>Hi</p>", "Hi")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_sender_not_configured(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "some-key")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "")

        result = await email_service._send_email("to@example.com", "Subject", "<p>Hi</p>", "Hi")
        assert result is False

    @pytest.mark.asyncio
    async def test_sends_email_successfully(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "test-api-key")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "noreply@example.com")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_NAME", "CloudLab")

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_post = AsyncMock(return_value=mock_response)

        with patch("email_service.httpx.AsyncClient") as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = mock_post
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client_instance

            result = await email_service._send_email("to@example.com", "Test", "<p>Hi</p>", "Hi")

        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_api_failure(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "test-api-key")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "noreply@example.com")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_NAME", "CloudLab")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"

        mock_post = AsyncMock(return_value=mock_response)

        with patch("email_service.httpx.AsyncClient") as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = mock_post
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client_instance

            result = await email_service._send_email("to@example.com", "Test", "<p>Hi</p>", "Hi")

        assert result is False


class TestSendInvite:
    @pytest.mark.asyncio
    async def test_constructs_correct_accept_url(self, monkeypatch):
        import email_service

        captured_calls = []

        async def mock_send_email(to_email, subject, html_body, text_body):
            captured_calls.append({
                "to_email": to_email,
                "subject": subject,
                "html_body": html_body,
                "text_body": text_body,
            })
            return True

        monkeypatch.setattr(email_service, "_send_email", mock_send_email)

        await email_service.send_invite("user@example.com", "abc123", "Admin", "https://app.example.com")

        assert len(captured_calls) == 1
        call = captured_calls[0]
        assert "https://app.example.com/#accept-invite-abc123" in call["html_body"]
        assert "https://app.example.com/#accept-invite-abc123" in call["text_body"]

    @pytest.mark.asyncio
    async def test_passes_correct_subject(self, monkeypatch):
        import email_service

        captured_calls = []

        async def mock_send_email(to_email, subject, html_body, text_body):
            captured_calls.append({"subject": subject})
            return True

        monkeypatch.setattr(email_service, "_send_email", mock_send_email)

        await email_service.send_invite("user@example.com", "token", "Admin", "https://app.example.com")

        assert captured_calls[0]["subject"] == "You're invited to CloudLab Manager"


class TestSendPasswordReset:
    @pytest.mark.asyncio
    async def test_constructs_correct_reset_url(self, monkeypatch):
        import email_service

        captured_calls = []

        async def mock_send_email(to_email, subject, html_body, text_body):
            captured_calls.append({
                "html_body": html_body,
                "text_body": text_body,
            })
            return True

        monkeypatch.setattr(email_service, "_send_email", mock_send_email)

        await email_service.send_password_reset("user@example.com", "reset-token-xyz", "https://app.example.com")

        assert len(captured_calls) == 1
        call = captured_calls[0]
        assert "https://app.example.com/#reset-password-reset-token-xyz" in call["html_body"]
        assert "https://app.example.com/#reset-password-reset-token-xyz" in call["text_body"]


class TestGetSmtpSender:
    def test_with_smtp_name_and_email(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_SENDER_NAME", "SMTP Sender")
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "smtp@example.com")

        result = email_service._get_smtp_sender()
        assert result == "SMTP Sender <smtp@example.com>"

    def test_falls_back_to_sendamatic_values(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_SENDER_NAME", "")
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_NAME", "Fallback Name")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "fallback@example.com")

        result = email_service._get_smtp_sender()
        assert result == "Fallback Name <fallback@example.com>"

    def test_email_only_when_no_name(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_SENDER_NAME", "")
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "smtp@example.com")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_NAME", "")

        result = email_service._get_smtp_sender()
        assert result == "smtp@example.com"


class TestSendEmailSmtp:
    @pytest.mark.asyncio
    async def test_returns_false_when_no_sender_email(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "")

        result = await email_service._send_email_smtp("to@example.com", "Subj", "<p>Hi</p>", "Hi")
        assert result is False

    @pytest.mark.asyncio
    async def test_sends_successfully_via_smtp(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(email_service, "SMTP_PORT", 587)
        monkeypatch.setattr(email_service, "SMTP_USERNAME", "user")
        monkeypatch.setattr(email_service, "SMTP_PASSWORD", "pass")
        monkeypatch.setattr(email_service, "SMTP_USE_TLS", True)
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "sender@example.com")
        monkeypatch.setattr(email_service, "SMTP_SENDER_NAME", "Test")

        mock_smtp = AsyncMock()
        with patch("email_service.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await email_service._send_email_smtp("to@example.com", "Test", "<p>Hi</p>", "Hi")

        assert result is True
        mock_smtp.connect.assert_awaited_once()
        mock_smtp.starttls.assert_awaited_once()
        mock_smtp.login.assert_awaited_once_with("user", "pass")
        mock_smtp.send_message.assert_awaited_once()
        mock_smtp.quit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_tls_when_disabled(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(email_service, "SMTP_PORT", 25)
        monkeypatch.setattr(email_service, "SMTP_USERNAME", "")
        monkeypatch.setattr(email_service, "SMTP_PASSWORD", "")
        monkeypatch.setattr(email_service, "SMTP_USE_TLS", False)
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "sender@example.com")
        monkeypatch.setattr(email_service, "SMTP_SENDER_NAME", "")

        mock_smtp = AsyncMock()
        with patch("email_service.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await email_service._send_email_smtp("to@example.com", "Test", "<p>Hi</p>", "Hi")

        assert result is True
        mock_smtp.starttls.assert_not_awaited()
        mock_smtp.login.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_false_on_smtp_error(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(email_service, "SMTP_PORT", 587)
        monkeypatch.setattr(email_service, "SMTP_USE_TLS", True)
        monkeypatch.setattr(email_service, "SMTP_USERNAME", "")
        monkeypatch.setattr(email_service, "SMTP_PASSWORD", "")
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "sender@example.com")
        monkeypatch.setattr(email_service, "SMTP_SENDER_NAME", "Test")

        mock_smtp = AsyncMock()
        mock_smtp.connect.side_effect = Exception("Connection refused")
        with patch("email_service.aiosmtplib.SMTP", return_value=mock_smtp):
            result = await email_service._send_email_smtp("to@example.com", "Test", "<p>Hi</p>", "Hi")

        assert result is False


class TestSendEmailRouting:
    @pytest.mark.asyncio
    async def test_routes_to_smtp_when_host_set(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")

        with patch("email_service._send_email_smtp", new_callable=AsyncMock, return_value=True) as mock_smtp:
            result = await email_service._send_email("to@example.com", "Test", "<p>Hi</p>", "Hi")

        assert result is True
        mock_smtp.assert_awaited_once_with("to@example.com", "Test", "<p>Hi</p>", "Hi")

    @pytest.mark.asyncio
    async def test_falls_back_to_sendamatic_when_no_smtp(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "key")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "sender@example.com")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_NAME", "Test")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("email_service.httpx.AsyncClient") as mock_client_class:
            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock(return_value=False)
            mock_client_class.return_value = mock_client_instance

            result = await email_service._send_email("to@example.com", "Test", "<p>Hi</p>", "Hi")

        assert result is True


class TestGetEmailTransportStatus:
    def test_smtp_configured(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(email_service, "SMTP_PORT", 465)
        monkeypatch.setattr(email_service, "SMTP_USE_TLS", True)
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "sender@example.com")

        status = email_service.get_email_transport_status()
        assert status["transport"] == "smtp"
        assert status["configured"] is True
        assert status["host"] == "smtp.example.com"
        assert status["port"] == 465
        assert status["tls"] is True

    def test_smtp_not_configured_no_sender(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(email_service, "SMTP_PORT", 587)
        monkeypatch.setattr(email_service, "SMTP_USE_TLS", True)
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "")

        status = email_service.get_email_transport_status()
        assert status["transport"] == "smtp"
        assert status["configured"] is False

    def test_smtp_falls_back_to_sendamatic_sender(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "smtp.example.com")
        monkeypatch.setattr(email_service, "SMTP_PORT", 587)
        monkeypatch.setattr(email_service, "SMTP_USE_TLS", False)
        monkeypatch.setattr(email_service, "SMTP_SENDER_EMAIL", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "fallback@example.com")

        status = email_service.get_email_transport_status()
        assert status["transport"] == "smtp"
        assert status["configured"] is True

    def test_sendamatic_configured(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "key")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "sender@example.com")

        status = email_service.get_email_transport_status()
        assert status["transport"] == "sendamatic"
        assert status["configured"] is True
        assert "host" not in status

    def test_sendamatic_not_configured(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SMTP_HOST", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "")

        status = email_service.get_email_transport_status()
        assert status["transport"] == "sendamatic"
        assert status["configured"] is False

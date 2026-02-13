"""Tests for app/email_service.py — email sending via Sendamatic API."""
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
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "noreply@example.com")

        result = await email_service._send_email("to@example.com", "Subject", "<p>Hi</p>", "Hi")
        assert result is False

    @pytest.mark.asyncio
    async def test_returns_false_when_sender_not_configured(self, monkeypatch):
        import email_service
        monkeypatch.setattr(email_service, "SENDAMATIC_API_KEY", "some-key")
        monkeypatch.setattr(email_service, "SENDAMATIC_SENDER_EMAIL", "")

        result = await email_service._send_email("to@example.com", "Subject", "<p>Hi</p>", "Hi")
        assert result is False

    @pytest.mark.asyncio
    async def test_sends_email_successfully(self, monkeypatch):
        import email_service
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

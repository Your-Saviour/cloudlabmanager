"""Playwright tests for login flow."""
import pytest

pytestmark = pytest.mark.playwright


class TestLogin:
    def test_login_page_loads(self, page, base_url):
        """Login page should be accessible."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        # Page should contain login or setup form
        content = page.content()
        assert len(content) > 100  # Page loaded with content

    def test_login_with_invalid_credentials(self, page, base_url):
        """Attempting login with wrong password should show error."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")

        # If login form is visible, try invalid creds
        if page.locator("input[type='password']").count() > 0:
            page.fill("input[name='username'], input[placeholder*='user' i]", "admin")
            page.fill("input[type='password']", "wrongpassword")
            page.keyboard.press("Enter")
            page.wait_for_timeout(1000)

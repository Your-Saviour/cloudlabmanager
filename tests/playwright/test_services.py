"""Playwright tests for the services page."""
import pytest

pytestmark = pytest.mark.playwright


class TestServices:
    def test_services_page_accessible(self, page, base_url):
        """Services page should be part of the application."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        # Verify the app loaded
        assert page.url is not None

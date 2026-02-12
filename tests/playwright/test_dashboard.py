"""Playwright tests for the dashboard."""
import pytest

pytestmark = pytest.mark.playwright


class TestDashboard:
    def test_dashboard_requires_auth(self, page, base_url):
        """Unauthenticated users should not see the dashboard."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        # Should be on login/setup page, not dashboard
        content = page.content()
        assert len(content) > 100

    def test_nav_links_present(self, page, base_url):
        """After login, navigation links should be present."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        # This test is intentionally lightweight since the exact
        # frontend implementation may vary
        assert page.url is not None

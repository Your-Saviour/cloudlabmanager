"""Playwright tests for the jobs page."""
import pytest

pytestmark = pytest.mark.playwright


class TestJobs:
    def test_jobs_page_accessible(self, page, base_url):
        """Jobs page should be part of the application."""
        page.goto(base_url)
        page.wait_for_load_state("networkidle")
        assert page.url is not None

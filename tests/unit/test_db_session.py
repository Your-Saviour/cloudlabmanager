"""Tests for app/db_session.py — get_db_session() dependency generator."""
import pytest
from unittest.mock import MagicMock, patch


class TestGetDbSession:
    def test_yields_session(self):
        mock_session = MagicMock()
        with patch("db_session.SessionLocal", return_value=mock_session):
            from db_session import get_db_session
            gen = get_db_session()
            session = next(gen)
            assert session is mock_session
            # Clean up the generator
            try:
                next(gen)
            except StopIteration:
                pass

    def test_commits_on_success(self):
        mock_session = MagicMock()
        with patch("db_session.SessionLocal", return_value=mock_session):
            from db_session import get_db_session
            gen = get_db_session()
            next(gen)
            # Exhaust the generator (no exception raised)
            try:
                next(gen)
            except StopIteration:
                pass

            mock_session.commit.assert_called_once()
            mock_session.rollback.assert_not_called()
            mock_session.close.assert_called_once()

    def test_rollbacks_on_error(self):
        mock_session = MagicMock()
        with patch("db_session.SessionLocal", return_value=mock_session):
            from db_session import get_db_session
            gen = get_db_session()
            next(gen)
            # Throw an exception into the generator
            with pytest.raises(ValueError):
                gen.throw(ValueError("test error"))

            mock_session.rollback.assert_called_once()
            mock_session.commit.assert_not_called()
            mock_session.close.assert_called_once()

"""Tests for app/dns.py — Cloudflare DNS integration."""
import pytest
from unittest.mock import patch, MagicMock


class TestDns:
    @patch("dns.Cloudflare")
    def test_get_all_zones_returns_dict(self, mock_cf_class):
        mock_client = MagicMock()
        mock_cf_class.return_value = mock_client

        zone1 = MagicMock()
        zone1.name = "example.com"
        zone1.id = "zone-id-1"
        zone2 = MagicMock()
        zone2.name = "example.org"
        zone2.id = "zone-id-2"

        mock_page = MagicMock()
        mock_page.result = [zone1, zone2]
        mock_client.zones.list.return_value = mock_page

        from dns import main as DnsMain
        dns_instance = DnsMain()

        result = dns_instance.get_all_zones()

        assert result == {"example.com": "zone-id-1", "example.org": "zone-id-2"}
        mock_client.zones.list.assert_called_once()

    @patch("dns.Cloudflare")
    def test_get_zone_information(self, mock_cf_class):
        mock_client = MagicMock()
        mock_cf_class.return_value = mock_client

        mock_zone = MagicMock()
        mock_zone.result = {"id": "zone-id-1", "name": "example.com", "status": "active"}
        mock_client.zones.get.return_value = mock_zone

        from dns import main as DnsMain
        dns_instance = DnsMain()

        result = dns_instance.get_zone_information("zone-id-1")

        assert result == {"id": "zone-id-1", "name": "example.com", "status": "active"}
        mock_client.zones.get.assert_called_once_with(zone_id="zone-id-1")

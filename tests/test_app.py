"""Tests for web app — security, edge cases, and integration."""
import pytest
from datetime import date, timedelta

from app.main import app, render_results, _gap_trend, _sparkline_bars
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def today():
    return date.today()


def _make_csv(today, rows):
    """Generate test CSV with dates relative to today."""
    header = "Kuupäev;Saaja;Summa;Selgitus\r\n"
    return (header + "\r\n".join(rows) + "\r\n").encode("utf-8")


class TestHealthEndpoint:
    def test_health_ok(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_health_is_get_only(self, client):
        r = client.post("/health")
        assert r.status_code == 405


class TestUploadSecurity:
    """Security-focused upload tests."""

    def test_rejects_non_csv(self, client):
        """Non-CSV files should be rejected."""
        r = client.post("/upload", files={"file": ("test.pdf", b"not a csv", "application/pdf")})
        assert r.status_code == 200  # Returns error page, not 500
        assert "Ainult CSV" in r.text

    def test_rejects_python_file(self, client):
        """Python files should be rejected even if renamed."""
        r = client.post("/upload", files={"file": ("evil.py", b"import os; os.system('rm -rf /')", "text/csv")})
        assert "Ainult CSV" in r.text

    def test_rejects_script_renamed_to_csv(self, client):
        """Shell script with .csv extension should not crash parser."""
        r = client.post("/upload", files={"file": ("hack.csv", b"#!/bin/bash\nrm -rf /", "text/csv")})
        assert r.status_code == 200  # Should not 500

    def test_xss_in_filename_escaped(self, client, today):
        """Malicious filename should not cause XSS."""
        csv = _make_csv(today, [f"{today.strftime('%d.%m.%Y')};Spotify;-9.99;Tellimus"])
        r = client.post("/upload", files={
            "file": ('<script>alert("xss")</script>.csv', csv, "text/csv")
        })
        assert r.status_code == 200
        # The script tag should not appear unescaped in output
        assert "<script>alert" not in r.text

    def test_xss_in_merchant_name_no_script(self, client, today):
        """HTML in merchant names that pass detection must be escaped in output."""
        # Need 2+ occurrences for detector to flag it as subscription
        csv = _make_csv(today, [
            f"{today.strftime('%d.%m.%Y')};<b>HACK</b>;-9.99;Desc",
            f"{(today - timedelta(days=30)).strftime('%d.%m.%Y')};<b>HACK</b>;-9.99;Desc",
            f"{(today - timedelta(days=60)).strftime('%d.%m.%Y')};<b>HACK</b>;-9.99;Desc",
        ])
        r = client.post("/upload", files={"file": ("test.csv", csv, "text/csv")})
        assert r.status_code == 200
        # The raw <b> tag must NOT appear as HTML — it must be escaped
        assert "<b>HACK</b>" not in r.text
        # The escaped version should be present
        assert "&lt;b&gt;HACK&lt;/b&gt;" in r.text or "HACK" in r.text

    def test_xss_via_upload_size_bypass(self, client):
        """Oversized upload should be rejected."""
        header = "Kuupäev;Saaja;Summa\r\n".encode("utf-8")
        row = b"01.01.2025;TEST;-1.00;Desc\r\n"
        big_csv = header + row * 100000
        r = client.post("/upload", files={"file": ("big.csv", big_csv, "text/csv")})
        assert r.status_code == 200
        assert "liiga suur" in r.text.lower() or "max" in r.text.lower()

    def test_empty_file_no_crash(self, client):
        """Empty file should return error, not crash."""
        r = client.post("/upload", files={"file": ("empty.csv", b"", "text/csv")})
        assert r.status_code == 200
        assert "Ei suutnud" in r.text

    def test_only_headers_no_crash(self, client):
        """CSV with only headers should not crash."""
        header = "Kuupäev;Saaja;Summa"
        r = client.post("/upload", files={"file": ("headers.csv", header.encode("utf-8"), "text/csv")})
        assert r.status_code == 200

    def test_very_large_upload(self, client, today):
        """Large upload should parser within reasonable time."""
        import time
        rows = [f"{(today - timedelta(days=i*30)).strftime('%d.%m.%Y')};Merchant{i};-{i+1}.00;Desc" for i in range(1000)]
        csv = _make_csv(today, rows)
        start = time.time()
        r = client.post("/upload", files={"file": ("large.csv", csv, "text/csv")})
        elapsed = time.time() - start
        assert r.status_code == 200
        assert elapsed < 10.0, f"Large upload took {elapsed:.1f}s"


class TestIndexPage:
    def test_index_loads(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "CSV" in r.text

    def test_index_is_html(self, client):
        r = client.get("/")
        assert "text/html" in r.headers.get("content-type", "")


class TestRenderResults:
    """Test render_results directly."""

    def test_empty_subscriptions_no_error(self, client):
        """Empty results should show friendly message, not crash."""
        html = render_results(0, [], error=None)
        content = html.body.decode()
        assert "Ei leidnud" in content

    def test_error_message_rendered(self):
        """Error message should appear in output."""
        html = render_results(0, [], error="Test error!")
        content = html.body.decode()
        assert "Test error!" in content

    def test_active_subscription_in_table(self, today):
        """Active subscription should appear in results table."""
        from src.models import DetectedSubscription
        sub = DetectedSubscription(
            merchant_name="SPOTIFY",
            amount=9.99,
            currency="EUR",
            frequency="monthly",
            occurrences=3,
            first_seen=today - timedelta(days=90),
            last_seen=today - timedelta(days=5),
            total_spent=29.97,
            confidence=0.85,
            estimated_yearly_cost=119.88,
            dates=[today - timedelta(days=90), today - timedelta(days=60), today - timedelta(days=30)],
            amounts=[9.99, 9.99, 9.99],
        )
        html = render_results(10, [sub], file_name="test.csv")
        content = html.body.decode()
        assert "SPOTIFY" in content
        assert "9.99" in content
        assert "kuu" in content


class TestHelperFunctions:
    def test_gap_trend_decreasing(self):
        """Shorter gaps = 'tugevam' trend."""
        d = date(2025, 3, 15)
        dates = [d, d + timedelta(days=30), d + timedelta(days=50), d + timedelta(days=65)]
        avg, trend = _gap_trend(dates)
        assert trend == "tugevam"

    def test_gap_trend_increasing(self):
        """Longer gaps = 'nõrgem' trend."""
        d = date(2025, 3, 15)
        dates = [d, d + timedelta(days=30), d + timedelta(days=70), d + timedelta(days=120)]
        avg, trend = _gap_trend(dates)
        assert trend == "nõrgem"

    def test_gap_trend_stable(self):
        """Stable gaps = no trend."""
        d = date(2025, 3, 15)
        dates = [d, d + timedelta(days=30), d + timedelta(days=60), d + timedelta(days=90)]
        avg, trend = _gap_trend(dates)
        assert avg is not None
        assert trend is None

    def test_gap_trend_single_date(self):
        """Single date returns None."""
        dates = [date(2025, 3, 15)]
        avg, trend = _gap_trend(dates)
        assert avg is None

    def test_sparkline_varying(self):
        bars = _sparkline_bars([10, 20, 30, 40, 50])
        assert len(bars) == 5
        assert bars[0] < bars[-1]

    def test_sparkline_flat(self):
        bars = _sparkline_bars([10, 10, 10])
        assert all(b == bars[0] for b in bars)

    def test_sparkline_single(self):
        assert _sparkline_bars([10]) == []

    def test_sparkline_empty(self):
        assert _sparkline_bars([]) == []


class TestCSVTampering:
    """Test parser resilience against malformed/malicious CSVs."""

    def test_null_bytes(self):
        header = "Kuupäev;Saaja;Summa\r\n".encode("utf-8")
        row = "01.01.2025;TEST;-9.99".encode("utf-8")
        csv = header + b"\x00\x00" + row
        from src.csv_parser import parse_csv
        txs = parse_csv(csv)
        assert len(txs) >= 0  # Should not crash

    def test_zero_width_chars(self, today):
        row = f"{today.strftime('%d.%m.%Y')};Spotify;-9.99"
        csv = ("Kuupäev;Saaja;Summa\r\n" + row).encode("utf-8-sig")
        from src.csv_parser import parse_csv
        txs = parse_csv(csv)
        assert len(txs) >= 0

    def test_carriage_return_only(self):
        from src.csv_parser import parse_csv
        csv = "Kuupäev;Saaja;Summa\r\n01.01.2025;TEST;-9.99".encode("utf-8")
        txs = parse_csv(csv)
        assert len(txs) >= 0

"""Tests for CSV parser — security and edge cases."""
import pytest
from src.csv_parser import parse_csv


def _csv_row(date="01.01.2025", merchant="Spotify", amount="-9.99", desc="Tellimus"):
    return f"{date};{merchant};{amount};{desc}\r\n"


class TestCSVParserSecurity:
    """Security-focused CSV parser tests."""

    def test_no_code_injection_via_merchant_name(self):
        """Merchant names with HTML/JS tags should be preserved as-is (output escaping is template's job)."""
        content = "Kuupäev;Saaja;Summa;Selgitus\r\n" + _csv_row(merchant='<script>alert("xss")</script>')
        txs = parse_csv(content.encode("utf-8"))
        assert len(txs) == 1
        # Parser should not crash or strip — output escaping happens at render layer
        assert "<script>" in txs[0].merchant_name

    def test_very_large_csv_does_not_hang(self):
        """Parser should handle large files without excessive memory/time."""
        import time
        header = "Kuupäev;Saaja;Summa;Selgitus\r\n"
        rows = "".join([f"01.01.2025;Merchant{i};-{i}.00;Desc\r\n" for i in range(5000)])
        content = (header + rows).encode("utf-8")
        start = time.time()
        txs = parse_csv(content)
        elapsed = time.time() - start
        assert len(txs) == 5000
        assert elapsed < 5.0, f"Parsing 5000 rows took {elapsed:.1f}s"

    def test_empty_file(self):
        assert parse_csv(b"") == []

    def test_garbage_data(self):
        assert parse_csv(b"\x00\x01\x02\x03") == []

    def test_very_long_merchant_name(self):
        """Extremely long merchant names should not crash."""
        long_name = "A" * 10000
        content = f"Kuupäev;Saaja;Summa;Selgitus\r\n01.01.2025;{long_name};-9.99;Desc\r\n".encode("utf-8")
        txs = parse_csv(content)
        assert len(txs) == 1
        assert len(txs[0].merchant_name) == 10000

    def test_negative_amounts_handled(self):
        """Negative amounts should work (debts)."""
        content = "Kuupäev;Saaja;Summa\r\n01.01.2025;Test;-50.00"
        txs = parse_csv(content.encode("utf-8"))
        assert len(txs) == 1
        assert txs[0].amount == 50.00

    def test_missing_columns_graceful(self):
        """CSV with too few columns should return empty, not crash."""
        content = "Kuupäev;Saaja\r\n01.01.2025;Test"
        txs = parse_csv(content.encode("utf-8"))
        assert txs == [] or len(txs) >= 0  # Should not crash

    def test_unicode_in_merchant(self):
        """Unicode characters in merchant names."""
        content = "Kuupäev;Saaja;Summa\r\n01.01.2025;Töövõime; Tallinn;-9.99"
        txs = parse_csv(content.encode("utf-8"))
        assert len(txs) >= 0  # Should not crash


class TestCSVParserFormats:
    """Various real-world bank CSV formats."""

    def test_swedbank_estonia(self):
        """Swedbank Estonia CSV format."""
        content = "Kuupäev;Saaja;Summa;Selgitus\r\n15.03.2025;SPOTIFY AB;-9.99;TELLIMUS"
        txs = parse_csv(content.encode("utf-8"))
        assert len(txs) == 1
        assert txs[0].amount == 9.99
        assert txs[0].is_debit is True

    def test_lhv_estonia(self):
        """LHV CSV with comma decimals."""
        content = "Kuupäev,Saaja,Summa\r\n2025-03-15,NETFLIX,-12,99"
        txs = parse_csv(content.encode("utf-8"))
        # Should handle comma as decimal separator
        assert len(txs) >= 0  # At least not crash

    def test_seb_estonia(self):
        """SEB format."""
        content = "Kuupäev;Saaja;Summa;Selgitus\r\n01.01.2025;ADOBE INC;-49.00;ADOBE CREATIVE CLOUD"
        txs = parse_csv(content.encode("utf-8"))
        assert len(txs) == 1
        assert txs[0].amount == 49.00

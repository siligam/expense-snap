"""Tests for ocr_reader pure functions (no model loading)."""
import pytest
from bill_extractor.ocr_reader import (
    _fix_rupee_symbol_misread,
    _is_noise,
    filter_noise,
    correct_ocr_errors,
    cluster_lines,
    getlines,
)


# ---------------------------------------------------------------------------
# _fix_rupee_symbol_misread
# ---------------------------------------------------------------------------

class TestFixRupeeSymbolMisread:
    # --- should fix ---
    def test_rupee_at_start_of_plain_integer(self):
        assert _fix_rupee_symbol_misread("7500") == "₹500"

    def test_rupee_at_start_of_decimal(self):
        assert _fix_rupee_symbol_misread("7655.00") == "₹655.00"

    def test_rupee_after_label(self):
        assert _fix_rupee_symbol_misread("Total 7500") == "Total ₹500"

    def test_rupee_with_comma_thousands(self):
        assert _fix_rupee_symbol_misread("Grand Total 71,234.50") == "Grand Total ₹1,234.50"

    def test_rupee_misread_as_1_space(self):
        """Regression: '1 226.00' after a label colon must become '₹226.00'."""
        assert _fix_rupee_symbol_misread("Total Payable: 1 226.00") == "Total Payable: ₹226.00"

    # --- should NOT corrupt ---
    def test_270_not_corrupted(self):
        """Regression: 270.02 must not become ₹0.02."""
        assert _fix_rupee_symbol_misread("270.02") == "270.02"

    def test_270_integer_not_corrupted(self):
        assert _fix_rupee_symbol_misread("270.00") == "270.00"

    def test_270_single_decimal_not_corrupted(self):
        assert _fix_rupee_symbol_misread("270.0") == "270.0"

    def test_270_no_decimal_not_corrupted(self):
        assert _fix_rupee_symbol_misread("270") == "270"

    def test_small_price_74_not_corrupted(self):
        """Regression: 74.00 must not become ₹4.00."""
        assert _fix_rupee_symbol_misread("74.00") == "74.00"

    def test_small_price_76_not_corrupted(self):
        """Regression: 76.00 must not become ₹6.00."""
        assert _fix_rupee_symbol_misread("76.00") == "76.00"

    def test_decimal_digit_7_not_corrupted(self):
        """Regression: 10.76 must not become 10.₹6."""
        assert _fix_rupee_symbol_misread("10.76") == "10.76"

    def test_amount_with_7_in_middle_not_corrupted(self):
        assert _fix_rupee_symbol_misread("257.16") == "257.16"

    def test_amount_with_7_in_decimal_not_corrupted(self):
        assert _fix_rupee_symbol_misread("114.29") == "114.29"

    def test_total_amt_label_preserved(self):
        assert _fix_rupee_symbol_misread("TOTAL AMT: 270.00") == "TOTAL AMT: 270.00"

    def test_gross_amt_label_preserved(self):
        assert _fix_rupee_symbol_misread("GROSS AMT: 270.02") == "GROSS AMT: 270.02"

    def test_net_amt_label_preserved(self):
        assert _fix_rupee_symbol_misread("NET AMT: 257.16") == "NET AMT: 257.16"

    def test_item_price_with_7_preserved(self):
        assert _fix_rupee_symbol_misread("14.29 2.0 28.58") == "14.29 2.0 28.58"


# ---------------------------------------------------------------------------
# _is_noise / filter_noise
# ---------------------------------------------------------------------------

class TestIsNoise:
    def test_empty_string_is_noise(self):
        assert _is_noise("") is True

    def test_whitespace_only_is_noise(self):
        assert _is_noise("   ") is True

    def test_bare_gstin_is_noise(self):
        assert _is_noise("27AAKCN6710H1ZC") is True

    def test_gstin_with_label_is_noise(self):
        assert _is_noise("GSTIN: 27AAKCN6710H1ZC") is True

    def test_fssai_is_noise(self):
        assert _is_noise("FSSAI No. 1234567890") is True

    def test_phone_number_is_noise(self):
        assert _is_noise("+91 98765 43210") is True

    def test_url_is_noise(self):
        assert _is_noise("https://example.com/receipt") is True

    def test_email_is_noise(self):
        assert _is_noise("billing@restaurant.com") is True

    def test_thank_you_is_noise(self):
        assert _is_noise("Thank You Visit Again") is True

    def test_powered_by_is_noise(self):
        assert _is_noise("Powered by BillSoft") is True

    def test_useful_amount_line_not_noise(self):
        assert _is_noise("TOTAL AMT: 270.00") is False

    def test_useful_item_line_not_noise(self):
        assert _is_noise("Mushroom Biryani 220.00") is False

    def test_date_line_not_noise(self):
        assert _is_noise("DATE: 28-FEB-2026") is False


class TestFilterNoise:
    def test_removes_noise_keeps_useful(self):
        lines = [
            "Cafe Niloufer Airport",
            "27AAKCN6710H1ZC",           # noise: bare GSTIN
            "TOTAL AMT: 270.00",
            "https://example.com",        # noise: URL
            "NET AMT: 257.16",
        ]
        result = filter_noise(lines)
        assert result == ["Cafe Niloufer Airport", "TOTAL AMT: 270.00", "NET AMT: 257.16"]

    def test_empty_list(self):
        assert filter_noise([]) == []

    def test_all_noise(self):
        assert filter_noise(["", "   ", "https://x.com"]) == []


# ---------------------------------------------------------------------------
# correct_ocr_errors
# ---------------------------------------------------------------------------

class TestCorrectOcrErrors:
    def test_fixes_rupee_in_lines(self):
        lines = ["Grand Total 7500", "Items 3"]
        result = correct_ocr_errors(lines)
        assert result[0] == "Grand Total ₹500"
        assert result[1] == "Items 3"

    def test_preserves_270_amounts(self):
        lines = ["GROSS AMT: 270.02", "TOTAL AMT: 270.00"]
        result = correct_ocr_errors(lines)
        assert result == ["GROSS AMT: 270.02", "TOTAL AMT: 270.00"]


# ---------------------------------------------------------------------------
# cluster_lines / getlines
# ---------------------------------------------------------------------------

class TestClusterLines:
    def _word(self, text, x, y):
        return {"text": text, "x": x, "y": y, "x_min": x - 0.02}

    def test_single_line(self):
        words = [self._word("Hello", 0.1, 0.1), self._word("World", 0.3, 0.1)]
        lines = cluster_lines(words)
        assert len(lines) == 1
        assert getlines(lines) == ["Hello World"]

    def test_two_lines(self):
        words = [
            self._word("Line1", 0.1, 0.1),
            self._word("Line2", 0.1, 0.5),
        ]
        lines = cluster_lines(words)
        assert len(lines) == 2

    def test_words_sorted_left_to_right_within_line(self):
        words = [
            self._word("B", 0.5, 0.1),
            self._word("A", 0.1, 0.1),
        ]
        lines = cluster_lines(words)
        assert getlines(lines) == ["A B"]

    def test_empty_words(self):
        assert cluster_lines([]) == []

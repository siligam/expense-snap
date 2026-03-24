"""Tests for bill_parser pure helper functions (no model loading)."""
import pytest
from bill_extractor.bill_parser import (
    _extract_number_string,
    _normalize_time,
    _normalize_date,
    _infer_meal_type_from_time,
    _compute_stay_duration_days,
    _extract_first_json_object,
    _safe_json_loads,
    _join_bill_text,
)


# ---------------------------------------------------------------------------
# _extract_number_string
# ---------------------------------------------------------------------------

class TestExtractNumberString:
    def test_plain_float(self):
        assert _extract_number_string("270.00") == "270.00"

    def test_plain_integer(self):
        assert _extract_number_string("500") == "500.00"

    def test_with_comma_thousands(self):
        assert _extract_number_string("1,234.50") == "1234.50"

    def test_numeric_int(self):
        assert _extract_number_string(500) == "500.00"

    def test_numeric_float(self):
        assert _extract_number_string(270.02) == "270.02"

    def test_none_returns_none(self):
        assert _extract_number_string(None) is None

    def test_empty_string_returns_none(self):
        assert _extract_number_string("") is None

    def test_no_digits_returns_none(self):
        assert _extract_number_string("N/A") is None

    def test_embedded_in_text(self):
        assert _extract_number_string("Total: 270.00 INR") == "270.00"

    def test_rupee_prefixed(self):
        assert _extract_number_string("₹270.00") == "270.00"


# ---------------------------------------------------------------------------
# _normalize_time
# ---------------------------------------------------------------------------

class TestNormalizeTime:
    def test_already_24h(self):
        assert _normalize_time("19:11") == "19:11"

    def test_single_digit_hour(self):
        assert _normalize_time("7:30") == "07:30"

    def test_pm_conversion(self):
        assert _normalize_time("7:11PM") == "19:11"

    def test_am_no_change(self):
        assert _normalize_time("7:11AM") == "07:11"

    def test_12pm_is_noon(self):
        assert _normalize_time("12:00PM") == "12:00"

    def test_12am_is_midnight(self):
        assert _normalize_time("12:00AM") == "00:00"

    def test_none_returns_none(self):
        assert _normalize_time(None) is None

    def test_empty_returns_none(self):
        assert _normalize_time("") is None

    def test_embedded_time_extracted(self):
        assert _normalize_time("TIME:07:11 PM") == "07:11"


# ---------------------------------------------------------------------------
# _normalize_date
# ---------------------------------------------------------------------------

class TestNormalizeDate:
    def test_dd_mm_yyyy(self):
        assert _normalize_date("28/02/2026") == "28/02/2026"

    def test_zero_pads(self):
        assert _normalize_date("1/2/2026") == "01/02/2026"

    def test_2digit_year(self):
        assert _normalize_date("24/02/26") == "24/02/2026"

    def test_dd_mon_yyyy(self):
        assert _normalize_date("28 Feb 2026") == "28/02/2026"

    def test_dd_mon_no_year(self):
        assert _normalize_date("27 Feb") == "27/02"

    def test_none_returns_none(self):
        assert _normalize_date(None) is None

    def test_empty_returns_none(self):
        assert _normalize_date("") is None


# ---------------------------------------------------------------------------
# _infer_meal_type_from_time
# ---------------------------------------------------------------------------

class TestInferMealType:
    def test_breakfast(self):
        assert _infer_meal_type_from_time("07:11") == "breakfast"

    def test_breakfast_boundary_start(self):
        assert _infer_meal_type_from_time("05:00") == "breakfast"

    def test_breakfast_boundary_end(self):
        assert _infer_meal_type_from_time("10:59") == "breakfast"

    def test_lunch(self):
        assert _infer_meal_type_from_time("13:00") == "lunch"

    def test_lunch_boundary_start(self):
        assert _infer_meal_type_from_time("11:00") == "lunch"

    def test_lunch_boundary_end(self):
        assert _infer_meal_type_from_time("15:59") == "lunch"

    def test_dinner(self):
        assert _infer_meal_type_from_time("19:11") == "dinner"

    def test_dinner_boundary_start(self):
        assert _infer_meal_type_from_time("18:00") == "dinner"

    def test_dinner_boundary_end(self):
        assert _infer_meal_type_from_time("23:59") == "dinner"

    def test_late_night_unknown(self):
        assert _infer_meal_type_from_time("02:00") == "unknown"

    def test_none_returns_unknown(self):
        assert _infer_meal_type_from_time(None) == "unknown"

    def test_invalid_format_returns_unknown(self):
        assert _infer_meal_type_from_time("7pm") == "unknown"


# ---------------------------------------------------------------------------
# _compute_stay_duration_days
# ---------------------------------------------------------------------------

class TestComputeStayDurationDays:
    def test_5_day_stay(self):
        assert _compute_stay_duration_days("23/02/2026", "28/02/2026") == 5

    def test_1_day_stay(self):
        assert _compute_stay_duration_days("01/03/2026", "02/03/2026") == 1

    def test_none_check_in(self):
        assert _compute_stay_duration_days(None, "28/02/2026") is None

    def test_none_check_out(self):
        assert _compute_stay_duration_days("23/02/2026", None) is None

    def test_both_none(self):
        assert _compute_stay_duration_days(None, None) is None


# ---------------------------------------------------------------------------
# _extract_first_json_object / _safe_json_loads
# ---------------------------------------------------------------------------

class TestExtractFirstJsonObject:
    def test_bare_json(self):
        assert _extract_first_json_object('{"a": 1}') == '{"a": 1}'

    def test_wrapped_in_markdown(self):
        raw = '```json\n{"a": 1}\n```'
        assert _extract_first_json_object(raw) == '{"a": 1}'

    def test_json_with_surrounding_text(self):
        raw = 'Here is the result: {"a": 1} done.'
        assert _extract_first_json_object(raw) == '{"a": 1}'

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            _extract_first_json_object("no json here")


class TestSafeJsonLoads:
    def test_parses_dict(self):
        assert _safe_json_loads('{"category": "food"}') == {"category": "food"}

    def test_parses_from_markdown(self):
        raw = '```json\n{"total_amount": "270.00"}\n```'
        assert _safe_json_loads(raw) == {"total_amount": "270.00"}


# ---------------------------------------------------------------------------
# _join_bill_text
# ---------------------------------------------------------------------------

class TestJoinBillText:
    def test_list_of_lines(self):
        result = _join_bill_text(["Line 1", "Line 2", "Line 3"])
        assert result == "Line 1\nLine 2\nLine 3"

    def test_string_passthrough(self):
        assert _join_bill_text("already a string") == "already a string"

    def test_skips_empty_lines(self):
        result = _join_bill_text(["A", "", "B"])
        assert result == "A\nB"

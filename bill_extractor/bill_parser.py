from __future__ import annotations

import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


JsonDict = Dict[str, Any]
BillTextInput = Union[str, Sequence[str]]


from .bill_examples import (
    FOOD_EXAMPLE_LINES, FOOD_EXAMPLE_OUTPUT,
    HOTEL_EXAMPLE_LINES, HOTEL_EXAMPLE_OUTPUT,
    TRAVEL_EXAMPLE_LINES, TRAVEL_EXAMPLE_OUTPUT,
)

# =============================================================================
# Helpers
# =============================================================================

def _join_bill_text(bill_text: BillTextInput) -> str:
    if isinstance(bill_text, str):
        return bill_text.strip()
    return "\n".join(str(x) for x in bill_text if str(x).strip()).strip()


def _extract_first_json_object(text: str) -> str:
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        return text

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON object found in model output:\n{text}")
    return match.group(0)


def _safe_json_loads(text: str) -> JsonDict:
    obj = json.loads(_extract_first_json_object(text))
    if not isinstance(obj, dict):
        raise ValueError("Expected JSON object from model output.")
    return obj


def _extract_number_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}"

    s = str(value).strip()
    if not s:
        return None

    m = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?", s)
    if not m:
        return None

    try:
        return f"{float(m.group(0).replace(',', '')):.2f}"
    except ValueError:
        return None


def _normalize_time(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None

    if re.fullmatch(r"\d{1,2}:\d{2}", s):
        hh, mm = s.split(":")
        return f"{int(hh):02d}:{mm}"

    m = re.fullmatch(r"(\d{1,2}):(\d{2})\s*([AaPp][Mm])", s)
    if m:
        hh, mm, ampm = m.groups()
        hour = int(hh)
        ampm = ampm.lower()
        if ampm == "pm" and hour != 12:
            hour += 12
        if ampm == "am" and hour == 12:
            hour = 0
        return f"{hour:02d}:{mm}"

    m = re.search(r"(\d{1,2}):(\d{2})", s)
    if m:
        return f"{int(m.group(1)):02d}:{m.group(2)}"

    return s


_MONTH_NAMES = {
    "jan":"01","feb":"02","mar":"03","apr":"04","may":"05","jun":"06",
    "jul":"07","aug":"08","sep":"09","oct":"10","nov":"11","dec":"12",
}

def _normalize_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    # Expand 2-digit year: DD/MM/YY → DD/MM/YYYY
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", s)
    if m:
        d, mo, y = m.groups()
        return f"{d.zfill(2)}/{mo.zfill(2)}/20{y}"
    # Zero-pad DD/MM/YYYY
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        d, mo, y = m.groups()
        return f"{d.zfill(2)}/{mo.zfill(2)}/{y}"
    # DD Mon YYYY  (e.g. "27 Feb 2026")
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})", s)
    if m:
        d, mon, y = m.groups()
        mo = _MONTH_NAMES.get(mon[:3].lower())
        if mo:
            return f"{d.zfill(2)}/{mo}/{y}"
    # DD Mon  (e.g. "27 Feb" — no year)
    m = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,})", s)
    if m:
        d, mon = m.groups()
        mo = _MONTH_NAMES.get(mon[:3].lower())
        if mo:
            return f"{d.zfill(2)}/{mo}"
    return s


def _infer_meal_type_from_time(time_str: Optional[str]) -> str:
    if not time_str:
        return "unknown"

    m = re.fullmatch(r"(\d{2}):(\d{2})", time_str)
    if not m:
        return "unknown"

    hh = int(m.group(1))
    mm = int(m.group(2))
    total_minutes = hh * 60 + mm

    if 5 * 60 <= total_minutes <= 10 * 60 + 59:
        return "breakfast"
    if 11 * 60 <= total_minutes <= 15 * 60 + 59:
        return "lunch"
    if 18 * 60 <= total_minutes <= 23 * 60 + 59:
        return "dinner"
    return "unknown"


def _compute_stay_duration_days(check_in: Optional[str], check_out: Optional[str]) -> Optional[int]:
    if not check_in or not check_out:
        return None

    formats = [
        "%d/%m/%Y",
        "%d/%m/%y",
        "%Y-%m-%d",
    ]

    in_dt = None
    out_dt = None

    for fmt in formats:
        try:
            in_dt = datetime.strptime(check_in, fmt)
            break
        except ValueError:
            pass

    for fmt in formats:
        try:
            out_dt = datetime.strptime(check_out, fmt)
            break
        except ValueError:
            pass

    if in_dt is None or out_dt is None:
        return None

    return (out_dt.date() - in_dt.date()).days


# =============================================================================
# Prompt builders
# =============================================================================

def build_router_prompt(bill_text: BillTextInput) -> str:
    text = _join_bill_text(bill_text)

    return f"""You are a routing system for OCR bill text from India.

Your task is to classify the OCR bill text into exactly one category:
- "food"
- "travel"
- "hotel"

Definitions:
- "food": restaurant, cafe, bakery, food court, delivery receipt, meal receipt, in-room dining, room service, IRD food bill, restaurant check — any bill that primarily lists food/drink items with a total amount
- "travel": taxi, auto ride, cab, Uber, Ola, train, metro, bus, flight, any transport receipt
- "hotel": hotel stay invoice, resort accommodation invoice, room rent billing — the primary charge is for room accommodation with check-in and check-out dates

Critical rules:
- If the bill lists individual food or drink items (e.g. "Egg Biryani", "Mushroom Biryani") with prices and a food total, classify as "food" — even if the bill comes from a hotel or mentions a room number or guest name.
- "In Room Dining", "IRD", "Room Service", "Restaurant", "Outlet" on a bill that lists food items → "food"
- Only classify as "hotel" if the primary charge is for room accommodation/stay (shows Arrival/Departure dates and room rent as the main line item).

Return only valid JSON.
Do not return markdown.
Do not return explanations.
Do not return any text before or after the JSON.

Return exactly this schema:
{{
  "category": "food"
}}

Examples:

Example 1 input:
{json.dumps(TRAVEL_EXAMPLE_LINES, ensure_ascii=False, indent=2)}

Example 1 output:
{json.dumps({"category": "travel"}, ensure_ascii=False, indent=2)}

Example 2 input:
{json.dumps(HOTEL_EXAMPLE_LINES, ensure_ascii=False, indent=2)}

Example 2 output:
{json.dumps({"category": "hotel"}, ensure_ascii=False, indent=2)}

Example 3 input:
{json.dumps(FOOD_EXAMPLE_LINES, ensure_ascii=False, indent=2)}

Example 3 output:
{json.dumps({"category": "food"}, ensure_ascii=False, indent=2)}

OCR BILL TEXT:
{text}
"""


def build_food_extraction_prompt(bill_text: BillTextInput) -> str:
    text = _join_bill_text(bill_text)

    return f"""You are an information extraction system for OCR food bills from India.

Return only valid JSON.
Do not return markdown.
Do not return explanations.
Do not return any text before or after the JSON.

Extract exactly these fields:
- total_amount
- currency
- date
- time
- category
- meal_type

Rules:
- category must be exactly "food"
- currency must be exactly "INR"
- total_amount must be the final payable amount, preferably near labels like Grand Total, Total Amount, Total, Total AMT, Gross AMT, Net Amount, Final Amount; prefer "Total AMT" or "Gross AMT" over "Net AMT" when both are present
- use the bill date as found; format it as DD/MM/YYYY — always use numeric month (e.g. "27 Feb 2026" → "27/02/2026", "24/02/26" → "24/02/2026"); include the 4-digit year when available or inferable
- use the bill time as it appears in the OCR if found (may appear as HH:MM or alongside a date, e.g. "23/02/2026 19:13")
- meal_type rules:
  - breakfast if time is between 05:00 and 10:59
  - lunch if time is between 11:00 and 15:59
  - dinner if time is between 18:00 and 23:59
  - otherwise "unknown"
- if a value is missing, return null
- do not hallucinate

Example input:
{json.dumps(FOOD_EXAMPLE_LINES, ensure_ascii=False, indent=2)}

Example output:
{json.dumps(FOOD_EXAMPLE_OUTPUT, ensure_ascii=False, indent=2)}

Return exactly this schema:
{{
  "total_amount": null,
  "currency": "INR",
  "date": null,
  "time": null,
  "category": "food",
  "meal_type": null
}}

OCR BILL TEXT:
{text}
"""


def build_travel_extraction_prompt(bill_text: BillTextInput) -> str:
    text = _join_bill_text(bill_text)

    return f"""You are an information extraction system for OCR travel bills from India.

Return only valid JSON.
Do not return markdown.
Do not return explanations.
Do not return any text before or after the JSON.

Extract exactly these fields:
- category
- date
- time
- amount

Rules:
- category must be exactly "travel"
- amount must be the trip fare or final billed amount
- date: format as DD/MM/YYYY with numeric month (e.g. "27 Feb" → "27/02", "27 Feb 2026" → "27/02/2026"); include the 4-digit year when available or inferable
- time: extract exactly as found
- if a value is missing, return null
- do not hallucinate

Example input:
{json.dumps(TRAVEL_EXAMPLE_LINES, ensure_ascii=False, indent=2)}

Example output:
{json.dumps(TRAVEL_EXAMPLE_OUTPUT, ensure_ascii=False, indent=2)}

Return exactly this schema:
{{
  "category": "travel",
  "date": null,
  "time": null,
  "amount": null
}}

OCR BILL TEXT:
{text}
"""


def build_hotel_extraction_prompt(bill_text: BillTextInput) -> str:
    text = _join_bill_text(bill_text)

    return f"""You are an information extraction system for OCR hotel invoices from India.

Return only valid JSON.
Do not return markdown.
Do not return explanations.
Do not return any text before or after the JSON.

Extract exactly these fields:
- category
- name
- check_in
- check_out
- stay_duration_days
- amount
- currency

Rules:
- category must be exactly "hotel"
- name should be the billed guest name if present
- check_in should be the arrival/check-in date formatted as DD/MM/YYYY
- check_out should be the departure/check-out date formatted as DD/MM/YYYY
- stay_duration_days should be the number of days between check_out and check_in
- amount should be the final total payable amount
- currency must be "INR"
- if a value is missing, return null
- do not hallucinate

Example input:
{json.dumps(HOTEL_EXAMPLE_LINES, ensure_ascii=False, indent=2)}

Example output:
{json.dumps(HOTEL_EXAMPLE_OUTPUT, ensure_ascii=False, indent=2)}

Return exactly this schema:
{{
  "category": "hotel",
  "name": null,
  "check_in": null,
  "check_out": null,
  "stay_duration_days": null,
  "amount": null,
  "currency": "INR"
}}

OCR BILL TEXT:
{text}
"""


# =============================================================================
# Main extractor
# =============================================================================

@dataclass
class BillingExtractionConfig:
    model_name: str = "Qwen/Qwen2.5-1.5B-Instruct"
    max_new_tokens_router: int = 128
    max_new_tokens_extract: int = 512
    do_sample: bool = False
    temperature: float = 0.0


def _best_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda")
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class BillingInformationExtractor:
    def __init__(self, config: Optional[BillingExtractionConfig] = None) -> None:
        self.config = config or BillingExtractionConfig()
        self.device = _best_device()
        # float16 is faster on GPU/MPS; float32 on CPU avoids precision issues
        dtype = torch.float32 if self.device.type == "cpu" else torch.float16
        logger.info("Using device: %s (dtype=%s)", self.device, dtype)
        self.tokenizer = AutoTokenizer.from_pretrained(self.config.model_name, use_fast=True)
        self.model = AutoModelForCausalLM.from_pretrained(
            self.config.model_name,
            dtype=dtype,
        ).to(self.device)
        self.model.eval()
        # Clear sampling flags from generation_config to suppress warnings when do_sample=False
        for attr in ("temperature", "top_p", "top_k"):
            if hasattr(self.model.generation_config, attr):
                setattr(self.model.generation_config, attr, None)

    def _generate(self, prompt: str, max_new_tokens: int) -> str:
        messages = [{"role": "user", "content": prompt}]
        formatted = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = self.tokenizer(formatted, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        input_len = inputs["input_ids"].shape[-1]

        with torch.no_grad():
            output_ids = self.model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                do_sample=self.config.do_sample,
                pad_token_id=self.tokenizer.eos_token_id,
            )

        new_tokens = output_ids[0][input_len:]
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        if not text.strip():
            raise RuntimeError("Model returned empty text.")
        logger.debug("Generated text (%d chars):\n%s", len(text), text)
        return text

    def route_category(self, bill_text: BillTextInput) -> str:
        prompt = build_router_prompt(bill_text)
        raw = self._generate(prompt, self.config.max_new_tokens_router)
        data = _safe_json_loads(raw)

        category = str(data.get("category", "")).strip().lower()
        if category not in {"food", "travel", "hotel"}:
            raise ValueError(f"Invalid routed category: {category}")
        return category

    def extract_food(self, bill_text: BillTextInput) -> JsonDict:
        prompt = build_food_extraction_prompt(bill_text)
        raw = self._generate(prompt, self.config.max_new_tokens_extract)
        data = _safe_json_loads(raw)

        total_amount = _extract_number_string(data.get("total_amount"))
        date = _normalize_date(data.get("date"))
        time = _normalize_time(data.get("time"))
        # Always derive meal_type from the extracted time — more reliable than LLM guess
        meal_type = _infer_meal_type_from_time(time)

        return {
            "total_amount": total_amount,
            "currency": "INR",
            "date": date,
            "time": time,
            "category": "food",
            "meal_type": meal_type,
        }

    def extract_travel(self, bill_text: BillTextInput) -> JsonDict:
        prompt = build_travel_extraction_prompt(bill_text)
        raw = self._generate(prompt, self.config.max_new_tokens_extract)
        data = _safe_json_loads(raw)

        return {
            "category": "travel",
            "date": _normalize_date(data.get("date")),
            "time": _normalize_time(data.get("time")),
            "amount": _extract_number_string(data.get("amount")),
        }

    def extract_hotel(self, bill_text: BillTextInput) -> JsonDict:
        prompt = build_hotel_extraction_prompt(bill_text)
        raw = self._generate(prompt, self.config.max_new_tokens_extract)
        data = _safe_json_loads(raw)

        name = data.get("name")
        if name is not None:
            name = str(name).strip() or None

        check_in = _normalize_date(data.get("check_in"))
        check_out = _normalize_date(data.get("check_out"))

        stay_duration_days = data.get("stay_duration_days")
        if isinstance(stay_duration_days, str) and stay_duration_days.strip().isdigit():
            stay_duration_days = int(stay_duration_days.strip())
        elif not isinstance(stay_duration_days, int):
            stay_duration_days = _compute_stay_duration_days(check_in, check_out)

        return {
            "category": "hotel",
            "name": name,
            "check_in": check_in,
            "check_out": check_out,
            "stay_duration_days": stay_duration_days,
            "amount": _extract_number_string(data.get("amount")),
            "currency": "INR",
        }

    def extract(self, bill_text: BillTextInput) -> JsonDict:
        category = self.route_category(bill_text)

        if category == "food":
            return self.extract_food(bill_text)
        if category == "travel":
            return self.extract_travel(bill_text)
        if category == "hotel":
            return self.extract_hotel(bill_text)

        raise RuntimeError(f"Unsupported category after routing: {category}")


# =============================================================================
# Example usage
# =============================================================================

if __name__ == "__main__":
    extractor = BillingInformationExtractor()

    food_result = extractor.extract(FOOD_EXAMPLE_LINES)
    print("FOOD RESULT:")
    print(json.dumps(food_result, indent=2, ensure_ascii=False))

    travel_result = extractor.extract(TRAVEL_EXAMPLE_LINES)
    print("\nTRAVEL RESULT:")
    print(json.dumps(travel_result, indent=2, ensure_ascii=False))

    hotel_result = extractor.extract(HOTEL_EXAMPLE_LINES)
    print("\nHOTEL RESULT:")
    print(json.dumps(hotel_result, indent=2, ensure_ascii=False))
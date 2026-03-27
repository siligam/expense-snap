"""
bill_extractor — Extract structured expense data from receipt photos and PDFs.

Pipeline: DocTR OCR → Qwen2.5-1.5B-Instruct LLM → structured JSON.
First run:             bill-extractor init
Start the web app:     bill-extractor serve
"""

__version__ = "0.5.0"

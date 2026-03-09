"""
One-time setup script to download all required models for offline use.

Run this once before using the application:
    python download_models.py
"""
from transformers import AutoModelForCausalLM, AutoTokenizer
from doctr.models import ocr_predictor

LLM_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def download_llm():
    print(f"Downloading LLM tokenizer: {LLM_MODEL}")
    AutoTokenizer.from_pretrained(LLM_MODEL)
    print("Tokenizer downloaded.")

    print(f"Downloading LLM weights: {LLM_MODEL}")
    AutoModelForCausalLM.from_pretrained(LLM_MODEL)
    print("LLM downloaded.")


def download_ocr():
    print("Downloading doctr OCR models (detection + recognition)...")
    ocr_predictor(pretrained=True)
    print("OCR models downloaded.")


def download():
    download_ocr()
    print()
    download_llm()
    print("\nAll models cached. You can now run the application offline.")


if __name__ == "__main__":
    download()

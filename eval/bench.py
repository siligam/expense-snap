"""LLM backend benchmark for bill-extractor.

Runs all 16 sample receipts through each configured backend, measures load
time and per-file inference time, and scores extraction accuracy against a
ground truth file.

Usage:
    # From the repo root (package must be installed: pip install -e .)
    python eval/bench.py

    # With options:
    python eval/bench.py --threads 4 --backends baseline candidate_b
    python eval/bench.py --skip-ocr eval/ocr_cache.json

Setup:
    1. Process all sample images through the app and verify results.
    2. cp ~/.bill_extractor/history.json eval/ground_truth.json
    3. Edit ground_truth.json to keep only the 16 sample records.
    4. export HF_TOKEN=<your token>
    5. python -m bill_extractor.download_gguf qwen2.5-1.5b-q4km
    6. python -m bill_extractor.download_gguf qwen2.5-0.5b-q4km
    7. python eval/bench.py
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

# ── repo root on path so we can import bill_extractor without install ─────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from bill_extractor import ocr_reader
from bill_extractor.bill_parser import BillingInformationExtractor, _normalize_date
from bill_extractor.llm_backend import create_backend

try:
    from rich.console import Console
    from rich.table import Table
    from rich import box
    RICH = True
except ImportError:
    RICH = False

SAMPLES_DIR = Path(__file__).parent.parent / "samples"
GROUND_TRUTH_FILE = Path(__file__).parent / "ground_truth.json"
MODELS_DIR = Path.home() / ".bill_extractor" / "models"

SAMPLE_EXTENSIONS = {".jpeg", ".jpg", ".png", ".webp", ".pdf"}

console = Console() if RICH else None


# ── Backend definitions ───────────────────────────────────────────────────────

@dataclass
class BackendSpec:
    key: str            # short id for --backends filter
    name: str           # display name
    backend_type: str   # "transformers" | "llamacpp"
    model_name: str | None = None    # transformers
    model_path: str | None = None    # llamacpp
    n_threads: int = 4

    def is_available(self) -> bool:
        if self.backend_type == "llamacpp":
            p = Path(self.model_path).expanduser() if self.model_path else None
            return p is not None and p.exists()
        # transformers: assume available if torch + transformers installed
        try:
            import torch  # noqa: F401
            import transformers  # noqa: F401
            return True
        except ImportError:
            return False

    def build_backend(self, n_threads_override: int | None = None):
        if self.backend_type == "llamacpp":
            return create_backend(
                "llamacpp",
                model_path=self.model_path,
                n_threads=n_threads_override or self.n_threads,
            )
        return create_backend("transformers", model_name=self.model_name)


BACKENDS: list[BackendSpec] = [
    BackendSpec(
        key="baseline",
        name="Baseline — 1.5B transformers float16",
        backend_type="transformers",
        model_name="Qwen/Qwen2.5-1.5B-Instruct",
    ),
    BackendSpec(
        key="candidate_a",
        name="Candidate A — 0.5B transformers float16",
        backend_type="transformers",
        model_name="Qwen/Qwen2.5-0.5B-Instruct",
    ),
    BackendSpec(
        key="candidate_b",
        name="Candidate B — 1.5B Q4_K_M llama-cpp",
        backend_type="llamacpp",
        model_path=str(MODELS_DIR / "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf"),
        n_threads=4,
    ),
    BackendSpec(
        key="candidate_c",
        name="Candidate C — 0.5B Q4_K_M llama-cpp",
        backend_type="llamacpp",
        model_path=str(MODELS_DIR / "Qwen2.5-0.5B-Instruct-Q4_K_M.gguf"),
        n_threads=4,
    ),
]

# Approximate peak RAM for informational table (not measured at runtime)
APPROX_RAM = {
    "baseline":    "~3.0 GB",
    "candidate_a": "~1.2 GB",
    "candidate_b": "~1.1 GB",
    "candidate_c": "~0.4 GB",
}


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class FileResult:
    filename: str
    t_inference_s: float
    category: str | None
    fields: dict | None
    error: str | None


@dataclass
class BackendResult:
    backend_key: str
    backend_name: str
    t_load_s: float
    file_results: list[FileResult] = field(default_factory=list)
    load_error: str | None = None

    @property
    def total_inference_s(self) -> float:
        return sum(r.t_inference_s for r in self.file_results)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.file_results if r.error)


# ── Scoring ───────────────────────────────────────────────────────────────────

SCORE_FIELDS = {
    "food":   ["category", "date", "time", "total_amount", "meal_type"],
    "travel": ["category", "date", "time", "amount"],
    "hotel":  ["category", "date", "check_in", "check_out", "stay_duration_days", "amount"],
}


def _score_field(extracted: Any, truth: Any, field_name: str) -> bool | None:
    """Return True/False, or None if field is not in ground truth."""
    if truth is None:
        return None
    if extracted is None:
        return False
    if field_name in ("total_amount", "amount"):
        try:
            return abs(float(str(extracted).replace(",", "")) -
                       float(str(truth).replace(",", ""))) < 0.01
        except (ValueError, TypeError):
            return str(extracted).strip() == str(truth).strip()
    if field_name in ("date", "check_in", "check_out"):
        return _normalize_date(extracted) == _normalize_date(truth)
    if field_name == "stay_duration_days":
        try:
            return int(extracted) == int(truth)
        except (ValueError, TypeError):
            return str(extracted) == str(truth)
    return str(extracted).strip().lower() == str(truth).strip().lower()


def score_result(
    extracted: dict | None,
    truth_result: dict,
) -> tuple[int, int]:
    """Return (correct, total) scoreable fields."""
    if extracted is None:
        return 0, 0
    category = truth_result.get("category", "food")
    fields = SCORE_FIELDS.get(category, [])
    correct = total = 0
    for f in fields:
        s = _score_field(extracted.get(f), truth_result.get(f), f)
        if s is None:
            continue
        total += 1
        if s:
            correct += 1
    return correct, total


# ── OCR ───────────────────────────────────────────────────────────────────────

def run_ocr(samples_dir: Path) -> dict[str, list[str]]:
    """OCR all sample files; return dict[filename → lines]."""
    cache: dict[str, list[str]] = {}
    files = sorted(
        f for f in samples_dir.iterdir()
        if f.suffix.lower() in SAMPLE_EXTENSIONS
    )
    _print(f"\n[bold]OCR pass[/bold] — {len(files)} files", markup=True)
    t0 = time.perf_counter()
    for f in files:
        _print(f"  {f.name} … ", end="")
        try:
            lines = ocr_reader.process(str(f))
            cache[f.name] = lines
            _print("ok")
        except Exception as exc:
            _print(f"ERROR: {exc}")
            cache[f.name] = []
    elapsed = time.perf_counter() - t0
    _print(f"  OCR total: {elapsed:.1f}s\n")
    return cache


# ── Benchmark ─────────────────────────────────────────────────────────────────

def run_backend(
    spec: BackendSpec,
    ocr_cache: dict[str, list[str]],
    n_threads_override: int | None,
) -> BackendResult:
    _print(f"\n[bold cyan]{spec.name}[/bold cyan]", markup=True)

    t0 = time.perf_counter()
    try:
        backend = spec.build_backend(n_threads_override)
        extractor = BillingInformationExtractor(backend=backend)
        t_load = time.perf_counter() - t0
        _print(f"  Load: {t_load:.1f}s")
    except Exception as exc:
        t_load = time.perf_counter() - t0
        _print(f"  Load FAILED: {exc}")
        return BackendResult(
            backend_key=spec.key,
            backend_name=spec.name,
            t_load_s=t_load,
            load_error=str(exc),
        )

    result = BackendResult(
        backend_key=spec.key, backend_name=spec.name, t_load_s=t_load
    )

    for filename, lines in sorted(ocr_cache.items()):
        _print(f"  {filename} … ", end="")
        t1 = time.perf_counter()
        try:
            fields = extractor.extract(lines) if lines else None
            elapsed = time.perf_counter() - t1
            category = fields.get("category") if fields else None
            result.file_results.append(FileResult(
                filename=filename,
                t_inference_s=elapsed,
                category=category,
                fields=fields,
                error=None,
            ))
            _print(f"{elapsed:.1f}s [{category}]")
        except Exception as exc:
            elapsed = time.perf_counter() - t1
            result.file_results.append(FileResult(
                filename=filename,
                t_inference_s=elapsed,
                category=None,
                fields=None,
                error=str(exc),
            ))
            _print(f"ERROR: {exc}")

    _print(f"  Total inference: {result.total_inference_s:.1f}s")
    return result


# ── Output ────────────────────────────────────────────────────────────────────

def _print(msg: str = "", end: str = "\n", markup: bool = False) -> None:
    if RICH:
        console.print(msg, end=end, markup=markup, highlight=False)
    else:
        import re
        print(re.sub(r"\[/?[^\]]+\]", "", msg), end=end)


def print_results(
    backend_results: list[BackendResult],
    ground_truth: dict[str, dict],
) -> None:
    names = [r.backend_name for r in backend_results]

    # ── Table 1: Load times ───────────────────────────────────────────────────
    _print("\n[bold]Table 1 — Model load time[/bold]", markup=True)
    if RICH:
        t = Table(box=box.SIMPLE_HEAD)
        t.add_column("Backend", style="cyan")
        t.add_column("Load (s)", justify="right")
        t.add_column("RAM (est.)", justify="right")
        t.add_column("Status")
        for r in backend_results:
            status = "[red]FAILED[/red]" if r.load_error else "[green]✓[/green]"
            ram = APPROX_RAM.get(r.backend_key, "?")
            t.add_row(r.backend_name, f"{r.t_load_s:.1f}", ram, status)
        console.print(t)
    else:
        for r in backend_results:
            status = "FAILED" if r.load_error else "OK"
            print(f"  {r.backend_name:50s}  {r.t_load_s:5.1f}s  {status}")

    # ── Table 2: Per-file inference speed ─────────────────────────────────────
    _print("\n[bold]Table 2 — Inference speed (seconds per file)[/bold]", markup=True)
    all_files = sorted({
        fr.filename
        for r in backend_results
        for fr in r.file_results
    })
    if RICH:
        t = Table(box=box.SIMPLE_HEAD)
        t.add_column("File", style="dim")
        t.add_column("Category")
        for r in backend_results:
            t.add_column(r.backend_name, justify="right")

        file_totals: dict[str, float] = {}
        for fname in all_files:
            row = [fname]
            category = ""
            for r in backend_results:
                fr = next((x for x in r.file_results if x.filename == fname), None)
                if fr:
                    if not category and fr.category:
                        category = fr.category
                    cell = f"[red]ERR[/red]" if fr.error else f"{fr.t_inference_s:.1f}"
                else:
                    cell = "[dim]-[/dim]"
                row.append(cell)
            row.insert(1, category)
            t.add_row(*row)

        totals_row = ["[bold]Total[/bold]", ""]
        for r in backend_results:
            totals_row.append(f"[bold]{r.total_inference_s:.1f}[/bold]")
        t.add_row(*totals_row)
        console.print(t)
    else:
        header = f"  {'File':30s}  {'Cat':8s}" + "".join(f"  {n[:15]:>15s}" for n in names)
        print(header)
        for fname in all_files:
            category = ""
            row = f"  {fname:30s}  {category:8s}"
            for r in backend_results:
                fr = next((x for x in r.file_results if x.filename == fname), None)
                if fr:
                    if not category and fr.category:
                        category = fr.category
                    row += f"  {'ERR':>15s}" if fr.error else f"  {fr.t_inference_s:>14.1f}s"
                else:
                    row += f"  {'-':>15s}"
            print(row)
        totals = "  " + " " * 40 + "".join(
            f"  {r.total_inference_s:>14.1f}s" for r in backend_results
        )
        print(f"  {'Total':30s}  {'':8s}" + "".join(
            f"  {r.total_inference_s:>14.1f}s" for r in backend_results
        ))

    # ── Table 3: Accuracy ─────────────────────────────────────────────────────
    _print("\n[bold]Table 3 — Extraction accuracy[/bold]", markup=True)
    if not ground_truth:
        _print("  [yellow]No ground_truth.json found — skipping accuracy table.[/yellow]",
               markup=True)
    else:
        overall: dict[str, tuple[int, int]] = {r.backend_key: (0, 0) for r in backend_results}
        if RICH:
            t = Table(box=box.SIMPLE_HEAD)
            t.add_column("File", style="dim")
            t.add_column("Category")
            for r in backend_results:
                t.add_column(r.backend_name, justify="right")

            for fname in all_files:
                truth = ground_truth.get(fname)
                if not truth:
                    continue
                truth_result = truth.get("result", {})
                category = truth_result.get("category", "?")
                row = [fname, category]
                for r in backend_results:
                    fr = next((x for x in r.file_results if x.filename == fname), None)
                    if fr and not fr.error and fr.fields:
                        c, tot = score_result(fr.fields, truth_result)
                        ok, prev_tot = overall[r.backend_key]
                        overall[r.backend_key] = (ok + c, prev_tot + tot)
                        pct = f"{c}/{tot} ({'✓' if c == tot else '~'})"
                        cell = f"[green]{pct}[/green]" if c == tot else f"[yellow]{pct}[/yellow]"
                    elif fr and fr.error:
                        cell = "[red]ERR[/red]"
                    else:
                        cell = "[dim]-[/dim]"
                    row.append(cell)
                t.add_row(*row)

            overall_row = ["[bold]Overall[/bold]", ""]
            for r in backend_results:
                c, tot = overall[r.backend_key]
                pct = f"{100*c//tot}%" if tot else "-"
                overall_row.append(f"[bold]{c}/{tot} ({pct})[/bold]")
            t.add_row(*overall_row)
            console.print(t)
        else:
            for fname in all_files:
                truth = ground_truth.get(fname)
                if not truth:
                    continue
                truth_result = truth.get("result", {})
                category = truth_result.get("category", "?")
                row = f"  {fname:30s}  {category:8s}"
                for r in backend_results:
                    fr = next((x for x in r.file_results if x.filename == fname), None)
                    if fr and not fr.error and fr.fields:
                        c, tot = score_result(fr.fields, truth_result)
                        ok, prev = overall[r.backend_key]
                        overall[r.backend_key] = (ok + c, prev + tot)
                        row += f"  {c}/{tot:>13s}"
                    else:
                        row += f"  {'ERR':>14s}"
                print(row)
            print("  " + "-" * 40)
            totals = f"  {'Overall':30s}  {'':8s}"
            for r in backend_results:
                c, tot = overall[r.backend_key]
                pct = f"{100*c//tot}%" if tot else "-"
                totals += f"  {f'{c}/{tot} ({pct})':>14s}"
            print(totals)

    # ── Summary ranking ───────────────────────────────────────────────────────
    _print("\n[bold]Summary[/bold]", markup=True)
    rows = []
    for r in backend_results:
        if r.load_error:
            continue
        c, tot = (0, 0)
        if ground_truth:
            for fname in all_files:
                truth = ground_truth.get(fname)
                if not truth:
                    continue
                fr = next((x for x in r.file_results if x.filename == fname), None)
                if fr and fr.fields:
                    ci, ti = score_result(fr.fields, truth.get("result", {}))
                    c += ci
                    tot += ti
        acc_str = f"{100*c//tot}%" if tot else "n/a"
        rows.append((r, acc_str, c, tot))

    rows.sort(key=lambda x: (-(x[2] / x[3] if x[3] else 0), x[0].total_inference_s))
    for i, (r, acc, _, _) in enumerate(rows, 1):
        ram = APPROX_RAM.get(r.backend_key, "?")
        _print(
            f"  [bold]{i}.[/bold] {r.backend_name:50s}  "
            f"accuracy={acc}  total={r.total_inference_s:.0f}s  RAM={ram}",
            markup=True,
        )


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="LLM backend benchmark for bill-extractor.")
    parser.add_argument(
        "--backends", nargs="+",
        metavar="KEY",
        help=f"Backends to run (default: all available). Keys: {[b.key for b in BACKENDS]}",
    )
    parser.add_argument(
        "--samples", type=Path, default=SAMPLES_DIR,
        help=f"Sample directory (default: {SAMPLES_DIR})",
    )
    parser.add_argument(
        "--threads", type=int, default=None,
        help="Override n_threads for all llamacpp backends.",
    )
    parser.add_argument(
        "--skip-ocr", type=Path, default=None, metavar="FILE",
        help="Load pre-cached OCR results from JSON file instead of re-running OCR.",
    )
    args = parser.parse_args()

    # Select backends
    selected = BACKENDS
    if args.backends:
        selected = [b for b in BACKENDS if b.key in args.backends]
        if not selected:
            print(f"No matching backends for: {args.backends}")
            sys.exit(1)

    available = [b for b in selected if b.is_available()]
    skipped = [b for b in selected if not b.is_available()]

    if skipped:
        _print("\n[yellow]Skipping (models not available):[/yellow]", markup=True)
        for b in skipped:
            _print(f"  {b.name}", markup=True)

    if not available:
        _print("\n[red]No backends available to run.[/red]", markup=True)
        sys.exit(1)

    # OCR
    if args.skip_ocr and args.skip_ocr.exists():
        _print(f"\nLoading cached OCR from {args.skip_ocr}")
        with open(args.skip_ocr) as f:
            ocr_cache = json.load(f)
    else:
        ocr_cache = run_ocr(args.samples)
        cache_path = Path(__file__).parent / "ocr_cache.json"
        with open(cache_path, "w") as f:
            json.dump(ocr_cache, f, ensure_ascii=False, indent=2)
        _print(f"OCR cache saved to {cache_path} (use --skip-ocr to reuse)")

    # Load ground truth
    ground_truth: dict[str, dict] = {}
    if GROUND_TRUTH_FILE.exists():
        with open(GROUND_TRUTH_FILE) as f:
            records = json.load(f)
        for rec in (records if isinstance(records, list) else []):
            fname = rec.get("filename")
            if fname:
                ground_truth[fname] = rec
        _print(f"Ground truth loaded: {len(ground_truth)} records")
    else:
        _print(
            f"\n[yellow]Warning:[/yellow] {GROUND_TRUTH_FILE} not found. "
            "Accuracy scoring will be skipped.\n"
            "See the setup instructions at the top of this file.",
            markup=True,
        )

    # Run backends
    backend_results: list[BackendResult] = []
    for spec in available:
        result = run_backend(spec, ocr_cache, args.threads)
        backend_results.append(result)

    # Print results
    print_results(backend_results, ground_truth)

    # Save JSON
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(__file__).parent / f"results_{ts}.json"
    serialisable = []
    for r in backend_results:
        d = asdict(r)
        serialisable.append(d)
    with open(out_path, "w") as f:
        json.dump(serialisable, f, ensure_ascii=False, indent=2)
    _print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()

"""Live CLI: run the configured extractor over a folder of real POF PDFs.

This calls the LLM directly (in-process, no HTTP server needed) and prints the structured
JSON for each PDF. Requires the relevant API key (GEMINI_API_KEY by default).

Usage:
    python tests/run_samples.py                       # uses ../Test POFs
    python tests/run_samples.py "C:/path/to/pdfs"     # custom folder
    python tests/run_samples.py "C:/path" --out out/  # also write <name>.json files
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.extractors import get_extractor  # noqa: E402

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "Test POFs"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the POF extractor over a folder of PDFs.")
    parser.add_argument("folder", nargs="?", default=str(DEFAULT_DIR), help="Folder containing .pdf files")
    parser.add_argument("--out", default=None, help="Optional folder to write <name>.json results to")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        print(f"Folder not found: {folder}")
        return 1

    pdfs = sorted(folder.rglob("*.pdf"))
    if not pdfs:
        print(f"No PDF files found under: {folder}")
        return 1

    out_dir = Path(args.out) if args.out else None
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    extractor = get_extractor()
    print(f"Provider: {extractor.name} ({extractor.model})\nFound {len(pdfs)} PDF(s)\n")

    failures = 0
    for pdf in pdfs:
        print("=" * 80)
        print(pdf.name)
        try:
            fields = extractor.extract(pdf.read_bytes(), pdf.name)
            payload = fields.model_dump_json(indent=2)
            print(payload)
            if out_dir:
                (out_dir / f"{pdf.stem}.json").write_text(payload, encoding="utf-8")
        except Exception as exc:  # keep going through the batch
            failures += 1
            print(f"  !! extraction failed: {exc}")

    print("=" * 80)
    print(f"Done. {len(pdfs) - failures}/{len(pdfs)} succeeded.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

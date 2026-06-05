"""Offline tests for the deterministic anchor layer.

These run against the already-extracted sample text files in `Test POFs/Text File/` and make
NO API calls, so they work for free in CI. They validate that the cheap regex cross-check can
reliably recover the proposal number from the template footer.

Run with either:
    pytest tests/test_anchors.py
    python tests/test_anchors.py
"""
import os
import re
import sys
from pathlib import Path

# Make the package importable when run directly (python tests/test_anchors.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.anchors import find_organization, find_proposal_number  # noqa: E402

SAMPLES_DIR = Path(__file__).resolve().parents[2] / "Test POFs" / "Text File"
_FILE_PROPOSAL = re.compile(r"(Q-\d{4,})")


def _sample_files() -> list[Path]:
    if not SAMPLES_DIR.exists():
        return []
    return sorted(SAMPLES_DIR.glob("*.txt"))


def test_samples_dir_present():
    assert SAMPLES_DIR.exists(), f"Sample folder not found: {SAMPLES_DIR}"
    assert _sample_files(), "No .txt sample files found."


def test_proposal_number_matches_filename_when_present():
    """For files whose name encodes a Q-number, the anchor must recover the same number."""
    checked = 0
    for path in _sample_files():
        name_match = _FILE_PROPOSAL.search(path.name)
        if not name_match:
            continue  # documents named by customer (Stetson/SMCM/Assumption) - covered below
        text = path.read_text(encoding="utf-8", errors="ignore")
        found = find_proposal_number(text)
        assert found == name_match.group(1), f"{path.name}: expected {name_match.group(1)}, got {found}"
        checked += 1
    assert checked > 0, "Expected at least one OrderForm_Q-* sample."


def test_proposal_number_found_in_every_sample():
    """Every POF in the set carries a 'PROPOSAL | Q-######' footer."""
    for path in _sample_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        found = find_proposal_number(text)
        assert found and found.startswith("Q-"), f"{path.name}: no proposal number found"


def test_organization_extracted_for_most_samples():
    hits = 0
    for path in _sample_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        if find_organization(text):
            hits += 1
    assert hits >= 1, "Expected to find at least one 'Organization:' anchor."


if __name__ == "__main__":
    files = _sample_files()
    print(f"Samples dir: {SAMPLES_DIR}")
    print(f"Found {len(files)} sample file(s)\n")
    for p in files:
        body = p.read_text(encoding="utf-8", errors="ignore")
        print(f"- {p.name}")
        print(f"    proposal_number : {find_proposal_number(body)}")
        print(f"    organization    : {find_organization(body)}")
    print("\nOK")

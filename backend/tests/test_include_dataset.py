"""Tests for the INCLUDE (Indian Sign Language, word-level) dataset path.

INCLUDE differs from WLASL in two ways that matter to correctness rather than
convenience:

1. **Classes come from folder names**, not a metadata JSON. Those names carry
   listing artefacts ("1. loud") that are not part of the word, and the same
   word can appear under two category folders.
2. **It records no signer identity.** WLASL does, which is what makes Model B's
   signer-disjoint split possible. Claiming that split here — where every clip
   has signer_id -1 — would silently overstate the strongest evaluation this
   project offers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
EXTRACT = REPO_ROOT / "ml" / "scripts" / "extract_landmarks_video.py"
PREPROCESS = REPO_ROOT / "ml" / "scripts" / "preprocess_dynamic.py"

pytestmark = pytest.mark.skipif(
    not (EXTRACT.is_file() and PREPROCESS.is_file()), reason="ml scripts missing"
)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def extract():
    return _load("extract_video_mod", EXTRACT)


@pytest.fixture(scope="module")
def pre():
    return _load("preprocess_dynamic_mod", PREPROCESS)


# --------------------------------------------------------------------------- #
# Folder names become labels
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "folder,expected",
    [
        ("1. loud", "loud"),
        ("23. quiet", "quiet"),
        ("7 - hello", "hello"),
        ("12_thanks", "thanks"),
        ("hello", "hello"),
        ("  Good Morning  ", "good morning"),
        ("4. Happy", "happy"),
        ("some_word", "some word"),
    ],
)
def test_folder_names_become_clean_labels(extract, folder, expected):
    assert extract.clean_class_name(folder) == expected


def test_the_same_word_under_two_categories_collapses_to_one_class(extract):
    """INCLUDE numbers words per category, so "1. hello" and "9. hello" are
    the same word listed twice. Keeping the numbers would train two classes
    that are impossible to tell apart."""
    assert extract.clean_class_name("1. hello") == extract.clean_class_name("9. hello")


def test_a_number_inside_the_word_is_not_stripped(extract):
    """Only a LEADING listing index is an artefact."""
    assert extract.clean_class_name("class 10") == "class 10"


# --------------------------------------------------------------------------- #
# The signer-disjoint claim
# --------------------------------------------------------------------------- #


def test_split_by_signer_is_degenerate_when_identity_is_unknown(pre):
    """The failure this guard exists to prevent.

    With every clip marked signer_id -1, they form a single group, so the
    greedy assignment hands the whole dataset to one split and leaves the
    others empty. Nothing raises — the run would simply produce a meaningless
    evaluation while the manifest claimed the strongest one available.
    """
    glosses = np.array(["a"] * 20 + ["b"] * 20)
    signers = np.full(40, -1)

    indices = pre.split_by_signer(glosses, signers, seed=42)

    non_empty = [name for name in ("train", "val", "test") if len(indices[name])]
    assert len(non_empty) == 1, (
        "unknown signers should collapse into one group — if this ever splits "
        "sensibly, the fallback in main() is no longer needed"
    )


def test_split_by_signer_works_when_identity_is_known(pre):
    """The complement: with real signer IDs the split does its job."""
    glosses = np.array(["a"] * 30 + ["b"] * 30)
    signers = np.array([i % 6 for i in range(60)])

    indices = pre.split_by_signer(glosses, signers, seed=42)

    train_signers = {int(signers[i]) for i in indices["train"]}
    test_signers = {int(signers[i]) for i in indices["test"]}

    assert train_signers and test_signers
    assert not (train_signers & test_signers), "a signer appeared in train AND test"


def test_random_split_covers_every_class(pre):
    """The fallback must still put every word in every split."""
    glosses = np.array([word for word in ("a", "b", "c") for _ in range(20)])

    indices = pre.split_randomly(glosses, seed=42)

    for name in ("train", "val", "test"):
        present = {glosses[i] for i in indices[name]}
        assert present == {"a", "b", "c"}, f"{name} is missing a class"

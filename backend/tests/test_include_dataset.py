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


# --------------------------------------------------------------------------- #
# The layout inspector
# --------------------------------------------------------------------------- #
#
# This is a decision tool: someone downloads an unknown dataset and needs to
# know in seconds whether it is usable, rather than after a three-hour
# extraction fails. Misreporting a layout sends them down the wrong path, so
# each verdict is pinned.


def _make_video(path: Path) -> None:
    import cv2
    import numpy as np

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 25, (32, 32))
    for _ in range(3):
        writer.write(np.zeros((32, 32, 3), dtype=np.uint8))
    writer.release()


def test_inspector_reports_missing_directory(extract, tmp_path, capsys):
    assert extract.inspect_layout(tmp_path / "nope") == 1
    assert "NOT FOUND" in capsys.readouterr().out


def test_inspector_recognises_folder_per_word(extract, tmp_path, capsys):
    for word in ("1. hello", "2. thanks", "3. cat", "4. dog", "5. red", "6. blue"):
        for clip in range(5):
            _make_video(tmp_path / "Category" / word / f"c{clip}.mp4")

    assert extract.inspect_layout(tmp_path) == 0

    out = capsys.readouterr().out
    assert "one folder per word" in out
    assert "--dataset include" in out
    # Numbering stripped, so the labels are the words themselves.
    assert "hello" in out and "1. hello" not in out.split("sample labels")[1]


def test_inspector_recognises_wlasl_metadata(extract, tmp_path, capsys):
    import json

    for index in range(12):
        _make_video(tmp_path / "videos" / f"{index:05d}.mp4")
    (tmp_path / "WLASL_v0.3.json").write_text(
        json.dumps([{"gloss": "book", "instances": [{"video_id": "00001"}]}])
    )

    assert extract.inspect_layout(tmp_path) == 0
    assert "--dataset wlasl" in capsys.readouterr().out


def test_inspector_flags_a_flat_pile_as_unusable(extract, tmp_path, capsys):
    """Videos in one folder means the word is in the filename, which cannot be
    guessed. The inspector must say so and show the names rather than
    pretending the dataset is fine."""
    for word in ("hello", "thanks", "cat"):
        for index in range(8):
            _make_video(tmp_path / f"{word}_{index}.mp4")

    assert extract.inspect_layout(tmp_path) == 1

    out = capsys.readouterr().out
    assert "ONE folder" in out
    assert "hello_" in out, "should print sample filenames to work from"


def test_inspector_redirects_image_datasets_to_the_alphabet_path(extract, tmp_path, capsys):
    """An alphabet dataset downloaded into the video folder is a likely mistake,
    and the fix is a different command entirely."""
    import cv2
    import numpy as np

    for letter in "ABCDEFGH":
        directory = tmp_path / letter
        directory.mkdir(parents=True)
        for index in range(6):
            cv2.imwrite(str(directory / f"{index}.jpg"), np.zeros((32, 32, 3), np.uint8))

    assert extract.inspect_layout(tmp_path) == 1

    out = capsys.readouterr().out
    assert "image frames" in out
    assert "isl_alphabet" in out, "should point at the alphabet pipeline"


def test_inspector_warns_when_there_are_too_few_clips_per_word(extract, tmp_path, capsys):
    for word in ("hello", "thanks", "cat", "dog", "red", "blue"):
        _make_video(tmp_path / word / "only.mp4")

    assert extract.inspect_layout(tmp_path) == 0
    assert "WARNING" in capsys.readouterr().out

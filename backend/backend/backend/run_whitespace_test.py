"""Run the whitespace contamination test through isolated pytest fixtures.

The test's database and file storage are provided by
``backend/tests/conftest.py``; this wrapper never creates a project-local DB.
"""

from pathlib import Path

import pytest


def main() -> int:
    backend_dir = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "tests" / "test_train_test_contamination.py").is_file()
    )
    return pytest.main(
        [
            "-q",
            str(backend_dir / "tests" / "test_train_test_contamination.py"),
            "-k",
            "test_train_test_contamination_whitespace_handling",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())

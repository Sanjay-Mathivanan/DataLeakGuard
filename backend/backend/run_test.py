"""Run one legacy contamination test through the isolated pytest fixtures.

This compatibility wrapper intentionally delegates database and storage setup
to ``backend/tests/conftest.py`` rather than creating a shared project-local
SQLite database.
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
            "test_exact_train_test_contamination_detected",
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())

"""M0 smoke test: the package imports and reports a version."""

import aegis


def test_package_imports() -> None:
    assert aegis.__version__ == "0.1.0"

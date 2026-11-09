# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Peter Lawler

"""Unit tests verifying LICENSE file and SPDX license identifier headers."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_license_file_exists() -> None:
    """Verify LICENSE exists and contains required MIT copyright information."""
    license_path = ROOT / "LICENSE"
    assert license_path.is_file(), "LICENSE file must exist at repo root"
    content = license_path.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: MIT" in content
    assert "Copyright (c) 2026 Peter Lawler / OpenTasmania" in content
    assert "MIT License" in content


def test_python_files_contain_spdx() -> None:
    """Verify all Python source and test files contain SPDX license headers."""
    py_dirs = [ROOT / "custom_components", ROOT / "tests"]
    py_files: list[Path] = []
    for d in py_dirs:
        py_files.extend(d.rglob("*.py"))

    assert py_files, "Expected to find python files to check"
    missing: list[str] = []
    for path in py_files:
        content = path.read_text(encoding="utf-8")
        has_spdx = "SPDX-License-Identifier: MIT" in content
        has_copy = "Copyright (c) 2026 Peter Lawler" in content
        if not (has_spdx and has_copy):
            missing.append(str(path.relative_to(ROOT)))

    assert not missing, f"Python files missing SPDX/Copyright header: {missing}"


def test_typescript_files_contain_spdx() -> None:
    """Verify TypeScript files in frontend/src and config contain SPDX license headers."""
    ts_files = list((ROOT / "frontend" / "src").rglob("*.ts"))
    vite_cfg = ROOT / "frontend" / "vite.config.ts"
    if vite_cfg.exists():
        ts_files.append(vite_cfg)

    assert ts_files, "Expected to find TypeScript files to check"
    missing: list[str] = []
    for path in ts_files:
        content = path.read_text(encoding="utf-8")
        has_spdx = "SPDX-License-Identifier: MIT" in content
        has_copy = "Copyright (c) 2026 Peter Lawler" in content
        if not (has_spdx and has_copy):
            missing.append(str(path.relative_to(ROOT)))

    assert not missing, f"TypeScript files missing SPDX/Copyright header: {missing}"


def test_markdown_files_contain_spdx() -> None:
    """Verify README.md, INSTALL.md, and docs markdown files contain SPDX license headers."""
    md_files = [ROOT / "README.md", ROOT / "INSTALL.md"]
    docs_dir = ROOT / "docs"
    if docs_dir.exists():
        md_files.extend(docs_dir.rglob("*.md"))

    missing: list[str] = []
    for path in md_files:
        content = path.read_text(encoding="utf-8")
        if "SPDX-License-Identifier: MIT" not in content:
            missing.append(str(path.relative_to(ROOT)))

    assert not missing, f"Markdown files missing SPDX header: {missing}"


def test_pyproject_contains_mit_license() -> None:
    """Verify pyproject.toml defines MIT license metadata and SPDX header."""
    pyproject_path = ROOT / "pyproject.toml"
    assert pyproject_path.is_file(), "pyproject.toml must exist"
    content = pyproject_path.read_text(encoding="utf-8")
    assert 'license = { text = "MIT" }' in content
    assert "SPDX-License-Identifier: MIT" in content


def test_frontend_bundle_contains_spdx() -> None:
    """Verify compiled Lovelace card bundle preserves the license header banner."""
    bundle_path = ROOT / "custom_components" / "junie_remote" / "frontend" / "junie-remote-card.js"
    assert bundle_path.is_file(), "Lovelace bundle must exist"
    content = bundle_path.read_text(encoding="utf-8")
    assert "SPDX-License-Identifier: MIT" in content
    assert "Copyright (c) 2026 Peter Lawler" in content

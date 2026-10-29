"""Tests for scripts/filemap.py (INDEX.md generator)."""

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "filemap", Path(__file__).resolve().parents[1] / "scripts" / "filemap.py")
fm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fm)


def test_collect_summarizes_and_excludes(tmp_path):
    (tmp_path / "a.py").write_text('"""First line.\n\nMore.\n"""\n', encoding="utf-8")
    (tmp_path / "b.md").write_text("# Heading One\n\ntext\n", encoding="utf-8")
    (tmp_path / "INDEX.md").write_text("# self\n", encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "big.csv").write_text("x", encoding="utf-8")
    files = fm.collect(tmp_path)
    names = [f[0] for f in files]
    assert names == ["a.py", "b.md"]  # INDEX.md and data/ excluded
    assert files[0][2] == "First line."
    assert files[1][2] == "Heading One"


def test_render_groups_by_top_dir(tmp_path):
    out = fm.render([("x/a.py", 10, "Doc."), ("y/b.py", 2048, "")])
    assert "### x" in out and "### y" in out and "`x/a.py`" in out

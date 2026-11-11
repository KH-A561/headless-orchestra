"""Проверка границ: Ableton-специфика только в адаптере и мосте, без api_layer."""

from __future__ import annotations

from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
AGENTS_PKG = PROJECT_DIR / "agents"


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if p.is_file())


class TestBoundaries:
    def test_no_ableton_strings_outside_adapter(self) -> None:
        excluded_names = {"live_bridge.py"}
        for path in _py_files(AGENTS_PKG):
            if path.name in excluded_names:
                continue
            if path.parent.name == "adapters" and path.name == "ableton.py":
                continue
            text = path.read_text(encoding="utf-8")
            assert "get_clip_notes" not in text, f"get_clip_notes leaked into {path}"
            assert "DrumGroupDevice" not in text, f"DrumGroupDevice leaked into {path}"

    def test_no_api_layer_import_anywhere(self) -> None:
        import_needle = "import " + "api_layer"
        from_needle = "from " + "api_layer"
        for path in _py_files(PROJECT_DIR):
            text = path.read_text(encoding="utf-8")
            assert import_needle not in text, f"api_layer import in {path}"
            assert from_needle not in text, f"api_layer import in {path}"

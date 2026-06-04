#!/usr/bin/env python3
"""Prepare the static GitHub Pages site under docs/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from map_data import build_us_state_winners  # noqa: E402
from state_labels import format_jurisdiction_label, jurisdiction_name  # noqa: E402

DOCS_DIR = ROOT / "docs"
DATA_DIR = DOCS_DIR / "data"
SOURCE_DATA_DIR = ROOT / "src" / "voting_data"
STYLES_SRC = ROOT / "static" / "styles.css"
STYLES_DEST = DOCS_DIR / "assets" / "styles.css"
UI_SRC = ROOT / "static" / "ui.js"
UI_DEST = DOCS_DIR / "assets" / "ui.js"
MAP_BG_SRC = ROOT / "static" / "map-background.js"
MAP_BG_DEST = DOCS_DIR / "assets" / "map-background.js"
MAP_BRIDGE_SRC = ROOT / "static" / "map-bridge.js"
MAP_BRIDGE_DEST = DOCS_DIR / "assets" / "map-bridge.js"
SHELL_SRC = ROOT / "static" / "app-shell.js"
SHELL_DEST = DOCS_DIR / "assets" / "app-shell.js"
STATIC_DATA_DIR = ROOT / "static" / "data"


def build_manifest() -> dict:
    states: list[dict[str, str]] = []
    if SOURCE_DATA_DIR.exists():
        for path in sorted(SOURCE_DATA_DIR.glob("*_timeline.json")):
            code = path.stem.replace("_timeline", "").upper()
            states.append(
                {
                    "code": code,
                    "file": path.name,
                    "name": jurisdiction_name(code),
                    "label": format_jurisdiction_label(code),
                }
            )
    return {"states": states, "generated_from": str(SOURCE_DATA_DIR)}


def copy_timeline_data() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in sorted(SOURCE_DATA_DIR.glob("*_timeline.json")):
        target = DATA_DIR / path.name
        shutil.copy2(path, target)
        copied += 1
    return copied


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / "assets").mkdir(parents=True, exist_ok=True)
    (DOCS_DIR / ".nojekyll").touch(exist_ok=True)

    if STYLES_SRC.exists():
        shutil.copy2(STYLES_SRC, STYLES_DEST)
    if UI_SRC.exists():
        shutil.copy2(UI_SRC, UI_DEST)
    if MAP_BG_SRC.exists():
        shutil.copy2(MAP_BG_SRC, MAP_BG_DEST)
    if MAP_BRIDGE_SRC.exists():
        shutil.copy2(MAP_BRIDGE_SRC, MAP_BRIDGE_DEST)
    if SHELL_SRC.exists():
        shutil.copy2(SHELL_SRC, SHELL_DEST)

    copied = copy_timeline_data()
    manifest = build_manifest()
    (DATA_DIR / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )

    winners = build_us_state_winners(SOURCE_DATA_DIR)
    STATIC_DATA_DIR.mkdir(parents=True, exist_ok=True)
    winners_path = STATIC_DATA_DIR / "us_state_winners.json"
    winners_path.write_text(json.dumps(winners, ensure_ascii=True, indent=2), encoding="utf-8")
    shutil.copy2(winners_path, DATA_DIR / "us_state_winners.json")

    print(f"Prepared docs site at {DOCS_DIR}")
    print(f"Copied {copied} timeline files to {DATA_DIR}")
    print(f"Manifest states: {len(manifest['states'])}")


if __name__ == "__main__":
    main()

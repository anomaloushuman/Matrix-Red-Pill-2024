"""US jurisdiction names and display labels for data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Dict

# Red + blue blend — used for third-party votes and provisional ballots.
PATRIOT_PURPLE = "#9b5de5"

US_JURISDICTION_NAMES: Dict[str, str] = {
    "al": "Alabama",
    "ak": "Alaska",
    "az": "Arizona",
    "ar": "Arkansas",
    "ca": "California",
    "co": "Colorado",
    "ct": "Connecticut",
    "de": "Delaware",
    "dc": "District of Columbia",
    "fl": "Florida",
    "ga": "Georgia",
    "hi": "Hawaii",
    "id": "Idaho",
    "il": "Illinois",
    "in": "Indiana",
    "ia": "Iowa",
    "ks": "Kansas",
    "ky": "Kentucky",
    "la": "Louisiana",
    "me": "Maine",
    "md": "Maryland",
    "ma": "Massachusetts",
    "mi": "Michigan",
    "mn": "Minnesota",
    "ms": "Mississippi",
    "mo": "Missouri",
    "mt": "Montana",
    "ne": "Nebraska",
    "nv": "Nevada",
    "nh": "New Hampshire",
    "nj": "New Jersey",
    "nm": "New Mexico",
    "ny": "New York",
    "nc": "North Carolina",
    "nd": "North Dakota",
    "oh": "Ohio",
    "ok": "Oklahoma",
    "or": "Oregon",
    "pa": "Pennsylvania",
    "ri": "Rhode Island",
    "sc": "South Carolina",
    "sd": "South Dakota",
    "tn": "Tennessee",
    "tx": "Texas",
    "ut": "Utah",
    "vt": "Vermont",
    "va": "Virginia",
    "wa": "Washington",
    "wv": "West Virginia",
    "wi": "Wisconsin",
    "wy": "Wyoming",
}


def jurisdiction_name(code: str) -> str:
    key = str(code).strip().lower()
    return US_JURISDICTION_NAMES.get(key, key.upper())


def format_jurisdiction_label(code: str) -> str:
    key = str(code).strip().lower()
    return f"{jurisdiction_name(key)} ({key.upper()})"


def label_for_local_json(path: Path) -> str:
    stem = path.stem.lower()
    if stem.endswith("_timeline"):
        code = stem[: -len("_timeline")]
        return format_jurisdiction_label(code)
    if "pageneralconcatenator" in stem:
        return f"{format_jurisdiction_label('pa')} — Concatenator"
    if stem.endswith("concatenator-latest") or "concatenator" in stem:
        prefix = stem.split("generalconcatenator")[0].replace("latest", "").strip("-_")
        if len(prefix) == 2:
            return f"{format_jurisdiction_label(prefix)} — Concatenator"
    return path.name

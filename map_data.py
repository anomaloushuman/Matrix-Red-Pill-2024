"""Election map payloads and US geography helpers for the Three.js background."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

CODE_TO_FIPS: Dict[str, str] = {
    "AL": "01",
    "AK": "02",
    "AZ": "04",
    "AR": "05",
    "CA": "06",
    "CO": "08",
    "CT": "09",
    "DE": "10",
    "DC": "11",
    "FL": "12",
    "GA": "13",
    "HI": "15",
    "ID": "16",
    "IL": "17",
    "IN": "18",
    "IA": "19",
    "KS": "20",
    "KY": "21",
    "LA": "22",
    "ME": "23",
    "MD": "24",
    "MA": "25",
    "MI": "26",
    "MN": "27",
    "MS": "28",
    "MO": "29",
    "MT": "30",
    "NE": "31",
    "NV": "32",
    "NH": "33",
    "NJ": "34",
    "NM": "35",
    "NY": "36",
    "NC": "37",
    "ND": "38",
    "OH": "39",
    "OK": "40",
    "OR": "41",
    "PA": "42",
    "RI": "44",
    "SC": "45",
    "SD": "46",
    "TN": "47",
    "TX": "48",
    "UT": "49",
    "VT": "50",
    "VA": "51",
    "WA": "53",
    "WV": "54",
    "WI": "55",
    "WY": "56",
}

FIPS_TO_CODE: Dict[str, str] = {value: key for key, value in CODE_TO_FIPS.items()}

STATE_NEIGHBORS: Dict[str, List[str]] = {
    "AL": ["TN", "GA", "FL", "MS"],
    "AK": [],
    "AZ": ["CA", "NV", "UT", "NM", "CO"],
    "AR": ["MO", "TN", "MS", "LA", "TX", "OK"],
    "CA": ["OR", "NV", "AZ"],
    "CO": ["WY", "NE", "KS", "OK", "NM", "AZ", "UT"],
    "CT": ["MA", "RI", "NY"],
    "DE": ["MD", "PA", "NJ"],
    "DC": ["MD", "VA"],
    "FL": ["GA", "AL"],
    "GA": ["FL", "AL", "TN", "NC", "SC"],
    "HI": [],
    "ID": ["MT", "WY", "UT", "NV", "OR", "WA"],
    "IL": ["WI", "IA", "MO", "KY", "IN"],
    "IN": ["MI", "OH", "KY", "IL"],
    "IA": ["MN", "WI", "IL", "MO", "NE", "SD"],
    "KS": ["NE", "MO", "OK", "CO"],
    "KY": ["IL", "IN", "OH", "WV", "VA", "TN", "MO"],
    "LA": ["TX", "AR", "MS"],
    "ME": ["NH"],
    "MD": ["PA", "DE", "VA", "WV"],
    "MA": ["NH", "RI", "CT", "NY", "VT"],
    "MI": ["OH", "IN", "WI"],
    "MN": ["WI", "IA", "SD", "ND"],
    "MS": ["TN", "AL", "LA", "AR"],
    "MO": ["IA", "IL", "KY", "TN", "AR", "OK", "KS", "NE"],
    "MT": ["ND", "SD", "WY", "ID"],
    "NE": ["SD", "IA", "MO", "KS", "CO", "WY"],
    "NV": ["OR", "ID", "UT", "AZ", "CA"],
    "NH": ["ME", "MA", "VT"],
    "NJ": ["NY", "PA", "DE"],
    "NM": ["CO", "OK", "TX", "AZ"],
    "NY": ["VT", "MA", "CT", "NJ", "PA"],
    "NC": ["VA", "TN", "GA", "SC"],
    "ND": ["MN", "SD", "MT"],
    "OH": ["MI", "PA", "WV", "KY", "IN"],
    "OK": ["KS", "MO", "AR", "TX", "NM", "CO"],
    "OR": ["WA", "ID", "NV", "CA"],
    "PA": ["NY", "NJ", "DE", "MD", "WV", "OH"],
    "RI": ["MA", "CT"],
    "SC": ["NC", "GA"],
    "SD": ["ND", "MN", "IA", "NE", "WY", "MT"],
    "TN": ["KY", "VA", "NC", "GA", "AL", "MS", "AR", "MO"],
    "TX": ["OK", "AR", "LA", "NM"],
    "UT": ["ID", "WY", "CO", "NM", "AZ", "NV"],
    "VT": ["NY", "MA", "NH"],
    "VA": ["MD", "WV", "KY", "TN", "NC", "DC"],
    "WA": ["ID", "OR"],
    "WV": ["OH", "PA", "MD", "VA", "KY"],
    "WI": ["MI", "MN", "IA", "IL"],
    "WY": ["MT", "SD", "NE", "CO", "UT", "ID"],
}


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def election_winner(results: Optional[Dict[str, Any]]) -> str:
    if not isinstance(results, dict):
        return "other"
    biden = int(results.get("bidenj") or results.get("biden") or 0)
    trump = int(results.get("trumpd") or results.get("trump") or 0)
    other = int(results.get("jorgensenj") or results.get("other") or 0)
    if biden > trump and biden >= other:
        return "biden"
    if trump > biden and trump >= other:
        return "trump"
    return "other"


def state_code_from_source(source: Dict[str, Any]) -> str:
    explicit = str(source.get("state_code", "") or "").strip().upper()
    if explicit:
        return explicit
    source_id = str(source.get("id", "") or "")
    path_value = str(source.get("path", "") or "")
    haystack = f"{source_id} {path_value}".lower()
    match = re.search(r"([a-z]{2})_timeline\.json", haystack)
    if match:
        return match.group(1).upper()
    if "pageneralconcatenator" in haystack:
        return "PA"
    return ""


def winner_from_timeseries(payload: Dict[str, Any]) -> str:
    rows = payload.get("timeseries")
    if not isinstance(rows, list):
        return "other"
    for row in reversed(rows):
        if not isinstance(row, dict):
            continue
        votes = int(row.get("votes") or 0)
        if votes <= 0:
            continue
        return election_winner(row.get("results"))
    return "other"


def winner_from_counties(payload: Dict[str, Any]) -> str:
    totals = {"biden": 0, "trump": 0, "other": 0}
    rows = payload.get("county_totals")
    if not isinstance(rows, list):
        return "other"
    for row in rows:
        if not isinstance(row, dict):
            continue
        results = row.get("results")
        if not isinstance(results, dict):
            continue
        totals["biden"] += int(results.get("bidenj") or 0)
        totals["trump"] += int(results.get("trumpd") or 0)
        totals["other"] += int(results.get("jorgensenj") or 0)
    if totals["biden"] > totals["trump"] and totals["biden"] >= totals["other"]:
        return "biden"
    if totals["trump"] > totals["biden"] and totals["trump"] >= totals["other"]:
        return "trump"
    return "other"


def build_county_rows(payload: Dict[str, Any]) -> List[Dict[str, str]]:
    rows = payload.get("county_totals")
    if not isinstance(rows, list):
        return []
    counties: List[Dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        results = row.get("results") if isinstance(row.get("results"), dict) else {}
        fips = str(row.get("locality_fips") or "").strip()
        name = str(row.get("locality_name") or "").strip()
        if not name and not fips:
            continue
        counties.append(
            {
                "fips": fips.zfill(5) if fips and fips.isdigit() else "",
                "name": name,
                "name_key": normalize_name(name),
                "winner": election_winner(results),
            }
        )
    return counties


def build_map_data(payload: Any, state_code: str) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}
    code = str(state_code or payload.get("state") or "").strip().upper()
    state_fips = CODE_TO_FIPS.get(code, "")
    state_winner = winner_from_timeseries(payload)
    if state_winner == "other":
        state_winner = winner_from_counties(payload)
    return {
        "state_code": code,
        "state_fips": state_fips,
        "state_winner": state_winner,
        "neighbors": STATE_NEIGHBORS.get(code, []),
        "counties": build_county_rows(payload),
    }


def summarize_timeline_file(path: Path) -> Optional[Dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    code = path.stem.replace("_timeline", "").upper()
    fips = CODE_TO_FIPS.get(code, "")
    if not fips:
        return None
    winner = winner_from_timeseries(payload)
    if winner == "other":
        winner = winner_from_counties(payload)
    return {"code": code, "fips": fips, "winner": winner}


def build_us_state_winners(data_dir: Path) -> Dict[str, Any]:
    by_fips: Dict[str, str] = {}
    by_code: Dict[str, str] = {}
    if not data_dir.exists():
        return {"by_fips": by_fips, "by_code": by_code}
    for path in sorted(data_dir.glob("*_timeline.json")):
        summary = summarize_timeline_file(path)
        if not summary:
            continue
        by_fips[summary["fips"]] = summary["winner"]
        by_code[summary["code"]] = summary["winner"]
    return {"by_fips": by_fips, "by_code": by_code}

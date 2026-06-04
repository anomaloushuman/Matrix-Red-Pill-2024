from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib import error, request as urlrequest


DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_SLEEP_SECONDS = 0.2
DEFAULT_OUTPUT_DIR = Path("src/voting_data")
DEFAULT_REPORT_PATH = Path("src/voting_data/state_timeline_fetch_report.json")

STATE_SLUGS: Dict[str, str] = {
    "AL": "alabama",
    "AK": "alaska",
    "AZ": "arizona",
    "AR": "arkansas",
    "CA": "california",
    "CO": "colorado",
    "CT": "connecticut",
    "DE": "delaware",
    "FL": "florida",
    "GA": "georgia",
    "HI": "hawaii",
    "ID": "idaho",
    "IL": "illinois",
    "IN": "indiana",
    "IA": "iowa",
    "KS": "kansas",
    "KY": "kentucky",
    "LA": "louisiana",
    "ME": "maine",
    "MD": "maryland",
    "MA": "massachusetts",
    "MI": "michigan",
    "MN": "minnesota",
    "MS": "mississippi",
    "MO": "missouri",
    "MT": "montana",
    "NE": "nebraska",
    "NV": "nevada",
    "NH": "new-hampshire",
    "NJ": "new-jersey",
    "NM": "new-mexico",
    "NY": "new-york",
    "NC": "north-carolina",
    "ND": "north-dakota",
    "OH": "ohio",
    "OK": "oklahoma",
    "OR": "oregon",
    "PA": "pennsylvania",
    "RI": "rhode-island",
    "SC": "south-carolina",
    "SD": "south-dakota",
    "TN": "tennessee",
    "TX": "texas",
    "UT": "utah",
    "VT": "vermont",
    "VA": "virginia",
    "WA": "washington",
    "WV": "west-virginia",
    "WI": "wisconsin",
    "WY": "wyoming",
    "DC": "district-of-columbia",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download and normalize NYT 2020 state race-page timeline data."
    )
    parser.add_argument(
        "--states",
        default=",".join(STATE_SLUGS.keys()),
        help="Comma-separated state codes to fetch (default: all + DC).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where normalized state timeline files are written.",
    )
    parser.add_argument(
        "--report-path",
        default=str(DEFAULT_REPORT_PATH),
        help="Path to write fetch report JSON.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout per request.",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Sleep between state requests.",
    )
    return parser.parse_args()


def _request_json(url: str, timeout_seconds: int) -> Any:
    req = urlrequest.Request(url, headers={"User-Agent": "Matrix-Red-Pill-TimelineFetcher/1.0"})
    with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _normalize_states(raw_states: str) -> List[str]:
    values = [token.strip().upper() for token in raw_states.split(",")]
    normalized: List[str] = []
    for value in values:
        if not value:
            continue
        if value in STATE_SLUGS:
            normalized.append(value)
    return normalized


def _to_int(value: Any) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return 0


def _extract_timeseries(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    races = data.get("races")
    if not isinstance(races, list) or not races:
        return []

    race = races[0] if isinstance(races[0], dict) else {}
    rows = race.get("timeseries")
    if not isinstance(rows, list):
        return []

    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        timestamp = row.get("timestamp")
        votes = _to_int(row.get("votes"))
        if not isinstance(timestamp, str) or not timestamp:
            continue
        shares = row.get("vote_shares")
        shares_dict = shares if isinstance(shares, dict) else {}

        biden_share = float(shares_dict.get("bidenj", 0) or 0)
        trump_share = float(shares_dict.get("trumpd", 0) or 0)
        biden_votes = max(0, _to_int(votes * biden_share))
        trump_votes = max(0, _to_int(votes * trump_share))
        third_party_votes = max(0, votes - biden_votes - trump_votes)

        normalized_rows.append(
            {
                "timestamp": timestamp,
                "votes": votes,
                "results": {
                    "bidenj": biden_votes,
                    "trumpd": trump_votes,
                    "jorgensenj": third_party_votes,
                },
                "vote_shares": {
                    "bidenj": biden_share,
                    "trumpd": trump_share,
                },
            }
        )

    return normalized_rows


def _sum_results(results: Dict[str, Any]) -> int:
    return sum(_to_int(v) for v in results.values())


def _subtract_results(total: Dict[str, Any], absentee: Dict[str, Any]) -> Dict[str, int]:
    keys = set(total.keys()) | set(absentee.keys())
    derived: Dict[str, int] = {}
    for key in keys:
        derived[str(key)] = max(0, _to_int(total.get(key)) - _to_int(absentee.get(key)))
    return derived


def _normalize_vote_type_row(
    locality_name: str,
    vote_type: str,
    results: Dict[str, Any],
    *,
    locality_fips: str = "",
) -> Dict[str, Any]:
    result_dict = {str(k): _to_int(v) for k, v in results.items() if isinstance(k, str)}
    return {
        "locality_name": locality_name,
        "locality_fips": locality_fips,
        "vote_type": vote_type,
        "votes": _sum_results(result_dict),
        "results": result_dict,
    }


def _derive_county_by_vote_type_from_counties(counties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build absentee + electionday rows from race-page county results splits."""
    rows: List[Dict[str, Any]] = []
    for county in counties:
        if not isinstance(county, dict):
            continue
        locality_name = str(county.get("name", "") or "")
        locality_fips = str(county.get("fips", "") or "")
        total_results = county.get("results")
        absentee_results = county.get("results_absentee")
        if not isinstance(total_results, dict):
            continue

        total_dict = {str(k): _to_int(v) for k, v in total_results.items() if isinstance(k, str)}
        if not total_dict:
            continue

        if isinstance(absentee_results, dict) and absentee_results:
            absentee_dict = {
                str(k): _to_int(v) for k, v in absentee_results.items() if isinstance(k, str)
            }
            absentee_votes = _to_int(county.get("absentee_votes"))
            if absentee_votes <= 0:
                absentee_votes = _sum_results(absentee_dict)
            if absentee_votes > 0:
                absentee_row = _normalize_vote_type_row(
                    locality_name,
                    "absentee",
                    absentee_dict,
                    locality_fips=locality_fips,
                )
                absentee_row["votes"] = absentee_votes
                rows.append(absentee_row)

            in_person = _subtract_results(total_dict, absentee_dict)
            in_person_votes = _sum_results(in_person)
            if in_person_votes > 0:
                rows.append(
                    _normalize_vote_type_row(
                        locality_name,
                        "electionday",
                        in_person,
                        locality_fips=locality_fips,
                    )
                )
        else:
            rows.append(
                _normalize_vote_type_row(
                    locality_name,
                    "total",
                    total_dict,
                    locality_fips=locality_fips,
                )
            )

    return rows


def _extract_county_totals(payload: Any) -> List[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, dict):
        return []
    races = data.get("races")
    if not isinstance(races, list) or not races:
        return []
    race = races[0] if isinstance(races[0], dict) else {}
    counties = race.get("counties")
    if not isinstance(counties, list):
        return []

    rows: List[Dict[str, Any]] = []
    for county in counties:
        if not isinstance(county, dict):
            continue
        results = county.get("results")
        result_dict = results if isinstance(results, dict) else {}
        rows.append(
            {
                "locality_name": county.get("name", ""),
                "locality_fips": county.get("fips", ""),
                "votes": _to_int(county.get("votes")),
                "absentee_votes": _to_int(county.get("absentee_votes")),
                "precincts": _to_int(county.get("precincts")),
                "is_reporting": bool(county.get("reporting", True)),
                "results": {
                    str(k): _to_int(v) for k, v in result_dict.items() if isinstance(k, str)
                },
                "last_updated": county.get("last_updated"),
            }
        )
    return rows


def _aggregate_precinct_vote_types(precincts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[tuple[str, str], Dict[str, Any]] = {}
    for row in precincts:
        if not isinstance(row, dict):
            continue
        locality_name = str(row.get("locality_name", "") or "")
        vote_type = str(row.get("vote_type", "") or "unknown")
        key = (locality_name, vote_type)
        if key not in grouped:
            grouped[key] = {
                "locality_name": locality_name,
                "vote_type": vote_type,
                "votes": 0,
                "results": {},
            }

        grouped[key]["votes"] += _to_int(row.get("votes"))
        results = row.get("results")
        if isinstance(results, dict):
            for cand, value in results.items():
                cand_key = str(cand)
                grouped[key]["results"][cand_key] = grouped[key]["results"].get(cand_key, 0) + _to_int(value)

    return list(grouped.values())


def _scale_vote_type_rows(rows: List[Dict[str, Any]], scale: float) -> List[Dict[str, Any]]:
    if scale <= 0:
        return []
    scaled_rows: List[Dict[str, Any]] = []
    for row in rows:
        results = row.get("results")
        result_dict = results if isinstance(results, dict) else {}
        scaled_results = {
            str(key): int(round(_to_int(value) * scale))
            for key, value in result_dict.items()
            if isinstance(key, str)
        }
        votes = _to_int(row.get("votes"))
        if votes > 0:
            votes = int(round(votes * scale))
        else:
            votes = _sum_results(scaled_results)
        scaled_rows.append(
            {
                "locality_name": row.get("locality_name", ""),
                "locality_fips": row.get("locality_fips", ""),
                "vote_type": row.get("vote_type", "unknown"),
                "votes": votes,
                "results": scaled_results,
            }
        )
    return scaled_rows


def _build_versioned_snapshots(
    timeseries: List[Dict[str, Any]],
    base_rows: List[Dict[str, Any]],
    method: str,
) -> List[Dict[str, Any]]:
    """Attach county + ballot-type rows to each reporting update (timeseries vote change)."""
    if not timeseries or not base_rows:
        return []

    ordered = sorted(
        [point for point in timeseries if isinstance(point, dict) and point.get("timestamp")],
        key=lambda point: str(point["timestamp"]),
    )
    final_votes = 0
    for point in reversed(ordered):
        final_votes = _to_int(point.get("votes"))
        if final_votes > 0:
            break
    if final_votes <= 0:
        return []

    snapshots: List[Dict[str, Any]] = []
    previous_votes = -1
    for point in ordered:
        votes = _to_int(point.get("votes"))
        if votes <= 0 or votes == previous_votes:
            continue
        previous_votes = votes
        scale = votes / float(final_votes)
        snapshots.append(
            {
                "timestamp": str(point["timestamp"]),
                "total_votes": votes,
                "county_by_vote_type": _scale_vote_type_rows(base_rows, scale),
                "method": method,
            }
        )
    return snapshots


def _fetch_general_concatenator_vote_types(
    state_code: str, timeout_seconds: int
) -> tuple[List[Dict[str, Any]], Optional[str], str]:
    url = (
        "https://static01.nyt.com/elections-assets/2020/data/api/2020-11-03/precincts/"
        f"{state_code}GeneralConcatenator-latest.json"
    )
    try:
        payload = _request_json(url, timeout_seconds=timeout_seconds)
        if not isinstance(payload, dict):
            return [], None, "Concatenator payload is not an object."

        county_by_vote_type = payload.get("county_by_vote_type")
        if isinstance(county_by_vote_type, list) and county_by_vote_type:
            normalized: List[Dict[str, Any]] = []
            for row in county_by_vote_type:
                if not isinstance(row, dict):
                    continue
                results = row.get("results")
                result_dict = results if isinstance(results, dict) else {}
                normalized.append(
                    {
                        "locality_name": str(row.get("locality_name", "") or ""),
                        "vote_type": str(row.get("vote_type", "") or "unknown"),
                        "votes": _to_int(row.get("votes")),
                        "results": {
                            str(k): _to_int(v)
                            for k, v in result_dict.items()
                            if isinstance(k, str)
                        },
                    }
                )
            return normalized, url, ""

        precincts = payload.get("precincts")
        if isinstance(precincts, list) and precincts:
            formatted_precincts = [row for row in precincts if isinstance(row, dict)]
            return _aggregate_precinct_vote_types(formatted_precincts), url, ""

        return [], url, "No county_by_vote_type or precincts list in concatenator."
    except error.HTTPError as exc:
        return [], None, f"HTTP {exc.code}"
    except (error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [], None, f"{type(exc).__name__}: {exc}"


def fetch_state_timeline(state_code: str, timeout_seconds: int) -> Dict[str, Any]:
    slug = STATE_SLUGS[state_code]
    url = (
        "https://static01.nyt.com/elections-assets/2020/data/api/2020-11-03/"
        f"race-page/{slug}/president.json"
    )

    result: Dict[str, Any] = {
        "state": state_code,
        "slug": slug,
        "url": url,
        "success": False,
        "rows": 0,
        "error": "",
    }

    try:
        payload = _request_json(url, timeout_seconds=timeout_seconds)
        rows = _extract_timeseries(payload)
        county_totals = _extract_county_totals(payload)
        county_by_vote_type, concat_url, concat_error = _fetch_general_concatenator_vote_types(
            state_code=state_code,
            timeout_seconds=timeout_seconds,
        )
        derived_vote_types: List[Dict[str, Any]] = []
        if isinstance(payload, dict):
            data_block = payload.get("data")
            races_block = data_block.get("races") if isinstance(data_block, dict) else []
            race = races_block[0] if isinstance(races_block, list) and races_block else {}
            counties = race.get("counties") if isinstance(race, dict) else []
            if isinstance(counties, list):
                derived_vote_types = _derive_county_by_vote_type_from_counties(counties)

        county_count = len(county_totals)
        concat_covers_state = bool(county_by_vote_type) and (
            county_count == 0 or len(county_by_vote_type) >= county_count
        )
        if concat_covers_state:
            vote_type_method = "concatenator"
        elif derived_vote_types:
            county_by_vote_type = derived_vote_types
            vote_type_method = "derived_county_absentee_split"
            concat_url = url
            concat_error = ""
        elif county_by_vote_type:
            vote_type_method = "concatenator_partial"
        else:
            vote_type_method = ""
        if not rows:
            result["error"] = "No usable timeseries rows found."
            return result
        result["success"] = True
        result["rows"] = len(rows)
        result["county_rows"] = len(county_totals)
        result["vote_type_rows"] = len(county_by_vote_type)
        result["vote_type_method"] = vote_type_method
        if concat_error:
            result["vote_type_error"] = concat_error

        snapshot_method = (
            f"{vote_type_method}_timeseries"
            if vote_type_method
            else "county_totals_timeseries"
        )
        versioned_snapshots = _build_versioned_snapshots(
            rows,
            county_by_vote_type,
            snapshot_method,
        )
        result["snapshot_count"] = len(versioned_snapshots)

        result["payload"] = {
            "source": "nyt-race-page",
            "state": state_code,
            "slug": slug,
            "url": url,
            "county_totals_source": url,
            "county_by_vote_type_source": concat_url,
            "county_by_vote_type_method": vote_type_method,
            "versioned_snapshots_method": snapshot_method,
            "fetched_at_unix": int(time.time()),
            "timeseries": rows,
            "county_totals": county_totals,
            "county_by_vote_type": county_by_vote_type,
            "versioned_snapshots": versioned_snapshots,
        }
        return result
    except error.HTTPError as exc:
        result["error"] = f"HTTP {exc.code}"
        return result
    except (error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result


def main() -> None:
    args = parse_args()
    states = _normalize_states(args.states)
    if not states:
        raise SystemExit("No valid states provided.")

    output_dir = Path(args.output_dir).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    report_rows: List[Dict[str, Any]] = []

    for state in states:
        result = fetch_state_timeline(state, timeout_seconds=max(5, int(args.timeout_seconds)))
        if result.get("success"):
            output_path = output_dir / f"{state.lower()}_timeline.json"
            output_path.write_text(json.dumps(result["payload"], ensure_ascii=True, indent=2))
            result["output_file"] = str(output_path)
            print(
                f"[OK] {state} -> {output_path.name} "
                f"(timeseries={result['rows']}, snapshots={result.get('snapshot_count', 0)}, "
                f"counties={result.get('county_rows', 0)}, vote_types={result.get('vote_type_rows', 0)})"
            )
        else:
            print(f"[MISS] {state} -> {result['error']}")
        result.pop("payload", None)
        report_rows.append(result)
        if args.sleep_seconds > 0:
            time.sleep(float(args.sleep_seconds))

    success_count = sum(1 for row in report_rows if row.get("success"))
    report = {
        "generated_at_unix": int(time.time()),
        "states_requested": states,
        "success_count": success_count,
        "missing_count": len(report_rows) - success_count,
        "results": report_rows,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=True, indent=2))
    print("")
    print(f"Wrote report to {report_path}")
    print(f"Succeeded: {success_count} | Missing: {len(report_rows) - success_count}")


if __name__ == "__main__":
    main()

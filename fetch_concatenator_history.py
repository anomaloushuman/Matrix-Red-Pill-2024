from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib import error, request as urlrequest

from fetch_state_timelines import (
    _aggregate_precinct_vote_types,
    _normalize_states,
    _request_json,
    _to_int,
)


CONCATENATOR_STATES = {"FL", "MI", "PA"}
DEFAULT_OUTPUT_DIR = Path("src/voting_data")
DEFAULT_WORKERS = 24


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch historical NYT GeneralConcatenator snapshots and merge them "
            "into state timeline files as versioned_snapshots."
        )
    )
    parser.add_argument("--states", default="PA,FL,MI", help="Comma-separated state codes.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--max-probes-per-second", type=int, default=1000)
    parser.add_argument("--timeout-seconds", type=int, default=12)
    return parser.parse_args()


def _normalize_concatenator_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    county_by_vote_type = payload.get("county_by_vote_type")
    if isinstance(county_by_vote_type, list) and county_by_vote_type:
        rows: List[Dict[str, Any]] = []
        for row in county_by_vote_type:
            if not isinstance(row, dict):
                continue
            results = row.get("results")
            result_dict = results if isinstance(results, dict) else {}
            rows.append(
                {
                    "locality_name": str(row.get("locality_name", "") or ""),
                    "vote_type": str(row.get("vote_type", "") or "unknown"),
                    "votes": _to_int(row.get("votes")),
                    "results": {
                        str(key): _to_int(value)
                        for key, value in result_dict.items()
                        if isinstance(key, str)
                    },
                }
            )
        return rows

    precincts = payload.get("precincts")
    if isinstance(precincts, list):
        return _aggregate_precinct_vote_types([row for row in precincts if isinstance(row, dict)])
    return []


def _vote_change_seconds(timeseries: List[Dict[str, Any]]) -> List[str]:
    ordered = sorted(
        [point for point in timeseries if isinstance(point, dict) and point.get("timestamp")],
        key=lambda point: str(point["timestamp"]),
    )
    seconds: List[str] = []
    previous_votes = -1
    for point in ordered:
        votes = _to_int(point.get("votes"))
        if votes <= 0 or votes == previous_votes:
            continue
        previous_votes = votes
        timestamp = str(point["timestamp"])
        second = timestamp.split(".")[0]
        if not second.endswith("Z"):
            second = f"{second}Z"
        seconds.append(second)
    return seconds


def _probe_second(
    state_code: str,
    second_timestamp: str,
    timeout_seconds: int,
    max_probes: int,
) -> Optional[Dict[str, Any]]:
    prefix = (
        "https://static01.nyt.com/elections-assets/2020/data/api/2020-11-03/precincts/"
        f"{state_code}GeneralConcatenator-{second_timestamp}."
    )

    def try_ms(millisecond: int) -> Optional[Dict[str, Any]]:
        url = f"{prefix}{millisecond:03d}Z.json"
        try:
            payload = _request_json(url, timeout_seconds=timeout_seconds)
            if not isinstance(payload, dict):
                return None
            rows = _normalize_concatenator_rows(payload)
            if not rows:
                return None
            return {
                "timestamp": f"{second_timestamp}.{millisecond:03d}Z",
                "total_votes": sum(row.get("votes", 0) for row in rows),
                "county_by_vote_type": rows,
                "method": "concatenator_historical",
                "source_url": url,
            }
        except (error.HTTPError, error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError):
            return None

    for millisecond in range(0, max_probes):
        snapshot = try_ms(millisecond)
        if snapshot is not None:
            return snapshot
    return None


def _discover_snapshots(
    state_code: str,
    timeseries: List[Dict[str, Any]],
    workers: int,
    timeout_seconds: int,
    max_probes: int,
) -> List[Dict[str, Any]]:
    targets = _vote_change_seconds(timeseries)
    snapshots: List[Dict[str, Any]] = []
    seen_seconds: Set[str] = set()

    probe_seconds: List[str] = []
    for second in targets:
        if second in seen_seconds:
            continue
        seen_seconds.add(second)
        probe_seconds.append(second)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {
            pool.submit(_probe_second, state_code, second, timeout_seconds, max_probes): second
            for second in probe_seconds
        }
        for future in as_completed(futures):
            snapshot = future.result()
            if snapshot is not None:
                snapshots.append(snapshot)

    snapshots.sort(key=lambda row: str(row["timestamp"]))
    return snapshots


def _merge_snapshots(
    existing: List[Dict[str, Any]], historical: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for snapshot in existing:
        if isinstance(snapshot, dict) and snapshot.get("timestamp"):
            merged[str(snapshot["timestamp"])] = snapshot
    for snapshot in historical:
        if not isinstance(snapshot, dict) or not snapshot.get("timestamp"):
            continue
        timestamp = str(snapshot["timestamp"])
        second = timestamp.split(".")[0] + "Z"
        replaced = False
        for key in list(merged.keys()):
            if key.split(".")[0] + "Z" == second:
                merged[key] = snapshot
                replaced = True
        if not replaced:
            merged[timestamp] = snapshot
    return [merged[key] for key in sorted(merged.keys())]


def enrich_state_timeline(
    state_code: str,
    output_dir: Path,
    workers: int,
    timeout_seconds: int,
    max_probes: int,
) -> Dict[str, Any]:
    timeline_path = output_dir / f"{state_code.lower()}_timeline.json"
    if not timeline_path.exists():
        return {"state": state_code, "success": False, "error": f"Missing {timeline_path}"}

    timeline = json.loads(timeline_path.read_text())
    timeseries = timeline.get("timeseries")
    if not isinstance(timeseries, list):
        return {"state": state_code, "success": False, "error": "Timeline has no timeseries."}

    historical = _discover_snapshots(
        state_code=state_code,
        timeseries=timeseries,
        workers=workers,
        timeout_seconds=timeout_seconds,
        max_probes=max_probes,
    )
    existing = timeline.get("versioned_snapshots")
    existing_rows = existing if isinstance(existing, list) else []
    timeline["versioned_snapshots"] = _merge_snapshots(existing_rows, historical)
    timeline["versioned_snapshots_method"] = (
        "concatenator_historical+timeseries"
        if historical
        else timeline.get("versioned_snapshots_method", "")
    )
    timeline["concatenator_historical_count"] = len(historical)
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=True, indent=2))
    return {
        "state": state_code,
        "success": True,
        "historical_snapshots": len(historical),
        "total_snapshots": len(timeline["versioned_snapshots"]),
        "output_file": str(timeline_path),
    }


def main() -> None:
    args = parse_args()
    states = [state for state in _normalize_states(args.states) if state in CONCATENATOR_STATES]
    if not states:
        raise SystemExit(f"No valid states. Use one of: {sorted(CONCATENATOR_STATES)}")

    output_dir = Path(args.output_dir).expanduser().resolve()
    for state in states:
        result = enrich_state_timeline(
            state_code=state,
            output_dir=output_dir,
            workers=max(1, int(args.workers)),
            timeout_seconds=max(5, int(args.timeout_seconds)),
            max_probes=max(1, int(args.max_probes_per_second)),
        )
        if result.get("success"):
            print(
                f"[OK] {state}: historical={result['historical_snapshots']} "
                f"total={result['total_snapshots']} -> {result['output_file']}"
            )
        else:
            print(f"[MISS] {state}: {result.get('error')}")


if __name__ == "__main__":
    main()

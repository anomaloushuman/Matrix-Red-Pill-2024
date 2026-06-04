from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib import error, request as urlrequest


DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_RETRIES = 3
DEFAULT_SLEEP_SECONDS = 0.4
DEFAULT_OUTPUT_DIR = Path("src/voting_data")
DEFAULT_REPORT_PATH = Path("src/voting_data/concatenator_fetch_report.json")

STATE_CODES = [
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
    "DC",
]

URL_TEMPLATES = [
    "https://static01.nyt.com/elections-assets/2020/data/api/2020-11-03/precincts/{state}GeneralConcatenator-latest.json",
    "https://static01.nyt.com/elections-assets/2020/data/api/2020-11-03/counties/{state}GeneralConcatenator-latest.json",
    "https://static01.nyt.com/elections-assets/2020/data/api/2020-11-03/state/{state}GeneralConcatenator-latest.json",
    "https://static01.nyt.com/elections-assets/2020/data/api/2020-11-03/races/{state}GeneralConcatenator-latest.json",
]


@dataclass
class FetchResult:
    state: str
    success: bool
    output_file: Optional[str]
    source_url: Optional[str]
    status_code: Optional[int]
    top_level_keys: List[str]
    payload_type: str
    payload_size_bytes: int
    errors: List[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download NYT 2020 GeneralConcatenator JSON payloads by state."
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory where state JSON files are written.",
    )
    parser.add_argument(
        "--report-path",
        default=str(DEFAULT_REPORT_PATH),
        help="Path where the fetch report JSON is written.",
    )
    parser.add_argument(
        "--states",
        default=",".join(STATE_CODES),
        help="Comma-separated state codes to fetch (default: all + DC).",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout per request.",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=DEFAULT_RETRIES,
        help="Retries per URL template (network/5xx only).",
    )
    parser.add_argument(
        "--sleep-seconds",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        help="Sleep between requests to avoid hammering endpoints.",
    )
    return parser.parse_args()


def _request_json(url: str, timeout_seconds: int) -> tuple[Any, int, bytes]:
    req = urlrequest.Request(url, headers={"User-Agent": "Matrix-Red-Pill-Downloader/1.0"})
    with urlrequest.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read()
        status = int(getattr(resp, "status", 200))
    payload = json.loads(raw.decode("utf-8"))
    return payload, status, raw


def _normalize_states(raw_states: str) -> List[str]:
    values = [token.strip().upper() for token in raw_states.split(",")]
    return [state for state in values if state]


def _top_level_keys(payload: Any) -> List[str]:
    if isinstance(payload, dict):
        return sorted([str(key) for key in payload.keys()])[:30]
    return []


def fetch_one_state(
    state: str,
    output_dir: Path,
    timeout_seconds: int,
    retries: int,
    sleep_seconds: float,
) -> FetchResult:
    errors_seen: List[str] = []

    for template in URL_TEMPLATES:
        url = template.format(state=state)
        for attempt in range(1, retries + 1):
            try:
                payload, status_code, raw = _request_json(url, timeout_seconds=timeout_seconds)
                output_name = f"{state}GeneralConcatenator-latest.json"
                output_path = output_dir / output_name
                output_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2))
                return FetchResult(
                    state=state,
                    success=True,
                    output_file=str(output_path),
                    source_url=url,
                    status_code=status_code,
                    top_level_keys=_top_level_keys(payload),
                    payload_type=type(payload).__name__,
                    payload_size_bytes=len(raw),
                    errors=errors_seen,
                )
            except error.HTTPError as exc:
                errors_seen.append(f"{url} [attempt {attempt}/{retries}] HTTP {exc.code}")
                # 4xx means this pattern is likely unavailable for this state.
                if 400 <= int(exc.code) < 500:
                    break
            except (error.URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                errors_seen.append(f"{url} [attempt {attempt}/{retries}] {type(exc).__name__}: {exc}")

            if attempt < retries and sleep_seconds > 0:
                time.sleep(sleep_seconds)

    return FetchResult(
        state=state,
        success=False,
        output_file=None,
        source_url=None,
        status_code=None,
        top_level_keys=[],
        payload_type="",
        payload_size_bytes=0,
        errors=errors_seen,
    )


def write_report(path: Path, report: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=True, indent=2))


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    states = _normalize_states(args.states)
    if not states:
        raise SystemExit("No states were provided.")

    output_dir.mkdir(parents=True, exist_ok=True)

    results: List[FetchResult] = []
    for state in states:
        result = fetch_one_state(
            state=state,
            output_dir=output_dir,
            timeout_seconds=max(1, int(args.timeout_seconds)),
            retries=max(1, int(args.retries)),
            sleep_seconds=max(0.0, float(args.sleep_seconds)),
        )
        results.append(result)
        marker = "OK" if result.success else "MISS"
        print(f"[{marker}] {state}: {result.source_url or 'no matching endpoint'}")

    successes = [r for r in results if r.success]
    misses = [r for r in results if not r.success]

    report = {
        "generated_at_unix": int(time.time()),
        "output_dir": str(output_dir),
        "states_requested": states,
        "states_succeeded": [r.state for r in successes],
        "states_missing": [r.state for r in misses],
        "success_count": len(successes),
        "missing_count": len(misses),
        "results": [r.__dict__ for r in results],
    }
    write_report(report_path, report)
    print("")
    print(f"Wrote report to {report_path}")
    print(f"Succeeded: {len(successes)} | Missing: {len(misses)}")


if __name__ == "__main__":
    main()

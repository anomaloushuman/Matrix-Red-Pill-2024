from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib import error, request as urlrequest

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from flask import Flask, jsonify, render_template, request, url_for

from map_data import build_map_data, state_code_from_source
from state_labels import (
    PATRIOT_PURPLE,
    format_jurisdiction_label,
    jurisdiction_name,
    label_for_local_json,
)


TIMESTAMP_KEYS = [
    "timestamp",
    "ts",
    "time",
    "updated_at",
    "last_updated",
    "lastUpdate",
    "created_at",
    "datetime",
]

CANDIDATE_ALIASES = {
    "biden": ["bidenj", "biden", "joseph r biden jr", "joseph biden", "dem"],
    "trump": ["trumpd", "trump", "donald trump", "gop", "rep"],
    "third_party": ["jorgensenj", "jorgensen", "libertarian", "other"],
}

TOTAL_KEYS = ["votes", "total_votes", "total", "vote_count", "tot_votes"]
VOTE_TYPE_COLORS = {
    "absentee": "#3b82f6",
    "electionday": "#ef233c",
    "provisional": PATRIOT_PURPLE,
}
CANDIDATE_COLORS = {
    "biden": "#3b82f6",
    "trump": "#ef233c",
    "other": PATRIOT_PURPLE,
}
MANIFEST_PATH = Path("config/sources.json")
ROOT_DIR = Path(__file__).parent.resolve()
DEFAULT_TIMEOUT_SECONDS = 15

app = Flask(__name__)


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def find_json_files(root: Path) -> List[Path]:
    return sorted(root.glob("*.json"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(value: Any) -> Optional[pd.Timestamp]:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts
    except (TypeError, ValueError):
        return None


def iter_dict_records(node: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from iter_dict_records(value)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, (dict, list)):
                yield from iter_dict_records(item)


def _extract_numeric_from_dict(dct: Dict[str, Any], keys: List[str]) -> Optional[float]:
    lowered = {str(k).strip().lower(): v for k, v in dct.items()}
    for key in keys:
        val = lowered.get(key)
        if isinstance(val, (int, float)):
            return float(val)
    return None


def safe_parse_int(value: str, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def safe_parse_float(value: str, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(min_value, min(max_value, parsed))


def parse_filter_timestamp(value: str) -> Optional[pd.Timestamp]:
    if not value:
        return None
    return parse_timestamp(value)


def extract_timepoint(record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    lowered = {str(k).strip().lower(): v for k, v in record.items()}

    timestamp = None
    for key in TIMESTAMP_KEYS:
        timestamp = parse_timestamp(lowered.get(key))
        if timestamp is not None:
            break

    if timestamp is None:
        return None

    results_container = lowered.get("results")
    results = results_container if isinstance(results_container, dict) else {}
    lowered_results = {str(k).strip().lower(): v for k, v in results.items()}

    point: Dict[str, Any] = {"timestamp": timestamp}
    numeric_found = False

    for candidate, aliases in CANDIDATE_ALIASES.items():
        value = _extract_numeric_from_dict(lowered_results, aliases)
        if value is None:
            value = _extract_numeric_from_dict(lowered, aliases)
        if value is not None:
            point[candidate] = value
            numeric_found = True
        else:
            point[candidate] = 0.0

    total_votes = _extract_numeric_from_dict(lowered_results, TOTAL_KEYS)
    if total_votes is None:
        total_votes = _extract_numeric_from_dict(lowered, TOTAL_KEYS)
    if total_votes is not None:
        point["total_votes"] = total_votes
        numeric_found = True
    else:
        point["total_votes"] = point["biden"] + point["trump"] + point["third_party"]

    return point if numeric_found else None


def build_timeseries(payload: Any) -> pd.DataFrame:
    aggregated: Dict[pd.Timestamp, Dict[str, float]] = {}

    for record in iter_dict_records(payload):
        point = extract_timepoint(record)
        if point is None:
            continue
        ts = point["timestamp"]
        if ts not in aggregated:
            aggregated[ts] = {
                "biden": 0.0,
                "trump": 0.0,
                "third_party": 0.0,
                "total_votes": 0.0,
            }
        for key in ("biden", "trump", "third_party", "total_votes"):
            aggregated[ts][key] += float(point.get(key, 0.0))

    if not aggregated:
        return pd.DataFrame()

    df = (
        pd.DataFrame([{"timestamp": ts, **vals} for ts, vals in aggregated.items()])
        .sort_values("timestamp")
        .drop_duplicates(subset=["timestamp"], keep="last")
    )
    return df.reset_index(drop=True)


def build_version_index(df: pd.DataFrame) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    working = df.copy().sort_values("timestamp").reset_index(drop=True)
    working["delta_votes"] = working["total_votes"].diff().fillna(0)
    working["version_id"] = working["timestamp"].astype(str)

    rows: List[Dict[str, Any]] = []
    for idx, row in working.iterrows():
        rows.append(
            {
                "version_id": str(row["version_id"]),
                "version_label": f"V{idx + 1:04d}",
                "timestamp": str(row["timestamp"]),
                "total_votes": int(row["total_votes"]),
                "delta_votes": int(row["delta_votes"]),
                "biden": int(row["biden"]),
                "trump": int(row["trump"]),
                "third_party": int(row["third_party"]),
            }
        )
    return rows


def filter_timeseries_window(
    df: pd.DataFrame,
    start_ts: Optional[pd.Timestamp],
    end_ts: Optional[pd.Timestamp],
) -> pd.DataFrame:
    if df.empty:
        return df
    filtered = df.copy()
    if start_ts is not None:
        filtered = filtered[filtered["timestamp"] >= start_ts]
    if end_ts is not None:
        filtered = filtered[filtered["timestamp"] <= end_ts]
    return filtered.reset_index(drop=True)


def detect_stop_count_events(
    df: pd.DataFrame,
    min_gap_minutes: int = 45,
    cadence_multiplier: float = 4.0,
) -> pd.DataFrame:
    if df.empty or len(df) < 3:
        return pd.DataFrame()

    analysis = df.copy().sort_values("timestamp").reset_index(drop=True)
    analysis["delta_votes"] = analysis["total_votes"].diff()
    analysis["delta_minutes"] = (
        analysis["timestamp"].diff().dt.total_seconds().div(60).fillna(0)
    )

    positive_intervals = analysis.loc[
        (analysis["delta_votes"] > 0) & (analysis["delta_minutes"] > 0), "delta_minutes"
    ]
    cadence = float(positive_intervals.median()) if not positive_intervals.empty else 5.0
    stop_threshold = max(float(min_gap_minutes), cadence * float(cadence_multiplier))

    positive_vote_deltas = analysis.loc[analysis["delta_votes"] > 0, "delta_votes"]
    burst_threshold = (
        float(positive_vote_deltas.quantile(0.9)) if not positive_vote_deltas.empty else 0.0
    )

    events: List[Dict[str, Any]] = []
    for idx in range(1, len(analysis)):
        gap_minutes = float(analysis.loc[idx, "delta_minutes"])
        if gap_minutes < stop_threshold:
            continue

        next_total = float(analysis.loc[idx, "total_votes"])
        prev_total = float(analysis.loc[idx - 1, "total_votes"])
        post_gap_added = max(0.0, next_total - prev_total)

        events.append(
            {
                "event_id": len(events) + 1,
                "stop_start": analysis.loc[idx - 1, "timestamp"],
                "stop_end": analysis.loc[idx, "timestamp"],
                "stop_gap_minutes": round(gap_minutes, 2),
                "votes_added_after_gap": int(post_gap_added),
                "is_large_post_gap_burst": bool(
                    post_gap_added >= burst_threshold and burst_threshold > 0
                ),
                "burst_threshold_votes": int(round(burst_threshold)),
            }
        )

    return pd.DataFrame(events)


def county_vote_type_records_for_version(
    payload: Dict[str, Any], version_ts: Optional[str] = None
) -> List[Dict[str, Any]]:
    snapshots = payload.get("versioned_snapshots")
    if isinstance(snapshots, list) and snapshots:
        if version_ts:
            for snapshot in snapshots:
                if isinstance(snapshot, dict) and snapshot.get("timestamp") == version_ts:
                    records = snapshot.get("county_by_vote_type")
                    return records if isinstance(records, list) else []

            eligible = [
                snapshot
                for snapshot in snapshots
                if isinstance(snapshot, dict)
                and isinstance(snapshot.get("timestamp"), str)
                and snapshot["timestamp"] <= version_ts
            ]
            if eligible:
                eligible.sort(key=lambda row: str(row["timestamp"]))
                records = eligible[-1].get("county_by_vote_type")
                return records if isinstance(records, list) else []

        last_snapshot = snapshots[-1]
        if isinstance(last_snapshot, dict):
            records = last_snapshot.get("county_by_vote_type")
            return records if isinstance(records, list) else []

    records = payload.get("county_by_vote_type")
    return records if isinstance(records, list) else []


def extract_county_vote_type(payload: Any, version_ts: Optional[str] = None) -> pd.DataFrame:
    if not isinstance(payload, dict):
        return pd.DataFrame()

    records = county_vote_type_records_for_version(payload, version_ts=version_ts)
    if not records:
        return pd.DataFrame()

    parsed_rows: List[Dict[str, Any]] = []
    for row in records:
        if not isinstance(row, dict):
            continue
        results = row.get("results", {}) if isinstance(row.get("results"), dict) else {}
        parsed_rows.append(
            {
                "county": row.get("locality_name", "unknown"),
                "vote_type": row.get("vote_type", "unknown"),
                "votes": float(row.get("votes", 0) or 0),
                "biden": float(results.get("bidenj", 0) or 0),
                "trump": float(results.get("trumpd", 0) or 0),
                "third_party": float(results.get("jorgensenj", 0) or 0),
            }
        )

    return pd.DataFrame(parsed_rows)


def extract_pa_vote_type(payload: Any, version_ts: Optional[str] = None) -> pd.DataFrame:
    return extract_county_vote_type(payload, version_ts=version_ts)


def create_schema_fingerprint(payload: Any) -> Dict[str, Any]:
    top_level_keys: List[str] = []
    record_key_signatures: List[List[str]] = []

    if isinstance(payload, dict):
        top_level_keys = sorted([str(k) for k in payload.keys()])[:25]

    unique_signatures: Dict[Tuple[str, ...], bool] = {}
    for record in iter_dict_records(payload):
        signature = tuple(sorted([str(k) for k in record.keys()])[:20])
        if signature and signature not in unique_signatures:
            unique_signatures[signature] = True
        if len(unique_signatures) >= 5:
            break

    record_key_signatures = [list(sig) for sig in list(unique_signatures.keys())[:5]]
    normalized_repr = json.dumps(
        {"top_level_keys": top_level_keys, "record_signatures": record_key_signatures},
        sort_keys=True,
    )
    digest = hashlib.sha256(normalized_repr.encode("utf-8")).hexdigest()[:16]
    return {
        "hash": digest,
        "top_level_keys": top_level_keys,
        "record_signatures": record_key_signatures,
    }


def load_source_manifest(manifest_path: Path) -> List[Dict[str, Any]]:
    payload = load_json(manifest_path)
    if not isinstance(payload, dict):
        return []

    items = payload.get("sources")
    if not isinstance(items, list):
        return []

    normalized: List[Dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            continue
        if raw.get("enabled", True) is False:
            continue
        source_id = str(raw.get("id", "")).strip()
        if not source_id:
            continue
        normalized.append(
            {
                "id": source_id,
                "label": str(raw.get("label", source_id)),
                "dataset_group": str(raw.get("dataset_group", "timeline")),
                "type": str(raw.get("type", "local_file")),
                "parser_hint": str(raw.get("parser_hint", "timeline")),
                "notes": str(raw.get("notes", "")),
                "path": raw.get("path"),
                "endpoint": raw.get("endpoint"),
            }
        )
    return normalized


def discover_local_sources(data_dir: Path) -> List[Dict[str, Any]]:
    if not data_dir.exists() or not data_dir.is_dir():
        return []

    ignored_suffixes = (
        "_fetch_report.json",
        "concatenator_fetch_report.json",
    )
    discovered: List[Dict[str, Any]] = []
    for path in find_json_files(data_dir):
        if path.name.endswith(ignored_suffixes):
            continue
        lower_name = path.name.lower()
        is_pa_concat = "pageneralconcatenator-latest" in lower_name
        if is_pa_concat:
            dataset_group = "county_vote_type"
            parser_hint = "county_vote_type"
        else:
            dataset_group = "timeline"
            parser_hint = "timeline"
        discovered.append(
            {
                "id": f"local::{path.name}",
                "label": label_for_local_json(path),
                "dataset_group": dataset_group,
                "type": "local_file",
                "parser_hint": parser_hint,
                "notes": "Auto-discovered local JSON source (read-only).",
                "path": str(path.resolve()),
                "endpoint": None,
            }
        )
    return discovered


def resolve_local_path(path_value: Any, data_dir: Path) -> Optional[Path]:
    if not isinstance(path_value, str) or not path_value.strip():
        return None
    resolved_value = path_value.replace("{data_dir}", str(data_dir))
    candidate = Path(resolved_value).expanduser()
    if not candidate.is_absolute():
        candidate = ROOT_DIR / candidate
    return candidate.resolve()


def fetch_source_payload(source: Dict[str, Any], data_dir: Path) -> Tuple[Optional[Any], Dict[str, Any]]:
    fetched_at = utc_now_iso()
    connector_type = str(source.get("type", "local_file"))
    source_url = ""
    error_message = ""
    payload: Optional[Any] = None

    if connector_type == "local_file":
        local_path = resolve_local_path(source.get("path"), data_dir)
        source_url = f"file://{local_path}" if local_path else ""
        if local_path is None:
            error_message = "Local source path is missing."
        elif not local_path.exists():
            error_message = f"Local source does not exist: {local_path}"
        else:
            payload = load_json(local_path)
            if payload is None:
                error_message = f"Unable to parse JSON from {local_path}"
    elif connector_type == "remote_json":
        endpoint = source.get("endpoint")
        source_url = str(endpoint or "")
        if not endpoint:
            error_message = "Remote endpoint is missing."
        else:
            try:
                req = urlrequest.Request(
                    str(endpoint),
                    headers={"User-Agent": "Matrix-Red-Pill-Explorer/1.0"},
                )
                with urlrequest.urlopen(req, timeout=DEFAULT_TIMEOUT_SECONDS) as resp:
                    raw = resp.read()
                payload = json.loads(raw.decode("utf-8"))
            except (error.URLError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                error_message = f"Remote fetch failed: {exc}"
    else:
        error_message = f"Unsupported source type: {connector_type}"

    schema = create_schema_fingerprint(payload) if payload is not None else {
        "hash": "",
        "top_level_keys": [],
        "record_signatures": [],
    }

    envelope = {
        "source_id": source.get("id", ""),
        "source_label": source.get("label", ""),
        "dataset_group": source.get("dataset_group", ""),
        "parser_hint": source.get("parser_hint", ""),
        "source_notes": source.get("notes", ""),
        "source_url": source_url,
        "fetched_at": fetched_at,
        "schema_fingerprint": schema,
        "error": error_message,
    }
    return payload, envelope


def group_sources(sources: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for source in sources:
        group_name = str(source.get("dataset_group", "timeline"))
        grouped.setdefault(group_name, []).append(source)
    return grouped


def patriot_plot_layout(
    title: str,
    *,
    x_title: str = "",
    y_title: str = "",
    margin_l: int = 84,
    margin_r: int = 36,
    margin_t: int = 78,
    margin_b: int = 120,
    x_tickangle: int = -40,
    legend_y: float = -0.22,
) -> Dict[str, Any]:
    axis_style = {
        "automargin": True,
        "gridcolor": "rgba(96, 165, 250, 0.22)",
        "zerolinecolor": "rgba(148, 163, 184, 0.35)",
        "linecolor": "rgba(148, 163, 184, 0.45)",
        "tickfont": {"size": 11, "color": "#e8f0ff"},
        "title_font": {"size": 13, "color": "#e8f0ff"},
    }
    return {
        "title": {"text": title, "font": {"family": "Orbitron", "size": 16, "color": "#f8fafc"}},
        "paper_bgcolor": "rgba(5, 9, 20, 0.98)",
        "plot_bgcolor": "rgba(8, 14, 30, 0.98)",
        "font": {"family": "Rajdhani", "color": "#e8f0ff", "size": 13},
        "margin": {"l": margin_l, "r": margin_r, "t": margin_t, "b": margin_b},
        "legend": {
            "orientation": "h",
            "y": legend_y,
            "x": 0.5,
            "xanchor": "center",
            "bgcolor": "rgba(5, 9, 20, 0.88)",
            "bordercolor": "rgba(96, 165, 250, 0.35)",
            "borderwidth": 1,
        },
        "xaxis": {
            **axis_style,
            "title": {"text": x_title, "standoff": 20},
            "tickangle": x_tickangle,
        },
        "yaxis": {
            **axis_style,
            "title": {"text": y_title, "standoff": 18},
        },
    }


def build_timeline_chart(df: pd.DataFrame, events_df: pd.DataFrame) -> str:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(x=df["timestamp"], y=df["total_votes"], mode="lines", name="Total votes")
    )
    fig.add_trace(go.Scatter(x=df["timestamp"], y=df["biden"], mode="lines", name="Biden"))
    fig.add_trace(go.Scatter(x=df["timestamp"], y=df["trump"], mode="lines", name="Trump"))
    fig.add_trace(
        go.Scatter(
            x=df["timestamp"],
            y=df["third_party"],
            mode="lines",
            name="Third Party",
            line=dict(color=PATRIOT_PURPLE, width=2),
        )
    )

    if not events_df.empty:
        for _, event in events_df.iterrows():
            fig.add_vrect(
                x0=event["stop_start"],
                x1=event["stop_end"],
                fillcolor="rgba(245, 158, 11, 0.2)",
                line_width=0,
                layer="below",
            )

    fig.update_layout(
        **patriot_plot_layout(
            "Cumulative Vote Timeline with Stop-Count Windows",
            x_title="Time (UTC)",
            y_title="Votes",
            margin_b=90,
            legend_y=-0.18,
        ),
        legend_title="Series",
    )
    return fig.to_html(full_html=False, include_plotlyjs="cdn", config={"responsive": True})


def build_pa_vote_type_chart(pa_df: pd.DataFrame) -> str:
    grouped = (
        pa_df.groupby(["county", "vote_type"], as_index=False)["votes"]
        .sum()
        .sort_values("votes", ascending=False)
    )
    top_grouped = grouped.head(40)
    chart = px.bar(
        top_grouped,
        x="county",
        y="votes",
        color="vote_type",
        title="Top County Vote-Type Buckets (by votes)",
        color_discrete_map=VOTE_TYPE_COLORS,
    )
    chart.update_layout(
        **patriot_plot_layout(
            "Top County Vote-Type Buckets (by votes)",
            x_title="County",
            y_title="Votes",
            x_tickangle=-55,
            margin_b=170,
            margin_l=90,
            legend_y=-0.3,
        ),
        barmode="group",
    )
    return chart.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})


def build_pa_absentee_chart(pa_df: pd.DataFrame) -> tuple[str, List[Dict[str, Any]]]:
    county_totals = pa_df.groupby("county", as_index=False)["votes"].sum().rename(
        columns={"votes": "county_total_votes"}
    )
    absentee = (
        pa_df[pa_df["vote_type"].astype(str).str.contains("absentee", case=False, na=False)]
        .groupby("county", as_index=False)["votes"]
        .sum()
        .rename(columns={"votes": "absentee_votes"})
    )
    shares = county_totals.merge(absentee, on="county", how="left").fillna(0)
    shares["absentee_share"] = (
        shares["absentee_votes"]
        / shares["county_total_votes"].where(shares["county_total_votes"] > 0, 1)
    )
    shares = shares.sort_values("absentee_share", ascending=False)

    scatter = px.scatter(
        shares,
        x="county_total_votes",
        y="absentee_share",
        hover_name="county",
        size="absentee_votes",
        title="Absentee Share vs County Total Votes",
        labels={"county_total_votes": "County Total Votes", "absentee_share": "Absentee Share"},
    )
    scatter.update_layout(
        **patriot_plot_layout(
            "Absentee Share vs County Total Votes",
            x_title="County Total Votes",
            y_title="Absentee Share",
            margin_b=100,
            legend_y=-0.2,
        )
    )
    top_table = shares.head(25).to_dict(orient="records")
    return scatter.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True}), top_table


def build_vote_type_spread_chart(vote_type_df: pd.DataFrame) -> tuple[str, List[Dict[str, Any]]]:
    if vote_type_df.empty:
        return "", []

    grouped = (
        vote_type_df.groupby("vote_type", as_index=False)["votes"]
        .sum()
        .sort_values("votes", ascending=False)
    )
    total_votes = float(grouped["votes"].sum()) if not grouped.empty else 0.0
    grouped["share_pct"] = grouped["votes"].apply(
        lambda value: (float(value) / total_votes * 100.0) if total_votes > 0 else 0.0
    )

    pie = px.pie(
        grouped,
        names="vote_type",
        values="votes",
        title="Vote-Type Spread for Selected Timestamp",
        color="vote_type",
        color_discrete_map=VOTE_TYPE_COLORS,
    )
    pie.update_layout(**patriot_plot_layout("Vote-Type Spread for Selected Timestamp", margin_b=70, legend_y=-0.15))
    rows = grouped.to_dict(orient="records")
    return pie.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True}), rows


def build_county_vote_type_detail(
    vote_type_df: pd.DataFrame,
) -> tuple[str, List[Dict[str, Any]]]:
    if vote_type_df.empty:
        return "", []

    grouped = (
        vote_type_df.groupby(["county", "vote_type"], as_index=False)["votes"]
        .sum()
        .sort_values(["county", "vote_type"])
    )
    pivot = grouped.pivot(index="county", columns="vote_type", values="votes").fillna(0)

    def _series_for(name: str) -> pd.Series:
        for column in pivot.columns:
            if str(column).strip().lower() == name:
                return pivot[column]
        return pd.Series(0, index=pivot.index, dtype=float)

    absentee = _series_for("absentee")
    electionday = _series_for("electionday")
    provisional = _series_for("provisional")
    total = pivot.sum(axis=1)
    safe_total = total.where(total > 0, 1)

    county_rows = pd.DataFrame(
        {
            "county": pivot.index,
            "absentee_votes": absentee,
            "electionday_votes": electionday,
            "provisional_votes": provisional,
            "county_total_votes": total,
            "absentee_share": absentee / safe_total,
        }
    ).reset_index(drop=True)
    county_rows = county_rows.sort_values("county_total_votes", ascending=False)

    if county_rows.empty:
        return "", []

    quantiles = county_rows["county_total_votes"].quantile([0.33, 0.66]).to_list()
    low, high = float(quantiles[0]), float(quantiles[1])

    def classify_size(votes: float) -> str:
        if votes <= low:
            return "small"
        if votes <= high:
            return "medium"
        return "large"

    county_rows["county_size"] = county_rows["county_total_votes"].apply(classify_size)
    top_counties = county_rows.head(25)

    long_df = top_counties.melt(
        id_vars=["county", "county_total_votes", "county_size"],
        value_vars=["absentee_votes", "electionday_votes", "provisional_votes"],
        var_name="vote_type",
        value_name="votes",
    )
    long_df = long_df[long_df["votes"] > 0]
    long_df["vote_type"] = long_df["vote_type"].str.replace("_votes", "", regex=False)

    chart = px.bar(
        long_df,
        x="county",
        y="votes",
        color="vote_type",
        title="County Vote-Type Totals (Selected Timestamp)",
        barmode="group",
        color_discrete_map={
            **VOTE_TYPE_COLORS,
            "absentee_votes": VOTE_TYPE_COLORS["absentee"],
            "electionday_votes": VOTE_TYPE_COLORS["electionday"],
            "provisional_votes": VOTE_TYPE_COLORS["provisional"],
        },
    )
    chart.update_layout(
        **patriot_plot_layout(
            "County Vote-Type Totals (Selected Timestamp)",
            x_title="County",
            y_title="Votes",
            x_tickangle=-55,
            margin_b=170,
            margin_l=90,
            legend_y=-0.32,
        ),
        barmode="group",
    )

    return chart.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True}), county_rows.to_dict(
        orient="records"
    )


def _normalize_candidate_key(raw_key: str) -> str:
    key = str(raw_key).strip().lower()
    if key == "bidenj":
        return "biden"
    if key == "trumpd":
        return "trump"
    return "other"


def _extract_absentee_county_totals(
    snapshot_rows: List[Dict[str, Any]],
) -> tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    absentee_by_county: Dict[str, Dict[str, float]] = {}
    county_totals: Dict[str, float] = {}
    for row in snapshot_rows:
        if not isinstance(row, dict):
            continue
        county = str(row.get("locality_name", "") or "").strip()
        if not county:
            continue
        votes = float(row.get("votes", 0) or 0)
        county_totals[county] = county_totals.get(county, 0.0) + votes
        vote_type = str(row.get("vote_type", "") or "").strip().lower()
        if "absentee" not in vote_type:
            continue

        results = row.get("results")
        result_dict = results if isinstance(results, dict) else {}
        bucket = absentee_by_county.setdefault(
            county,
            {"votes": 0.0, "biden": 0.0, "trump": 0.0, "other": 0.0},
        )
        bucket["votes"] += votes
        for candidate_key, value in result_dict.items():
            normalized = _normalize_candidate_key(str(candidate_key))
            bucket[normalized] += float(value or 0)
    return absentee_by_county, county_totals


def detect_absentee_drop_events(
    payload: Any,
    min_absentee_drop_votes: int,
    quantile_threshold: float = 0.95,
    max_rows: int = 250,
) -> tuple[List[Dict[str, Any]], int]:
    if not isinstance(payload, dict):
        return [], 0
    snapshots = payload.get("versioned_snapshots")
    if not isinstance(snapshots, list) or len(snapshots) < 2:
        return [], 0

    ordered = [
        snapshot
        for snapshot in snapshots
        if isinstance(snapshot, dict)
        and isinstance(snapshot.get("timestamp"), str)
        and isinstance(snapshot.get("county_by_vote_type"), list)
    ]
    ordered.sort(key=lambda row: str(row["timestamp"]))
    if len(ordered) < 2:
        return [], 0

    events: List[Dict[str, Any]] = []
    for idx in range(1, len(ordered)):
        prev = ordered[idx - 1]
        curr = ordered[idx]
        prev_absentee, _ = _extract_absentee_county_totals(prev["county_by_vote_type"])
        curr_absentee, curr_totals = _extract_absentee_county_totals(curr["county_by_vote_type"])
        counties = set(prev_absentee.keys()) | set(curr_absentee.keys())

        for county in counties:
            prev_row = prev_absentee.get(
                county,
                {"votes": 0.0, "biden": 0.0, "trump": 0.0, "other": 0.0},
            )
            curr_row = curr_absentee.get(
                county,
                {"votes": 0.0, "biden": 0.0, "trump": 0.0, "other": 0.0},
            )
            drop_votes = curr_row["votes"] - prev_row["votes"]
            if drop_votes <= 0:
                continue

            biden_delta = curr_row["biden"] - prev_row["biden"]
            trump_delta = curr_row["trump"] - prev_row["trump"]
            other_delta = curr_row["other"] - prev_row["other"]
            winner_key, winner_votes = max(
                [("biden", biden_delta), ("trump", trump_delta), ("other", other_delta)],
                key=lambda item: item[1],
            )
            share = (winner_votes / drop_votes) if drop_votes > 0 else 0.0
            events.append(
                {
                    "timestamp": curr["timestamp"],
                    "county": county,
                    "absentee_drop_votes": int(round(drop_votes)),
                    "biden_delta": int(round(max(0.0, biden_delta))),
                    "trump_delta": int(round(max(0.0, trump_delta))),
                    "other_delta": int(round(max(0.0, other_delta))),
                    "winner": winner_key,
                    "winner_votes": int(round(max(0.0, winner_votes))),
                    "winner_share": float(share),
                    "county_total_votes": int(round(curr_totals.get(county, 0.0))),
                }
            )

    if not events:
        return [], 0

    deltas = pd.Series([row["absentee_drop_votes"] for row in events], dtype="float64")
    dynamic_threshold = int(max(min_absentee_drop_votes, float(deltas.quantile(quantile_threshold))))
    filtered = [row for row in events if row["absentee_drop_votes"] >= dynamic_threshold]
    filtered.sort(key=lambda row: row["absentee_drop_votes"], reverse=True)
    return filtered[:max_rows], dynamic_threshold


def build_absentee_drop_chart(events: List[Dict[str, Any]]) -> str:
    if not events:
        return ""
    frame = pd.DataFrame(events).sort_values("timestamp")
    chart = px.scatter(
        frame,
        x="timestamp",
        y="absentee_drop_votes",
        color="winner",
        size="winner_votes",
        hover_name="county",
        title="Large Absentee Vote Drops by Timestamp",
        labels={"absentee_drop_votes": "Absentee Votes Added", "timestamp": "Timestamp (UTC)"},
        color_discrete_map=CANDIDATE_COLORS,
    )
    chart.update_layout(
        **patriot_plot_layout(
            "Large Absentee Vote Drops by Timestamp",
            x_title="Timestamp (UTC)",
            y_title="Absentee Votes Added",
            margin_b=110,
            margin_l=96,
            legend_y=-0.2,
        )
    )
    return chart.to_html(full_html=False, include_plotlyjs=False, config={"responsive": True})


def serialize_events(events_df: pd.DataFrame) -> List[Dict[str, Any]]:
    if events_df.empty:
        return []
    rows = events_df.copy()
    rows["stop_start"] = rows["stop_start"].astype(str)
    rows["stop_end"] = rows["stop_end"].astype(str)
    return rows.to_dict(orient="records")


@app.route("/api/manifest")
def api_manifest() -> Any:
    data_dir = Path(request.args.get("data_dir", "src/voting_data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = ROOT_DIR / data_dir
    states: List[Dict[str, str]] = []
    for path in sorted(data_dir.glob("*_timeline.json")):
        code = path.stem.replace("_timeline", "").upper()
        states.append(
            {
                "code": code,
                "file": path.name,
                "name": jurisdiction_name(code),
                "label": format_jurisdiction_label(code),
            }
        )
    return jsonify({"states": states})


@app.route("/api/timeline/<path:filename>")
def api_timeline(filename: str) -> Any:
    if ".." in filename or "/" in filename.replace("\\", "/"):
        return jsonify({"error": "Invalid filename."}), 400
    data_dir = Path(request.args.get("data_dir", "src/voting_data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = ROOT_DIR / data_dir
    path = data_dir / filename
    if not path.exists() or not path.is_file():
        return jsonify({"error": f"Timeline file not found: {filename}"}), 404
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify(payload)


@app.route("/")
def index() -> str:
    return render_template(
        "index.html",
        map_winners_url=url_for("static", filename="data/us_state_winners.json"),
    )


def _legacy_index() -> str:
    data_dir_input = request.args.get("data_dir", "src/voting_data")
    selected_group = request.args.get("dataset_group", "timeline")
    selected_source_id = request.args.get("source_id", "")
    selected_version_ts = request.args.get("version_ts", "")
    start_ts_raw = request.args.get("start_ts", "")
    end_ts_raw = request.args.get("end_ts", "")
    min_gap = safe_parse_int(request.args.get("min_gap", "45"), 45, 15, 240)
    cadence_multiplier = safe_parse_float(request.args.get("cadence_mult", "4.0"), 4.0, 2.0, 8.0)
    min_absentee_drop = safe_parse_int(request.args.get("min_abs_drop", "5000"), 5000, 100, 500000)
    data_dir = Path(data_dir_input).expanduser()

    error_message = None
    info_message = None
    timeline_html = ""
    event_rows: List[Dict[str, Any]] = []
    pa_vote_type_html = ""
    pa_absentee_html = ""
    pa_table_rows: List[Dict[str, Any]] = []
    vote_type_spread_html = ""
    vote_type_spread_rows: List[Dict[str, Any]] = []
    county_vote_type_detail_html = ""
    county_vote_type_detail_rows: List[Dict[str, Any]] = []
    absentee_drop_rows: List[Dict[str, Any]] = []
    absentee_drop_threshold = 0
    absentee_drop_html = ""
    map_data: Dict[str, Any] = {}
    sources = load_source_manifest(MANIFEST_PATH)
    sources.extend(discover_local_sources(data_dir))

    grouped_sources = group_sources(sources)
    dataset_groups = sorted(grouped_sources.keys())
    if selected_group not in grouped_sources:
        selected_group = dataset_groups[0] if dataset_groups else "timeline"

    current_group_sources = grouped_sources.get(selected_group, [])
    if current_group_sources and selected_source_id:
        selected_source = next(
            (src for src in current_group_sources if src.get("id") == selected_source_id),
            current_group_sources[0],
        )
    else:
        selected_source = current_group_sources[0] if current_group_sources else None

    metrics = {"snapshots": 0, "stop_windows": 0, "bursts": 0}
    version_rows: List[Dict[str, Any]] = []
    selected_version_row: Optional[Dict[str, Any]] = None
    source_lineage: Dict[str, Any] = {}

    if not current_group_sources:
        error_message = f"No sources are available for dataset group '{selected_group}'."
    elif selected_source is None:
        error_message = "No source selected."
    else:
        payload, source_lineage = fetch_source_payload(selected_source, data_dir)
        if payload is None:
            error_message = source_lineage.get("error") or "Unable to load the selected source."
        else:
            state_code = state_code_from_source(selected_source) or str(payload.get("state", "")).upper()
            if state_code:
                map_data = build_map_data(payload, state_code)
            parser_hint = selected_source.get("parser_hint", "timeline")
            if parser_hint == "timeline":
                full_df = build_timeseries(payload)
                if full_df.empty:
                    info_message = "No timestamped vote snapshots found in this source."
                else:
                    version_rows = build_version_index(full_df)
                    selected_version_lookup = selected_version_ts or (
                        version_rows[-1]["version_id"] if version_rows else ""
                    )
                    selected_version_ts = selected_version_lookup
                    selected_version_row = next(
                        (row for row in version_rows if row["version_id"] == selected_version_lookup),
                        None,
                    )
                    start_ts = parse_filter_timestamp(start_ts_raw)
                    end_ts = parse_filter_timestamp(end_ts_raw)
                    if selected_version_row is not None:
                        version_end = parse_timestamp(selected_version_row["version_id"])
                        if end_ts is None or (version_end is not None and version_end < end_ts):
                            end_ts = version_end

                    filtered_df = filter_timeseries_window(full_df, start_ts, end_ts)
                    if filtered_df.empty:
                        info_message = "No snapshot rows match the selected timestamp filters."
                    else:
                        events_df = detect_stop_count_events(
                            filtered_df,
                            min_gap_minutes=min_gap,
                            cadence_multiplier=cadence_multiplier,
                        )
                        metrics["snapshots"] = int(len(filtered_df))
                        metrics["stop_windows"] = int(len(events_df))
                        metrics["bursts"] = (
                            int(events_df["is_large_post_gap_burst"].sum()) if not events_df.empty else 0
                        )
                        timeline_html = build_timeline_chart(filtered_df, events_df)
                        event_rows = serialize_events(events_df)

                vote_type_df = extract_county_vote_type(
                    payload, version_ts=selected_version_ts or None
                )
                if not vote_type_df.empty:
                    pa_vote_type_html = build_pa_vote_type_chart(vote_type_df)
                    pa_absentee_html, pa_table_rows = build_pa_absentee_chart(vote_type_df)
                    vote_type_spread_html, vote_type_spread_rows = build_vote_type_spread_chart(
                        vote_type_df
                    )
                    (
                        county_vote_type_detail_html,
                        county_vote_type_detail_rows,
                    ) = build_county_vote_type_detail(vote_type_df)
                    absentee_drop_rows, absentee_drop_threshold = detect_absentee_drop_events(
                        payload,
                        min_absentee_drop_votes=min_absentee_drop,
                    )
                    absentee_drop_html = build_absentee_drop_chart(absentee_drop_rows)
            elif parser_hint in ("pa_vote_type", "county_vote_type"):
                full_df = build_timeseries(payload)
                if not full_df.empty:
                    version_rows = build_version_index(full_df)
                    selected_version_lookup = selected_version_ts or (
                        version_rows[-1]["version_id"] if version_rows else ""
                    )
                    selected_version_ts = selected_version_lookup
                    selected_version_row = next(
                        (row for row in version_rows if row["version_id"] == selected_version_lookup),
                        None,
                    )
                    start_ts = parse_filter_timestamp(start_ts_raw)
                    end_ts = parse_filter_timestamp(end_ts_raw)
                    if selected_version_row is not None:
                        version_end = parse_timestamp(selected_version_row["version_id"])
                        if end_ts is None or (version_end is not None and version_end < end_ts):
                            end_ts = version_end
                    filtered_df = filter_timeseries_window(full_df, start_ts, end_ts)
                    if not filtered_df.empty:
                        events_df = detect_stop_count_events(
                            filtered_df,
                            min_gap_minutes=min_gap,
                            cadence_multiplier=cadence_multiplier,
                        )
                        metrics["snapshots"] = int(len(filtered_df))
                        timeline_html = build_timeline_chart(filtered_df, events_df)
                        event_rows = serialize_events(events_df)

                vote_type_df = extract_county_vote_type(
                    payload, version_ts=selected_version_ts or None
                )
                if vote_type_df.empty:
                    info_message = "Selected source does not contain county_by_vote_type data."
                else:
                    metrics["snapshots"] = max(metrics["snapshots"], int(len(vote_type_df)))
                    pa_vote_type_html = build_pa_vote_type_chart(vote_type_df)
                    pa_absentee_html, pa_table_rows = build_pa_absentee_chart(vote_type_df)
                    vote_type_spread_html, vote_type_spread_rows = build_vote_type_spread_chart(
                        vote_type_df
                    )
                    (
                        county_vote_type_detail_html,
                        county_vote_type_detail_rows,
                    ) = build_county_vote_type_detail(vote_type_df)
                    absentee_drop_rows, absentee_drop_threshold = detect_absentee_drop_events(
                        payload,
                        min_absentee_drop_votes=min_absentee_drop,
                    )
                    absentee_drop_html = build_absentee_drop_chart(absentee_drop_rows)
            else:
                error_message = f"Unsupported parser hint: {parser_hint}"

    return render_template(
        "index.html",
        data_dir_input=data_dir_input,
        manifest_path=str(MANIFEST_PATH),
        dataset_groups=dataset_groups,
        selected_group=selected_group,
        group_sources=current_group_sources,
        selected_source_id=selected_source.get("id") if selected_source else "",
        selected_parser_hint=selected_source.get("parser_hint", "") if selected_source else "",
        version_rows=version_rows,
        selected_version_row=selected_version_row,
        selected_version_ts=selected_version_ts,
        start_ts_raw=start_ts_raw,
        end_ts_raw=end_ts_raw,
        min_gap=min_gap,
        cadence_multiplier=cadence_multiplier,
        min_absentee_drop=min_absentee_drop,
        metrics=metrics,
        error_message=error_message,
        info_message=info_message,
        timeline_html=timeline_html,
        event_rows=event_rows,
        source_lineage=source_lineage,
        pa_vote_type_html=pa_vote_type_html,
        pa_absentee_html=pa_absentee_html,
        pa_table_rows=pa_table_rows,
        vote_type_spread_html=vote_type_spread_html,
        vote_type_spread_rows=vote_type_spread_rows,
        county_vote_type_detail_html=county_vote_type_detail_html,
        county_vote_type_detail_rows=county_vote_type_detail_rows,
        absentee_drop_rows=absentee_drop_rows,
        absentee_drop_threshold=absentee_drop_threshold,
        absentee_drop_html=absentee_drop_html,
        map_data=map_data,
        map_winners_url=url_for("static", filename="data/us_state_winners.json"),
    )


if __name__ == "__main__":
    app.run(debug=True, port=4547)

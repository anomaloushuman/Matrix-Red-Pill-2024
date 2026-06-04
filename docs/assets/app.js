/* global Plotly */

const PATRIOT_COLORS = {
  paper: "rgba(5, 9, 20, 0.98)",
  plot: "rgba(8, 14, 30, 0.98)",
  grid: "rgba(96, 165, 250, 0.22)",
  text: "#e8f0ff",
  red: "#ef233c",
  blue: "#3b82f6",
  purple: "#9b5de5",
  white: "#f8fafc",
};

const VOTE_TYPE_COLORS = {
  absentee: PATRIOT_COLORS.blue,
  electionday: PATRIOT_COLORS.red,
  provisional: PATRIOT_COLORS.purple,
};

const CANDIDATE_COLORS = {
  biden: PATRIOT_COLORS.blue,
  trump: PATRIOT_COLORS.red,
  other: PATRIOT_COLORS.purple,
};

const SWAP_MS = 280;

async function fadeContentSwap(run) {
  const content = document.getElementById("app-content");
  const loader = document.getElementById("page-loader");
  document.body.classList.add("is-swapping");
  if (loader) {
    loader.classList.add("is-active");
  }
  if (content) {
    content.classList.add("is-swapping");
  }
  await new Promise((resolve) => window.setTimeout(resolve, SWAP_MS));
  await run();
  if (content) {
    content.classList.remove("is-swapping");
  }
  document.body.classList.remove("is-swapping");
  if (loader) {
    loader.classList.remove("is-active");
  }
}

function makeLayout(title, options = {}) {
  return {
    title: {
      text: title,
      font: { family: "Orbitron, sans-serif", size: 16, color: PATRIOT_COLORS.white },
      x: 0.02,
      xanchor: "left",
    },
    paper_bgcolor: PATRIOT_COLORS.paper,
    plot_bgcolor: PATRIOT_COLORS.plot,
    font: { family: "Rajdhani, sans-serif", color: PATRIOT_COLORS.text, size: 13 },
    autosize: true,
    margin: {
      l: options.marginL ?? 84,
      r: options.marginR ?? 36,
      t: options.marginT ?? 78,
      b: options.marginB ?? 120,
    },
    xaxis: {
      automargin: true,
      tickangle: options.xTickAngle ?? -40,
      gridcolor: PATRIOT_COLORS.grid,
      zerolinecolor: "rgba(148, 163, 184, 0.35)",
      linecolor: "rgba(148, 163, 184, 0.45)",
      title: {
        text: options.xTitle || "",
        standoff: 20,
        font: { size: 13, color: PATRIOT_COLORS.text },
      },
      tickfont: { size: 11, color: PATRIOT_COLORS.text },
    },
    yaxis: {
      automargin: true,
      gridcolor: PATRIOT_COLORS.grid,
      zerolinecolor: "rgba(148, 163, 184, 0.35)",
      linecolor: "rgba(148, 163, 184, 0.45)",
      title: {
        text: options.yTitle || "",
        standoff: 18,
        font: { size: 13, color: PATRIOT_COLORS.text },
      },
      tickfont: { size: 11, color: PATRIOT_COLORS.text },
    },
    legend: {
      orientation: "h",
      y: options.legendY ?? -0.24,
      x: 0.5,
      xanchor: "center",
      bgcolor: "rgba(5, 9, 20, 0.88)",
      bordercolor: "rgba(96, 165, 250, 0.35)",
      borderwidth: 1,
      font: { color: PATRIOT_COLORS.text },
    },
    colorway: [PATRIOT_COLORS.blue, PATRIOT_COLORS.red, PATRIOT_COLORS.purple, "#f59e0b", "#c084fc"],
  };
}

async function plotChart(elementId, data, layout) {
  const element = document.getElementById(elementId);
  if (!element) {
    return;
  }
  await Plotly.newPlot(element, data, layout, { responsive: true, displayModeBar: true });
  Plotly.Plots.resize(element);
}

let manifest = { states: [] };
let currentPayload = null;
let currentFileName = "";
let versionRows = [];

function basePath() {
  const path = window.location.pathname.replace(/\/index\.html$/, "");
  if (path.endsWith("/")) {
    return path.slice(0, -1);
  }
  return path || "";
}

function assetUrl(relativePath) {
  const cleaned = relativePath.replace(/^\//, "");
  return `${basePath()}/${cleaned}`;
}

function timelineDataUrl(fileName) {
  const apiBase = document.getElementById("timeline-api-base");
  if (apiBase?.textContent?.trim()) {
    const base = apiBase.textContent.trim().replace(/\/$/, "");
    return `${base}/${encodeURIComponent(fileName)}`;
  }
  return assetUrl(`data/${fileName}`);
}

function showPanel(id, message) {
  const panel = document.getElementById(id);
  if (!message) {
    panel.classList.add("hidden");
    panel.textContent = "";
    return;
  }
  panel.textContent = message;
  panel.classList.remove("hidden");
}

function setStatus(message) {
  document.getElementById("load-status").textContent = message;
}

function parseTimestamp(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function buildTimeseries(payload) {
  const rows = Array.isArray(payload.timeseries) ? payload.timeseries : [];
  const mapped = rows
    .map((row) => {
      const timestamp = parseTimestamp(row.timestamp);
      if (!timestamp) {
        return null;
      }
      const results = row.results || {};
      const biden = Number(results.bidenj || 0);
      const trump = Number(results.trumpd || 0);
      const third = Number(results.jorgensenj || 0);
      const total = Number(row.votes || biden + trump + third);
      return { timestamp, total_votes: total, biden, trump, third_party: third };
    })
    .filter(Boolean)
    .sort((a, b) => a.timestamp - b.timestamp);

  const deduped = [];
  const seen = new Set();
  for (const row of mapped) {
    const key = row.timestamp.toISOString();
    if (seen.has(key)) {
      continue;
    }
    seen.add(key);
    deduped.push(row);
  }
  return deduped;
}

function buildVersionIndex(timeseries) {
  const rows = [];
  let previousTotal = 0;
  timeseries.forEach((row, index) => {
    const delta = row.total_votes - previousTotal;
    previousTotal = row.total_votes;
    rows.push({
      version_id: row.timestamp.toISOString(),
      version_label: `V${String(index + 1).padStart(4, "0")}`,
      timestamp: row.timestamp.toISOString(),
      total_votes: Math.round(row.total_votes),
      delta_votes: Math.round(delta),
      biden: Math.round(row.biden),
      trump: Math.round(row.trump),
      third_party: Math.round(row.third_party),
    });
  });
  return rows;
}

function filterTimeseriesWindow(timeseries, endTs) {
  if (!endTs) {
    return timeseries;
  }
  return timeseries.filter((row) => row.timestamp <= endTs);
}

function detectStopCountEvents(timeseries, minGapMinutes, cadenceMultiplier) {
  if (timeseries.length < 3) {
    return [];
  }
  const deltas = [];
  for (let i = 1; i < timeseries.length; i += 1) {
    const gapMinutes = (timeseries[i].timestamp - timeseries[i - 1].timestamp) / 60000;
    const deltaVotes = timeseries[i].total_votes - timeseries[i - 1].total_votes;
    deltas.push({ gapMinutes, deltaVotes });
  }
  const positiveGaps = deltas.filter((d) => d.deltaVotes > 0 && d.gapMinutes > 0).map((d) => d.gapMinutes);
  const cadence = positiveGaps.length
    ? positiveGaps.sort((a, b) => a - b)[Math.floor(positiveGaps.length / 2)]
    : 5;
  const stopThreshold = Math.max(minGapMinutes, cadence * cadenceMultiplier);
  const positiveVoteDeltas = deltas.filter((d) => d.deltaVotes > 0).map((d) => d.deltaVotes).sort((a, b) => a - b);
  const burstThreshold = positiveVoteDeltas.length
    ? positiveVoteDeltas[Math.floor(positiveVoteDeltas.length * 0.9)]
    : 0;

  const events = [];
  for (let i = 1; i < timeseries.length; i += 1) {
    const gapMinutes = (timeseries[i].timestamp - timeseries[i - 1].timestamp) / 60000;
    if (gapMinutes < stopThreshold) {
      continue;
    }
    const votesAdded = Math.max(0, timeseries[i].total_votes - timeseries[i - 1].total_votes);
    events.push({
      event_id: events.length + 1,
      stop_start: timeseries[i - 1].timestamp.toISOString(),
      stop_end: timeseries[i].timestamp.toISOString(),
      stop_gap_minutes: Number(gapMinutes.toFixed(2)),
      votes_added_after_gap: Math.round(votesAdded),
      is_large_post_gap_burst: votesAdded >= burstThreshold && burstThreshold > 0,
      burst_threshold_votes: Math.round(burstThreshold),
    });
  }
  return events;
}

function countyVoteTypeRecordsForVersion(payload, versionTs) {
  const snapshots = Array.isArray(payload.versioned_snapshots) ? payload.versioned_snapshots : [];
  if (snapshots.length) {
    if (versionTs) {
      const exact = snapshots.find((snap) => snap.timestamp === versionTs);
      if (exact && Array.isArray(exact.county_by_vote_type)) {
        return exact.county_by_vote_type;
      }
      const eligible = snapshots
        .filter((snap) => typeof snap.timestamp === "string" && snap.timestamp <= versionTs)
        .sort((a, b) => a.timestamp.localeCompare(b.timestamp));
      if (eligible.length) {
        const last = eligible[eligible.length - 1];
        return Array.isArray(last.county_by_vote_type) ? last.county_by_vote_type : [];
      }
    }
    const last = snapshots[snapshots.length - 1];
    return Array.isArray(last.county_by_vote_type) ? last.county_by_vote_type : [];
  }
  return Array.isArray(payload.county_by_vote_type) ? payload.county_by_vote_type : [];
}

function extractCountyVoteType(payload, versionTs) {
  const records = countyVoteTypeRecordsForVersion(payload, versionTs);
  return records.map((row) => {
    const results = row.results || {};
    return {
      county: row.locality_name || "unknown",
      vote_type: row.vote_type || "unknown",
      votes: Number(row.votes || 0),
      biden: Number(results.bidenj || 0),
      trump: Number(results.trumpd || 0),
      third_party: Number(results.jorgensenj || 0),
    };
  });
}

function normalizeCandidateKey(rawKey) {
  const key = String(rawKey).toLowerCase();
  if (key === "bidenj") {
    return "biden";
  }
  if (key === "trumpd") {
    return "trump";
  }
  return "other";
}

function extractAbsenteeCountyTotals(snapshotRows) {
  const absenteeByCounty = {};
  const countyTotals = {};
  snapshotRows.forEach((row) => {
    const county = String(row.locality_name || "").trim();
    if (!county) {
      return;
    }
    const votes = Number(row.votes || 0);
    countyTotals[county] = (countyTotals[county] || 0) + votes;
    const voteType = String(row.vote_type || "").toLowerCase();
    if (!voteType.includes("absentee")) {
      return;
    }
    if (!absenteeByCounty[county]) {
      absenteeByCounty[county] = { votes: 0, biden: 0, trump: 0, other: 0 };
    }
    const bucket = absenteeByCounty[county];
    bucket.votes += votes;
    const results = row.results || {};
    Object.entries(results).forEach(([candidateKey, value]) => {
      bucket[normalizeCandidateKey(candidateKey)] += Number(value || 0);
    });
  });
  return { absenteeByCounty, countyTotals };
}

function quantile(values, q) {
  if (!values.length) {
    return 0;
  }
  const sorted = [...values].sort((a, b) => a - b);
  const index = Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * q));
  return sorted[index];
}

function detectAbsenteeDropEvents(payload, minAbsenteeDropVotes) {
  const snapshots = Array.isArray(payload.versioned_snapshots)
    ? payload.versioned_snapshots.filter(
        (snap) => snap && typeof snap.timestamp === "string" && Array.isArray(snap.county_by_vote_type),
      )
    : [];
  snapshots.sort((a, b) => a.timestamp.localeCompare(b.timestamp));
  if (snapshots.length < 2) {
    return { events: [], threshold: minAbsenteeDropVotes };
  }

  const events = [];
  for (let i = 1; i < snapshots.length; i += 1) {
    const prev = snapshots[i - 1];
    const curr = snapshots[i];
    const prevData = extractAbsenteeCountyTotals(prev.county_by_vote_type);
    const currData = extractAbsenteeCountyTotals(curr.county_by_vote_type);
    const counties = new Set([
      ...Object.keys(prevData.absenteeByCounty),
      ...Object.keys(currData.absenteeByCounty),
    ]);

    counties.forEach((county) => {
      const prevRow = prevData.absenteeByCounty[county] || { votes: 0, biden: 0, trump: 0, other: 0 };
      const currRow = currData.absenteeByCounty[county] || { votes: 0, biden: 0, trump: 0, other: 0 };
      const dropVotes = currRow.votes - prevRow.votes;
      if (dropVotes <= 0) {
        return;
      }
      const bidenDelta = currRow.biden - prevRow.biden;
      const trumpDelta = currRow.trump - prevRow.trump;
      const otherDelta = currRow.other - prevRow.other;
      const candidates = [
        ["biden", bidenDelta],
        ["trump", trumpDelta],
        ["other", otherDelta],
      ];
      const winner = candidates.reduce((best, current) => (current[1] > best[1] ? current : best));
      events.push({
        timestamp: curr.timestamp,
        county,
        absentee_drop_votes: Math.round(dropVotes),
        biden_delta: Math.round(Math.max(0, bidenDelta)),
        trump_delta: Math.round(Math.max(0, trumpDelta)),
        other_delta: Math.round(Math.max(0, otherDelta)),
        winner: winner[0],
        winner_votes: Math.round(Math.max(0, winner[1])),
        winner_share: dropVotes > 0 ? winner[1] / dropVotes : 0,
        county_total_votes: Math.round(currData.countyTotals[county] || 0),
      });
    });
  }

  if (!events.length) {
    return { events: [], threshold: minAbsenteeDropVotes };
  }
  const dynamicThreshold = Math.max(
    minAbsenteeDropVotes,
    Math.round(quantile(events.map((e) => e.absentee_drop_votes), 0.95)),
  );
  const filtered = events
    .filter((event) => event.absentee_drop_votes >= dynamicThreshold)
    .sort((a, b) => b.absentee_drop_votes - a.absentee_drop_votes)
    .slice(0, 250);
  return { events: filtered, threshold: dynamicThreshold };
}

function buildCountyVoteTypeDetail(rows) {
  const byCounty = {};
  rows.forEach((row) => {
    if (!byCounty[row.county]) {
      byCounty[row.county] = {
        county: row.county,
        absentee_votes: 0,
        electionday_votes: 0,
        provisional_votes: 0,
        county_total_votes: 0,
      };
    }
    const bucket = byCounty[row.county];
    const voteType = String(row.vote_type).toLowerCase();
    bucket.county_total_votes += row.votes;
    if (voteType.includes("absentee")) {
      bucket.absentee_votes += row.votes;
    } else if (voteType.includes("election")) {
      bucket.electionday_votes += row.votes;
    } else if (voteType.includes("provisional")) {
      bucket.provisional_votes += row.votes;
    }
  });

  const countyRows = Object.values(byCounty).map((row) => ({
    ...row,
    absentee_share: row.county_total_votes > 0 ? row.absentee_votes / row.county_total_votes : 0,
  }));
  countyRows.sort((a, b) => b.county_total_votes - a.county_total_votes);

  const totals = countyRows.map((row) => row.county_total_votes).sort((a, b) => a - b);
  const low = totals[Math.floor(totals.length * 0.33)] || 0;
  const high = totals[Math.floor(totals.length * 0.66)] || 0;
  countyRows.forEach((row) => {
    if (row.county_total_votes <= low) {
      row.county_size = "small";
    } else if (row.county_total_votes <= high) {
      row.county_size = "medium";
    } else {
      row.county_size = "large";
    }
  });
  return countyRows;
}

function renderTable(containerId, columns, rows) {
  const container = document.getElementById(containerId);
  if (!rows.length) {
    container.innerHTML = '<p class="muted">No rows to display.</p>';
    return;
  }
  const header = columns.map((col) => `<th>${col.label}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns.map((col) => `<td>${col.render(row)}</td>`).join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  container.innerHTML = `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderAnalysis() {
  if (!currentPayload) {
    return;
  }

  const minGap = Number(document.getElementById("min-gap").value || 45);
  const cadenceMult = Number(document.getElementById("cadence-mult").value || 4);
  const minAbsDrop = Number(document.getElementById("min-abs-drop").value || 5000);
  const versionTs = document.getElementById("version-select").value;
  const versionEnd = parseTimestamp(versionTs);

  const timeseries = buildTimeseries(currentPayload);
  if (!timeseries.length) {
    showPanel("error-panel", "No timestamped vote snapshots found in this source.");
    return;
  }
  showPanel("error-panel", "");

  const filtered = filterTimeseriesWindow(timeseries, versionEnd);
  const stopEvents = detectStopCountEvents(filtered, minGap, cadenceMult);
  const voteTypeRows = extractCountyVoteType(currentPayload, versionTs);
  const countyDetail = buildCountyVoteTypeDetail(voteTypeRows);
  const absentee = detectAbsenteeDropEvents(currentPayload, minAbsDrop);

  document.getElementById("metric-snapshots").textContent = String(filtered.length);
  document.getElementById("metric-stops").textContent = String(stopEvents.length);
  document.getElementById("metric-drops").textContent = String(absentee.events.length);
  document.getElementById("drop-threshold-note").textContent = `Rows shown are >= ${absentee.threshold} votes (dynamic threshold with your minimum filter).`;

  plotChart(
    "timeline-chart",
    [
      {
        x: filtered.map((r) => r.timestamp),
        y: filtered.map((r) => r.total_votes),
        mode: "lines",
        name: "Total votes",
        line: { color: PATRIOT_COLORS.white, width: 2.2 },
      },
      {
        x: filtered.map((r) => r.timestamp),
        y: filtered.map((r) => r.biden),
        mode: "lines",
        name: "Biden",
        line: { color: PATRIOT_COLORS.blue, width: 2 },
      },
      {
        x: filtered.map((r) => r.timestamp),
        y: filtered.map((r) => r.trump),
        mode: "lines",
        name: "Trump",
        line: { color: PATRIOT_COLORS.red, width: 2 },
      },
      {
        x: filtered.map((r) => r.timestamp),
        y: filtered.map((r) => r.third_party),
        mode: "lines",
        name: "Third Party",
        line: { color: PATRIOT_COLORS.purple, width: 1.8 },
      },
    ],
    {
      ...makeLayout("Cumulative Vote Timeline with Stop-Count Windows", {
        xTitle: "Time (UTC)",
        yTitle: "Votes",
        marginB: 90,
        legendY: -0.18,
      }),
      shapes: stopEvents.map((event) => ({
        type: "rect",
        xref: "x",
        yref: "paper",
        x0: event.stop_start,
        x1: event.stop_end,
        y0: 0,
        y1: 1,
        fillcolor: "rgba(245, 158, 11, 0.22)",
        line: { width: 0 },
        layer: "below",
      })),
    },
  );

  renderTable("stop-events-table", [
    { label: "ID", render: (r) => r.event_id },
    { label: "Stop Start", render: (r) => r.stop_start },
    { label: "Stop End", render: (r) => r.stop_end },
    { label: "Gap (min)", render: (r) => r.stop_gap_minutes },
    { label: "Votes Added", render: (r) => r.votes_added_after_gap },
    { label: "Large Burst", render: (r) => (r.is_large_post_gap_burst ? "Yes" : "No") },
    { label: "Burst Threshold", render: (r) => r.burst_threshold_votes },
  ], stopEvents);

  const spread = {};
  voteTypeRows.forEach((row) => {
    spread[row.vote_type] = (spread[row.vote_type] || 0) + row.votes;
  });
  const spreadRows = Object.entries(spread)
    .map(([vote_type, votes]) => ({ vote_type, votes }))
    .sort((a, b) => b.votes - a.votes);
  const spreadTotal = spreadRows.reduce((sum, row) => sum + row.votes, 0);

  if (spreadRows.length) {
    plotChart(
      "vote-type-spread-chart",
      [
        {
          labels: spreadRows.map((r) => r.vote_type),
          values: spreadRows.map((r) => r.votes),
          type: "pie",
          marker: {
            colors: spreadRows.map((r) => VOTE_TYPE_COLORS[r.vote_type] || PATRIOT_COLORS.purple),
          },
          textinfo: "label+percent",
          textfont: { color: PATRIOT_COLORS.white, size: 12 },
          hole: 0.35,
        },
      ],
      makeLayout("Vote-Type Spread for Selected Timestamp", { marginB: 70, legendY: -0.15 }),
    );
    renderTable("vote-type-spread-table", [
      { label: "Vote Type", render: (r) => r.vote_type },
      { label: "Votes", render: (r) => Math.round(r.votes) },
      {
        label: "Share",
        render: (r) => `${spreadTotal > 0 ? ((r.votes / spreadTotal) * 100).toFixed(2) : "0.00"}%`,
      },
    ], spreadRows);
  } else {
    document.getElementById("vote-type-spread-chart").innerHTML = "";
    document.getElementById("vote-type-spread-table").innerHTML = '<p class="muted">No vote-type rows at this timestamp.</p>';
  }

  const topCounties = countyDetail.slice(0, 25);
  if (topCounties.length) {
    plotChart(
      "county-vote-type-chart",
      [
        {
          x: topCounties.map((c) => c.county),
          y: topCounties.map((c) => c.absentee_votes),
          type: "bar",
          name: "absentee",
          marker: { color: VOTE_TYPE_COLORS.absentee },
        },
        {
          x: topCounties.map((c) => c.county),
          y: topCounties.map((c) => c.electionday_votes),
          type: "bar",
          name: "electionday",
          marker: { color: VOTE_TYPE_COLORS.electionday },
        },
        {
          x: topCounties.map((c) => c.county),
          y: topCounties.map((c) => c.provisional_votes),
          type: "bar",
          name: "provisional",
          marker: { color: VOTE_TYPE_COLORS.provisional },
        },
      ],
      {
        ...makeLayout("County Vote-Type Totals (Selected Timestamp)", {
          xTitle: "County",
          yTitle: "Votes",
          xTickAngle: -55,
          marginB: 170,
          marginL: 90,
          legendY: -0.32,
        }),
        barmode: "group",
      },
    );
    renderTable("county-vote-type-table", [
      { label: "County", render: (r) => r.county },
      { label: "Absentee", render: (r) => Math.round(r.absentee_votes) },
      { label: "Election Day", render: (r) => Math.round(r.electionday_votes) },
      { label: "Provisional", render: (r) => Math.round(r.provisional_votes) },
      { label: "Total Votes", render: (r) => Math.round(r.county_total_votes) },
      { label: "Absentee Share", render: (r) => `${(r.absentee_share * 100).toFixed(2)}%` },
      { label: "County Size", render: (r) => r.county_size },
    ], countyDetail);
  } else {
    document.getElementById("county-vote-type-chart").innerHTML = "";
    document.getElementById("county-vote-type-table").innerHTML = '<p class="muted">No county vote-type rows at this timestamp.</p>';
  }

  if (absentee.events.length) {
    const winnerColors = CANDIDATE_COLORS;
    plotChart(
      "absentee-drop-chart",
      [
        {
          x: absentee.events.map((r) => r.timestamp),
          y: absentee.events.map((r) => r.absentee_drop_votes),
          mode: "markers",
          marker: {
            size: absentee.events.map((r) => Math.max(10, Math.sqrt(r.winner_votes) * 1.4)),
            color: absentee.events.map((r) => winnerColors[r.winner] || PATRIOT_COLORS.white),
            line: { color: "rgba(248, 250, 252, 0.35)", width: 1 },
            opacity: 0.9,
          },
          text: absentee.events.map(
            (r) => `${r.county}<br>+${r.absentee_drop_votes} absentee<br>${r.winner} +${r.winner_votes}`,
          ),
          hoverinfo: "text",
          type: "scatter",
        },
      ],
      makeLayout("Large Absentee Vote Drops by Timestamp", {
        xTitle: "Timestamp (UTC)",
        yTitle: "Absentee Votes Added",
        marginB: 110,
        marginL: 96,
        legendY: -0.2,
      }),
    );
    renderTable("absentee-drop-table", [
      { label: "Timestamp", render: (r) => r.timestamp },
      { label: "County", render: (r) => r.county },
      { label: "Absentee Added", render: (r) => r.absentee_drop_votes },
      { label: "Biden", render: (r) => r.biden_delta },
      { label: "Trump", render: (r) => r.trump_delta },
      { label: "Other", render: (r) => r.other_delta },
      { label: "Top Recipient", render: (r) => r.winner },
      { label: "Recipient Share", render: (r) => `${(r.winner_share * 100).toFixed(2)}%` },
      { label: "County Total Votes", render: (r) => r.county_total_votes },
    ], absentee.events);
  } else {
    document.getElementById("absentee-drop-chart").innerHTML = "";
    document.getElementById("absentee-drop-table").innerHTML = "<p class=\"muted\">No large absentee drops matched current filters.</p>";
  }
}

async function syncMapBackground(fileName) {
  if (!window.buildMapDataFromPayload || !currentPayload) {
    return;
  }
  const map = await window.mapBackgroundReady;
  if (!map) {
    return;
  }
  const mapData = window.buildMapDataFromPayload(currentPayload, fileName);
  map.applyData(mapData);
}

async function loadState(fileName) {
  currentFileName = fileName;
  setStatus(`Loading ${fileName}…`);
  const response = await fetch(timelineDataUrl(fileName));
  if (!response.ok) {
    throw new Error(`Unable to load ${fileName} (${response.status})`);
  }
  currentPayload = await response.json();
  const timeseries = buildTimeseries(currentPayload);
  versionRows = buildVersionIndex(timeseries);

  const versionSelect = document.getElementById("version-select");
  versionSelect.innerHTML = "";
  versionRows.forEach((row) => {
    const option = document.createElement("option");
    option.value = row.version_id;
    option.textContent = `${row.version_label} | ${row.timestamp} | Total ${row.total_votes}`;
    versionSelect.appendChild(option);
  });
  if (versionRows.length) {
    versionSelect.value = versionRows[versionRows.length - 1].version_id;
  }
  setStatus(`Loaded ${fileName} (${versionRows.length} versions).`);
  renderAnalysis();
  const map = await window.mapBackgroundReady;
  if (map) {
    map.mapData = window.buildMapDataFromPayload(currentPayload, fileName);
  }
}

function updateSheetTitle(fileName) {
  const title = document.getElementById("sheet-state-title");
  if (!title) {
    return;
  }
  const state = manifest.states?.find((row) => row.file === fileName);
  title.textContent = state?.label || "State Analysis";
}

async function enterSelectedState() {
  const fileName = document.getElementById("state-select")?.value;
  if (!fileName) {
    return;
  }
  const btn = document.getElementById("enter-state-btn");
  if (btn) {
    btn.disabled = true;
  }
  try {
    await window.mapBackgroundReady;
    await loadState(fileName);
    updateSheetTitle(fileName);
    await window.AppShell.openStateDetail();
  } catch (error) {
    showPanel("error-panel", String(error.message || error));
  } finally {
    if (btn) {
      btn.disabled = false;
    }
  }
}

function manifestUrl() {
  const el = document.getElementById("manifest-api-url");
  if (el?.textContent?.trim()) {
    return el.textContent.trim();
  }
  return assetUrl("data/manifest.json");
}

async function init() {
  try {
    const response = await fetch(manifestUrl());
    if (!response.ok) {
      throw new Error("Missing docs/data/manifest.json. Run: python scripts/build_pages_site.py");
    }
    manifest = await response.json();
    const select = document.getElementById("state-select");
    select.innerHTML = "";
    manifest.states.forEach((state) => {
      const option = document.createElement("option");
      option.value = state.file;
      option.textContent = state.label || `${state.name} (${state.code})`;
      select.appendChild(option);
    });
    if (!manifest.states.length) {
      throw new Error("No timeline files found in manifest.");
    }
    select.value = manifest.states.find((s) => s.code === "PA")?.file || manifest.states[0].file;
    await window.mapBackgroundReady;
    setStatus(`Select a state — ${manifest.states.length} jurisdictions loaded.`);
  } catch (error) {
    showPanel("error-panel", String(error.message || error));
    setStatus("Failed to initialize site.");
  }
}

document.getElementById("enter-state-btn")?.addEventListener("click", () => {
  enterSelectedState().catch((error) => {
    showPanel("error-panel", String(error.message || error));
  });
});

document.getElementById("analysis-form")?.addEventListener("submit", (event) => {
  event.preventDefault();
  fadeContentSwap(() => Promise.resolve(renderAnalysis())).catch((error) => {
    showPanel("error-panel", String(error.message || error));
  });
});

document.getElementById("version-select")?.addEventListener("change", () => {
  fadeContentSwap(async () => {
    renderAnalysis();
    await syncMapBackground(currentFileName);
  })
    .catch((error) => {
      showPanel("error-panel", String(error.message || error));
    });
});

init().then(() => {
  requestAnimationFrame(() => document.body.classList.add("is-loaded"));
});

/* global MapBackground */
(function () {
  const CODE_TO_FIPS = {
    AL: "01", AK: "02", AZ: "04", AR: "05", CA: "06", CO: "08", CT: "09", DE: "10", DC: "11",
    FL: "12", GA: "13", HI: "15", ID: "16", IL: "17", IN: "18", IA: "19", KS: "20", KY: "21",
    LA: "22", ME: "23", MD: "24", MA: "25", MI: "26", MN: "27", MS: "28", MO: "29", MT: "30",
    NE: "31", NV: "32", NH: "33", NJ: "34", NM: "35", NY: "36", NC: "37", ND: "38", OH: "39",
    OK: "40", OR: "41", PA: "42", RI: "44", SC: "45", SD: "46", TN: "47", TX: "48", UT: "49",
    VT: "50", VA: "51", WA: "53", WV: "54", WI: "55", WY: "56",
  };

  const STATE_NEIGHBORS = {
    AL: ["TN", "GA", "FL", "MS"],
    AK: [],
    AZ: ["CA", "NV", "UT", "NM", "CO"],
    AR: ["MO", "TN", "MS", "LA", "TX", "OK"],
    CA: ["OR", "NV", "AZ"],
    CO: ["WY", "NE", "KS", "OK", "NM", "AZ", "UT"],
    CT: ["MA", "RI", "NY"],
    DE: ["MD", "PA", "NJ"],
    DC: ["MD", "VA"],
    FL: ["GA", "AL"],
    GA: ["FL", "AL", "TN", "NC", "SC"],
    HI: [],
    ID: ["MT", "WY", "UT", "NV", "OR", "WA"],
    IL: ["WI", "IA", "MO", "KY", "IN"],
    IN: ["MI", "OH", "KY", "IL"],
    IA: ["MN", "WI", "IL", "MO", "NE", "SD"],
    KS: ["NE", "MO", "OK", "CO"],
    KY: ["IL", "IN", "OH", "WV", "VA", "TN", "MO"],
    LA: ["TX", "AR", "MS"],
    ME: ["NH"],
    MD: ["PA", "DE", "VA", "WV"],
    MA: ["NH", "RI", "CT", "NY", "VT"],
    MI: ["OH", "IN", "WI"],
    MN: ["WI", "IA", "SD", "ND"],
    MS: ["TN", "AL", "LA", "AR"],
    MO: ["IA", "IL", "KY", "TN", "AR", "OK", "KS", "NE"],
    MT: ["ND", "SD", "WY", "ID"],
    NE: ["SD", "IA", "MO", "KS", "CO", "WY"],
    NV: ["OR", "ID", "UT", "AZ", "CA"],
    NH: ["ME", "MA", "VT"],
    NJ: ["NY", "PA", "DE"],
    NM: ["CO", "OK", "TX", "AZ"],
    NY: ["VT", "MA", "CT", "NJ", "PA"],
    NC: ["VA", "TN", "GA", "SC"],
    ND: ["MN", "SD", "MT"],
    OH: ["MI", "PA", "WV", "KY", "IN"],
    OK: ["KS", "MO", "AR", "TX", "NM", "CO"],
    OR: ["WA", "ID", "NV", "CA"],
    PA: ["NY", "NJ", "DE", "MD", "WV", "OH"],
    RI: ["MA", "CT"],
    SC: ["NC", "GA"],
    SD: ["ND", "MN", "IA", "NE", "WY", "MT"],
    TN: ["KY", "VA", "NC", "GA", "AL", "MS", "AR", "MO"],
    TX: ["OK", "AR", "LA", "NM"],
    UT: ["ID", "WY", "CO", "NM", "AZ", "NV"],
    VT: ["NY", "MA", "NH"],
    VA: ["MD", "WV", "KY", "TN", "NC", "DC"],
    WA: ["ID", "OR"],
    WV: ["OH", "PA", "MD", "VA", "KY"],
    WI: ["MI", "MN", "IA", "IL"],
    WY: ["MT", "SD", "NE", "CO", "UT", "ID"],
  };

  function normalizeName(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
  }

  function electionWinner(results) {
    if (!results || typeof results !== "object") {
      return "other";
    }
    const biden = Number(results.bidenj || results.biden || 0);
    const trump = Number(results.trumpd || results.trump || 0);
    const other = Number(results.jorgensenj || results.other || 0);
    if (biden > trump && biden >= other) {
      return "biden";
    }
    if (trump > biden && trump >= other) {
      return "trump";
    }
    return "other";
  }

  function winnerFromTimeseries(payload) {
    const rows = Array.isArray(payload.timeseries) ? payload.timeseries : [];
    for (let i = rows.length - 1; i >= 0; i -= 1) {
      const row = rows[i];
      if (!row || Number(row.votes || 0) <= 0) {
        continue;
      }
      return electionWinner(row.results);
    }
    return "other";
  }

  function winnerFromCounties(payload) {
    const totals = { biden: 0, trump: 0, other: 0 };
    const rows = Array.isArray(payload.county_totals) ? payload.county_totals : [];
    rows.forEach((row) => {
      const results = row?.results || {};
      totals.biden += Number(results.bidenj || 0);
      totals.trump += Number(results.trumpd || 0);
      totals.other += Number(results.jorgensenj || 0);
    });
    if (totals.biden > totals.trump && totals.biden >= totals.other) {
      return "biden";
    }
    if (totals.trump > totals.biden && totals.trump >= totals.other) {
      return "trump";
    }
    return "other";
  }

  function stateCodeFromPayload(payload, fileName) {
    if (payload?.state) {
      return String(payload.state).toUpperCase();
    }
    const match = String(fileName || "").match(/^([a-z]{2})_timeline\.json$/i);
    return match ? match[1].toUpperCase() : "";
  }

  function buildMapDataFromPayload(payload, fileName) {
    const stateCode = stateCodeFromPayload(payload, fileName);
    if (!stateCode) {
      return null;
    }
    let stateWinner = winnerFromTimeseries(payload);
    if (stateWinner === "other") {
      stateWinner = winnerFromCounties(payload);
    }
    const counties = (Array.isArray(payload.county_totals) ? payload.county_totals : []).map(
      (row) => ({
        fips: row.locality_fips ? String(row.locality_fips).padStart(5, "0") : "",
        name: String(row.locality_name || ""),
        name_key: normalizeName(row.locality_name),
        winner: electionWinner(row.results),
      }),
    );
    return {
      state_code: stateCode,
      state_fips: CODE_TO_FIPS[stateCode] || "",
      state_winner: stateWinner,
      neighbors: STATE_NEIGHBORS[stateCode] || [],
      counties,
    };
  }

  function resolveAssetPath(relativePath) {
    const cleaned = String(relativePath || "").replace(/^\//, "");
    const path = window.location.pathname.replace(/\/index\.html$/, "");
    const base = path.endsWith("/") ? path.slice(0, -1) : path;
    return `${base || ""}/${cleaned}`;
  }

  function winnersUrlFromPage() {
    const el = document.getElementById("map-winners-url");
    if (el?.textContent) {
      const raw = el.textContent.trim();
      if (raw.startsWith("http://") || raw.startsWith("https://") || raw.startsWith("/static/")) {
        return raw;
      }
      return resolveAssetPath(raw);
    }
    if (document.querySelector('link[href="assets/styles.css"]')) {
      return resolveAssetPath("data/us_state_winners.json");
    }
    return "/static/data/us_state_winners.json";
  }

  async function bootMapBackground() {
    if (typeof MapBackground === "undefined") {
      throw new Error("MapBackground is not loaded. Check map-background.js.");
    }
    if (typeof d3 === "undefined" || typeof d3.geoAlbersUsa !== "function") {
      throw new Error("d3.geoAlbersUsa is unavailable. Ensure d3@7 is loaded before map-background.js.");
    }
    if (typeof THREE === "undefined") {
      throw new Error("THREE is unavailable. Ensure three.js is loaded.");
    }
    if (typeof topojson === "undefined") {
      throw new Error("topojson is unavailable. Ensure topojson-client is loaded.");
    }

    const map = new MapBackground("map-canvas");
    await map.init({ winnersUrl: winnersUrlFromPage() });
    map.setViewportElement(
      document.getElementById("map-viewport-full") ||
        document.getElementById("map-viewport-transition") ||
        document.getElementById("map-viewport-inline"),
    );

    const dataEl = document.getElementById("map-data");
    if (dataEl?.textContent?.trim()) {
      try {
        map.applyData(JSON.parse(dataEl.textContent));
      } catch (error) {
        console.warn("Invalid map-data JSON, showing US overview.", error);
        map.applyUsOverview();
      }
    } else {
      map.applyUsOverview();
    }
    return map;
  }

  window.buildMapDataFromPayload = buildMapDataFromPayload;

  window.mapBackgroundReady = bootMapBackground()
    .then((map) => {
      window.mapBackground = map;
      return map;
    })
    .catch((error) => {
      console.error("[Warfront map] failed to initialize:", error);
      const status = document.getElementById("load-status");
      if (status) {
        status.textContent = `Map background unavailable: ${error.message}`;
      }
      return null;
    });
})();

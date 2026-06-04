/* global THREE, topojson, d3 */
(function () {
  const WINNER_COLORS = {
    biden: 0x3b82f6,
    trump: 0xef233c,
    other: 0x9b5de5,
  };

  const STATE_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json";
  const COUNTY_URL = "https://cdn.jsdelivr.net/npm/us-atlas@3/counties-10m.json";

  const CODE_TO_FIPS = {
    AL: "01", AK: "02", AZ: "04", AR: "05", CA: "06", CO: "08", CT: "09", DE: "10", DC: "11",
    FL: "12", GA: "13", HI: "15", ID: "16", IL: "17", IN: "18", IA: "19", KS: "20", KY: "21",
    LA: "22", ME: "23", MD: "24", MA: "25", MI: "26", MN: "27", MS: "28", MO: "29", MT: "30",
    NE: "31", NV: "32", NH: "33", NJ: "34", NM: "35", NY: "36", NC: "37", ND: "38", OH: "39",
    OK: "40", OR: "41", PA: "42", RI: "44", SC: "45", SD: "46", TN: "47", TX: "48", UT: "49",
    VT: "50", VA: "51", WA: "53", WV: "54", WI: "55", WY: "56",
  };

  const FIPS_TO_CODE = Object.fromEntries(
    Object.entries(CODE_TO_FIPS).map(([code, fips]) => [fips, code]),
  );

  function lerp(a, b, t) {
    return a + (b - a) * t;
  }

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
  }

  function padGeoBounds(bounds, ratio) {
    if (!isValidGeoBounds(bounds)) {
      return bounds;
    }
    const width = bounds[1][0] - bounds[0][0];
    const height = bounds[1][1] - bounds[0][1];
    return [
      [bounds[0][0] - width * ratio, bounds[0][1] - height * ratio],
      [bounds[1][0] + width * ratio, bounds[1][1] + height * ratio],
    ];
  }

  function disposeObject3D(obj) {
    if (obj.material && obj.material !== OUTLINE_MATERIAL) {
      obj.material.dispose();
    }
    if (obj.geometry) {
      obj.geometry.dispose();
    }
  }

  function boundsToView(bounds) {
    return {
      left: bounds[0][0],
      right: bounds[1][0],
      top: -bounds[0][1],
      bottom: -bounds[1][1],
    };
  }

  function isValidGeoBounds(bounds) {
    if (!bounds || bounds.length < 2) {
      return false;
    }
    const [[x0, y0], [x1, y1]] = bounds;
    return [x0, y0, x1, y1].every(Number.isFinite) && x1 > x0 + 1 && y1 > y0 + 1;
  }

  function sanitizeView(view) {
    if (
      !Number.isFinite(view.left) ||
      !Number.isFinite(view.right) ||
      !Number.isFinite(view.top) ||
      !Number.isFinite(view.bottom) ||
      view.right <= view.left ||
      view.top <= view.bottom
    ) {
      return { left: -1, right: 1, top: 1, bottom: -1 };
    }
    return view;
  }

  function aspectAdjustedBounds(bounds, viewportWidth, viewportHeight) {
    if (!isValidGeoBounds(bounds)) {
      return bounds;
    }
    const safeWidth = Math.max(1, Number(viewportWidth) || 1);
    const safeHeight = Math.max(1, Number(viewportHeight) || 1);
    const targetAspect = safeWidth / safeHeight;

    let x0 = bounds[0][0];
    let y0 = bounds[0][1];
    let x1 = bounds[1][0];
    let y1 = bounds[1][1];
    const width = x1 - x0;
    const height = y1 - y0;
    const boundsAspect = width / height;

    if (boundsAspect > targetAspect) {
      const targetHeight = width / targetAspect;
      const delta = (targetHeight - height) / 2;
      y0 -= delta;
      y1 += delta;
    } else if (boundsAspect < targetAspect) {
      const targetWidth = height * targetAspect;
      const delta = (targetWidth - width) / 2;
      x0 -= delta;
      x1 += delta;
    }

    return [[x0, y0], [x1, y1]];
  }

  const OUTLINE_MATERIAL = new THREE.LineBasicMaterial({
    color: 0x93c5fd,
    transparent: true,
    opacity: 0.85,
  });

  function normalizeName(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[^a-z0-9]/g, "");
  }

  function winnerColor(winner) {
    return new THREE.Color(WINNER_COLORS[winner] || WINNER_COLORS.other);
  }

  function projectedBounds(projection, object) {
    return d3.geoPath(projection).bounds(object);
  }

  function ringToShape(ring, projection) {
    const shape = new THREE.Shape();
    ring.forEach((coord, index) => {
      const projected = projection(coord);
      if (!projected) {
        return;
      }
      const [x, y] = projected;
      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        return;
      }
      if (index === 0) {
        shape.moveTo(x, -y);
      } else {
        shape.lineTo(x, -y);
      }
    });
    return shape;
  }

  function geometryFromFeature(feature, projection) {
    const geometries = [];
    const { type, coordinates } = feature.geometry;
    const polygons = type === "Polygon" ? [coordinates] : coordinates;
    polygons.forEach((polygon) => {
      if (!polygon.length) {
        return;
      }
      const shape = ringToShape(polygon[0], projection);
      polygon.slice(1).forEach((hole) => {
        shape.holes.push(ringToShape(hole, projection));
      });
      geometries.push(new THREE.ShapeGeometry(shape));
    });
    return geometries;
  }

  function outlineFromFeature(feature, projection) {
    const group = new THREE.Group();
    const addRing = (ring) => {
      if (!Array.isArray(ring) || ring.length < 2) {
        return;
      }
      const positions = [];
      ring.forEach((coord) => {
        const projected = projection(coord);
        if (!projected) {
          return;
        }
        const [x, y] = projected;
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
          return;
        }
        positions.push(x, -y, 0.01);
      });
      if (positions.length < 6) {
        return;
      }
      const geometry = new THREE.BufferGeometry();
      geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
      geometry.computeBoundingSphere();
      group.add(new THREE.LineLoop(geometry, OUTLINE_MATERIAL));
    };

    const { type, coordinates } = feature.geometry;
    if (type === "Polygon") {
      coordinates.forEach(addRing);
    } else {
      coordinates.forEach((polygon) => {
        if (Array.isArray(polygon)) {
          polygon.forEach(addRing);
        }
      });
    }
    return group;
  }

  class MapBackground {
    constructor(canvasId) {
      this.canvas = document.getElementById(canvasId);
      this.viewportEl = null;
      this.ready = false;
      this.pendingData = null;
      this.usWinners = { by_fips: {}, by_code: {} };
      this.mapData = null;
      this.stateMeshes = new Map();
      this.clock = new THREE.Clock();
      this.winnersJsonUrl = "/static/data/us_state_winners.json";
      this.view = { left: 0, right: 1, top: 1, bottom: 0 };
      this.targetView = { left: 0, right: 1, top: 1, bottom: 0 };
      this.layoutAnimFrame = null;
      this.countyLayer = null;
      this.viewportRectOverride = null;
    }

    setViewportElement(element) {
      this.viewportEl = element || null;
      if (this.ready) {
        this.refreshLayout();
      }
    }

    setViewportRectOverride(rect) {
      if (!rect) {
        this.viewportRectOverride = null;
        return;
      }
      const next = {
        left: Number(rect.left),
        top: Number(rect.top),
        width: Number(rect.width),
        height: Number(rect.height),
      };
      if (
        !Number.isFinite(next.left) ||
        !Number.isFinite(next.top) ||
        !Number.isFinite(next.width) ||
        !Number.isFinite(next.height) ||
        next.width < 1 ||
        next.height < 1
      ) {
        return;
      }
      this.viewportRectOverride = next;
    }

    getViewportRect() {
      if (this.viewportRectOverride) {
        return this.viewportRectOverride;
      }
      if (this.viewportEl) {
        const rect = this.viewportEl.getBoundingClientRect();
        return {
          left: rect.left,
          top: rect.top,
          width: Math.max(rect.width, 1),
          height: Math.max(rect.height, 1),
        };
      }
      return {
        left: 0,
        top: 0,
        width: window.innerWidth,
        height: window.innerHeight,
      };
    }

    async init(options = {}) {
      if (!this.canvas) {
        throw new Error("Missing #map-canvas element.");
      }
      if (typeof THREE === "undefined" || typeof d3 === "undefined" || typeof topojson === "undefined") {
        throw new Error("Map libraries failed to load.");
      }
      if (options.winnersUrl) {
        this.winnersJsonUrl = options.winnersUrl;
      }

      this.renderer = new THREE.WebGLRenderer({
        canvas: this.canvas,
        antialias: true,
        alpha: true,
      });
      this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      this.renderer.setClearColor(0x000000, 0);

      this.scene = new THREE.Scene();
      this.mapRoot = new THREE.Group();
      this.stateLayer = new THREE.Group();
      this.countyLayer = new THREE.Group();
      this.countyLayer.visible = false;
      this.mapRoot.add(this.stateLayer);
      this.mapRoot.add(this.countyLayer);
      this.scene.add(this.mapRoot);

      window.addEventListener("resize", () => this.refreshLayout());

      const [statesResponse, countiesResponse, winnersResponse] = await Promise.all([
        fetch(STATE_URL),
        fetch(COUNTY_URL),
        fetch(this.winnersJsonUrl),
      ]);
      if (!statesResponse.ok || !countiesResponse.ok) {
        throw new Error("Unable to load US map geometry.");
      }

      const [usTopo, countyTopo, winners] = await Promise.all([
        statesResponse.json(),
        countiesResponse.json(),
        winnersResponse.ok ? winnersResponse.json() : { by_fips: {}, by_code: {} },
      ]);

      this.usWinners = winners;
      this.states = topojson.feature(usTopo, usTopo.objects.states).features;
      this.counties = topojson.feature(countyTopo, countyTopo.objects.counties).features;

      this.ready = true;
      this.refreshLayout();
      this.applyUsOverview();

      if (this.pendingData) {
        const pending = this.pendingData;
        this.pendingData = null;
        this.applyData(pending);
      }
      this.animate();
    }

    setTargetBounds(bounds, viewportRect = this.getViewportRect()) {
      if (!isValidGeoBounds(bounds)) {
        return;
      }
      const adjusted = aspectAdjustedBounds(bounds, viewportRect.width, viewportRect.height);
      if (!isValidGeoBounds(adjusted)) {
        return;
      }
      const next = boundsToView(adjusted);
      this.targetView = sanitizeView(next);
      if (!this.camera) {
        this.view = { ...this.targetView };
        this.camera = new THREE.OrthographicCamera(
          this.view.left,
          this.view.right,
          this.view.top,
          this.view.bottom,
          0.1,
          2000,
        );
        this.camera.position.set(0, 0, 500);
        this.camera.lookAt(0, 0, 0);
      }
    }

    fitFeatures(features, padding = 0.05) {
      const { width, height } = this.getViewportRect();
      if (width < 16 || height < 16) {
        return null;
      }
      const padX = Math.max(width * padding, 4);
      const padY = Math.max(height * padding, 4);
      const collection = { type: "FeatureCollection", features };
      this.baseProjection = d3.geoAlbersUsa().fitExtent(
        [[padX, padY], [width - padX, height - padY]],
        collection,
      );
      this.projection = (coord) => this.baseProjection(coord);
      const bounds = projectedBounds(this.baseProjection, collection);
      if (!isValidGeoBounds(bounds)) {
        return null;
      }
      this.mapWidth = bounds[1][0] - bounds[0][0];
      this.mapHeight = bounds[1][1] - bounds[0][1];
      this.setTargetBounds(bounds, { width, height });
      return bounds;
    }

    buildStates() {
      while (this.stateLayer.children.length) {
        const child = this.stateLayer.children[0];
        this.stateLayer.remove(child);
        child.traverse(disposeObject3D);
      }
      this.stateMeshes.clear();

      this.states.forEach((feature) => {
        const fips = String(feature.id).padStart(2, "0");
        const code = FIPS_TO_CODE[fips] || "";
        const group = new THREE.Group();
        group.userData = { fips, code, type: "state" };
        geometryFromFeature(feature, this.projection).forEach((geometry) => {
          group.add(
            new THREE.Mesh(
              geometry,
              new THREE.MeshBasicMaterial({
                color: 0x1e293b,
                transparent: true,
                opacity: 0.35,
                side: THREE.DoubleSide,
                depthWrite: false,
              }),
            ),
          );
        });
        const outline = outlineFromFeature(feature, this.projection);
        outline.renderOrder = 2;
        group.add(outline);
        this.stateLayer.add(group);
        this.stateMeshes.set(fips, group);
      });
    }

    clearCounties() {
      while (this.countyLayer.children.length) {
        const child = this.countyLayer.children.pop();
        child.traverse(disposeObject3D);
      }
    }

    buildCounties(stateFips, countyWinners) {
      this.clearCounties();
      const winnersByFips = new Map();
      const winnersByName = new Map();
      countyWinners.forEach((row) => {
        if (row.fips) {
          winnersByFips.set(String(row.fips).padStart(5, "0"), row.winner);
        }
        const key = row.name_key || normalizeName(row.name);
        if (key) {
          winnersByName.set(key, row.winner);
        }
      });

      const prefix = String(stateFips).padStart(2, "0");
      this.counties
        .filter((feature) => String(feature.id).padStart(5, "0").startsWith(prefix))
        .forEach((feature) => {
          const fips = String(feature.id).padStart(5, "0");
          const nameKey = normalizeName(feature.properties?.name || "");
          const winner = winnersByFips.get(fips) || winnersByName.get(nameKey) || "other";
          const fill = winnerColor(winner);
          geometryFromFeature(feature, this.projection).forEach((geometry) => {
            const mesh = new THREE.Mesh(
              geometry,
              new THREE.MeshBasicMaterial({
                color: fill,
                transparent: true,
                opacity: 0.68,
                side: THREE.DoubleSide,
                depthWrite: false,
              }),
            );
            mesh.renderOrder = 1;
            this.countyLayer.add(mesh);
          });
          const outline = outlineFromFeature(feature, this.projection);
          outline.traverse((child) => {
            if (child.material) {
              child.material.color.setHex(0xe2e8f0);
              child.material.opacity = 0.55;
            }
          });
          outline.renderOrder = 3;
          this.countyLayer.add(outline);
        });
    }

    setStateMaterial(group, winner, role) {
      const color = winnerColor(winner);
      let fillOpacity = 0.2;
      let outlineOpacity = 0.3;
      let outlineColor = 0x334155;

      if (role === "focus") {
        fillOpacity = 0.82;
        outlineOpacity = 1;
        outlineColor = 0xf8fafc;
      } else if (role === "neighbor") {
        fillOpacity = 0.12;
        outlineOpacity = 0.95;
        outlineColor = 0x60a5fa;
      } else if (role === "us") {
        fillOpacity = 0.55;
        outlineOpacity = 0.7;
        outlineColor = 0x94a3b8;
      } else {
        fillOpacity = 0.06;
        outlineOpacity = 0.22;
      }

      const applyOutline = (obj) => {
        if (obj.isLineLoop || obj.isLineSegments || obj.isLine) {
          obj.material.color.setHex(outlineColor);
          obj.material.opacity = outlineOpacity;
        }
      };

      group.children.forEach((child) => {
        if (child.isMesh) {
          child.material.color.copy(color);
          child.material.opacity = fillOpacity;
        }
        if (child.isGroup) {
          child.traverse(applyOutline);
        } else {
          applyOutline(child);
        }
      });
    }

    getFocusFeature(mapData) {
      const code = String(mapData?.state_code || "").toUpperCase();
      const fips = String(mapData?.state_fips || CODE_TO_FIPS[code] || "").padStart(2, "0");
      return this.states.find((feature) => String(feature.id).padStart(2, "0") === fips);
    }

    animateTargetView(endView, durationMs) {
      const target = sanitizeView(endView);
      const startView = sanitizeView({ ...this.view });
      const start = performance.now();
      return new Promise((resolve) => {
        const step = (now) => {
          const t = easeInOutCubic(Math.min(1, (now - start) / durationMs));
          this.targetView = sanitizeView({
            left: lerp(startView.left, target.left, t),
            right: lerp(startView.right, target.right, t),
            top: lerp(startView.top, target.top, t),
            bottom: lerp(startView.bottom, target.bottom, t),
          });
          if (t < 1) {
            requestAnimationFrame(step);
          } else {
            resolve();
          }
        };
        requestAnimationFrame(step);
      });
    }

    applyStateMaterials(mapData) {
      const code = String(mapData.state_code || "").toUpperCase();
      const fips = String(mapData.state_fips || CODE_TO_FIPS[code] || "").padStart(2, "0");
      const neighbors = new Set((mapData.neighbors || []).map((value) => value.toUpperCase()));

      this.stateMeshes.forEach((group, stateFips) => {
        const stateCode = FIPS_TO_CODE[stateFips] || "";
        let role = "dim";
        if (stateFips === fips) {
          role = "focus";
        } else if (neighbors.has(stateCode)) {
          role = "neighbor";
        }
        const winner =
          stateFips === fips
            ? mapData.state_winner
            : this.usWinners.by_fips?.[stateFips] || "other";
        this.setStateMaterial(group, winner, role);
      });
    }

    async flyToState(mapData, durationMs = 640) {
      const feature = this.getFocusFeature(mapData);
      if (!feature) {
        return;
      }
      this.mapData = mapData;
      this.applyUsOverview({ keepMapData: true });
      this.view = { ...this.targetView };

      const rawBounds = projectedBounds(this.baseProjection, feature);
      if (!isValidGeoBounds(rawBounds)) {
        return;
      }
      const bounds = padGeoBounds(rawBounds, 0.22);
      if (!isValidGeoBounds(bounds)) {
        return;
      }
      this.applyStateMaterials(mapData);
      const vp = this.getViewportRect();
      const adjusted = aspectAdjustedBounds(bounds, vp.width, vp.height);
      await this.animateTargetView(boundsToView(adjusted), durationMs);

      const fips = String(mapData.state_fips || "").padStart(2, "0");
      this.buildCounties(fips, mapData.counties || []);
      this.countyLayer.visible = true;
    }

    async flyToUsOverview(durationMs = 560) {
      this.countyLayer.visible = false;
      this.clearCounties();
      const startView = sanitizeView({ ...this.view });
      const fitted = this.fitFeatures(this.states, 0.04);
      if (!fitted) {
        return;
      }
      this.buildStates();
      this.stateMeshes.forEach((group, fips) => {
        const winner = this.usWinners.by_fips?.[fips] || "other";
        this.setStateMaterial(group, winner, "us");
      });
      const bounds = padGeoBounds(fitted, 0.05);
      if (!isValidGeoBounds(bounds)) {
        return;
      }
      const vp = this.getViewportRect();
      const adjusted = aspectAdjustedBounds(bounds, vp.width, vp.height);
      this.view = startView;
      await this.animateTargetView(boundsToView(adjusted), durationMs);
      this.mapData = null;
    }

    applyUsOverview(options = {}) {
      this.countyLayer.visible = false;
      if (!options.keepMapData) {
        this.mapData = null;
      }
      this.fitFeatures(this.states, 0.04);
      this.buildStates();
      this.stateMeshes.forEach((group, fips) => {
        const winner = this.usWinners.by_fips?.[fips] || "other";
        this.setStateMaterial(group, winner, "us");
      });
    }

    applyStateFocus(mapData) {
      const code = String(mapData.state_code || "").toUpperCase();
      const fips = String(mapData.state_fips || CODE_TO_FIPS[code] || "").padStart(2, "0");
      const neighbors = new Set((mapData.neighbors || []).map((value) => value.toUpperCase()));

      const focusFeature = this.states.find(
        (feature) => String(feature.id).padStart(2, "0") === fips,
      );
      if (!focusFeature) {
        this.applyUsOverview();
        return;
      }

      // Keep a little extra padding so the focused state stays fully inside the viewer bounds.
      this.fitFeatures([focusFeature], 0.14);
      this.buildStates();
      this.buildCounties(fips, mapData.counties || []);
      this.countyLayer.visible = true;

      this.stateMeshes.forEach((group, stateFips) => {
        const stateCode = FIPS_TO_CODE[stateFips] || "";
        let role = "dim";
        if (stateFips === fips) {
          role = "focus";
        } else if (neighbors.has(stateCode)) {
          role = "neighbor";
        }
        const winner =
          stateFips === fips
            ? mapData.state_winner
            : this.usWinners.by_fips?.[stateFips] || "other";
        this.setStateMaterial(group, winner, role);
      });
    }

    applyData(mapData, options = {}) {
      if (!this.ready) {
        this.pendingData = mapData;
        return;
      }
      if (!mapData || !mapData.state_code) {
        this.applyUsOverview();
        return;
      }
      if (options.fly) {
        return this.flyToState(mapData, options.durationMs || 640);
      }
      this.mapData = mapData;
      this.applyStateFocus(mapData);
    }

    updateRendererViewport() {
      if (!this.renderer) {
        return;
      }
      const fullW = window.innerWidth;
      const fullH = window.innerHeight;
      this.renderer.setSize(fullW, fullH, false);

      const vp = this.getViewportRect();
      const scissorY = fullH - vp.top - vp.height;
      this.renderer.setScissorTest(true);
      this.renderer.setScissor(vp.left, scissorY, vp.width, vp.height);
      this.renderer.setViewport(vp.left, scissorY, vp.width, vp.height);
    }

    refreshLayout() {
      if (!this.renderer || !this.states) {
        return;
      }
      const vp = this.getViewportRect();
      this.updateRendererViewport();
      if (vp.width < 16 || vp.height < 16) {
        return;
      }
      if (this.mapData?.state_code) {
        this.applyStateFocus(this.mapData);
      } else {
        this.applyUsOverview();
      }
    }

    /**
     * Re-fit the map every frame while CSS animates viewport height (sheet / stage).
     */
    runLayoutAnimation(durationMs = 650) {
      if (this.layoutAnimFrame) {
        cancelAnimationFrame(this.layoutAnimFrame);
      }
      const start = performance.now();
      const step = (now) => {
        this.refreshLayout();
        if (now - start < durationMs) {
          this.layoutAnimFrame = requestAnimationFrame(step);
        } else {
          this.layoutAnimFrame = null;
          this.refreshLayout();
        }
      };
      this.layoutAnimFrame = requestAnimationFrame(step);
      return new Promise((resolve) => window.setTimeout(resolve, durationMs));
    }

    animate() {
      requestAnimationFrame(() => this.animate());
      if (!this.renderer || !this.camera) {
        return;
      }

      const dt = Math.min(this.clock.getDelta(), 0.05);
      const ease = 1 - Math.pow(0.00008, dt * 60);
      const target = sanitizeView(this.targetView);
      this.view = sanitizeView({
        left: lerp(this.view.left, target.left, ease),
        right: lerp(this.view.right, target.right, ease),
        top: lerp(this.view.top, target.top, ease),
        bottom: lerp(this.view.bottom, target.bottom, ease),
      });

      this.camera.left = this.view.left;
      this.camera.right = this.view.right;
      this.camera.top = this.view.top;
      this.camera.bottom = this.view.bottom;
      this.camera.updateProjectionMatrix();

      const fullW = window.innerWidth;
      const fullH = window.innerHeight;
      this.renderer.setScissorTest(false);
      this.renderer.setViewport(0, 0, fullW, fullH);
      this.renderer.setClearColor(0x000000, 0);
      this.renderer.clear(true, true, true);

      this.updateRendererViewport();
      if (Number.isFinite(this.view.left)) {
        this.renderer.render(this.scene, this.camera);
      }
    }
  }

  window.MapBackground = MapBackground;
})();

/* global MapBackground */
(function () {
  const GLITCH_MS = 760;
  const GLITCH_MID_MS = 340;
  const LAYOUT_MS = 400;
  const MORPH_SCROLL_DISTANCE = 380;
  const MORPH_PROGRESS_EPSILON = 0.0125;
  const HEADER_PIN_TOP_PX = 10;
  const MATRIX_CHARS = "01 2020年の選挙は盗まれた このウェブサイトは、選挙に不正があったことを証明している 01";

  function $(id) {
    return document.getElementById(id);
  }

  function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  function nextFrame() {
    return new Promise((resolve) => requestAnimationFrame(resolve));
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function clamp01(value) {
    return Math.max(0, Math.min(1, value));
  }

  function easeInOutCubic(t) {
    return t < 0.5 ? 4 * t * t * t : 1 - ((-2 * t + 2) ** 3) / 2;
  }

  function rectFromElement(element) {
    if (!element) {
      return null;
    }
    const rect = element.getBoundingClientRect();
    if (
      !Number.isFinite(rect.left) ||
      !Number.isFinite(rect.top) ||
      !Number.isFinite(rect.width) ||
      !Number.isFinite(rect.height)
    ) {
      return null;
    }
    return {
      left: rect.left,
      top: rect.top,
      width: Math.max(1, rect.width),
      height: Math.max(1, rect.height),
    };
  }

  function lerpRect(fromRect, toRect, t) {
    return {
      left: fromRect.left + (toRect.left - fromRect.left) * t,
      top: fromRect.top + (toRect.top - fromRect.top) * t,
      width: fromRect.width + (toRect.width - fromRect.width) * t,
      height: fromRect.height + (toRect.height - fromRect.height) * t,
    };
  }

  function setMapViewportForMode(mode) {
    const map = window.mapBackground;
    if (!map) {
      return;
    }
    if (mode === "detail-transition") {
      map.setViewportElement($("map-viewport-transition"));
    } else if (mode === "detail-inline") {
      map.setViewportElement($("map-viewport-inline"));
    } else {
      map.setViewportElement($("map-viewport-full"));
    }
  }

  function resizeCharts() {
    if (!window.Plotly) {
      return;
    }
    document.querySelectorAll(".js-plotly-plot").forEach((plot) => {
      Plotly.Plots.resize(plot);
    });
  }

  let matrixFrame = null;
  let morphCleanup = null;

  function startMatrixRain() {
    const canvas = $("glitch-matrix-canvas");
    if (!canvas) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    const resize = () => {
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
    };
    resize();

    const fontSize = 13;
    const columns = Math.ceil(canvas.width / fontSize);
    const drops = new Float32Array(columns);
    for (let i = 0; i < columns; i += 1) {
      drops[i] = Math.random() * -40;
    }

    const draw = () => {
      ctx.fillStyle = "rgba(3, 8, 20, 0.18)";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.font = `600 ${fontSize}px "Courier New", monospace`;

      for (let i = 0; i < columns; i += 1) {
        const x = i * fontSize;
        const y = drops[i] * fontSize;
        const char = MATRIX_CHARS[Math.floor(Math.random() * MATRIX_CHARS.length)];
        const head = Math.random() > 0.985;
        ctx.fillStyle = head ? "#f8fafc" : "#60a5fa";
        ctx.shadowColor = "#3b82f6";
        ctx.shadowBlur = head ? 10 : 4;
        ctx.fillText(char, x, y);
        ctx.shadowBlur = 0;

        if (y > canvas.height && Math.random() > 0.965) {
          drops[i] = 0;
        }
        drops[i] += 0.55 + Math.random() * 0.85;
      }

      matrixFrame = requestAnimationFrame(draw);
    };

    draw();
    window.addEventListener("resize", resize);
    canvas._matrixResize = resize;
  }

  function stopMatrixRain() {
    if (matrixFrame) {
      cancelAnimationFrame(matrixFrame);
      matrixFrame = null;
    }
    const canvas = $("glitch-matrix-canvas");
    if (canvas?._matrixResize) {
      window.removeEventListener("resize", canvas._matrixResize);
      delete canvas._matrixResize;
    }
    if (canvas) {
      const ctx = canvas.getContext("2d");
      ctx?.clearRect(0, 0, canvas.width, canvas.height);
    }
  }

  function showGlitchOverlay(label, direction) {
    const overlay = $("matrix-glitch-overlay");
    const labelEl = overlay?.querySelector(".glitch-label");
    if (labelEl) {
      labelEl.textContent = label;
    }
    document.body.classList.add("matrix-glitch-active", direction);
    overlay?.classList.add("is-active");
    overlay?.setAttribute("aria-hidden", "false");
    startMatrixRain();
  }

  function hideGlitchOverlay() {
    stopMatrixRain();
    document.body.classList.remove(
      "matrix-glitch-active",
      "matrix-glitch-to-detail",
      "matrix-glitch-to-entry",
      "map-bg-fade-out",
    );
    const overlay = $("matrix-glitch-overlay");
    overlay?.classList.remove("is-active");
    overlay?.setAttribute("aria-hidden", "true");
  }

  async function fadeMapOut() {
    document.body.classList.add("map-bg-fade-out");
    await wait(280);
  }

  async function fadeMapIn() {
    document.body.classList.remove("map-bg-fade-out");
    await wait(280);
  }

  async function runGlitchTransition(direction, midCallback) {
    if (prefersReducedMotion()) {
      document.body.classList.add("map-bg-fade-out");
      await wait(220);
      await midCallback();
      document.body.classList.remove("map-bg-fade-out");
      await wait(220);
      return;
    }

    const toDetail = direction === "matrix-glitch-to-detail";
    const label = toDetail ? "LOADING TO :: STATE NODE" : "UNLOADING TO :: US GRID";
    showGlitchOverlay(label, direction);
    await wait(GLITCH_MID_MS);
    await midCallback();
    await wait(GLITCH_MS - GLITCH_MID_MS);
    hideGlitchOverlay();
  }

  function stopMorphController() {
    if (morphCleanup) {
      morphCleanup();
      morphCleanup = null;
    }
  }

  function startMorphController(map) {
    const scrollEl = $("detail-scroll");
    const transitionViewport = $("map-viewport-transition");
    const inlineViewport = $("map-viewport-inline");
    const detailHero = document.querySelector(".detail-hero");
    if (!scrollEl || !transitionViewport || !inlineViewport) {
      return () => {};
    }

    let rafId = 0;
    let mode = "transition";
    let pinScrollTop = null;
    let targetProgress = 0;
    let currentProgress = 0;
    let lastAppliedProgress = -1;

    const computeTargetProgress = () => {
      const heroRect = rectFromElement(detailHero);
      if (heroRect && heroRect.top <= HEADER_PIN_TOP_PX && pinScrollTop === null) {
        pinScrollTop = Math.max(1, scrollEl.scrollTop);
      }
      const heroPinnedToTop = Boolean(heroRect && heroRect.top <= HEADER_PIN_TOP_PX);
      const morphDistance = pinScrollTop || MORPH_SCROLL_DISTANCE;
      const scrollProgress = clamp01(scrollEl.scrollTop / morphDistance);
      return heroPinnedToTop ? 1 : scrollProgress;
    };

    const applyProgress = (progress) => {
      if (
        Math.abs(progress - lastAppliedProgress) < MORPH_PROGRESS_EPSILON &&
        progress > 0 &&
        progress < 1
      ) {
        return;
      }
      lastAppliedProgress = progress;
      const eased = easeInOutCubic(progress);
      document.documentElement.style.setProperty("--map-morph-progress", `${eased}`);

      if (eased >= 1) {
        map.setViewportRectOverride(null);
        if (mode !== "inline") {
          mode = "inline";
          setMapViewportForMode("detail-inline");
          map.refreshLayout();
        }
        return;
      }

      if (mode !== "transition") {
        mode = "transition";
        setMapViewportForMode("detail-transition");
      }

      const startRect = rectFromElement(transitionViewport);
      const endRect = rectFromElement(inlineViewport);
      if (!startRect || !endRect) {
        return;
      }
      const rect = lerpRect(startRect, endRect, eased);
      map.setViewportRectOverride(rect);
      map.refreshLayout();
    };

    const animateProgress = () => {
      rafId = 0;
      const delta = targetProgress - currentProgress;
      if (Math.abs(delta) > 0.001) {
        currentProgress += delta * 0.24;
        if (Math.abs(delta) < 0.01) {
          currentProgress = targetProgress;
        }
      } else {
        currentProgress = targetProgress;
      }

      applyProgress(currentProgress);

      if (Math.abs(targetProgress - currentProgress) > 0.001) {
        rafId = requestAnimationFrame(animateProgress);
      }
    };

    const scheduleUpdate = () => {
      targetProgress = computeTargetProgress();
      if (rafId) {
        return;
      }
      rafId = requestAnimationFrame(animateProgress);
    };

    scrollEl.addEventListener("scroll", scheduleUpdate, { passive: true });
    window.addEventListener("resize", scheduleUpdate);
    scheduleUpdate();

    return () => {
      scrollEl.removeEventListener("scroll", scheduleUpdate);
      window.removeEventListener("resize", scheduleUpdate);
      if (rafId) {
        cancelAnimationFrame(rafId);
        rafId = 0;
      }
      map.setViewportRectOverride(null);
      document.documentElement.style.setProperty("--map-morph-progress", "0");
    };
  }

  async function openStateDetail() {
    const map = window.mapBackground;
    const body = document.body;
    const detailView = $("state-detail-view");
    const detailScroll = $("detail-scroll");

    const mapData = map?.mapData;
    if (!mapData?.state_code) {
      return;
    }

    stopMorphController();
    document.documentElement.style.setProperty("--map-morph-progress", "0");

    await runGlitchTransition("matrix-glitch-to-detail", async () => {
      await fadeMapOut();
      body.classList.remove("map-mode-entry");
      body.classList.add("map-mode-detail");
      detailView?.setAttribute("aria-hidden", "false");
      if (detailScroll) {
        detailScroll.scrollTop = 0;
      }

      setMapViewportForMode("detail-transition");
      map.setViewportRectOverride(null);
      await nextFrame();
      await nextFrame();

      map.applyStateFocus(mapData);
      await map.runLayoutAnimation(LAYOUT_MS);
      morphCleanup = startMorphController(map);
    });

    await fadeMapIn();
    map.refreshLayout();

    window.dispatchEvent(new Event("resize"));
    resizeCharts();
  }

  async function closeStateDetail() {
    const map = window.mapBackground;
    const body = document.body;
    const detailView = $("state-detail-view");
    const detailScroll = $("detail-scroll");

    stopMorphController();
    document.documentElement.style.setProperty("--map-morph-progress", "0");

    await runGlitchTransition("matrix-glitch-to-entry", async () => {
      await fadeMapOut();
      detailView?.setAttribute("aria-hidden", "true");
      if (detailScroll) {
        detailScroll.scrollTop = 0;
      }
      setMapViewportForMode("entry");
      map.setViewportRectOverride(null);
      await nextFrame();

      if (map) {
        map.applyUsOverview();
        map.mapData = null;
      }

      body.classList.remove("map-mode-detail");
      body.classList.add("map-mode-entry");
    });

    await fadeMapIn();

    window.dispatchEvent(new Event("resize"));
    resizeCharts();
  }

  window.AppShell = {
    openStateDetail,
    closeStateDetail,
    setMapViewportForMode,
    GLITCH_MS,
    LAYOUT_MS,
  };

  document.addEventListener("DOMContentLoaded", () => {
    $("sheet-dismiss")?.addEventListener("click", () => {
      closeStateDetail().catch(console.error);
    });
  });
})();

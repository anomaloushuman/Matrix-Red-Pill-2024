(function () {
  const SWAP_MS = 320;

  function markLoaded() {
    requestAnimationFrame(() => {
      document.body.classList.add("is-loaded");
    });
  }

  function swapThenSubmit(form) {
    const content = document.getElementById("app-content");
    const loader = document.getElementById("page-loader");
    document.body.classList.add("is-swapping");
    if (loader) {
      loader.classList.add("is-active");
    }
    if (content) {
      content.classList.add("is-swapping");
    }
    window.setTimeout(() => form.submit(), SWAP_MS);
  }

  function bindFilterForm() {
    const form = document.getElementById("filter-form");
    if (!form) {
      return;
    }
    form.querySelectorAll("select").forEach((select) => {
      select.addEventListener("change", () => swapThenSubmit(form));
    });
    form.addEventListener("submit", (event) => {
      if (document.body.classList.contains("is-swapping")) {
        return;
      }
      event.preventDefault();
      swapThenSubmit(form);
    });
  }

  markLoaded();
  bindFilterForm();
})();

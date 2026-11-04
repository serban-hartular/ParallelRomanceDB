/* htmx owns the workspace; Tabulator owns the preserved grid inside it. */
(() => {
  "use strict";

  const preferences = new Map();
  let active = null;
  let updates = Promise.resolve();

  function settingsFor(dataset) {
    const key = `xldb.layout.v1.${dataset}`;
    if (!preferences.has(key)) {
      let saved = {};
      try {
        saved = JSON.parse(localStorage.getItem(key) || "{}");
      } catch (_) {
        // Keep the controls usable when browser storage is unavailable.
      }
      preferences.set(key, {
        key,
        columns: saved?.columns && typeof saved.columns === "object" ? saved.columns : {},
        heights: saved?.heights && typeof saved.heights === "object" ? saved.heights : {},
      });
    }
    return preferences.get(key);
  }

  function saveSettings(settings) {
    try {
      localStorage.setItem(settings.key, JSON.stringify({
        columns: settings.columns,
        heights: settings.heights,
      }));
    } catch (_) {
      // The in-memory preferences still survive searches and selections.
    }
  }

  function fieldKey(instance, field) {
    const column = instance.payload.columns.find(item => item.field === field);
    return column ? `content:${column.title}` : `meta:${field}`;
  }

  function saveColumn(instance, column) {
    if (instance.updating) return;
    instance.settings.columns[fieldKey(instance, column.getField())] = {
      width: column.getWidth(),
      visible: column.isVisible(),
    };
    saveSettings(instance.settings);
    syncColumnChooser(instance);
  }

  function syncColumnChooser(instance) {
    document.querySelectorAll("[data-grid-field]").forEach(input => {
      const column = instance.table.getColumn(input.dataset.gridField);
      input.checked = column ? column.isVisible() : true;
    });
  }

  function restoreRowHeight(instance, row) {
    const heights = instance.settings.heights[String(instance.payload.etimon)] || {};
    const height = Number(heights[row.getIndex()]);
    if (Number.isFinite(height) && height >= 32 && height <= 20000) {
      // Tabulator 6.3.1 exposes resizing through its internal row object,
      // but has no public per-row setHeight API. Keep this adapter isolated
      // and recheck it when upgrading the pinned vendor version.
      row._getSelf().setHeight(height);
    }
  }

  function escapeTitle(text) {
    const span = document.createElement("span");
    span.textContent = text;
    return span.innerHTML;
  }

  function columnDefinitions(instance) {
    const definitions = [
      {
        title: "Label", field: "label", width: 180, minWidth: 100,
        frozen: true, formatter: "textarea", cssClass: "grid-label",
      },
      {
        title: "No.", field: "label_number", width: 55, minWidth: 45,
        frozen: true, hozAlign: "center", cssClass: "grid-number",
      },
      ...instance.payload.columns.map(column => ({
        title: escapeTitle(column.title),
        field: column.field,
        width: 290,
        minWidth: 100,
        variableHeight: true,
        formatter(cell) {
          const element = document.createElement("div");
          element.className = "grid-content";
          if (instance.payload.plaintext) {
            element.classList.add("plain-content");
            element.textContent = cell.getValue() ?? "";
          } else {
            // HTML comes only from the workbook's escaped rich-text converter.
            element.innerHTML = cell.getValue() || "";
          }
          return element;
        },
      })),
    ];
    return definitions.map(definition => {
      const saved = instance.settings.columns[fieldKey(instance, definition.field)] || {};
      const width = Number(saved.width);
      if (Number.isFinite(width) && width >= definition.minWidth && width <= 2000) {
        definition.width = width;
      }
      // The identifying columns always remain visible.
      definition.visible = definition.frozen || saved.visible !== false;
      return definition;
    });
  }

  function createGrid(element, payload) {
    const instance = {
      element, payload, settings: settingsFor(payload.dataset),
      signature: JSON.stringify(payload.columns), updating: true,
    };
    instance.ready = new Promise(resolve => { instance.resolveReady = resolve; });
    element.hidden = false;
    instance.table = new Tabulator(element, {
      data: payload.rows,
      columns: columnDefinitions(instance),
      index: "id",
      height: "70vh",
      layout: "fitData",
      renderVertical: "basic",
      resizableRows: true,
      columnDefaults: { headerSort: false, resizable: "header", vertAlign: "top" },
      rowFormatter: row => restoreRowHeight(instance, row),
    });
    instance.table.on("tableBuilt", instance.resolveReady);
    instance.table.on("columnResized", column => {
      saveColumn(instance, column);
      instance.table.getRows().forEach(row => restoreRowHeight(instance, row));
    });
    instance.table.on("columnVisibilityChanged", column => {
      saveColumn(instance, column);
      instance.table.getRows().forEach(row => restoreRowHeight(instance, row));
    });
    instance.table.on("rowResized", row => {
      if (instance.updating) return;
      const number = String(instance.payload.etimon);
      const heights = instance.settings.heights[number] ||= {};
      heights[row.getIndex()] = Math.max(32, Math.round(row.getElement().offsetHeight));
      saveSettings(instance.settings);
    });
    return instance;
  }

  function destroyGrid() {
    if (active) {
      active.resolveReady();
      active.table.destroy();
      active = null;
    }
  }

  function showError(message) {
    const status = document.getElementById("request-status");
    if (status) {
      status.textContent = message;
      status.classList.add("is-error");
    }
  }

  async function renderWorkspace(workspace, reset = false) {
    if (!workspace?.isConnected) return;
    const payload = JSON.parse(workspace.querySelector(".workspace-data").textContent);
    document.title = payload.title;
    const form = document.querySelector(".search-form");
    form.elements.q.value = payload.criteria.query;
    form.elements.label.value = payload.criteria.label;
    form.elements.column.value = payload.criteria.column;

    const element = document.getElementById("etimon-grid");
    if (!element) {
      destroyGrid();
      return;
    }
    if (typeof Tabulator === "undefined") {
      showError("Interactive table unavailable. The standard table is shown.");
      return;
    }
    if (active && active.element !== element) destroyGrid();
    const previousEtimon = active?.payload.etimon;
    const isNew = !active;
    if (isNew) active = createGrid(element, payload);
    const instance = active;
    await instance.ready;
    if (!workspace.isConnected || active !== instance) return;
    instance.updating = true;
    try {
      instance.payload = payload;
      const signature = JSON.stringify(payload.columns);
      if (reset || signature !== instance.signature) {
        instance.table.setColumns(columnDefinitions(instance));
        instance.signature = signature;
      }
      if (!isNew || reset) await instance.table.replaceData(payload.rows);
      // The preserved element has just moved into the new workspace.
      instance.table.redraw(true);
      instance.table.getRows().forEach(row => restoreRowHeight(instance, row));
      syncColumnChooser(instance);
      element.closest(".detail-panel").classList.add("grid-active");
      if (previousEtimon !== payload.etimon) {
        element.querySelector(".tabulator-tableholder").scrollTop = 0;
      }
    } finally {
      instance.updating = false;
    }
  }

  function scheduleWorkspace(workspace, reset = false) {
    updates = updates.catch(() => {}).then(() => renderWorkspace(workspace, reset)).catch(error => {
      console.error("Could not update the etimon grid", error);
      showError("The interactive table could not update. Please reload the page.");
    });
  }

  function initialize() {
    const workspace = document.getElementById("workspace");
    if (workspace && !workspace.dataset.initialized) {
      workspace.dataset.initialized = "true";
      scheduleWorkspace(workspace);
    }
  }

  document.addEventListener("change", event => {
    if (!event.target.matches("[data-grid-field]") || !active || active.updating) return;
    const column = active.table.getColumn(event.target.dataset.gridField);
    if (column) event.target.checked ? column.show() : column.hide();
  });

  document.addEventListener("click", event => {
    if (!event.target.closest("[data-reset-layout]") || !active) return;
    active.settings.columns = {};
    active.settings.heights = {};
    saveSettings(active.settings);
    scheduleWorkspace(document.getElementById("workspace"), true);
  });

  document.addEventListener("htmx:load", initialize);
  document.addEventListener("htmx:beforeCleanupElement", event => {
    if (active && event.detail.elt === active.element) destroyGrid();
  });
  document.addEventListener("htmx:beforeRequest", () => {
    const status = document.getElementById("request-status");
    status.textContent = "Updating…";
    status.classList.remove("is-error");
    document.getElementById("workspace").setAttribute("aria-busy", "true");
  });
  document.addEventListener("htmx:afterRequest", () => {
    document.getElementById("workspace").removeAttribute("aria-busy");
  });
  document.addEventListener("htmx:responseError", () => showError("The search could not complete. Please try again."));
  document.addEventListener("htmx:sendError", () => showError("Could not reach the server. Please try again."));

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();

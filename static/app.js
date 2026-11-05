/* htmx owns the workspace; Tabulator owns the preserved grid inside it. */
(() => {
  "use strict";

  const preferences = new Map();
  let active = null;
  let scrollbars = null;
  let resultsScrollbars = null;
  let updates = Promise.resolve();
  let resultsHidden = false;
  let workspaceBusy = false;
  let mutationBusy = false;
  let pendingFocus = null;
  let creationButton = null;
  let deletionTarget = null;

  function editing() { return window.XLDBCellEditor?.active; }

  function restoreScroll(instance, position) {
    const viewport = instance.element.querySelector('.tabulator-tableholder');
    if (!viewport || !position) return;
    viewport.scrollLeft = position.left;
    viewport.scrollTop = position.top;
    scrollbars?.schedule();
  }

  function revealCell(instance, row, field) {
    const viewport = instance.element.querySelector('.tabulator-tableholder');
    const cell = row.getCell(field).getElement();
    const bounds = viewport.getBoundingClientRect();
    const rowBounds = row.getElement().getBoundingClientRect();
    viewport.scrollTop += rowBounds.top - bounds.top - Math.max(0, (viewport.clientHeight - rowBounds.height) / 2);
    const frozenWidth = instance.table.getColumns().filter(column => column.getDefinition().frozen && column.isVisible())
      .reduce((width, column) => width + column.getWidth(), 0);
    const cellBounds = cell.getBoundingClientRect();
    const available = viewport.clientWidth - frozenWidth;
    viewport.scrollLeft += cellBounds.left - bounds.left - frozenWidth - Math.max(0, (available - cellBounds.width) / 2);
    cell.tabIndex = -1;
    cell.focus({ preventScroll: true });
    scrollbars?.schedule();
  }

  function editCell(instance, cell) {
    if (!instance.payload.edit_mode || editing() || workspaceBusy || mutationBusy || instance.updating) return;
    const editor = cell.getRow().getData().editors?.[cell.getField()];
    if (!editor) return;
    if (!window.XLDBCellEditor || typeof Quill === "undefined") {
      showError("The cell editor could not load. Reload the page to try again.");
      return;
    }
    let saved = false;
    let scrollPosition;
    window.XLDBCellEditor.open(cell, {
      html: editor.html,
      lineHeight: editor.line_height,
      async onSave(ops, lineHeight) {
        const response = await fetch("/cell", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": instance.payload.csrf },
          body: JSON.stringify({ token: editor.token, ops, line_height: lineHeight }),
        });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || "Could not save. Please try again.");
        saved = true;
      },
      onBeforeClose() {
        const viewport = instance.element.querySelector('.tabulator-tableholder');
        scrollPosition = { left: viewport.scrollLeft, top: viewport.scrollTop };
      },
      onClose() {
        document.getElementById("request-status").classList.remove("is-error");
        cell.getRow().normalizeHeight();
        restoreRowHeight(instance, cell.getRow());
        restoreScroll(instance, scrollPosition);
        scrollbars?.schedule();
        if (saved) {
          instance.editScroll = { ...scrollPosition, etimon: instance.payload.etimon };
          htmx.ajax("GET", `/?etimon=${instance.payload.etimon}`, {
            target: "#workspace", swap: "outerHTML", source: document.body,
          }).catch(() => {
            instance.editScroll = null;
          });
        }
      },
    });
    scrollbars?.schedule();
  }

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

  function formatRow(instance, row) {
    const backgrounds = row.getData().backgrounds || {};
    // Paint the whole cell, including frozen identifiers and resized space.
    // Clear absent fills so replacing data cannot leave an old color behind.
    row.getCells().forEach(cell => {
      cell.getElement().style.backgroundColor = backgrounds[cell.getField()] || "";
      cell.getElement().style.lineHeight = row.getData().editors?.[cell.getField()]?.line_height || "";
      cell.getElement().classList.toggle("is-empty", cell.getValue() === "");
    });
    restoreRowHeight(instance, row);
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
        frozen: true, variableHeight: true, cssClass: "grid-label",
        formatter(cell) {
          const row = cell.getRow().getData();
          const label = document.createElement('div');
          label.style.whiteSpace = 'pre-wrap';
          label.textContent = row.label;
          if (instance.payload.edit_mode && row.delete_token) {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'delete-entry delete-row';
            button.textContent = 'Delete row';
            button.dataset.deleteRow = row.delete_token;
            button.dataset.rowLabel = row.label;
            button.dataset.rowNumber = row.label_number;
            button.setAttribute('aria-label', `Delete row: ${row.label} #${row.label_number}`);
            label.appendChild(button);
          }
          return label;
        },
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
          const highlighted = cell.getRow().getData().highlights?.[column.field];
          if (instance.payload.plaintext) {
            element.classList.add("plain-content");
          }
          if (highlighted !== undefined) {
            // Marks are generated server-side from escaped cell text.
            element.innerHTML = highlighted;
          } else if (instance.payload.plaintext) {
            element.textContent = cell.getValue() ?? "";
          } else {
            // HTML comes from the workbook converter or validated Delta renderer.
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
      height: "100%",
      layout: "fitData",
      renderVertical: "basic",
      resizableRows: true,
      columnDefaults: { headerSort: false, resizable: "header", vertAlign: "top" },
      rowFormatter: row => formatRow(instance, row),
    });
    instance.table.on("tableBuilt", instance.resolveReady);
    instance.table.on("cellDblClick", (event, cell) => {
      if (instance.payload.edit_mode && cell.getRow().getData().editors?.[cell.getField()]) event.preventDefault();
      editCell(instance, cell);
    });
    instance.table.on("renderComplete", () => scrollbars?.schedule());
    instance.table.on("columnResized", column => {
      saveColumn(instance, column);
      instance.table.getRows().forEach(row => restoreRowHeight(instance, row));
      scrollbars?.schedule();
    });
    instance.table.on("columnVisibilityChanged", column => {
      saveColumn(instance, column);
      instance.table.getRows().forEach(row => restoreRowHeight(instance, row));
      scrollbars?.schedule();
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

  function updateFilterSummary(filter) {
    const count = filter.querySelectorAll('input[type="checkbox"]:checked').length;
    filter.querySelector("[data-filter-summary]").textContent = count ? `${count} selected` : "All";
  }

  function bindScrollbars(workspace, viewport) {
    scrollbars?.destroy();
    scrollbars = null;
    if (viewport && typeof window.XLDBScrollbars === "function") {
      scrollbars = new window.XLDBScrollbars(workspace.querySelector(".table-frame"), viewport);
    }
  }

  function bindResultsScrollbars(workspace) {
    resultsScrollbars?.destroy();
    resultsScrollbars = null;
    const viewport = workspace?.querySelector("#results-viewport");
    if (viewport && typeof window.XLDBScrollbars === "function") {
      resultsScrollbars = new window.XLDBScrollbars(workspace.querySelector(".results-scroll-frame"), viewport);
    }
  }

  async function renderWorkspace(workspace, reset = false) {
    if (!workspace?.isConnected) return;
    bindScrollbars(null, null);
    const payload = JSON.parse(workspace.querySelector(".workspace-data").textContent);
    document.querySelector('[data-toggle-edit]').setAttribute('aria-pressed', String(payload.edit_mode));
    document.querySelector('[data-add-etymon]').hidden = !payload.edit_mode;
    document.querySelector('.collection-count').textContent = `${payload.total} etimon${payload.total === 1 ? '' : 's'} in the collection`;
    document.title = payload.title;
    const form = document.querySelector(".search-form");
    form.elements.q.value = payload.criteria.query;
    form.querySelectorAll("[data-search-filter]").forEach(filter => {
      const selected = new Set(payload.criteria[filter.dataset.searchFilter]);
      filter.querySelectorAll('input[type="checkbox"]').forEach(input => {
        input.checked = selected.has(input.value);
      });
      updateFilterSummary(filter);
      filter.open = false;
    });

    const element = document.getElementById("etimon-grid");
    if (!element) {
      destroyGrid();
      return;
    }
    if (typeof Tabulator === "undefined") {
      bindScrollbars(workspace, workspace.querySelector(".table-fallback"));
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
      element.closest(".detail-panel").classList.add("grid-active");
      // The preserved element has just moved into the new workspace.
      instance.table.redraw(true);
      instance.table.getRows().forEach(row => restoreRowHeight(instance, row));
      syncColumnChooser(instance);
      if (previousEtimon !== payload.etimon) {
        element.querySelector(".tabulator-tableholder").scrollTop = 0;
      }
      bindScrollbars(workspace, element.querySelector(".tabulator-tableholder"));
      const position = instance.editScroll;
      instance.editScroll = null;
      if (position?.etimon === payload.etimon) restoreScroll(instance, position);
      if (pendingFocus?.etimon === payload.etimon) {
        const location = pendingFocus;
        pendingFocus = null;
        const identity = payload.rows.find(row => row.label === location.label && row.label_number === location.label_number)?.id;
        const row = identity ? instance.table.getRow(identity) : null;
        const column = payload.columns.find(item => item.title === 'LIMBA FRANCEZĂ');
        if (row && column) {
          // A hidden French column should not hide the entry just created.
          const targetColumn = instance.table.getColumn(column.field);
          targetColumn.show();
          await new Promise(requestAnimationFrame);
          revealCell(instance, row, column.field);
        }
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

  function syncResultsPanel(workspace) {
    workspace.classList.add("results-ready");
    workspace.classList.toggle("results-hidden", resultsHidden);
    workspace.querySelector("#results-panel").hidden = resultsHidden;
    const toggle = workspace.querySelector("[data-toggle-results]");
    const label = resultsHidden ? "Show etymons" : "Hide etymons";
    toggle.hidden = false;
    toggle.setAttribute("aria-expanded", String(!resultsHidden));
    toggle.setAttribute("aria-label", label);
    toggle.title = label;
    toggle.querySelector("[data-results-toggle-icon]").textContent = resultsHidden ? "»" : "«";
    resultsScrollbars?.schedule();
  }

  function initialize() {
    const workspace = document.getElementById("workspace");
    if (workspace && !workspace.dataset.initialized) {
      if (workspace.dataset.revealResults === "true") resultsHidden = false;
      syncResultsPanel(workspace);
      bindResultsScrollbars(workspace);
      workspace.dataset.initialized = "true";
      scheduleWorkspace(workspace);
    }
  }

  document.addEventListener("change", event => {
    const filter = event.target.closest("[data-search-filter]");
    if (filter) updateFilterSummary(filter);
    if (!event.target.matches("[data-grid-field]") || !active || active.updating) return;
    if (editing()) {
      syncColumnChooser(active);
      showError("Close or cancel the cell editor before changing the table layout.");
      return;
    }
    const column = active.table.getColumn(event.target.dataset.gridField);
    if (column) event.target.checked ? column.show() : column.hide();
  });

  document.addEventListener("click", event => {
    const deletion = event.target.closest('[data-delete-row], [data-delete-etymon]');
    if (deletion) {
      event.preventDefault();
      if (editing()) {
        showError('Close or cancel the cell editor before deleting an item.');
        window.XLDBCellEditor.focus();
        return;
      }
      if (mutationBusy || workspaceBusy || active?.updating) return;
      const payload = JSON.parse(document.querySelector('.workspace-data').textContent);
      if (!payload.edit_mode) return;
      deletionTarget = { token: deletion.dataset.deleteRow || payload.delete_etymon_token, csrf: payload.csrf,
        etimon: payload.etimon, row: deletion.hasAttribute('data-delete-row') };
      const dialog = document.getElementById('delete-entry-dialog');
      dialog.querySelector('form').reset();
      dialog.querySelector('[type="submit"]').disabled = true;
      dialog.querySelector('.deletion-error').textContent = '';
      dialog.querySelector('#delete-entry-description').textContent = deletionTarget.row
        ? `Delete ${deletion.dataset.rowLabel} #${deletion.dataset.rowNumber} from etymon ${payload.etimon}: ${payload.etymon_name}?`
        : `Delete etymon ${payload.etimon}: ${payload.etymon_name}, including ALL its rows?`;
      dialog.showModal();
      dialog.querySelector('[data-cancel-delete]').focus();
      return;
    }
    const operation = event.target.closest('[data-toggle-edit], [data-add-row], [data-add-etymon]');
    if (operation) {
      event.preventDefault();
      if (editing()) {
        showError('Close or cancel the cell editor before switching mode or adding entries.');
        window.XLDBCellEditor.focus();
        return;
      }
      if (!mutationBusy && !workspaceBusy && !active?.updating) {
        if (operation.matches('[data-toggle-edit]')) changeEntries(operation);
        else {
          creationButton = operation;
          operation.closest('.add-row-menu')?.removeAttribute('open');
          const dialog = document.getElementById('create-entry-dialog');
          dialog.querySelector('form').reset();
          dialog.querySelector('.creation-error').textContent = '';
          dialog.querySelector('h2').textContent = operation.matches('[data-add-row]') ? 'Add row' : 'Add etymon';
          dialog.showModal();
          dialog.querySelector('textarea').focus();
        }
      }
      return;
    }
    if (editing() && event.target.closest("[data-toggle-results], [data-reset-layout], [data-export-excel], .add-row-menu")) {
      event.preventDefault();
      showError("Close or cancel the cell editor before exporting or changing the table layout.");
      window.XLDBCellEditor.focus();
      return;
    }
    document.querySelectorAll("details[open]").forEach(details => {
      if (!details.contains(event.target)) details.open = false;
    });
    if (event.target.closest("[data-toggle-results]")) {
      const workspace = document.getElementById("workspace");
      resultsHidden = !resultsHidden;
      syncResultsPanel(workspace);
      if (active && !active.updating) {
        active.table.redraw(true);
        active.table.getRows().forEach(row => restoreRowHeight(active, row));
      }
      scrollbars?.schedule();
      return;
    }
    const clearFilter = event.target.closest("[data-clear-filter]");
    if (clearFilter) {
      const filter = clearFilter.closest("[data-search-filter]");
      filter.querySelectorAll('input[type="checkbox"]').forEach(input => { input.checked = false; });
      updateFilterSummary(filter);
    }
    if (!event.target.closest("[data-reset-layout]") || !active) return;
    active.settings.columns = {};
    active.settings.heights = {};
    saveSettings(active.settings);
    scheduleWorkspace(document.getElementById("workspace"), true);
  });

  async function changeEntries(button) {
    const payload = JSON.parse(document.querySelector('.workspace-data').textContent);
    const mode = button.matches('[data-toggle-edit]');
    const addRow = button.matches('[data-add-row]');
    const path = mode ? '/mode' : addRow ? '/rows' : '/etymons';
    const body = mode ? { edit_mode: !payload.edit_mode } : addRow ? {
      etimon: payload.etimon, label: button.dataset.rowLabel,
    } : {};
    if (!mode) body.text = document.getElementById('create-entry-text').value;
    mutationBusy = true;
    button.disabled = true;
    try {
      const response = await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': payload.csrf },
        body: JSON.stringify(body),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'Could not update the collection.');
      if (!mode) {
        pendingFocus = result;
        document.getElementById('create-entry-dialog').close();
      }
      await htmx.ajax('GET', result.etimon ? `/?etimon=${result.etimon}` : '/', {
        target: '#workspace', swap: 'outerHTML', source: document.body,
      });
      await updates;
    } catch (error) {
      pendingFocus = null;
      showError(error.message || 'Could not reach the server. Please try again.');
      document.querySelector('.creation-error').textContent = error.message;
    } finally {
      mutationBusy = false;
      button.disabled = false;
    }
  }

  document.addEventListener('submit', async event => {
    if (event.target.id !== 'create-entry-form') return;
    event.preventDefault();
    if (mutationBusy) return;
    const text = document.getElementById('create-entry-text');
    if (!text.value.trim()) {
      document.querySelector('.creation-error').textContent = 'Enter French text before creating an entry.';
      text.focus();
      return;
    }
    event.target.querySelector('[type="submit"]').disabled = true;
    try { await changeEntries(creationButton); }
    finally { event.target.querySelector('[type="submit"]').disabled = false; }
  });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-cancel-entry]') && !mutationBusy) document.getElementById('create-entry-dialog').close();
  });
  document.addEventListener('cancel', event => {
    if (['create-entry-dialog', 'delete-entry-dialog'].includes(event.target.id) && mutationBusy) event.preventDefault();
  }, true);

  document.addEventListener('input', event => {
    if (event.target.id === 'delete-entry-confirmation') {
      document.querySelector('#delete-entry-form [type="submit"]').disabled = mutationBusy || event.target.value !== 'DELETE';
    }
  });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-cancel-delete]') && !mutationBusy) document.getElementById('delete-entry-dialog').close();
  });
  document.addEventListener('submit', async event => {
    if (event.target.id !== 'delete-entry-form') return;
    event.preventDefault();
    if (mutationBusy || !deletionTarget || document.getElementById('delete-entry-confirmation').value !== 'DELETE') return;
    const target = deletionTarget;
    const dialog = document.getElementById('delete-entry-dialog');
    const submit = event.target.querySelector('[type="submit"]');
    mutationBusy = true;
    submit.disabled = true;
    try {
      const response = await fetch('/trash', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': target.csrf },
        body: JSON.stringify({ token: target.token, confirmation: 'DELETE' }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(result.error || 'Could not move the item to Trash.');
      dialog.close();
      if (target.row && active) {
        const viewport = active.element.querySelector('.tabulator-tableholder');
        active.editScroll = { etimon: target.etimon, left: viewport.scrollLeft, top: viewport.scrollTop };
      }
      await htmx.ajax('GET', target.row ? `/?etimon=${target.etimon}` : '/', {
        target: '#workspace', swap: 'outerHTML', source: document.body,
      });
      await updates;
    } catch (error) {
      dialog.querySelector('.deletion-error').textContent = error.message;
      showError(error.message || 'Could not reach the server.');
    } finally {
      mutationBusy = false;
      submit.disabled = document.getElementById('delete-entry-confirmation').value !== 'DELETE';
    }
  });

  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    const details = event.target.closest("details[open]");
    if (details) {
      details.open = false;
      details.querySelector("summary").focus();
    }
  });

  document.addEventListener("htmx:load", initialize);
  document.addEventListener("htmx:beforeCleanupElement", event => {
    if (resultsScrollbars && event.detail.elt === resultsScrollbars.frame) bindResultsScrollbars(null);
    if (scrollbars && event.detail.elt === scrollbars.frame) bindScrollbars(null, null);
    if (active && event.detail.elt === active.element) destroyGrid();
  });
  document.addEventListener("htmx:beforeRequest", event => {
    if (editing()) {
      event.preventDefault();
      showError("Close or cancel the cell editor before navigating or searching.");
      window.XLDBCellEditor.focus();
      return;
    }
    workspaceBusy = true;
    const status = document.getElementById("request-status");
    status.textContent = "Updating…";
    status.classList.remove("is-error");
    document.getElementById("workspace").setAttribute("aria-busy", "true");
  });
  document.addEventListener("htmx:afterRequest", () => {
    workspaceBusy = false;
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

/* One inline Quill editor at a time; persistence is supplied by the grid. */
(() => {
  "use strict";
  let current = null;
  let configured = false;

  function configure() {
    if (configured) return;
    for (const name of ["font", "size"]) {
      const format = Quill.import(`attributors/style/${name}`);
      format.whitelist = null;
      Quill.register(format, true);
    }
    configured = true;
  }

  function open(cell, { html, lineHeight, onSave, onBeforeClose, onClose }) {
    if (current || typeof Quill === "undefined") return false;
    configure();
    const element = cell.getElement();
    const cellStyle = getComputedStyle(element);
    const inheritedHeight = parseFloat(cellStyle.lineHeight) / parseFloat(cellStyle.fontSize);
    const initialLineHeight = lineHeight || (Number.isFinite(inheritedHeight) ? Number(inheritedHeight.toFixed(3)) : 1.6);
    let currentLineHeight = initialLineHeight;
    const originalNodes = [...element.childNodes];
    const originalHeight = cell.getRow().getElement().style.height;
    const panel = document.createElement("div");
    panel.className = "cell-editor";
    panel.style.backgroundColor = cellStyle.backgroundColor;
    panel.setAttribute("role", "group");
    panel.setAttribute("aria-label", "Edit cell");
    const toolbar = document.createElement("div");
    toolbar.className = "cell-editor-toolbar";
    for (const [name, value, title] of [
      ["bold", "", "Bold"], ["italic", "", "Italic"],
      ["underline", "", "Underline"], ["strike", "", "Strikethrough"],
      ["script", "sub", "Subscript"], ["script", "super", "Superscript"],
    ]) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `ql-${name}`;
      if (value) button.value = value;
      button.title = title;
      button.setAttribute("aria-label", title);
      toolbar.append(button);
    }
    for (const name of ["color", "background"]) {
      const select = document.createElement("select");
      select.className = `ql-${name}`;
      select.setAttribute("aria-label", name === "color" ? "Text color" : "Highlight color");
      toolbar.append(select);
    }
    const toolbarRow = document.createElement("div");
    toolbarRow.className = "cell-editor-toolbar-row";
    const typography = document.createElement("button");
    typography.type = "button";
    typography.className = "cell-editor-typography-toggle";
    typography.textContent = "Typography";
    typography.setAttribute("aria-expanded", "false");
    typography.setAttribute("aria-controls", "cell-editor-typography-menu");
    toolbarRow.append(toolbar, typography);
    const menu = document.createElement("div");
    menu.id = "cell-editor-typography-menu";
    menu.className = "cell-editor-typography-menu";
    menu.hidden = true;
    const sizeLabel = document.createElement("label");
    sizeLabel.textContent = "Font size (pt)";
    const sizeInput = document.createElement("input");
    sizeInput.type = "number";
    sizeInput.min = "1";
    sizeInput.max = "200";
    sizeInput.step = "any";
    sizeInput.required = true;
    sizeInput.placeholder = "Mixed";
    sizeLabel.append(sizeInput);
    const applySize = document.createElement("button");
    applySize.type = "button";
    applySize.textContent = "Apply size";
    const spacingLabel = document.createElement("label");
    spacingLabel.textContent = "Line spacing (whole cell)";
    const spacing = document.createElement("select");
    spacing.setAttribute("aria-label", "Line spacing (whole cell)");
    const heights = [...new Set([1, 1.15, 1.5, 1.6, 2, 2.5, 3, initialLineHeight])].sort((a, b) => a - b);
    heights.forEach(height => {
      const option = document.createElement("option");
      option.value = String(height);
      option.textContent = `${height}×`;
      spacing.append(option);
    });
    spacing.value = String(currentLineHeight);
    spacingLabel.append(spacing);
    menu.append(sizeLabel, applySize, spacingLabel);
    const host = document.createElement("div");
    const actions = document.createElement("div");
    actions.className = "cell-editor-actions";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "Close";
    close.title = "Save changes and close (Ctrl+Enter)";
    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.textContent = "Cancel";
    const status = document.createElement("span");
    status.setAttribute("role", "status");
    actions.append(close, cancel, status);
    panel.append(toolbarRow, menu, host, actions);
    element.replaceChildren(panel);
    element.classList.add("is-editing");
    const quill = new Quill(host, {
      theme: "snow",
      formats: ["bold", "italic", "underline", "strike", "script", "font", "size", "color", "background"],
      modules: { toolbar },
    });
    const Delta = Quill.import("delta");
    // Workbook text uses pre-wrap: retain spaces, tabs and line breaks.
    quill.clipboard.addMatcher(Node.TEXT_NODE, node => new Delta().insert(node.data));
    quill.clipboard.addMatcher(Node.ELEMENT_NODE, (node, delta) => {
      const attributes = {};
      // The Excel converter uses text-decoration-line; Quill's default
      // clipboard matcher only recognizes the text-decoration shorthand.
      const decorations = node.style.textDecorationLine;
      if (decorations.includes("underline")) attributes.underline = true;
      if (decorations.includes("line-through")) attributes.strike = true;
      const script = { super: "super", sub: "sub" }[node.style.verticalAlign];
      if (script) attributes.script = script;
      return delta.compose(new Delta().retain(delta.length(), attributes));
    });
    const source = document.createElement("div");
    source.innerHTML = html;
    // The workbook's outer fill belongs to the whole cell, not to text runs.
    if (source.firstElementChild?.tagName === "DIV") source.firstElementChild.style.backgroundColor = "";
    quill.setContents(quill.clipboard.convert({ html: source.innerHTML }), "silent");
    quill.root.style.lineHeight = String(currentLineHeight);
    const initial = JSON.stringify(quill.getContents());
    quill.history.clear();
    quill.root.setAttribute("aria-label", "Cell contents");
    quill.root.setAttribute("role", "textbox");
    quill.root.setAttribute("aria-multiline", "true");
    // Linguistic entries mix languages; leave spelling and wording to editors.
    quill.root.setAttribute("spellcheck", "false");
    quill.root.setAttribute("autocomplete", "off");
    quill.root.setAttribute("autocorrect", "off");
    quill.root.setAttribute("autocapitalize", "off");
    quill.root.setAttribute("writingsuggestions", "false");
    let saving = false;
    let selection = { index: 0, length: 0 };

    function updateSize() {
      const size = quill.getFormat(selection).size;
      const pixels = parseFloat(getComputedStyle(quill.root).fontSize);
      const points = typeof size === "string" ? parseFloat(size) * (size.endsWith("px") ? 0.75 : 1) : pixels * 0.75;
      sizeInput.value = Array.isArray(size) ? "" : String(Number(points.toFixed(2)));
    }

    quill.on("selection-change", range => {
      if (range) {
        selection = { index: range.index, length: range.length };
        updateSize();
      }
    });
    typography.addEventListener("click", () => {
      menu.hidden = !menu.hidden;
      typography.setAttribute("aria-expanded", String(!menu.hidden));
      cell.getRow().normalizeHeight();
      if (!menu.hidden) sizeInput.focus();
    });
    function changeSize() {
      if (!sizeInput.reportValidity()) return;
      const size = `${Number(sizeInput.value)}pt`;
      quill.setSelection(selection, "silent");
      quill.format("size", size, "user");
      updateSize();
      cell.getRow().normalizeHeight();
    }
    applySize.addEventListener("click", changeSize);
    sizeInput.addEventListener("keydown", event => {
      if (event.key === "Enter" && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        changeSize();
      }
    });
    spacing.addEventListener("change", () => {
      currentLineHeight = Number(spacing.value);
      quill.root.style.lineHeight = String(currentLineHeight);
      cell.getRow().normalizeHeight();
    });
    updateSize();

    function restore() {
      onBeforeClose?.();
      current = null;
      element.classList.remove("is-editing");
      element.replaceChildren(...originalNodes);
      cell.getRow().getElement().style.height = originalHeight;
      onClose();
    }

    async function finish(save = true) {
      if (saving) return false;
      if (!save || (JSON.stringify(quill.getContents()) === initial && currentLineHeight === initialLineHeight)) {
        restore();
        return true;
      }
      saving = true;
      close.disabled = cancel.disabled = true;
      typography.disabled = sizeInput.disabled = applySize.disabled = spacing.disabled = true;
      quill.enable(false);
      status.textContent = "Saving…";
      try {
        await onSave(quill.getContents().ops, currentLineHeight);
        restore();
        return true;
      } catch (error) {
        status.textContent = error.message || "Could not save. Please try again.";
        return false;
      } finally {
        saving = false;
        close.disabled = cancel.disabled = false;
        typography.disabled = sizeInput.disabled = applySize.disabled = spacing.disabled = false;
        quill.enable(true);
      }
    }

    const activeEditor = { finish, focus: () => quill.focus({ preventScroll: true }) };
    current = activeEditor;
    close.addEventListener("click", () => finish());
    cancel.addEventListener("click", () => finish(false));
    panel.addEventListener("keydown", event => {
      if (event.key === "Escape" || (event.key === "Enter" && (event.ctrlKey || event.metaKey))) {
        event.preventDefault();
        event.stopPropagation();
        finish(event.key !== "Escape");
      }
    });
    cell.getRow().normalizeHeight();
    // A native double-click selection can finish after the editor replaces the
    // cell. Give Quill an explicit caret, then repair focus after that event.
    function focusContents() {
      window.getSelection()?.removeAllRanges();
      quill.setSelection(Math.max(0, quill.getLength() - 1), 0, 'silent');
      quill.focus({ preventScroll: true });
    }
    focusContents();
    requestAnimationFrame(() => {
      if (current !== activeEditor) return;
      const selection = window.getSelection();
      if (document.activeElement !== quill.root || !quill.root.contains(selection?.anchorNode)) focusContents();
    });
    return true;
  }

  window.XLDBCellEditor = {
    open, get active() { return Boolean(current); },
    close: save => current?.finish(save), focus: () => current?.focus(),
  };
})();

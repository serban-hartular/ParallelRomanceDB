"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

// Geometry is supplied by the fixture; these tests exercise scrolling and
// lifecycle behavior without requiring a browser or frontend dependencies.
class Element {
  constructor(bounds = {}) {
    this.bounds = {left: 0, top: 0, width: 0, height: 0, ...bounds};
    this.handlers = new Map();
    this.attributes = {};
    this.style = {};
    this.classes = new Set();
    this.classList = {add: name => this.classes.add(name), remove: name => this.classes.delete(name)};
    this.captured = new Set();
    this.hidden = false;
  }
  addEventListener(name, handler) {
    if (!this.handlers.has(name)) this.handlers.set(name, new Set());
    this.handlers.get(name).add(handler);
  }
  removeEventListener(name, handler) { this.handlers.get(name)?.delete(handler); }
  emit(name, values = {}) {
    const event = {button: 0, pointerId: 1, target: this, preventDefault() {}, ...values};
    this.handlers.get(name)?.forEach(handler => handler(event));
  }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getBoundingClientRect() { return this.bounds; }
  contains(target) { return target === this; }
  focus() { this.focused = true; }
  setPointerCapture(id) { this.captured.add(id); }
  hasPointerCapture(id) { return this.captured.has(id); }
  releasePointerCapture(id) { this.captured.delete(id); }
  closest() { return null; }
}

function fixture({verticalOnly = false} = {}) {
  const window = new Element();
  const horizontal = new Element({width: 400, height: 18});
  const vertical = new Element({width: 18, height: 300});
  for (const rail of [horizontal, vertical]) {
    rail.thumb = new Element();
    rail.querySelector = () => rail.thumb;
  }
  const frame = new Element();
  frame.querySelector = name => name === ".scrollbar-horizontal" ? (verticalOnly ? null : horizontal) : vertical;
  const viewport = Object.assign(new Element(), {
    id: verticalOnly ? "results-viewport" : "etimon-fallback", clientWidth: 400, scrollWidth: 1600,
    clientHeight: 300, scrollHeight: 1200, scrollLeft: 0, scrollTop: 0,
    firstElementChild: new Element(),
  });
  const pending = new Map();
  let next = 0;
  let observer;
  class ResizeObserver {
    constructor(callback) { this.callback = callback; observer = this; }
    observe() {}
    disconnect() { this.disconnected = true; }
  }
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../static/scrollbars.js"), "utf8"), {
    window, ResizeObserver,
    requestAnimationFrame: callback => { pending.set(++next, callback); return next; },
    cancelAnimationFrame: id => pending.delete(id),
  });
  const controller = new window.XLDBScrollbars(frame, viewport);
  return {
    window, frame, viewport, horizontal, vertical, controller, observer, pending,
    flush() { const work = [...pending.values()]; pending.clear(); work.forEach(callback => callback()); },
  };
}

test("both scrollbar thumbs drag the viewport and clamp at the ends", () => {
  const f = fixture();
  f.horizontal.emit("pointerdown", {target: f.horizontal.thumb, clientX: 0});
  f.horizontal.emit("pointermove", {clientX: 150});
  assert.equal(f.viewport.scrollLeft, 600);
  f.horizontal.emit("pointermove", {clientX: 10000});
  assert.equal(f.viewport.scrollLeft, 1200);
  f.horizontal.emit("pointermove", {clientX: -100});
  assert.equal(f.viewport.scrollLeft, 0);
  f.horizontal.emit("pointerup");
  assert.equal(f.horizontal.captured.size, 0);
  f.vertical.emit("pointerdown", {target: f.vertical.thumb, clientY: 0});
  f.vertical.emit("pointermove", {clientY: 112.5});
  assert.equal(f.viewport.scrollTop, 450);
  f.vertical.emit("pointercancel");
  assert.equal(f.vertical.captured.size, 0);
});

test("track clicks and keyboard navigation scroll in either direction", () => {
  const f = fixture();
  f.horizontal.emit("pointerdown", {clientX: 200});
  assert.equal(f.viewport.scrollLeft, 600);
  f.horizontal.emit("pointerup");
  f.horizontal.emit("keydown", {key: "End"});
  assert.equal(f.viewport.scrollLeft, 1200);
  f.horizontal.emit("keydown", {key: "ArrowLeft"});
  assert.equal(f.viewport.scrollLeft, 1160);
  f.horizontal.emit("keydown", {key: "Home"});
  assert.equal(f.viewport.scrollLeft, 0);
  f.vertical.emit("keydown", {key: "PageDown"});
  assert.equal(f.viewport.scrollTop, 270);
  f.vertical.emit("keydown", {key: "ArrowUp"});
  assert.equal(f.viewport.scrollTop, 230);
});

test("native scrolling updates the thumbs and accessible values", () => {
  const f = fixture();
  f.viewport.scrollLeft = 600;
  f.viewport.scrollTop = 450;
  f.viewport.emit("scroll");
  f.flush();
  assert.equal(f.horizontal.thumb.style.transform, "translateX(150px)");
  assert.equal(f.vertical.thumb.style.transform, "translateY(112.5px)");
  assert.equal(f.horizontal.attributes["aria-valuenow"], "600");
  assert.equal(f.vertical.attributes["aria-valuenow"], "450");
  assert.equal(f.horizontal.attributes["aria-controls"], "etimon-fallback");
  f.controller.destroy();
  f.viewport.id = "";
  f.viewport.closest = () => ({id: "etimon-grid"});
  const replacement = new f.window.XLDBScrollbars(f.frame, f.viewport);
  assert.equal(f.horizontal.attributes["aria-controls"], "etimon-grid");
  assert.equal(f.horizontal.attributes["aria-valuenow"], "600");
  replacement.destroy();
});

test("resizing content hides unnecessary rails and restores them for overflow", () => {
  const f = fixture();
  f.viewport.scrollWidth = 400;
  f.viewport.scrollHeight = 300;
  f.observer.callback();
  f.flush();
  assert.equal(f.horizontal.hidden, true);
  assert.equal(f.vertical.hidden, true);
  f.viewport.scrollWidth = 2000;
  f.viewport.scrollHeight = 2400;
  f.observer.callback();
  f.flush();
  assert.equal(f.horizontal.hidden, false);
  assert.equal(f.vertical.hidden, false);
  assert.equal(f.horizontal.attributes["aria-valuemax"], "1600");
  assert.equal(f.vertical.attributes["aria-valuemax"], "2100");
});

test("cleanup cancels dragging, scheduled work, and listeners before an htmx swap", () => {
  const f = fixture();
  f.horizontal.emit("pointerdown", {target: f.horizontal.thumb, clientX: 0});
  f.viewport.emit("scroll");
  assert.equal(f.pending.size, 1);
  f.controller.destroy();
  assert.equal(f.pending.size, 0);
  assert.equal(f.observer.disconnected, true);
  assert.equal(f.frame.classes.has("custom-scrollbars"), false);
  assert.equal(f.horizontal.captured.size, 0);
  f.horizontal.emit("keydown", {key: "End"});
  f.viewport.emit("scroll");
  assert.equal(f.viewport.scrollLeft, 0);
  assert.equal(f.pending.size, 0);
});

test("a results list with only a vertical rail supports scrolling and hide/show", () => {
  const f = fixture({verticalOnly: true});
  assert.equal(f.vertical.attributes["aria-controls"], "results-viewport");
  assert.equal(f.frame.classes.has("custom-scrollbars"), true);
  f.vertical.emit("keydown", {key: "End"});
  assert.equal(f.viewport.scrollTop, 900);
  f.vertical.emit("pointerdown", {target: f.vertical.thumb, clientY: 225});
  f.vertical.emit("pointermove", {clientY: 0});
  assert.equal(f.viewport.scrollTop, 0);
  f.vertical.emit("pointerup");
  f.viewport.clientHeight = 0;
  f.viewport.scrollHeight = 0;
  f.observer.callback();
  f.flush();
  assert.equal(f.vertical.hidden, true);
  f.viewport.clientHeight = 300;
  f.viewport.scrollHeight = 1200;
  f.observer.callback();
  f.flush();
  assert.equal(f.vertical.hidden, false);
  f.viewport.scrollTop = 450;
  f.viewport.emit("scroll");
  f.flush();
  assert.equal(f.vertical.thumb.style.transform, "translateY(112.5px)");
  f.controller.destroy();
  assert.equal(f.observer.disconnected, true);
  assert.equal(f.vertical.hidden, true);
});

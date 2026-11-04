/* Persistent controls for native scrolling, independent of OS overlay scrollbars. */
(() => {
  "use strict";

  window.XLDBScrollbars = class {
    constructor(frame, viewport) {
      this.frame = frame;
      this.viewport = viewport;
      this.cleanup = [];
      this.pending = null;
      this.drag = null;
      this.axes = [
        {name: "horizontal", position: "scrollLeft", extent: "scrollWidth", client: "clientWidth", coordinate: "clientX", origin: "left", size: "width"},
        {name: "vertical", position: "scrollTop", extent: "scrollHeight", client: "clientHeight", coordinate: "clientY", origin: "top", size: "height"},
      ].map(axis => {
        axis.rail = frame.querySelector(`.scrollbar-${axis.name}`);
        axis.thumb = axis.rail.querySelector(".scrollbar-thumb");
        axis.rail.setAttribute("aria-controls", viewport.closest("#etimon-grid")?.id || viewport.id);
        this.listen(axis.rail, "pointerdown", event => this.startDrag(event, axis));
        this.listen(axis.rail, "pointermove", event => this.moveDrag(event, axis));
        this.listen(axis.rail, "lostpointercapture", () => this.endDrag());
        this.listen(axis.rail, "pointerup", () => this.endDrag());
        this.listen(axis.rail, "pointercancel", () => this.endDrag());
        this.listen(axis.rail, "keydown", event => this.keyScroll(event, axis));
        return axis;
      });
      this.listen(viewport, "scroll", () => this.schedule(), {passive: true});
      this.listen(window, "resize", () => this.schedule());
      if (typeof ResizeObserver !== "undefined") {
        this.observer = new ResizeObserver(() => this.schedule());
        this.observer.observe(viewport);
        if (viewport.firstElementChild) this.observer.observe(viewport.firstElementChild);
      }
      frame.classList.add("custom-scrollbars");
      this.refresh();
    }

    listen(element, name, handler, options) {
      element.addEventListener(name, handler, options);
      this.cleanup.push(() => element.removeEventListener(name, handler, options));
    }

    schedule() {
      if (this.pending !== null) return;
      this.pending = requestAnimationFrame(() => {
        this.pending = null;
        this.refresh();
      });
    }

    refresh() {
      for (const axis of this.axes) {
        const view = this.viewport[axis.client];
        const total = this.viewport[axis.extent];
        axis.max = Math.max(0, total - view);
        axis.rail.hidden = axis.max <= 1;
        const length = axis.rail.getBoundingClientRect()[axis.size];
        const thumb = Math.min(length, Math.max(32, length * view / (total || 1)));
        axis.travel = Math.max(0, length - thumb);
        const position = Math.max(0, Math.min(axis.max, this.viewport[axis.position]));
        const offset = axis.max ? position / axis.max * axis.travel : 0;
        axis.thumb.style[axis.size] = `${thumb}px`;
        axis.thumb.style.transform = axis.name === "horizontal" ? `translateX(${offset}px)` : `translateY(${offset}px)`;
        axis.rail.setAttribute("aria-valuemax", Math.round(axis.max));
        axis.rail.setAttribute("aria-valuenow", Math.round(position));
      }
    }

    setPosition(axis, value) {
      this.viewport[axis.position] = Math.max(0, Math.min(axis.max, value));
      this.refresh();
    }

    startDrag(event, axis) {
      if (event.button !== 0) return;
      event.preventDefault();
      this.refresh();
      if (!axis.travel) return;
      axis.rail.focus({preventScroll: true});
      if (!axis.thumb.contains(event.target)) {
        const bounds = axis.rail.getBoundingClientRect();
        const thumbLength = bounds[axis.size] - axis.travel;
        this.setPosition(axis, (event[axis.coordinate] - bounds[axis.origin] - thumbLength / 2) / axis.travel * axis.max);
      }
      this.drag = {axis, pointer: event.pointerId, start: event[axis.coordinate], position: this.viewport[axis.position]};
      axis.rail.classList.add("is-dragging");
      axis.rail.setPointerCapture(event.pointerId);
    }

    moveDrag(event, axis) {
      if (this.drag?.axis !== axis || this.drag.pointer !== event.pointerId || !axis.travel) return;
      this.setPosition(axis, this.drag.position + (event[axis.coordinate] - this.drag.start) / axis.travel * axis.max);
    }

    endDrag() {
      if (!this.drag) return;
      const {axis, pointer} = this.drag;
      this.drag = null;
      axis.rail.classList.remove("is-dragging");
      if (axis.rail.hasPointerCapture(pointer)) axis.rail.releasePointerCapture(pointer);
    }

    keyScroll(event, axis) {
      const negative = axis.name === "horizontal" ? "ArrowLeft" : "ArrowUp";
      const positive = axis.name === "horizontal" ? "ArrowRight" : "ArrowDown";
      const page = this.viewport[axis.client] * 0.9;
      let value = this.viewport[axis.position];
      switch (event.key) {
        case negative: value -= 40; break;
        case positive: value += 40; break;
        case "PageUp": value -= page; break;
        case "PageDown": value += page; break;
        case "Home": value = 0; break;
        case "End": value = axis.max; break;
        default: return;
      }
      event.preventDefault();
      this.setPosition(axis, value);
    }

    destroy() {
      this.endDrag();
      this.observer?.disconnect();
      if (this.pending !== null) cancelAnimationFrame(this.pending);
      this.cleanup.forEach(remove => remove());
      this.frame.classList.remove("custom-scrollbars");
      this.axes.forEach(axis => { axis.rail.hidden = true; });
    }
  };
})();

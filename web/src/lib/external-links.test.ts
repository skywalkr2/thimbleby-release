import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { installExternalLinks } from "./external-links";

describe("links to other addresses in the app's own window", () => {
  let undo: () => void;
  let opened: string[];

  beforeEach(() => {
    opened = [];
    (window as unknown as { pywebview: unknown }).pywebview = { api: { open_external: (u: string) => opened.push(u) } };
    undo = installExternalLinks();
    document.body.innerHTML = `<a id="out" href="http://192.0.2.1/a">out</a><a id="in" href="/today">in</a><a id="mail" href="mailto:a@example.com">m</a>`;
  });
  afterEach(() => {
    undo();
    delete (window as unknown as { pywebview?: unknown }).pywebview;
  });

  it("hands an outside link to the browser and stays on the page", () => {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("out")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    expect(opened).toEqual(["http://192.0.2.1/a"]);
  });

  it("leaves links inside the app alone", () => {
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("in")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
    expect(opened).toEqual([]);
  });

  it("hands window.open to the browser too", () => {
    expect(window.open("http://192.0.2.1/b")).toBeNull();
    expect(opened).toEqual(["http://192.0.2.1/b"]);
  });

  it("does nothing in an ordinary browser tab", () => {
    delete (window as unknown as { pywebview?: unknown }).pywebview;
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    document.getElementById("out")!.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

test("in the app's own window the page tells the window it has drawn, after it paints, even when the bridge comes later", async () => {
  const { reportDrawn } = await import("./external-links");
  const told: string[] = [];
  const w = window as unknown as { pywebview?: { api?: Record<string, unknown> } };
  delete w.pywebview;
  reportDrawn();
  await new Promise((r) => setTimeout(r, 50)); // two paints pass with no bridge yet
  expect(told).toEqual([]);
  w.pywebview = { api: { page_drawn: () => told.push("drawn") } };
  window.dispatchEvent(new Event("pywebviewready"));
  expect(told).toEqual(["drawn"]);
  delete w.pywebview;
});

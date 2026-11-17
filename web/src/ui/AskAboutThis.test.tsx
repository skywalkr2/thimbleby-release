import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, expect, test } from "vitest";
import { AskAboutThis } from "./AskAboutThis";

// The note box sizes itself in code (S-0574), so a web view that cannot size a box by its content (the Mac app's) still opens
// it tall enough for its example and grows it as the person types. jsdom has no layout: a stand-in for `scrollHeight` gives
// every line 20px plus 16px of padding, and counts the example when the box is empty, as a browser lays it out.
const EXAMPLE = "Tell Reginald what is wrong or missing,\nfor example: this is already done";
const LINE = 20;
const PAD = 16;
const original = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "scrollHeight");

function stubLayout(maxHeight: string) {
  Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", {
    configurable: true,
    get(this: HTMLTextAreaElement) {
      return this.value.split("\n").length * LINE + PAD;
    },
  });
  const style = window.getComputedStyle.bind(window);
  window.getComputedStyle = ((el: Element, pseudo?: string | null) => {
    const found = style(el, pseudo);
    return new Proxy(found, { get: (target, key) => (key === "maxHeight" ? maxHeight : Reflect.get(target, key) as unknown) });
  }) as typeof window.getComputedStyle;
  return () => {
    window.getComputedStyle = style;
  };
}

let restore: (() => void) | null = null;
afterEach(() => {
  restore?.();
  restore = null;
  if (original) Object.defineProperty(HTMLTextAreaElement.prototype, "scrollHeight", original);
});

function Box() {
  const [value, setValue] = useState("");
  return <AskAboutThis label="Ask about this" placeholder={EXAMPLE} value={value} onChange={setValue} onSend={() => undefined} sendLabel="Send" />;
}

const box = () => screen.getByRole("textbox", { name: "Ask about this" }) as HTMLTextAreaElement;

test("an empty box is as tall as its example, with no scroll bar, and the example is left in it", () => {
  restore = stubLayout("160px");
  render(<Box />);
  expect(box().style.height).toBe(`${2 * LINE + PAD}px`);
  expect(box().style.overflowY).toBe("hidden");
  expect(box().value).toBe("");
});

test("the height follows what is typed, up to the most the box may have, and scrolls only beyond it", async () => {
  restore = stubLayout("100px");
  render(<Box />);
  const user = userEvent.setup();
  await user.click(box());
  await user.type(box(), "one{Shift>}{Enter}{/Shift}two{Shift>}{Enter}{/Shift}three");
  expect(box().style.height).toBe(`${3 * LINE + PAD}px`);
  expect(box().style.overflowY).toBe("hidden");
  await user.type(box(), "{Shift>}{Enter}{/Shift}four{Shift>}{Enter}{/Shift}five");
  expect(box().style.height).toBe("100px");
  expect(box().style.overflowY).toBe("auto");
  await user.clear(box());
  expect(box().style.height).toBe(`${2 * LINE + PAD}px`);
});

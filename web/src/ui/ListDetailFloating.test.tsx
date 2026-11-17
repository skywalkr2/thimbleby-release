import "@testing-library/jest-dom/vitest";
import { act, waitFor } from "@testing-library/react";
import { useState } from "react";
import { expect, test } from "vitest";
import { renderApp } from "../test-utils";
import { ListDetail } from "./ListDetail";

// A card that describes a thing in the list: it never vanishes when the thing is not drawn, and it follows the thing when it
// comes back, with nothing changing in its props.
function Harness() {
  const [drawn, setDrawn] = useState(false);
  return (
    <>
      <button type="button" data-testid="draw" onClick={() => setDrawn(true)} />
      <ListDetail title="Planning chat" onClose={() => undefined} anchorTo="[data-entry-key='x']" floating detail={<p>When</p>}>
        {drawn && (
          <button type="button" data-entry-key="x">
            Entry
          </button>
        )}
      </ListDetail>
    </>
  );
}

test("a floating card whose entry is not drawn still shows, with no pointer, and sits beside the entry once it is drawn", async () => {
  document.documentElement.removeAttribute("data-narrow");
  window.matchMedia = ((query: string) => ({ matches: true, media: query, addEventListener: () => undefined, removeEventListener: () => undefined, addListener: () => undefined, removeListener: () => undefined, onchange: null, dispatchEvent: () => false })) as typeof window.matchMedia;
  const { getByTestId } = renderApp(<Harness />);
  const pane = () => document.querySelector<HTMLElement>("[data-detail-pane]")!;
  await waitFor(() => expect(pane().style.getPropertyValue("--float-left")).not.toBe(""));
  expect(pane().style.visibility).not.toBe("hidden");
  expect(pane()).not.toHaveAttribute("data-anchored");
  await act(async () => getByTestId("draw").click());
  await waitFor(() => expect(pane()).toHaveAttribute("data-anchored"));
  expect(pane().style.visibility).not.toBe("hidden");
});

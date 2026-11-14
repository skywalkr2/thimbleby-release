import { render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import { lazyScreen, preloadScreens } from "./lazy-screen";

describe("preloadScreens", () => {
  it("asks for each screen's chunk once, and a screen first drawn after it arrived shows with no placeholder", async () => {
    const load = vi.fn(async () => ({ Here: () => <p>The screen</p> }));
    const Here = lazyScreen(load, "Here");
    preloadScreens();
    preloadScreens();
    expect(load).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(load).toHaveBeenCalled());
    await Promise.resolve();
    render(
      <Suspense fallback={<p>Waiting</p>}>
        <Here />
      </Suspense>,
    );
    // The first draw already holds the screen: nothing to wait for, so no fallback was ever shown.
    expect(screen.getByText("The screen")).toBeTruthy();
    expect(screen.queryByText("Waiting")).toBeNull();
  });

  it("asks again for a chunk that did not arrive, when its screen is opened", async () => {
    let tries = 0;
    const load = vi.fn(async () => {
      tries += 1;
      if (tries === 1) throw new Error("offline");
      return { Here: () => <p>The screen</p> };
    });
    const Here = lazyScreen(load, "Here");
    preloadScreens();
    await Promise.resolve();
    await Promise.resolve();
    render(
      <Suspense fallback={<p>Waiting</p>}>
        <Here />
      </Suspense>,
    );
    expect(await screen.findByText("The screen")).toBeTruthy();
    expect(load).toHaveBeenCalledTimes(2);
  });
});

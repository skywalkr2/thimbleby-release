import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { renderApp } from "../test-utils";
import { ScreenBoundary } from "./PartBoundary";

function Broken(): never {
  throw new Error("TypeError: undefined is not a function at engine/internals");
}

test("a screen that throws leaves what is around it standing and offers Reload, with no internals shown", async () => {
  vi.spyOn(console, "error").mockImplementation(() => undefined);
  const reload = vi.fn();
  vi.stubGlobal("location", { ...window.location, reload });
  renderApp(
    <div>
      <nav aria-label="shell">the shell</nav>
      <ScreenBoundary>
        <Broken />
      </ScreenBoundary>
    </div>,
  );
  expect(screen.getByText("the shell")).toBeVisible();
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("This screen couldn't be shown");
  expect(alert).not.toHaveTextContent(/TypeError|engine|undefined/);
  await userEvent.click(screen.getByRole("button", { name: "Reload" }));
  expect(reload).toHaveBeenCalled();
  vi.unstubAllGlobals();
});

test("a screen that draws is untouched", () => {
  renderApp(
    <ScreenBoundary>
      <p>fine</p>
    </ScreenBoundary>,
  );
  expect(screen.getByText("fine")).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
});

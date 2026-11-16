import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeApi, Refuse, renderApp } from "../test-utils";
import { RemovingTheApp } from "./RemovingTheApp";

const FOLDER = "/Users/me/Library/Application Support/Thimbleby";

test("on the installed Mac app it names the folder the work stays in, and both buttons ask the app", async () => {
  const user = userEvent.setup();
  const calls = fakeApi({
    "GET desktop/removal": () => ({ available: true, folder: FOLDER }),
    "POST desktop/removal/show-app": () => undefined,
    "POST desktop/removal/open-folder": () => undefined,
  });
  renderApp(<RemovingTheApp />);
  expect(await screen.findByRole("heading", { name: "Removing Thimbleby from this Mac" })).toBeInTheDocument();
  expect(screen.getByText(new RegExp(`drag it from Applications to the Bin.*${FOLDER}`))).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open the folder" }));
  await user.click(screen.getByRole("button", { name: "Quit and show the app" }));
  await waitFor(() => expect(calls.map((c) => c.route)).toEqual(["GET desktop/removal", "POST desktop/removal/open-folder", "POST desktop/removal/show-app"]));
});

test("anywhere else (another system, or a program run from source) nothing is drawn", async () => {
  const calls = fakeApi({ "GET desktop/removal": () => ({ available: false, folder: "" }) });
  const { container } = renderApp(<RemovingTheApp />);
  await waitFor(() => expect(calls.some((c) => c.route === "GET desktop/removal")).toBe(true));
  expect(container.querySelector("[data-removal]")).toBeNull();
});

test("a button that fails says so in words and tells where to look by hand", async () => {
  const user = userEvent.setup();
  fakeApi({
    "GET desktop/removal": () => ({ available: true, folder: FOLDER }),
    "POST desktop/removal/show-app": () => new Refuse(409, "no"),
  });
  renderApp(<RemovingTheApp />);
  await user.click(await screen.findByRole("button", { name: "Quit and show the app" }));
  expect(await screen.findByText(/Open Finder and look in Applications for Thimbleby/)).toBeInTheDocument();
});

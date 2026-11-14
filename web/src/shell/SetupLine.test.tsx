import "@testing-library/jest-dom/vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { fakeApi, renderApp, setupStep as step, setupView } from "../test-utils";
import { SetupGroup } from "./SetupLine";

const CORE = ["workspace", "work", "ai", "mail", "backup", "people", "template", "first_note", "addons"];

function api(steps: S["SetupStepView"][], finished = false) {
  return fakeApi({ "GET setup": () => setupView(steps, { finished }) });
}

const open = () => {
  const onOpenGuide = vi.fn();
  renderApp(<SetupGroup workspace="Test" onOpenGuide={onOpenGuide} gaps={0} />);
  return { onOpenGuide };
};

beforeEach(() => window.localStorage.clear());

test("it is the last group: how far along in its header and one button to continue, with no bar or next-step line", async () => {
  api([step("workspace", { done: true }), step("people", { skipped: true }), step("ai"), step("backup")]);
  open();
  const line = await screen.findByRole("region", { name: /^Finish setting up/ });
  expect(line).toHaveTextContent("1 of 4 done");
});

test("a brand new workspace starts at zero and counts none done", async () => {
  api(CORE.map((id) => step(id)));
  open();
  const line = await screen.findByRole("region", { name: /^Finish setting up/ });
  expect(line).toHaveTextContent("0 of 6 done");
});

test("it reads the one count of six steps the server serves, the same one the walkthrough and its last screen show", async () => {
  api(
    CORE.map((id) =>
      id === "workspace" || id === "work" ? step(id, { done: true }) : id === "mail" ? step(id, { skipped: true }) : step(id),
    ),
  );
  open();
  const line = await screen.findByRole("region", { name: /^Finish setting up/ });
  expect(line).toHaveTextContent("2 of 6 done");
});

test("Continue setup opens the guide at the next step", async () => {
  const user = userEvent.setup();
  api([step("workspace", { done: true }), step("ai"), step("backup")]);
  const { onOpenGuide } = open();
  await user.click(await screen.findByRole("button", { name: "Continue setup" }));
  expect(onOpenGuide).toHaveBeenLastCalledWith("ai");
});

test("the optional extras and an add-on's own steps are neither counted nor named", async () => {
  api([step("ai"), step("template"), step("plugin/tidy", { label: "Connect the tidy-up tool", plugin: "plugin" })]);
  open();
  const line = await screen.findByRole("region", { name: /^Finish setting up/ });
  expect(line).toHaveTextContent("0 of 1 done");
  expect(screen.queryByText(/tidy-up/)).toBeNull();
});

test("once every step is done the group is gone", async () => {
  const calls = api([step("workspace", { done: true }), step("people", { done: true }), step("template")], true);
  open();
  await vi.waitFor(() => expect(calls.filter((c) => c.route === "GET setup").length).toBeGreaterThan(0));
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByRole("region", { name: /^Finish setting up/ })).toBeNull();
});

test("with every step skipped the line stays, counts none as done and names the first one passed by", async () => {
  const user = userEvent.setup();
  const calls = api(CORE.map((id) => step(id, { skipped: true })), true);
  const { onOpenGuide } = open();
  const line = await screen.findByRole("region", { name: /^Finish setting up/ });
  expect(line).toHaveTextContent("0 of 6 done");
  expect(calls.filter((c) => c.route === "GET setup").length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "Continue setup" }));
  expect(onOpenGuide).toHaveBeenLastCalledWith("workspace");
});

test("a step still to do comes before one skipped", async () => {
  const user = userEvent.setup();
  api([step("workspace", { skipped: true }), step("work", { done: true }), step("ai")]);
  const { onOpenGuide } = open();
  expect(await screen.findByRole("region", { name: /^Finish setting up/ })).toHaveTextContent("1 of 3 done");
  await user.click(screen.getByRole("button", { name: "Continue setup" }));
  expect(onOpenGuide).toHaveBeenLastCalledWith("ai");
});

test("hiding the line is remembered in this browser", async () => {
  const user = userEvent.setup();
  api([step("ai")]);
  open();
  await user.click(await screen.findByRole("button", { name: "More actions for setup" }));
  await user.click(screen.getByRole("menuitem", { name: "Hide" }));
  expect(screen.queryByRole("region", { name: /^Finish setting up/ })).toBeNull();
  document.body.innerHTML = "";
  api([step("ai")]);
  open();
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByRole("region", { name: /^Finish setting up/ })).toBeNull();
});

test("a browser that blocks storage still shows the line", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  api([step("ai")]);
  open();
  expect(await screen.findByRole("region", { name: /^Finish setting up/ })).toBeInTheDocument();
  vi.restoreAllMocks();
});

import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { expect, test } from "vitest";
import { Refuse, fakeApi, renderApp } from "../test-utils";
import { Addons } from "./Addons";
import { AiAccounts } from "./AiAccounts";
import { ActingAccounts } from "./ActingAccounts";
import { BackupsPanel } from "./BackupsPanel";
import { AssistantCloses } from "./HandledClosed";
import { Handover } from "./Handover";
import { Quality } from "./Quality";
import { RuleReview } from "./RuleReview";
import { Schedule } from "./Schedule";
import { SeriesPage } from "./SeriesPage";
import { Sources } from "./Sources";
import { SyncPanel } from "./SyncPanel";
import { TextSection } from "./TextSection";

// S-0431: on each screen that draws its skeleton apart from its failed state, a read that failed and is read again (the person's
// Try again, or the app's own re-read) keeps the alert and its button on screen until a read answers, never the skeleton.
const noop = () => undefined;
const screens: Array<[string, ReactElement, string]> = [
  ["Add-ons", <Addons />, "GET packs"],
  ["Quality", <Quality onBack={noop} />, "GET quality"],
  ["Handover", <Handover />, "GET sync/handover"],
  ["Handled for you", <AssistantCloses />, "GET silent-closes"],
  ["the rules review", <RuleReview onBack={noop} />, "GET knowledge/rules/review"],
  ["the acting accounts", <ActingAccounts />, "GET acts/accounts"],
  ["Backups", <BackupsPanel local />, "GET backups"],
  ["a series page", <SeriesPage id="SER-1" onBack={noop} />, "GET series/SER-1/page"],
  ["the AI accounts", <AiAccounts local level={3} />, "GET ai/accounts"],
  ["Sync", <SyncPanel />, "GET settings"],
  ["Schedule", <Schedule />, "GET schedule"],
  ["Connections", <Sources onAsk={noop} />, "GET watch"],
  ["a text section", <TextSection kind="project" id="P-1" field="notes" onReview={noop} />, "GET texts"],
];

test("every screen that draws a failed read apart from its skeleton keeps its alert and Try again while it reads again (S-0431)", async () => {
  for (const [name, element, route] of screens) {
    const user = userEvent.setup();
    let mode: "fail" | "hold" = "fail";
    const calls = fakeApi({
      [route]: () => (mode === "fail" ? new Refuse(500, "") : new Promise(() => undefined)),
    });
    const rendered = renderApp(element);
    const alert = await screen.findByRole("alert");
    const reads = () => calls.filter((c) => c.route.startsWith(route)).length;
    const before = reads();
    mode = "hold";
    await user.click(screen.getAllByRole("button", { name: "Try again" })[0]);
    await waitFor(() => expect(reads(), name).toBeGreaterThan(before));
    expect(screen.getAllByRole("alert").length, name).toBeGreaterThan(0);
    expect(alert, name).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Try again" }).length, name).toBeGreaterThan(0);
    rendered.unmount();
  }
});

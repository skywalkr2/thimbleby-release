import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { fakeApi, renderApp } from "../test-utils";
import { LearningNotice } from "./LearningNotice";

beforeEach(() => window.localStorage.clear());

test("while older mail is being read, the notice says Thimbleby is still learning, with how far along it is", async () => {
  fakeApi({ "GET today/learning": () => ({ active: true, read: 2, of: 5 }) });
  renderApp(<LearningNotice />);
  const notice = await screen.findByRole("status");
  expect(notice).toHaveTextContent("Thimbleby is still learning from your older mail.");
  expect(notice).toHaveTextContent("Batches read so far: 2 of 5.");
});

test("when no older read is under way there is no notice", async () => {
  const calls = fakeApi({ "GET today/learning": () => ({ active: false, read: 0, of: 0 }) });
  renderApp(<LearningNotice />);
  await waitFor(() => expect(calls.length).toBeGreaterThan(0));
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByRole("status")).toBeNull();
});

test("it can be hidden for the day and stays hidden when the page is opened again", async () => {
  fakeApi({ "GET today/learning": () => ({ active: true, read: 0, of: 0 }) });
  const first = renderApp(<LearningNotice />);
  await userEvent.click(await screen.findByRole("button", { name: "Hide for today" }));
  expect(screen.queryByRole("status")).toBeNull();
  first.unmount();
  renderApp(<LearningNotice />);
  await new Promise((r) => setTimeout(r, 20));
  expect(screen.queryByRole("status")).toBeNull();
});

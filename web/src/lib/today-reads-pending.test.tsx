import "@testing-library/jest-dom/vitest";
import { screen, waitFor } from "@testing-library/react";
import { fakeApi, renderApp } from "../test-utils";
import { useTodayCount } from "./today";

function Count() {
  const count = useTodayCount();
  return <p>{count === null ? "unknown" : `count ${count}`}</p>;
}

test("a read still loading never counts as zero, and the count shows once every read has answered (S-0727)", async () => {
  let answer: (lines: unknown[]) => void = () => {};
  const slow = new Promise<unknown[]>((resolve) => {
    answer = resolve;
  });
  fakeApi({
    "GET today/queue": () => [],
    "GET plugin-today": () => slow,
    "GET watch": () => [],
    "GET stages/requests": () => [],
    "GET stages/records": () => [],
    "GET stages/ready": () => [],
    "GET acts": () => ({ acts: [] }),
  });
  renderApp(<Count />);
  // Every read but one has answered: the sum is zero, and that is "can't tell", not "nothing".
  await new Promise((resolve) => setTimeout(resolve, 50));
  expect(screen.getByText("unknown")).toBeInTheDocument();
  answer([]);
  await waitFor(() => expect(screen.getByText("count 0")).toBeInTheDocument());
});

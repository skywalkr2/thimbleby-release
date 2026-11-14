import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useQuery } from "@tanstack/react-query";
import { vi } from "vitest";
import { fakeApi, renderApp } from "../test-utils";
import { ApiError } from "./api";
import { useAct } from "./act";
import { BannerSlot } from "../ui/BannerSlot";
import { Row } from "../ui/Row";

// A failed action says so in a toast that offers Try again, which runs the same call again (and says what happened this time).
fakeApi({});

function Doer(props: { run: () => Promise<string> }) {
  const act = useAct();
  return (
    <button type="button" onClick={() => void act(props.run, (made) => ({ message: `Made ${made}.` }))}>
      Do it
    </button>
  );
}

const region = () => screen.getByRole("region", { name: "Notifications" });

test("a failed action's toast offers Try again, which runs the same call again and then says it worked", async () => {
  const user = userEvent.setup();
  const run = vi
    .fn<() => Promise<string>>()
    .mockRejectedValueOnce(new ApiError(503, "The server is busy."))
    .mockResolvedValueOnce("the note");
  renderApp(<Doer run={run} />);
  await user.click(screen.getByRole("button", { name: "Do it" }));
  expect(await within(region()).findByText("That didn't work. The server is busy.")).toBeInTheDocument();
  await user.click(within(region()).getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
  expect(await within(region()).findByText("Made the note.")).toBeInTheDocument();
  // The failed toast went when it was used.
  expect(within(region()).queryByText(/That didn't work/)).toBeNull();
});

test("Try again that fails again offers Try again once more", async () => {
  const user = userEvent.setup();
  const run = vi.fn<() => Promise<string>>().mockRejectedValue(new ApiError(500, "Still no."));
  renderApp(<Doer run={run} />);
  await user.click(screen.getByRole("button", { name: "Do it" }));
  await user.click(await within(region()).findByRole("button", { name: "Try again" }));
  await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
  expect(await within(region()).findByRole("button", { name: "Try again" })).toBeInTheDocument();
});

test("a signed-out failure says so and offers no Try again, since a retry cannot help", async () => {
  const user = userEvent.setup();
  renderApp(<Doer run={() => Promise.reject(new ApiError(401, "no token"))} />);
  await user.click(screen.getByRole("button", { name: "Do it" }));
  expect(await within(region()).findByText(/You're signed out/)).toBeInTheDocument();
  expect(within(region()).queryByRole("button", { name: "Try again" })).toBeNull();
});

test("a failed action's toast is a warning (not a check), and a done one's toast is said at once, before the screens have read again", async () => {
  const user = userEvent.setup();
  renderApp(<Doer run={() => Promise.reject(new ApiError(500, "No."))} />);
  await user.click(screen.getByRole("button", { name: "Do it" }));
  const failed = (await within(region()).findByText(/That didn't work/)).closest("[data-toast]") as HTMLElement;
  expect(failed.querySelector("[data-tone]")).toHaveAttribute("data-tone", "warn");
});

test("the toast for what was done does not wait for the open screens' reads", async () => {
  const user = userEvent.setup();
  let release: () => void = () => undefined;
  const slow = new Promise<string>((resolve) => (release = () => resolve("late")));
  function Slow() {
    useQuery({ queryKey: ["slow"], queryFn: () => slow });
    return <Doer run={() => Promise.resolve("the note")} />;
  }
  renderApp(<Slow />);
  await user.click(screen.getByRole("button", { name: "Do it" }));
  // The read of the other screen is still pending, and the toast is already up.
  expect(await within(region()).findByText("Made the note.")).toBeInTheDocument();
  release();
});

// A save that names its row is not a toast: the row says which thing was not saved, that the change is kept, and offers Try again.
function NamedRow(props: { run: () => Promise<string> }) {
  const act = useAct();
  return (
    <ul>
      <Row as="li" title="Pay the deposit" failedId="a1" menu={undefined} primary={<button type="button" onClick={() => void act(props.run, (made) => ({ message: `Made ${made}.` }), undefined, { fail: { id: "a1", what: "Pay the deposit" } })}>Do it</button>} />
    </ul>
  );
}

test("a failed save that names its row is shown under that row, naming the thing, with no toast, and Try again saves it", async () => {
  const user = userEvent.setup();
  const run = vi
    .fn<() => Promise<string>>()
    .mockRejectedValueOnce(new ApiError(500, "The app couldn't write to its folder."))
    .mockResolvedValueOnce("it");
  renderApp(
    <>
      <BannerSlot />
      <NamedRow run={run} />
    </>,
  );
  await user.click(screen.getByRole("button", { name: "Do it" }));
  await screen.findAllByRole("alert");
  const line = document.querySelector<HTMLElement>("[data-not-saved]")!;
  // Round 4 (r4-s3): the row keeps only the short mark; the sentence is the banner's.
  expect(line).toHaveTextContent("Not saved");
  expect(line).not.toHaveTextContent("wasn't saved");
  // The one Try again is in the page's banner, which names the thing too; the note under the row has none.
  const banner = document.querySelector<HTMLElement>("[data-not-saved-banner]")!;
  expect(banner).toHaveTextContent("“Pay the deposit” wasn't saved. The app couldn't write to its folder. Nothing is lost");
  expect(within(line).queryByRole("button", { name: "Try again" })).toBeNull();
  expect(within(region()).queryByText(/That didn't work/)).toBeNull();
  expect(document.querySelector("[data-row-failed]")).not.toBeNull();
  await user.click(within(banner).getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  expect(document.querySelector("[data-row-failed]")).toBeNull();
});

test("a failed save whose row is not on screen is a toast with Try again, never held where nothing draws it", async () => {
  const user = userEvent.setup();
  const run = vi.fn<() => Promise<string>>().mockRejectedValue(new ApiError(500, "The app couldn't write to its folder."));
  function Lone() {
    const act = useAct();
    return (
      <button type="button" onClick={() => void act(run, undefined, undefined, { fail: { id: "gone", what: "Pay the deposit" } })}>
        Do it
      </button>
    );
  }
  renderApp(<Lone />);
  await user.click(screen.getByRole("button", { name: "Do it" }));
  expect(await within(region()).findByText(/That didn't work/)).toBeInTheDocument();
  expect(within(region()).getByRole("button", { name: "Try again" })).toBeInTheDocument();
  expect(screen.queryByRole("alert")).toBeNull();
});

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AuthImage } from "../ui/AuthImage";
import { openFile } from "./authed-file";
import { resetSession } from "./session";

beforeEach(() => {
  resetSession();
  window.localStorage.setItem("cockpit.session", "kept-session");
  URL.createObjectURL = vi.fn(() => "blob:local-1");
  URL.revokeObjectURL = vi.fn();
});
afterEach(() => {
  vi.unstubAllGlobals();
  resetSession();
});

test("a picture the server keeps is fetched with the session header and drawn from a local address", async () => {
  const fetchMock = vi.fn(async () => new Response(new Blob(["x"], { type: "image/png" }), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  render(<AuthImage src="api/brand/logo" alt="Your logo" />);
  expect(await screen.findByRole("img", { name: "Your logo" })).toHaveAttribute("src", "blob:local-1");
  const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
  expect(url).toBe("api/brand/logo");
  expect(init.headers).toEqual({ Authorization: "Bearer kept-session" });
});

test("a picture that can't be had draws nothing and is reported as a failed picture", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
  const failed = vi.fn();
  render(<AuthImage src="api/brand/logo" alt="Your logo" onError={failed} />);
  await waitFor(() => expect(failed).toHaveBeenCalled());
  expect(screen.queryByRole("img")).toBeNull();
});

test("a file link saves a document under its own name and opens a picture in a window opened from the click", async () => {
  const fetchMock = vi.fn(async () => new Response(new Blob(["x"]), { status: 200 }));
  vi.stubGlobal("fetch", fetchMock);
  const clicked: string[] = [];
  const original = HTMLAnchorElement.prototype.click;
  HTMLAnchorElement.prototype.click = function (this: HTMLAnchorElement) {
    clicked.push(`${this.download}|${this.href}`);
  };
  const win = { opener: {}, location: { href: "" }, close: vi.fn() };
  const open = vi.fn(() => win);
  vi.stubGlobal("open", open);
  const user = userEvent.setup();
  render(
    <>
      <a href="api/files/doc/content" onClick={openFile("api/files/doc/content", "notes.pdf", false)}>
        document
      </a>
      <a href="api/files/pic/content" onClick={openFile("api/files/pic/content", "pic.png", true)}>
        picture
      </a>
    </>,
  );
  await user.click(screen.getByText("document"));
  await waitFor(() => expect(clicked).toEqual(["notes.pdf|blob:local-1"]));
  expect(open).not.toHaveBeenCalled();
  await user.click(screen.getByText("picture"));
  await waitFor(() => expect(win.location.href).toBe("blob:local-1"));
  expect(open).toHaveBeenCalledWith("", "_blank");
  expect(win.opener).toBeNull();
  for (const call of fetchMock.mock.calls) expect((call as unknown as [string, RequestInit])[1].headers).toEqual({ Authorization: "Bearer kept-session" });
  HTMLAnchorElement.prototype.click = original;
});

test("a file that can't be fetched closes the window that was opened for it", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 404 })));
  const win = { opener: {}, location: { href: "" }, close: vi.fn() };
  vi.stubGlobal("open", vi.fn(() => win));
  const user = userEvent.setup();
  render(
    <a href="api/files/pic/content" onClick={openFile("api/files/pic/content", "pic.png", true)}>
      picture
    </a>,
  );
  await user.click(screen.getByText("picture"));
  await waitFor(() => expect(win.close).toHaveBeenCalled());
});

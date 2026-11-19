import "@testing-library/jest-dom/vitest";
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { Refuse, fakeApi, renderApp } from "../test-utils";
import { Sources } from "./Sources";

type Source = S["WatchSourceView"];

const source = (id: string, extra: Partial<Source> = {}): Source =>
  ({
    id,
    label: `Source ${id}`,
    connector: "folder",
    enabled: true,
    every_minutes: 60,
    every_minutes_set: false,
    last: null,
    failures: 0,
    ...extra,
  }) as unknown as Source;

const KINDS = [
  {
    name: "folder",
    label: "A folder",
    plugin: null,
    first_run: "baseline",
    items: [
      {
        key: "path",
        file: "source",
        group: "",
        description: "About path",
        type: "text",
        options: [],
        value: null,
        default: null,
        source: "default",
        locked: false,
        basic: false,
        editable: true,
      },
    ],
  },
] as unknown as S["WatchKindView"][];

async function typeInAddForm(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: "Add mail, calendar or folder" }),
  );
  const drawer = await screen.findByRole("dialog");
  await user.click(within(drawer).getByRole("radio", { name: /A folder/ }));
  await user.click(within(drawer).getByRole("button", { name: "Continue" }));
  const name = within(drawer).getByLabelText("Name");
  await user.type(name, "Typed name");
  await user.type(within(drawer).getByLabelText("Folder"), "Archive");
  return { drawer, name };
}

// What the person typed stays through every refresh of the sources while a source is still being read.
test("typing in the add form survives the sources being read again, a refresh that gives an answer with or without a last read, and one that fails", async () => {
  let sources = [source("a")];
  let fail = false;
  const { client } = (() => {
    fakeApi({
      "GET watch": () => {
        if (fail) return new Refuse(500, "down");
        return sources;
      },
      "GET watch/kinds": () => KINDS,
      "GET sign-ins": () => [],
      "GET settings": () => ({ items: [] }),
      "GET projects": () => [],
      "GET watch/authors": () => [],
    });
    return renderApp(<Sources onAsk={() => {}} />);
  })();
  const user = userEvent.setup();
  const { drawer, name } = await typeInAddForm(user);
  const form = drawer.querySelector("form[data-add-connection]");
  expect(form).not.toBeNull();
  // Still being read: the next answer says one more source is, then that it has been read, then the answer fails.
  sources = [source("a"), source("b")];
  await act(async () => client.invalidateQueries({ queryKey: ["watch"] }));
  await screen.findByText("Source b");
  sources = [
    source("a", { last: { outcome: "ok" } as Source["last"] }),
    source("b"),
  ];
  await act(async () => client.invalidateQueries({ queryKey: ["watch"] }));
  fail = true;
  await act(async () => client.invalidateQueries({ queryKey: ["watch"] }));
  await act(async () => client.invalidateQueries());
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(drawer.querySelector("form[data-add-connection]")).toBe(form);
  expect(name).toBeInTheDocument();
  expect(within(drawer).getByLabelText("Name")).toHaveValue("Typed name");
  expect(within(drawer).getByLabelText("Folder")).toHaveValue("Archive");
});

// A default that arrives after the form opened never lands on what the person typed (H5-16).
test("a kind's default value that arrives after the person typed leaves what they typed, in the folder and the name", async () => {
  let kinds = KINDS;
  fakeApi({
    "GET watch": () => [source("a")],
    "GET watch/kinds": () => kinds,
    "GET sign-ins": () => [],
    "GET settings": () => ({ items: [] }),
    "GET projects": () => [],
    "GET watch/authors": () => [],
  });
  const { client } = renderApp(<Sources onAsk={() => {}} />);
  const user = userEvent.setup();
  const { drawer } = await typeInAddForm(user);
  // The server's answer now carries a default for the folder, the way a later read of the kinds does.
  kinds = [{ ...KINDS[0], items: [{ ...KINDS[0].items[0], value: "inbox", default: "inbox", source: "default" }] }] as unknown as S["WatchKindView"][];
  await act(async () => client.invalidateQueries({ queryKey: ["watch", "kinds"] }));
  await act(async () => client.invalidateQueries());
  await waitFor(() => expect(client.isFetching()).toBe(0));
  expect(within(drawer).getByLabelText("Folder")).toHaveValue("Archive");
  expect(within(drawer).getByLabelText("Name")).toHaveValue("Typed name");
});

import "@testing-library/jest-dom/vitest";
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { S } from "../lib/api";
import { fakeApi, Refuse, renderApp } from "../test-utils";
import { ReportProblem } from "./ReportProblem";

type Problem = S["FeedbackProblem"];
const PROBLEM: Problem = {
  at: "2026-10-21T08:00:00Z",
  doing: "source_read",
  what: "folder",
  service: null,
  adapter: null,
  program_version: null,
  params: {},
  status: null,
  error_kind: "outage",
  text: "couldn't read <path>",
};
const DETAILS = "2026-01-01 08:00:00 ERROR engine.example: the source did not answer";
const ANSWER = "The assistant's last answer, from the request made 2026-10-21:\nIt holds the person's <b>own</b> material.";
const FACTS = { enabled: true, version: "9.8.7", system: "Example OS 1", reply_to: "own@example.com", details: DETAILS, answer: "" };

function open(over: { send?: () => unknown; problems?: Problem[]; facts?: Partial<typeof FACTS> } = {}) {
  const calls = fakeApi({
    "GET report/facts": () => ({ ...FACTS, ...over.facts }),
    "GET feedback/problems": () => ({ problems: over.problems ?? [PROBLEM] }),
    "POST report/send": over.send ?? (() => ({ ok: true, why: null })),
  });
  const onClose = vi.fn();
  renderApp(<ReportProblem onClose={onClose} />);
  return { calls, onClose, user: userEvent.setup() };
}

const words = () => screen.getByLabelText("What happened?");
const preview = () => screen.getByLabelText("What will be sent", { selector: "textarea" }) as HTMLTextAreaElement;
const detailsBox = () => screen.queryByLabelText("Technical details", { selector: "textarea" }) as HTMLTextAreaElement | null;
const sends = (calls: ReturnType<typeof open>["calls"]) => calls.filter((c) => c.route === "POST report/send");

test("the cursor is in the first field, and Send waits for words", async () => {
  open();
  expect(screen.getByRole("dialog", { name: "Report a problem" })).toBeInTheDocument();
  expect(words()).toHaveFocus();
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Send" })).toHaveAccessibleDescription("Write a few words to continue.");
});

test("what will be sent shows the words, the reply address, the version, the system, the problem lines and the technical details, and nothing is sent before Send", async () => {
  const { calls, user } = open();
  await waitFor(() => expect(screen.getByLabelText(/Your email address/)).toHaveValue("own@example.com"));
  expect(await screen.findByRole("checkbox", { name: "Include the recent problems (1)" })).toBeChecked();
  await user.type(words(), "The list is empty");
  const shown = preview().value;
  expect(shown).toContain("The list is empty");
  expect(shown).toContain("Reply to: own@example.com");
  expect(shown).toContain("App version: 9.8.7");
  expect(shown).toContain("System: Example OS 1");
  expect(shown).toContain("Recent problems");
  expect(shown).toContain("Doing: reading folder");
  expect(shown).toContain("Said: couldn't read <path>");
  expect(detailsBox()?.value).toBe(DETAILS);
  expect(sends(calls)).toHaveLength(0);
  // Unticking takes every problem line out; clearing the address says nobody is named.
  await user.click(screen.getByRole("checkbox", { name: "Include the recent problems (1)" }));
  await user.clear(screen.getByLabelText(/Your email address/));
  expect(preview().value).not.toContain("Recent problems");
  expect(preview().value).toContain("Reply to: nobody");
});

test("Send posts exactly the words, the address and the lines shown, once, says so and closes", async () => {
  const { calls, onClose, user } = open();
  await waitFor(() => expect(screen.getByLabelText(/Your email address/)).toHaveValue("own@example.com"));
  await screen.findByRole("checkbox", { name: "Include the recent problems (1)" });
  await user.type(words(), "It broke");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  const [only] = sends(calls);
  expect(sends(calls)).toHaveLength(1);
  const body = only.body as { words: string; reply_to: string; problems: string };
  expect(body.words).toBe("It broke");
  expect(body.reply_to).toBe("own@example.com");
  expect(body.problems.startsWith("Recent problems")).toBe(true);
  expect(preview().value).toContain(body.problems);
  expect(await screen.findByText("Sent. Thank you: the makers have your report.")).toBeInTheDocument();
});

test("a bad reply address is named and holds Send; a person with no address on record starts with an empty field", async () => {
  const { user } = open({ facts: { reply_to: "" } });
  await user.type(words(), "It broke");
  const field = screen.getByLabelText(/Your email address/);
  expect(field).toHaveValue("");
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  await user.type(field, "not an address");
  expect(await screen.findByRole("status")).toHaveTextContent(/doesn't look like an email address/);
  expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
});

test("a report the form did not take says why in words, keeps the dialog and the text, and offers Try again and Copy the report", async () => {
  let answer: unknown = { ok: false, why: "offline" };
  const { calls, onClose, user } = open({ send: () => answer });
  await user.type(words(), "It broke");
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("isn't connected to the internet. Nothing was sent.");
  expect(onClose).not.toHaveBeenCalled();
  expect(words()).toHaveValue("It broke");
  // The toast and the dialog both offer the two ways on; the dialog's are used here, the toast's are checked to be there.
  expect(screen.getAllByRole("button", { name: "Copy the report" })).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: "Try again" })).toHaveLength(2);
  const dialog = within(screen.getByRole("dialog"));
  await user.click(dialog.getByRole("button", { name: "Copy the report" }));
  expect(await navigator.clipboard.readText()).toContain("It broke");
  expect(await navigator.clipboard.readText()).toContain("App version: 9.8.7");
  answer = { ok: true, why: null };
  await user.click(dialog.getByRole("button", { name: "Try again" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(sends(calls)).toHaveLength(2);
});

test("a server that cannot be reached at all is told as the form not answering", async () => {
  const { user } = open({ send: () => new Refuse(500, "boom") });
  await user.type(words(), "It broke");
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Send" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("isn't answering right now");
});

test("the technical details are on by default and sent as shown", async () => {
  const { calls, user } = open();
  await user.type(words(), "It broke");
  const box = await screen.findByRole("checkbox", { name: "Include technical details" });
  expect(box).toBeChecked();
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(sends(calls)).toHaveLength(1));
  expect(sends(calls)[0].body).toMatchObject({ details: DETAILS, include_details: true });
});

test("with the technical details taken out they are not shown and the send carries none", async () => {
  const { calls, user } = open();
  await user.type(words(), "It broke");
  await user.click(await screen.findByRole("checkbox", { name: "Include technical details" }));
  expect(detailsBox()).toBeNull();
  await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(sends(calls)).toHaveLength(1));
  expect(sends(calls)[0].body).toMatchObject({ details: "", include_details: false });
});

test("with no technical details there is no checkbox for them", async () => {
  open({ facts: { details: "" } });
  await screen.findByRole("checkbox", { name: "Include the recent problems (1)" });
  expect(screen.queryByRole("checkbox", { name: "Include technical details" })).toBeNull();
});

test("with the facts still loading, words are enough: Send works, and the preview says the version and system come later", async () => {
  const calls = fakeApi({
    "GET report/facts": () => new Promise(() => {}),
    "GET feedback/problems": () => ({ problems: [] }),
    "POST report/send": () => ({ ok: true, why: null }),
  });
  const onClose = vi.fn();
  renderApp(<ReportProblem onClose={onClose} />);
  const user = userEvent.setup();
  expect(screen.getByRole("button", { name: "Send" })).toHaveAccessibleDescription("Write a few words to continue.");
  await user.type(words(), "It broke");
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Copy the report" })).toBeEnabled();
  expect(preview().value).toContain("App version: added when it is sent");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(sends(calls)).toHaveLength(1);
  expect(sends(calls)[0].body).toMatchObject({ words: "It broke", include_details: true });
});

test("with the facts failed, the form says so in a line, and Send still works", async () => {
  const calls = fakeApi({
    "GET report/facts": () => new Refuse(503, "busy"),
    "GET feedback/problems": () => ({ problems: [] }),
    "POST report/send": () => ({ ok: true, why: null }),
  });
  const onClose = vi.fn();
  renderApp(<ReportProblem onClose={onClose} />);
  const user = userEvent.setup();
  await user.type(words(), "It broke");
  expect(await screen.findByText(/version and system couldn't be read just now/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1));
  expect(sends(calls)).toHaveLength(1);
});

test("a bad reply address is the reason Send is held, not the missing words", async () => {
  const { user } = open({ facts: { reply_to: "" } });
  await user.type(words(), "It broke");
  await user.type(screen.getByLabelText(/Your email address/), "not an address");
  expect(screen.getByRole("button", { name: "Send" })).toHaveAccessibleDescription(/doesn't look like an email address/);
});

test("the preview has one visible heading", async () => {
  open();
  const shown = screen.getAllByText("What will be sent").filter((el) => !el.classList.contains("sr"));
  expect(shown).toHaveLength(1);
});

const answerBox = () => screen.queryByLabelText("The assistant's last answer", { selector: "textarea" }) as HTMLTextAreaElement | null;
const answerChoice = () => screen.queryByRole("checkbox", { name: "Include the assistant's last answer: it contains your material" });

test("with no kept answer the choice is not offered", async () => {
  open();
  await screen.findByRole("checkbox", { name: "Include technical details" });
  expect(answerChoice()).toBeNull();
  expect(answerBox()).toBeNull();
});

test("a kept answer is offered off: nothing of it is shown or sent until it is turned on, then exactly the shown text is sent as plain text", async () => {
  const { calls, user } = open({ facts: { answer: ANSWER } });
  const choice = await screen.findByRole("checkbox", { name: "Include the assistant's last answer: it contains your material" });
  expect(choice).not.toBeChecked();
  expect(answerBox()).toBeNull();
  await user.type(words(), "It stopped");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(sends(calls)).toHaveLength(1));
  expect(sends(calls)[0].body).toMatchObject({ include_answer: false, answer_block: "" });
  expect(JSON.stringify(sends(calls)[0].body)).not.toContain("material");
});

test("turned on, the answer is previewed as plain text and the same text is sent", async () => {
  const { calls, user } = open({ facts: { answer: ANSWER } });
  await user.click(await screen.findByRole("checkbox", { name: "Include the assistant's last answer: it contains your material" }));
  expect(answerBox()).not.toBeNull();
  expect(answerBox()!.value).toBe(ANSWER);
  expect(answerBox()).toHaveAttribute("readonly");
  expect(document.querySelector("b")).toBeNull(); // never rendered as markup
  await user.type(words(), "It stopped");
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(sends(calls)).toHaveLength(1));
  expect(sends(calls)[0].body).toMatchObject({ include_answer: true, answer_block: ANSWER });
});

test("lines that may hold the person's material show as removed with a note, and the report still goes and says what was left out", async () => {
  const removed = `2026-01-01 08:00:00 WARNING engine.example: slow\n[removed: may contain your material]`;
  const { calls, user } = open({
    facts: { details: removed, removed_lines: 1 } as Partial<typeof FACTS>,
    send: () => ({ ok: true, why: null, removed_lines: 1 }),
  });
  await user.type(words(), "It broke");
  await waitFor(() => expect(detailsBox()?.value).toContain("[removed: may contain your material]"));
  expect(screen.getByText(/1 line is marked removed: it may contain your material/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Send" }));
  await waitFor(() => expect(sends(calls)).toHaveLength(1));
  expect(sends(calls)[0].body).toMatchObject({ details: removed });
  expect(await screen.findByText(/1 line was left out because it may contain your material/)).toBeInTheDocument();
});

test("with nothing removed there is no note", async () => {
  open();
  await waitFor(() => expect(detailsBox()?.value).toBe(DETAILS));
  expect(screen.queryByText(/marked removed/)).not.toBeInTheDocument();
});

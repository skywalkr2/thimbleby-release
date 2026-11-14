import { render, screen } from "@testing-library/react";
import { WordingProvider, format, useWords } from "./wording";

function Said(props: { id: string }) {
  const { t } = useWords();
  return <p data-testid={props.id}>{t("schedule.view.work_week")}</p>;
}

test("a person with only their own life reads the variant of an entry, and everyone else the entry itself (X44)", () => {
  render(
    <>
      <WordingProvider justMe>
        <Said id="mine" />
      </WordingProvider>
      <WordingProvider>
        <Said id="shared" />
      </WordingProvider>
    </>,
  );
  expect(screen.getByTestId("mine")).toHaveTextContent("Weekdays");
  expect(screen.getByTestId("shared")).toHaveTextContent("Work week");
});

test("a workspace's own wording for an entry wins over the variant", () => {
  render(
    <WordingProvider justMe overrides={{ "schedule.view.work_week": "Mon to Fri" }}>
      <Said id="own" />
    </WordingProvider>,
  );
  expect(screen.getByTestId("own")).toHaveTextContent("Mon to Fri");
});

test("a title that ends with a full stop never doubles the punctuation the sentence puts after it (S-0348)", () => {
  const words = { a: "Decide about {text}: you have moved its day {n} times", b: "Done {text}.", c: "{text}, due {date}", d: "Dated {text}: {date}" };
  expect(format(words, "a", { text: "Send the headcount.", n: 5 })).toBe("Decide about Send the headcount: you have moved its day 5 times");
  expect(format(words, "b", { text: "Send the headcount." })).toBe("Done Send the headcount.");
  expect(format(words, "b", { text: "Is it sent?" })).toBe("Done Is it sent.");
  expect(format(words, "c", { text: "Send it.", date: "Fri" })).toBe("Send it, due Fri");
  expect(format(words, "d", { text: "Bring the floor plan.", date: "Fri, Nov 13" })).toBe("Dated Bring the floor plan: Fri, Nov 13");
  // A title that ends in an ellipsis, or with nothing after it, is left as it is.
  expect(format(words, "a", { text: "Send the headcount...", n: 5 })).toContain("Send the headcount...:");
  expect(format({ e: "Marked done: {text}" }, "e", { text: "Send it." })).toBe("Marked done: Send it.");
});

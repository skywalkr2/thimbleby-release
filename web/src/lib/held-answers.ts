// The answers to a held item, one set for every place that asks it: Today's line and the card of the change (the inspector)
// use these, so the words and the signals are the same wherever the person answers (design 7.6). The first answer applies
// the held change; the other leaves things as they were and records one correction the assistant learns from; each says
// what it did in a toast with Undo.
import { useState } from "react";
import { api, type S } from "./api";
import { useAct } from "./act";
import { endingWho, heldAnswers, heldTitle } from "./queue-words";
import { useWords } from "./wording";
import { useNoted } from "../components/NoteBox";

export interface HeldAnswers {
  title: string;
  primary: { label: string; run: () => void };
  /** The second visible button; the words that only said "closed" have three answers, so the others sit in the menu. */
  other?: { label: string; run: () => void };
  /** The answers that are not beside the first: "No longer needed" and "Not yet" for the words that only said "closed". */
  menu: Array<{ id: string; label: string; run: () => void }>;
  noting: boolean;
  closeNote: () => void;
  declineWithNote: (note: string) => Promise<S["Noted"] | undefined>;
  /** For a rule that contradicts one in force: "Narrow the new one", which opens the new rule's target for the person to limit
   * (only where the screen has room for the form), and what saving or leaving it does. */
  narrow?: { label: string; run: () => void };
  narrowing: boolean;
  saveNarrow: (scope: S["Scope"]) => void;
  closeNarrow: () => void;
}

export function useHeldAnswers(changeset: string, index: number, held: S["HeldAsk"] | null | undefined, onClosed?: () => void): HeldAnswers | null {
  const { t } = useWords();
  const act = useAct();
  const noted = useNoted();
  const [noting, setNoting] = useState(false);
  const [narrowing, setNarrowing] = useState(false);
  if (!held) return null;
  const cs = changeset;
  const words = heldAnswers(held, t);
  // One answer to one held question: a second press while the first is out is ignored.
  const once = { once: `held:${cs}:${index}` };
  const declineWithNote = (note: string) =>
    act(
      () => api.declineOp(cs, index, note),
      (done) => ({
        message: noted(t("queue.held.kept", { what: held.item }), done.request),
        undo: () => api.undeclineOp(cs, index),
      }),
      undefined,
      once,
    );
  const release = () =>
    void act(
      () => api.release(cs, index),
      () => ({ message: t("queue.held.done", { what: held.item }), undo: () => api.unreleaseOp(cs, index) }),
      undefined,
      once,
    );
  const decline = () => void declineWithNote("");
  const closeNote = () => {
    setNoting(false);
    onClosed?.();
  };
  const closeNarrow = () => {
    setNarrowing(false);
    onClosed?.();
  };
  const none = { narrowing: false, saveNarrow: () => undefined, closeNarrow };
  if (held.ask === "contradiction") {
    // Which rule wins. The new one retires the old in a change of its own, so Undo takes both back; keeping both is the
    // plain answer, optionally with the new rule limited first.
    const answer = (choice: "new" | "both", scope?: S["Scope"]) =>
      void act(
        () => api.ruleAnswer(cs, index, choice, scope),
        (done) => ({
          message: t(choice === "new" ? "queue.held.done.rule_new" : "queue.held.done.rule_both", { what: held.item }),
          undo: async () => {
            await api.unreleaseOp(cs, index);
            if (done.retired) await api.undo(done.retired);
          },
        }),
        undefined,
        { ...once, kinds: ["changeset", "rule", "request"] },
      );
    return {
      title: heldTitle(held, t),
      primary: { label: words.primary, run: () => answer("new") },
      other: { label: words.other, run: decline },
      menu: [{ id: "both", label: t("queue.held.a.rule_both"), run: () => answer("both") }],
      noting: false,
      closeNote,
      declineWithNote,
      narrow: { label: t("queue.held.a.rule_narrow"), run: () => setNarrowing(true) },
      narrowing,
      saveNarrow: (scope) => {
        setNarrowing(false);
        answer("both", scope);
      },
      closeNarrow,
    };
  }
  if (held.ask === "ending") {
    const toldNames = held.told ?? [];
    const answer = (ending: "done" | "called_off") =>
      void act(
        () => api.endingAnswer(cs, index, ending),
        (done) => ({
          message:
            ending === "called_off" && done.acts.length > 0
              ? t("queue.held.ending_off_note", { what: held.item, names: toldNames.join(", ") })
              : t(ending === "done" ? "queue.held.ending_done" : "queue.held.ending_off", { what: held.item, who: endingWho(held, t) }),
          undo: () => api.unreleaseOp(cs, index),
        }),
        undefined,
        once,
      );
    return {
      title: heldTitle(held, t),
      primary: { label: words.primary, run: () => answer("done") },
      menu: [
        { id: "called-off", label: t(toldNames.length > 0 ? "queue.held.e.ending_off_tell" : "queue.held.e.ending_off"), run: () => answer("called_off") },
        { id: "not-yet", label: words.other, run: decline },
      ],
      noting: false,
      closeNote,
      declineWithNote,
      ...none,
    };
  }
  // A drop of something that reached people is one answer, "Drop it and tell them": it drops the to-do and drafts a
  // note to each person told, which waits for the person's yes. With nobody told it is just "Drop it".
  const told = held.ask === "drop" ? (held.told ?? []) : [];
  const dropAndTell = () =>
    void act(
      () => api.releaseWithNote(cs, index),
      (done) => ({
        message: done.acts.length > 0 ? t("queue.held.done_note", { what: held.item, names: told.join(", ") }) : t("queue.held.done", { what: held.item }),
        undo: () => api.unreleaseOp(cs, index),
      }),
      undefined,
      once,
    );
  return {
    title: heldTitle(held, t),
    primary: { label: words.primary, run: told.length > 0 ? dropAndTell : release },
    other: { label: words.other, run: decline },
    menu:
      held.ask === "close" || held.ask === "part"
        ? [{ id: "note", label: t("note.add"), run: () => setNoting(true) }]
        : [],
    noting: noting && (held.ask === "close" || held.ask === "part"),
    closeNote,
    declineWithNote,
    ...none,
  };
}

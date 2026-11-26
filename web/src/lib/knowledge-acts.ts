// What the person can do to an entry or a rule (design 7.18): each acts at once, says what happened in a toast and can be
// undone from it. The server records the signal for each; Undo goes through the change the act made.
import { api, type S } from "./api";
import { useAct } from "./act";
import { useWords } from "./wording";

/** What an act needs of an entry or rule: its id and the version that was read. */
export interface Target {
  id: string;
  version: number;
}

/** Discarding an entry: it acts at once with Undo, and when the entry still has guesses on open to-dos (counted after the
 * discard, so one made meanwhile counts), the toast also offers one step that takes them all back, with its own Undo. */
export function useDiscardAct() {
  const { tn } = useWords();
  const act = useAct();
  return (item: Target, message: string, reason?: string) =>
    act(
      async () => {
        const done = await api.discardKnowledge(item.id, item.version, reason);
        const guesses = await api.knowledgeGuesses(item.id).then((g) => g.count, () => 0);
        return { done, guesses };
      },
      ({ done, guesses }) => ({
        message,
        undo: () => api.undo(done.changeset),
        action:
          guesses > 0
            ? {
                label: tn("knowledge.take_back_guesses", guesses),
                run: () =>
                  act(
                    () => api.takeBackGuesses(item.id),
                    (back) => ({ message: tn("toast.guesses_taken_back", guesses), undo: () => api.undo(back.changeset) }),
                  ),
              }
            : undefined,
      }),
      undefined,
      { once: `knowledge:${item.id}` },
    );
}

export function useKnowledgeActs() {
  const { t } = useWords();
  const act = useAct();
  const discard = useDiscardAct();
  const undo = (done: S["Applied"]) => () => api.undo(done.changeset);
  return {
    /** Keep a proposal; `body` carries wording or reach the person changed first. */
    keep: (item: Target, body: { text?: string } = {}) =>
      act(
        () => api.keepKnowledge(item.id, { read_version: item.version, ...body }),
        (done) => ({ message: t("knowledge.toast.kept"), undo: undo(done) }),
        undefined,
        { once: `knowledge:${item.id}` },
      ),
    discard: (item: Target) => discard(item, t("knowledge.toast.discarded")),
    justThisTime: (item: Target) =>
      act(
        () => api.justThisTime(item.id, item.version),
        (done) => ({ message: t("knowledge.toast.just_this_time"), undo: undo(done) }),
        undefined,
        { once: `knowledge:${item.id}` },
      ),
    retire: (item: Target) =>
      act(
        () => api.retireKnowledge(item.id, item.version),
        (done) => ({ message: t("knowledge.toast.retired"), undo: undo(done) }),
        undefined,
        { once: `knowledge:${item.id}` },
      ),
    /** "That's wrong" on something in use: it stops at once and is recorded as a correction. */
    wrong: (item: Target) =>
      act(
        () => api.wrongKnowledge(item.id, item.version),
        (done) => ({ message: t("knowledge.toast.wrong"), undo: undo(done) }),
        undefined,
        { once: `knowledge:${item.id}` },
      ),
    /** Bring a retired or set-aside entry back into use. */
    reuse: (item: Target) =>
      act(
        () => api.reuseKnowledge(item.id, item.version),
        (done) => ({ message: t("knowledge.toast.reused"), undo: undo(done) }),
        undefined,
        { once: `knowledge:${item.id}` },
      ),
    narrow: (item: Target, applies_to: S["Scope"]) =>
      act(
        () => api.narrowKnowledge(item.id, { read_version: item.version, applies_to }),
        (done) => ({ message: t("knowledge.toast.narrowed"), undo: undo(done) }),
        undefined,
        { once: `knowledge:${item.id}` },
      ),
    /** Add a word of the person's own with what it means: active at once, in their words. */
    addTerm: (term: string, meaning: string) =>
      act(
        () => api.addTerm(term, meaning),
        (done) => ({ message: t("knowledge.words.added", { word: term }), undo: undo(done) }),
        undefined,
        { once: "knowledge:add-term" },
      ),
    /** Keep a standing rule as it is in the review: its next review starts now. */
    keepRule: (item: Target) =>
      act(
        () => api.keepRule(item.id, item.version),
        (done) => ({ message: t("rules_review.kept"), undo: undo(done) }),
        undefined,
        { once: `knowledge:${item.id}` },
      ),
  };
}

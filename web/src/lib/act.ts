// Running an action: call the server, say what happened in a toast (with Undo when it can be undone, and with Try again,
// which runs the same call again, when it failed), then read again what changed. It goes through `useWrite`.
import { createContext, useCallback, useContext } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import { useFailedSaves, useToasts, type ToastInput } from "./toasts";
import { alreadyOut, justAnswered, justDone, runWrite, type WriteOptions } from "./write";
import { useWords } from "./wording";

/** What an action names about its write: the order key and the families to read again (none named reads everything). */
export type ActWrites = Pick<WriteOptions<unknown>, "key" | "touches" | "kinds" | "once" | "also"> & {
  /** With `once`: a press asked again within a double press's time after the first answered is ignored too, for an act that records
   * something each time it is done (a chase), so a double press never records it twice. */
  settle?: boolean;
  /** Where a failure is shown: the thing's key (the row's) and its name in the person's words. A failed save is then named beside that row, with Try again, instead of a toast. */
  fail?: { id: string; what: string };
};

/** The acts that change no record, each with the screens that show what it did. An answer to such an act carries only what another
 * writer changed at the same moment (the assistant's own work), so the screens that show this act's own result are named here and
 * read again whatever the answer names. A new act that records nothing joins this list, and `act` is given its entry. */
export const NO_RECORD_ACTS = {
  /** Signing out: the sign-in and source screens, and what Today and the status say of them. */
  signOut: { also: ["sign-ins", "watch", "status", "today"] },
  /** Signing in again, and starting to read what an account's sign-in left unread. */
  signIn: { also: ["sign-ins", "watch", "mail-services", "status", "today"] },
  /** Reading one source or all of an account's again ("Read now", a retry of a failed read). */
  readSource: { also: ["watch", "sign-ins", "mail-services", "status", "today", "waiting"] },
  /** Checking an AI account (its test, from its card, the first-run step or a Today line). */
  checkAccount: { also: ["ai-accounts", "ai-endpoints", "status", "today", "setup"] },
  /** Reading the week ahead again. */
  readWeek: { also: ["week-ahead", "brief", "today"] },
} as const satisfies Record<string, ActWrites>;

/** Signing out changes no record, so an answer that names kinds (another writer's, at the same moment) must not leave the
 * sign-in and source screens unread: they are read again whatever the answer names. */
export const SIGNED_OUT_READS: ActWrites = NO_RECORD_ACTS.signOut;

/** A part of a screen whose actions are one at a time (a row on Today): inside it, an action pressed while another of the same part is
 * still out is ignored, so a second press never sends a change twice. The value names the part. */
export const ActScope = createContext<string | null>(null);

export function useAct() {
  const client = useQueryClient();
  const scope = useContext(ActScope);
  const { push } = useToasts();
  const failed = useFailedSaves();
  const { t } = useWords();
  return useCallback(
    async function act<T>(
      run: () => Promise<T>,
      after?: (result: T) => Omit<ToastInput, "undo"> & { undo?: () => Promise<unknown> },
      /** A screen that shows a failed save itself (a "Not saved" row beside what was changed) takes the failure here, and no toast is made. */
      onError?: (err: unknown) => void,
      given: ActWrites = {},
    ): Promise<T | undefined> {
      const writes: ActWrites = given.once === undefined && scope !== null ? { ...given, once: `scope:${scope}` } : given;
      // A second press of the same thing while the first is out does nothing: the change is sent once.
      if (writes.once !== undefined && (alreadyOut(client, writes.once) || (writes.settle && justAnswered(client, writes.once)))) return undefined;
      try {
        const result = await runWrite(client, run, {
          key: writes.key,
          touches: writes.touches,
          also: writes.also,
          kinds: writes.kinds,
          once: writes.once,
          // What was done is said when the server answers, before the screens read again.
          answered: (result) => {
            if (!after) return;
            const toast = after(result);
            const undo = toast.undo;
            push({
              ...toast,
              undo: undo
                ? async (confirmed) => {
                    // Said once the server has undone it; the screens then read again, and the toast never waits for their reads.
                    await runWrite(client, undo, { ...writes, once: undefined, answered: confirmed });
                  }
                : undefined,
            });
          },
        });
        if (writes.fail) failed.clear(writes.fail.id);
        return result;
      } catch (err) {
        // "Changed since you looked", answered to the person's own second press of something that just worked: nothing to say.
        if (err instanceof ApiError && err.needs === "look-again" && writes.once !== undefined && justDone(client, writes.once)) return undefined;
        if (onError) {
          onError(err);
          return undefined;
        }
        const detail = err instanceof ApiError ? err.detail : "";
        const signedOut = err instanceof ApiError && err.status === 401;
        // A save that names its row is shown beside it, naming the thing and saying nothing is lost.
        if (writes.fail && !signedOut && failed.fail(writes.fail.id, { what: writes.fail.what, reason: detail, retry: () => act(run, after, undefined, writes) })) return undefined;
        // A failure offers to run the same call again, except a signed-out one, which no retry can fix.
        push({
          message: signedOut ? t("error.signed_out") : t("error.failed", { detail }),
          tone: "warn",
          action: signedOut ? undefined : { label: t("action.try_again"), run: () => act(run, after, undefined, writes) },
        });
        return undefined;
      }
    },
    [client, push, failed, t, scope],
  );
}

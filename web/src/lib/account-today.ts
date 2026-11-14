// An account that is not being read, as a Today line (design 7.7): told from the same account states the header and Connections
// read, so Today, the header's chip and a calendar's banner name the same account. An account that needs the person to sign in
// is a line at once; one that is only retrying (a failed or offline read with nothing to sign in to) stays in the header until
// it has gone on for a day.
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { accountsNeedingYou, accountStates, type AccountState } from "./connections";
import { onAnySide, type SideChoice } from "./sides";

/** How long an account that is only retrying may go unread before Today says so, in hours. */
export const RETRYING_LINE_AFTER_HOURS = 24;

/** The sides an account's connections serve, by id, each once. */
export const sidesOfAccount = (account: AccountState): string[] => Array.from(new Set(account.sources.flatMap((s) => s.sides ?? [])));

/** What of an account is not being read: its mail, its calendar, or both. */
export function unreadParts(account: AccountState): "mail" | "calendar" | "both" {
  const kinds = new Set(account.sources.filter((s) => s.enabled).flatMap((s) => s.reads ?? ["mail"]));
  return kinds.has("mail") && kinds.has("calendar") ? "both" : kinds.has("calendar") ? "calendar" : "mail";
}

/** The accounts that are a line on Today: the ones that need a sign-in, and the ones retrying for more than a day. */
export function accountsOnToday(all: AccountState[], now: Date): AccountState[] {
  const need = new Set(accountsNeedingYou(all).map((a) => a.key));
  const limit = RETRYING_LINE_AFTER_HOURS * 3600 * 1000;
  return all.filter((a) => need.has(a.key) || ((a.fare === "failed" || a.fare === "offline") && !!a.since && now.getTime() - new Date(a.since).getTime() > limit));
}

/** The lines for accounts not being read, narrowed to a side the way the queue's own lines are. */
export function useAccountToday(side: SideChoice = "all"): { count: number; accounts: AccountState[] } {
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const accounts = accountsOnToday(accountStates(watch.data ?? []), new Date()).filter((a) => onAnySide(sidesOfAccount(a), side));
  return { count: accounts.length, accounts };
}

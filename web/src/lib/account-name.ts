// What an account is called where the person reads it (Today's lines, a calendar's banner): never its address. First the side its
// calendar or mailbox serves; with several, the label Connections shows with any address or part of an address taken out; with
// nothing left, a plain phrase from the wording sheet.
import type { AccountState } from "./connections";
import { cutName } from "../ui/SideMark";
import { withoutAddress } from "./calendar";

export { withoutAddress };


/** The account's name: the one side its connections serve (calendars first, as the banner names them), else its label without
 * an address, else `fallback`. `sideName` gives a side's name by id. */
export function accountName(account: AccountState, sideName: (side: string) => string | undefined, fallback: string): string {
  const single = (sources: AccountState["sources"]): string | undefined => {
    const found = new Set(sources.filter((s) => s.sides?.length === 1).map((s) => (s.sides ?? [])[0]));
    return found.size === 1 ? sideName([...found][0]) : undefined;
  };
  const calendars = account.sources.filter((s) => (s.reads ?? []).includes("calendar"));
  const side = single(calendars) ?? single(account.sources);
  if (side) return cutName(side);
  const address = account.sources.find((s) => s.account)?.account ?? account.name;
  const label = withoutAddress(account.sources[0]?.label ?? "", address);
  return label || fallback;
}

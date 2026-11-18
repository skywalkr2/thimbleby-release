// What an account is called where Today names it (design 7.7): its service, never any part of its address. With one account of a
// service that is "Your <service> account"; with several of one service, the label the person gave the connection (an address or
// part of one taken out), and when two share a label, the service with the account's place among them.
import type { AccountState } from "./connections";
import { withoutAddress } from "./calendar";

export { withoutAddress };

/** The words an account is named in. `service` is the service's name as the person sees it ("" when unknown), `same` every account
 * of that service in the order they are listed (this one among them), and `words` the wording sheet's phrases. */
export function accountName(
  account: AccountState,
  service: string,
  same: AccountState[],
  words: { single: (service: string) => string; numbered: (service: string, n: number) => string; fallback: string },
): string {
  const named = service || words.fallback;
  if (same.length <= 1) return service ? words.single(service) : words.fallback;
  const labelOf = (a: AccountState) => withoutAddress(a.sources[0]?.label ?? "", a.sources.find((s) => s.account)?.account ?? a.name).trim();
  const label = labelOf(account);
  if (label && same.filter((a) => labelOf(a) === label).length === 1) return label;
  return words.numbered(named, same.findIndex((a) => a.key === account.key) + 1);
}

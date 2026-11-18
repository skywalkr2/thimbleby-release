import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { useWords } from "./wording";
import { useMoney } from "./money";

/** What a typical day of the assistant's sorting costs, in words, from the account that would sort: an amount for a priced
 *  account, runs a day for a plan, and the built-in rules when no account takes the work. Null until it is known. */
export function useSortingCostWords(enabled = true): string | null {
  const { t } = useWords();
  const money = useMoney();
  const cost = useQuery({ queryKey: ["sorting-cost"], queryFn: api.sortingCost, enabled });
  if (!enabled || !cost.data) return null;
  const { kind, messages, runs, estimate_usd } = cost.data;
  if (kind === "none") return t("sorting.cost.none");
  const said = t(`sorting.cost.messages.${messages === 1 ? "one" : "other"}`, { n: messages });
  const many = t(`sorting.cost.runs.${runs === 1 ? "one" : "other"}`, { n: runs });
  // An amount under a cent reads "less than a cent a day", never "about less than a cent".
  if (kind === "money" && estimate_usd != null && estimate_usd < 0.005) return t("sorting.cost.money_under", { messages: said });
  if (kind === "money" && estimate_usd != null) return t("sorting.cost.money", { amount: money(estimate_usd), messages: said });
  return t(kind === "runs" ? "sorting.cost.runs" : "sorting.cost.unknown", { runs: many, messages: said });
}

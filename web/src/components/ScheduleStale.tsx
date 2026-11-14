// A calendar that can't be read until the person signs in again (design 7.7, 7.15): one line above the calendar naming it, the
// calendar and when it was last updated (never the account's address, which is on Connections only), with the one button that fixes
// it. The entries it last read stay shown. Told from the same account states the header and Connections read.
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { accountsNeedingYou, accountStates, type AccountState } from "../lib/connections";
import { whenWords } from "../lib/coverage";
import { withoutAddress } from "../lib/calendar";
import { useIsNarrow } from "../lib/media";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Banner } from "../ui/Banner";
import { SideMark } from "../ui/SideMark";
import { useSignInAgain } from "./AccountRow";
import styles from "./Schedule.module.css";

function Line(props: { account: AccountState; nameOf: (id: string) => string | undefined }) {
  const { t } = useWords();
  const { account } = props;
  const again = useSignInAgain(account);
  const phone = useIsNarrow();
  const calendars = account.sources.filter((s) => (s.reads ?? []).includes("calendar"));
  const read = calendars.flatMap((s) => (s.read_at ? [s.read_at] : [])).sort().at(-1);
  // Each calendar by the name the page gives it (its side, else the person's name for it); the account's address is on Connections only.
  const named = Array.from(new Set(calendars.map((s) => props.nameOf(s.id) ?? (withoutAddress(s.label, s.account) || t("schedule.calendar.fallback"))))).join(", ");
  // When the calendars all serve one side, the line says it with the side's mark and name, as every other place on the page does.
  const sides = Array.from(new Set(calendars.flatMap((s) => (s.sides ?? []).slice(0, 1))));
  const side = sides.length === 1 && calendars.every((s) => (s.sides ?? []).length === 1) ? sides[0] : null;
  const when = read ? whenWords(read, new Date(), t) : "";
  // On a phone the line is one line: what is wrong and which calendar; the whole, with when it was last read, is on hover and in the sign-in button's name.
  const text = phone
    ? t("schedule.stale.phone", { calendar: named })
    : side
    ? read
      ? t("schedule.stale.side_since", { when })
      : t("schedule.stale.side")
    : read
      ? t("schedule.stale.line_since", { calendar: named, when })
      : t("schedule.stale.line", { calendar: named });
  return (
    <Banner
      as="li"
      data-schedule-stale=""
      action={
        again.item ? (
          <Button size="sm" variant="secondary" disabled={again.busy || !again.item.ready} aria-label={t("schedule.stale.sign_in_again", { calendar: named })} onClick={() => void again.start()}>
            {t("account.sign_in_again")}
          </Button>
        ) : undefined
      }
    >
      <span title={phone ? (read ? t("schedule.stale.line_since", { calendar: named, when }) : t("schedule.stale.line", { calendar: named })) : named}>
        {side && !phone && <SideMark side={side} />}
        {side && !phone ? " " : ""}
        {text}
      </span>
    </Banner>
  );
}

export function ScheduleStale(props: { nameOf: (id: string) => string | undefined }) {
  const { t } = useWords();
  const watch = useQuery({ queryKey: ["watch"], queryFn: api.watchSources });
  const calendars = (watch.data ?? []).filter((s) => (s.reads ?? []).includes("calendar"));
  const needing = accountsNeedingYou(accountStates(calendars));
  if (needing.length === 0) return null;
  return (
    <ul className={styles.staleList} aria-label={t("schedule.stale.label")} data-schedule-stale-list="">
      {needing.map((account) => (
        <Line key={account.key} account={account} nameOf={props.nameOf} />
      ))}
    </ul>
  );
}

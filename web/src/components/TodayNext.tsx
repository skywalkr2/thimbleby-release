// The day's next event, said inside the line under Today's heading on a phone (after "N things need you", never a line of its own): the schedule is folded to a bar far down the page there, so
// without it the first screen shows nothing of the day itself. It names the time and the title and links to the Schedule.
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { clockDay, clockTime, onTheClock, todayOn } from "../lib/dates";
import { useSideFilter } from "../lib/sides";
import { viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { keepNumber } from "../lib/keep-number";
import styles from "./Today.module.css";

export function TodayNext() {
  const { t } = useWords();
  const agenda = useQuery({ queryKey: ["today", "agenda"], queryFn: api.agenda });
  const filter = useSideFilter();
  const now = new Date();
  const today = todayOn(now);
  const minutes = onTheClock(now).minutes;
  const clock = (iso: string) => {
    const [h, m] = (iso.length > 10 ? iso.slice(11, 16) : "00:00").split(":").map(Number);
    return h * 60 + m;
  };
  const next = (agenda.data ?? [])
    .filter((e) => !e.cancelled && !e.all_day && filter.shows(e.side, e.views) && clockDay(e.start) === today && clock(e.start) >= minutes)
    .sort((a, b) => a.start.localeCompare(b.start))[0];
  if (!next) return null;
  return (
    <span className={styles.nextUp} data-next-event="">
      {" · "}
      <a href={viewHref("schedule")}>{t("today.next", { time: clockTime(next.start), title: keepNumber(next.title) })}</a>
    </span>
  );
}

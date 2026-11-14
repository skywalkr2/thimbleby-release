// A group of meetings in the side pane (design 7.7): the meetings of a clash (or of an overlap too narrow to draw side by side), every one
// as a row with its start, title and side, each opening its own details in the same pane. The pane's title says how many and when.
import { useWords } from "../lib/wording";
import { GroupRow } from "./ScheduleGroupCard";
import type { Calendars, Entry } from "./ScheduleEntry";
import styles from "./Schedule.module.css";

export function GroupDetails(props: { items: Entry[]; date: string; calendars: Calendars; onOpen: (entry: Entry, date: string | null) => void; allDay?: boolean }) {
  const { t } = useWords();
  return (
    <ul className={styles.clashRows} aria-label={t(props.allDay ? "schedule.group.list_all_day" : "schedule.group.list")} data-group-pane="">
      {props.items.map((e, k) => (
        <li key={`${e.snapshot}:${e.start}:${k}`}>
          <GroupRow entry={e} date={props.date} calendars={props.calendars} selected={null} onOpen={props.onOpen} />
        </li>
      ))}
    </ul>
  );
}

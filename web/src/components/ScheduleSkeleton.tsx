// What the calendar page shows while its days are coming (design 7.12): the shape of what will be there, so the page does not
// jump when the days arrive. The time grids get hour rows and a column for each day, with no block that could be read as an entry; the Month and the list by day on a phone
// get the list's rows.
import { Skeleton } from "../ui/Skeleton";
import styles from "./Schedule.module.css";

export function ScheduleSkeleton(props: { view: "grid" | "month" | "list"; days: number }) {
  // The month and the phone's list load as the rows they will be: a dot, a title and a line under it, in the list's own frame, with no button.
  if (props.view !== "grid") return <Skeleton rows={props.view === "month" ? 5 : 4} row={{ lead: true, action: "none", framed: true }} />;
  const columns = Math.max(1, props.days);
  return (
    <div>
    {/* The line that holds "Show all hours" once the grid is there, so the grid does not move down when it comes. */}
    <div className={styles.hoursSwitch} aria-hidden="true" data-hours-held="">
      <span className={styles.hoursHeld} />
    </div>
    <Skeleton shape="frame" kind="grid" className={styles.gridSkeleton} style={{ ["--cols" as string]: columns }}>
      {Array.from({ length: columns }, (_, n) => (
        <span key={n} className={styles.skeletonHead} aria-hidden="true" style={{ gridColumn: n + 2 }} />
      ))}
      {Array.from({ length: 8 }, (_, h) => (
        <span key={h} className={styles.skeletonHour} aria-hidden="true" style={{ gridRow: h + 2 }} />
      ))}
      {Array.from({ length: columns * 8 }, (_, n) => (
        <span key={`c${n}`} className={styles.skeletonCell} aria-hidden="true" style={{ gridRow: Math.floor(n / columns) + 2, gridColumn: (n % columns) + 2 }} />
      ))}
    </Skeleton>
    </div>
  );
}

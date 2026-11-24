// An entry's details beside the calendar (design 7.7): what it is, when, where, which calendar it is on (or that it is the
// app's own), which side it is on, a delivery's tracking, carrier, status and range, and "Open" to its page. The person's own
// entry can be moved or cancelled here at once (with Undo); a connected calendar's event, after the person's yes in Waiting to go
// out, or with the plain reason it can't be and where to change it. Every word of a connected calendar's is untrusted text and
// shown as text.
import { day } from "../lib/dates";
import { deliveryLines, deliveryRange } from "../lib/deliveries";
import { useWords } from "../lib/wording";
import { ButtonLink } from "../ui/Button";
import { Pill } from "../ui/Pill";
import { SideMark } from "../ui/SideMark";
import { Definition, DefinitionList } from "../ui/DefinitionList";
import { useEventActs } from "./EventActs";
import { RowMenu } from "./RowMenu";
import { SafeLink } from "./SafeText";
import { alsoIn, entryHref, fullWhen, type Calendars, type Entry } from "./ScheduleEntry";
import styles from "./Schedule.module.css";

export function EntryDetails(props: { entry: Entry; date: string | null; calendars: Calendars; onBack?: () => void }) {
  const { t } = useWords();
  const { entry } = props;
  const calendar =
    entry.kind === "due" ? t("schedule.pane.calendar_due") : entry.own ? t("schedule.pane.calendar_own") : (props.calendars.name(entry.source) ?? t("schedule.event.calendar_unknown"));
  const color = !entry.own && entry.kind !== "due" ? props.calendars.color(entry.source) : undefined;
  const range = deliveryRange(entry, t);
  const delivery = deliveryLines(entry.delivery, t);
  const rows: [string, React.ReactNode][] = [
    [t("schedule.pane.when"), fullWhen(entry, props.date, t)],
    ...(entry.where?.trim() ? [[t("schedule.event.where"), entry.where] as [string, React.ReactNode]] : []),
    ...(entry.repeats ? [[t("schedule.pane.repeats"), t(`meeting.repeat.${entry.repeats}`)] as [string, React.ReactNode]] : []),
    [
      t("schedule.event.calendar"),
      <span className={styles.calendarName}>
        {color && !props.calendars.bySide && <span className={styles.mark} data-color={color} aria-hidden="true" />}
        {calendar}
      </span>,
    ],
    ...(alsoIn(entry, props.calendars).length > 0 ? [[t("schedule.pane.also_in"), alsoIn(entry, props.calendars).join(", ")] as [string, React.ReactNode]] : []),
    ...(entry.side ? [[t("schedule.pane.side"), <SideMark side={entry.side} />] as [string, React.ReactNode]] : []),
    ...(entry.kind === "due" && props.date ? [[t("schedule.pane.due"), day(entry.start)] as [string, React.ReactNode]] : []),
    ...(entry.delivery
      ? [
          [
            t("schedule.pane.delivery"),
            <>
              {[range, ...delivery].filter(Boolean).join(" · ")}
              {entry.delivery.track && (
                <>
                  {" · "}
                  <SafeLink label={t("today.agenda.delivery.track")} url={entry.delivery.track} />
                </>
              )}
            </>,
          ] as [string, React.ReactNode],
        ]
      : []),
  ];
  const changeable = entry.kind === "due" || entry.kind === "delivery" ? null : entry.own ? entry.snapshot : (entry.entry ?? null);
  // Moving and calling off an entry that has a record of its own (the app's own entry, or a connected event the app keeps one for).
  // Its record says at once when it is called off, so the pane does not wait for the schedule to be read again.
  const acts = useEventActs(changeable ?? "", {}, !!changeable, entry.link, entry.own && entry.occurrence ? { was: entry.occurrence, start: entry.start, end: entry.end } : undefined);
  const calledOff = entry.cancelled || acts.calledOff;
  // A connected event the app keeps no entry for can't be drafted against: it is changed in its calendar app.
  const appOnly = entry.kind === "event" && !entry.own && !changeable;
  return (
    <div className={styles.pane}>
      {calledOff && (
        <p>
          <Pill tone="warn">{t(entry.held || acts.calledOff ? "calledoff.on_hold" : "today.agenda.called_off")}</Pill>
          {entry.called_off_why && (
            <span data-called-off-why=""> {t("today.agenda.called_off_why", { why: entry.called_off_why })}</span>
          )}
        </p>
      )}
      <DefinitionList>
        {rows.map(([name, value]) => (
          <Definition key={name}>
            <dt>{name}</dt>
            <dd>{value}</dd>
          </Definition>
        ))}
      </DefinitionList>
      {appOnly && <p className={styles.paneNote}>{t("acts.event.why.app_only")}</p>}
      <div className={styles.paneActs}>
        <ButtonLink variant="secondary" href={entryHref(entry)}>
          {entry.kind === "due" ? t("schedule.pane.open_todo") : t("schedule.pane.open")}
        </ButtonLink>
        {entry.link && <SafeLink label={t("schedule.open_calendar")} url={entry.link} />}
        {acts.menu.length > 0 && <RowMenu label={entry.title} actions={acts.menu} />}
        {acts.form}
        {acts.note}
      </div>
    </div>
  );
}

// To-dos and questions (design 7.5, 6.8, 6.9): every open to-do and every open question in one place each. A to-do row
// has its owners, due date, project (and the project that holds it), where it came from, and its state; a question row
// who it waits on and since when. Both are narrowed by project, person and state, each chosen from a list. A row's one
// primary act is the likeliest next step, and the rest are in its menu: edit, reassign, merge a near-duplicate, hold,
// drop, a note to the assistant. Every act is the person's own, at once, with Undo; the server records its signal.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { useReviewTime } from "../lib/review-time";
import { ActScope, useAct } from "../lib/act";
import { useIsNarrow, useMediaQuery } from "../lib/media";
import { useListChoice, type ListChoice } from "../lib/list-choice";
import { clockDay, day, monthDay, todayOn } from "../lib/dates";
import { useRowKeys } from "../lib/keys";
import {
  ACTION_STATES,
  NO_FILTERS,
  QUESTION_STATES,
  actionsShown,
  groupActions,
  questionsShown,
  takeFilters,
  type Filters,
  type OpenAction,
  type OpenQuestion,
  workCounts,
} from "../lib/open-items";
import { useSaid } from "../lib/repeat";
import { revealOrKeep } from "../lib/reveal";
import { openOnToday } from "./AnswerOnToday";
import { filterCanChange } from "../lib/filterbar";
import { onSide, useSideFilter, useSides, type SideChoice } from "../lib/sides";
import { useSideSlot } from "../lib/marks";
import { recordView, toHash, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { Pill } from "../ui/Pill";
import { Icon } from "../ui/Icon";
import { GroupLabel } from "../ui/GroupLabel";
import { SideMark } from "../ui/SideMark";
import { InlineAddTodo } from "./InlineAddTodo";
import { DoneList } from "./DoneList";
import { Row } from "../ui/Row";
import { NoBreak } from "../ui/NoBreak";
import { UndoLink } from "../ui/UndoLink";
import { FilteredEmpty } from "../ui/FilteredEmpty";
import { ListState } from "../ui/ListState";
import { AskChooser } from "./AskChooser";
import { SideFilter } from "./SideFilter";
import { useChangeThis, useNotMineToTrack, useQuestionMenu } from "./ChangeThis";
import { closeEditorOf, useOneEditor } from "../lib/one-editor";
import { useDropAction } from "./DropAction";
import { useAddTodo } from "./AddTodo";
import { useEditAction } from "./EditAction";
import { Button } from "../ui/Button";
import { useStopRepeat } from "./StopRepeat";
import { NoteBox, useNoted } from "./NoteBox";
import { LearnedLines } from "./Learned";
import { HoldNote, useHold } from "./OnHold";
import styles from "./OpenItems.module.css";
import { OriginLink } from "./Origin";
import { useHandToAssistant } from "./HandToAssistant";
import { usePlaceText } from "../lib/place";
import { NeedsADateLine } from "./NeedsADate";
import { ProjectTag } from "./ProjectTag";
import { ViewTags, useViewLabels } from "./ViewTags";
import { NotesTitle } from "./ActionNotes";
import { dateAndTime, useRemindMe } from "./ReminderLine";
import type { MenuAction } from "./RowMenu";
import { RowMenu } from "./RowMenu";
import { fullTitle, plainTitle } from "../lib/title-dates";
import { joinMeta, SIDE_PART } from "../lib/meta-join";

import { EmptyState } from "../ui/EmptyState";
import { FilterChip } from "../ui/FilterChip";
import { PageHeader } from "../ui/PageHeader";
import { RoundCheck } from "../ui/RoundCheck";
import { TabStrip } from "../ui/TabStrip";
import { RowList } from "../ui/RowList";
import { ListDetail } from "../ui/ListDetail";
import { RecordPage } from "./RecordPage";
type Tab = "actions" | "questions" | "done";

/** The width the list needs beside the pane: a round check, a title with its line under it, the primary and the menu. */
const TODOS_FIT = 480;
type T = (key: string, vars?: Record<string, string | number>) => string;
type TN = (key: string, n: number, vars?: Record<string, string | number>) => string;

export function OpenItems() {
  const { t, tn } = useWords();
  useReviewTime("open");
  const items = useQuery({ queryKey: ["open-items"], queryFn: api.openItems });
  const projects = useQuery({ queryKey: ["projects"], queryFn: api.projects });
  const narrow = useIsNarrow();
  const [tab, setTab] = useState<Tab>("actions");
  // The Done tab reads its own list, only while it is open; a to-do ticked or reopened anywhere reads it again.
  const finished = useQuery({ queryKey: ["open-items", "done"], queryFn: api.doneItems, enabled: tab === "done" });
  const [filters, setFilters] = useState<Filters>(takeFilters);
  // The to-dos just ticked stay in their place, struck through, with Undo, until the person moves on (another tab or filter).
  const [settled, setSettled] = useState<Map<string, OpenAction>>(new Map());
  const ids = useId();
  const addTodo = useAddTodo();
  // With a side beside Personal, the list can be narrowed to one side; what is on no side shows under every choice.
  const side = useSideFilter();
  const actions = (items.data?.actions ?? []).filter((a) => onSide(a.side, side.picked, a.views, !!a.project_name));
  const questions = (items.data?.questions ?? []).filter((q) => onSide(q.side, side.picked, q.views, (q.projects ?? []).length > 0));

  // What the open tab holds under a side choice (the side filter's own counts), and before any filter: a short tab has no filter bar.
  // A count beside a filter counts what the filters would show: the pills and the tabs say the number of rows the list holds under
  // the person, project and state chosen (a state belongs to its own tab, so the other tab leaves it out).
  const tabCount = (choice: SideChoice) =>
    tab === "done"
      ? (finished.data?.actions ?? []).filter((a) => onSide(a.side, choice, a.views, !!a.project_name)).length
      : tab === "actions"
        ? actionsShown(
            (items.data?.actions ?? []).filter((a) => onSide(a.side, choice, a.views, !!a.project_name)),
            filters,
          ).length
        : questionsShown(
            (items.data?.questions ?? []).filter((q) => onSide(q.side, choice, q.views, (q.projects ?? []).length > 0)),
            filters,
          ).length;
  // The sides the open tab's rows are on, before any side is chosen: the side choice can change the list only with two or more.
  const sidesHeld = new Set(
    (tab === "done" ? (finished.data?.actions ?? []) : tab === "actions" ? (items.data?.actions ?? []) : (items.data?.questions ?? [])).map((r) => r.side).filter(Boolean),
  ).size;
  // A tab's count is the number of rows the tab holds under the filters chosen (a state belongs to its own tab, so the other tab
  // leaves it out). What waits on the person is a named pair of its own: the menu's badge is its sum, and the line under the title
  // says it after the rows.
  const mine = workCounts(actions, questions);
  const tabNumbers = {
    actions: actionsShown(actions, tab === "actions" ? filters : { ...filters, state: "" }).length,
    questions: questionsShown(questions, tab === "questions" ? filters : { ...filters, state: "" }).length,
  };
  const today = todayOn(new Date());
  // The rows of the open tab shown now, the same rows as the list below and the tab's number: the to-dos with no day are a group of
  // their own at the top of the list.
  const narrowed = actionsShown(actions, filters);
  const needDate = narrowed.filter((a) => a.needs_date);
  const shownActions = narrowed.filter((a) => !a.needs_date);
  const shownQuestions = questionsShown(questions, filters);
  const total = tab === "done" ? 0 : tab === "actions" ? narrowed.length : shownQuestions.length;

  // "11 open: 6 overdue · 1 coming up · 4 need a date": the facts the list can be narrowed by come first, and they add up to the
  // number before them. Then the person's own count, the number the menu's badge is made of.
  const groupCount = (g: string) => groupActions(shownActions, today).find((x) => x.group === g)?.rows.length ?? 0;
  const parts =
    tab === "actions"
      ? [
          groupCount("overdue") > 0 && t("open.subtitle.overdue", { n: groupCount("overdue") }),
          groupCount("today") > 0 && t("open.subtitle.today", { n: groupCount("today") }),
          groupCount("coming") > 0 && tn("open.subtitle.coming", groupCount("coming")),
          groupCount("waiting") > 0 && t("open.subtitle.waiting", { n: groupCount("waiting") }),
          needDate.length > 0 && tn("open.subtitle.needs_date", needDate.length),
        ].filter((x): x is string => !!x)
      : [];
  const yours = ` · ${tn("open.subtitle.need", mine.yours)}`;
  const askedText = mine.asked > 0 ? ` · ${tn("open.subtitle.asked", mine.asked)}` : "";
  const subtitle =
    total === 0 ? undefined : (
      <>
        <strong>{tn("open.subtitle", total)}</strong>
        {parts.length > 0 && <span data-open-parts="">{`: ${parts.join(" · ")}`}</span>}
        {yours && <span data-need-count="">{yours}</span>}
        {askedText && <span data-asked-count="">{askedText}</span>}
      </>
    );

  const projectName = (id: string) => projects.data?.find((p) => p.id === id)?.name ?? actions.find((a) => a.project === id)?.project_name ?? id;
  const projectChoices = [...new Set(tab === "actions" ? actions.filter((a) => !a.side_name).map((a) => a.project).filter((p): p is string => !!p) : questions.flatMap((q) => q.projects ?? []))]
    .map((id) => ({ id, name: projectName(id) }))
    .sort((a, b) => a.name.localeCompare(b.name));
  const personChoices = [
    ...new Map((tab === "actions" ? actions.flatMap((a) => a.owners.map((o) => [o.person, o.name] as const)) : questions.map((q) => [q.to, q.to_name] as const))).entries(),
  ]
    .map(([id, name]) => ({ id, name }))
    .sort((a, b) => a.name.localeCompare(b.name));
  // With no side beside Personal the projects are the areas of the person's life, and a to-do with no owner is their own,
  // so neither "Project" nor "No owner" is offered to narrow by.
  const { justMe } = useSides();
  const states: readonly string[] = tab === "actions" ? ACTION_STATES.filter((s) => !(justMe && s === "no_owner")) : QUESTION_STATES;
  // A filter is drawn when it can change the list: the rows differ in what it narrows by, or it is on, so it can be cleared (in
  // place of a row count on To-dos). State offers the states the rows are in.
  const rowStates = new Set((tab === "actions" ? actions.map((a) => a.state) : questions.map((q) => q.state)) as string[]);
  const stateChoices = states.filter((s) => rowStates.has(s) || s === filters.state);
  const loaded = !items.isPending && !items.isError && actions.length + questions.length > 0 && tab !== "done";
  const showWho = loaded && filterCanChange(personChoices.length, filters.person !== "");
  const showState = loaded && filterCanChange(rowStates.size, filters.state !== "") && stateChoices.length > 0;
  const showProject = loaded && filterCanChange(projectChoices.length, filters.project !== "");
  const showSide = side.offered && filterCanChange(sidesHeld, side.picked !== "all");
  const narrowedBy = [filters.person, filters.state, filters.project].filter(Boolean).length + (side.picked !== "all" ? 1 : 0);

  // The to-dos that need a date are a group of their own at the top of the to-dos, and not in the list below it.
  const shown = tab === "actions" ? shownActions.length : shownQuestions.length;
  const set = (patch: Partial<Filters>) => {
    setSettled(new Map());
    setFilters((now) => ({ ...now, ...patch }));
  };
  const choose = (next: Tab) => {
    setTab(next);
    set({ state: "" });
  };
  // A to-do is shown done the moment its mark is pressed, before the save answers: its id waits here until the list stops holding it.
  const [pressed, setPressed] = useState<Set<string>>(new Set());
  const gone = (a: OpenAction) => setSettled((now) => new Map(now).set(a.id, a));
  const pressedNow = (a: OpenAction) => {
    gone(a);
    setPressed((now) => new Set(now).add(a.id));
  };
  const undone = (id: string) => {
    setSettled((now) => {
      const next = new Map(now);
      next.delete(id);
      return next;
    });
    setPressed((now) => {
      const next = new Set(now);
      next.delete(id);
      return next;
    });
  };
  const listed = actions.map((a) => a.id).join("\u0000");
  useEffect(() => {
    const held = new Set(listed.split("\u0000"));
    setPressed((now) => (now.size === 0 || [...now].every((id) => held.has(id)) ? now : new Set([...now].filter((id) => held.has(id)))));
  }, [listed]);
  const stillOpen = new Set(actions.filter((a) => !pressed.has(a.id)).map((a) => a.id));
  const ticked = [...settled.values()].filter((a) => !stillOpen.has(a.id) && actionsShown([a], filters).length > 0);

  // One cap for every section: with more to-dos than the setting names, each section shows the same smaller number, each with its own
  // "Show N more"; a list that fits is not cut.
  const sections = groupActions([...shownActions.filter((a) => !pressed.has(a.id)), ...ticked], today);
  const rowsShown = items.data?.rows_shown ?? 15;
  const sectionCap = sections.reduce((n, g) => n + g.rows.length, 0) > rowsShown ? Math.max(3, Math.floor(rowsShown / 3)) : rowsShown;
  // The list | detail choice (design 7.13): from 1024px the first to-do is chosen as the list opens and its page shows beside the
  // list (where the pane has room); below that a row opens the to-do's own page. Questions have no page of their own to show, so that tab stays one column.
  const beside = useMediaQuery("(min-width: 1024px)");
  // Whether the pane would fit beside the list (as ListDetail measures it): only then is the first to-do chosen as the list opens. Where it
  // would overlay the list, nothing is chosen until the person chooses a row.
  const [room, setRoom] = useState(false);
  const doneRows = (finished.data?.actions ?? []).filter((a) => onSide(a.side, side.picked, a.views, !!a.project_name));
  const tickedIds = new Set(ticked.map((a) => a.id));
  const keys = tab === "actions" ? sections.flatMap((g) => g.rows).filter((a) => !tickedIds.has(a.id)).map((a) => a.id) : tab === "done" ? doneRows.map((a) => a.id) : [];
  const choice = useListChoice({ keys, beside, wait: !room, reset: `${tab}|${filters.person}|${filters.state}|${filters.project}|${side.picked}` });
  const chosenText = [...actions, ...(finished.data?.actions ?? [])].find((a) => a.id === choice.chosen)?.text;
  const rowChoice = beside ? choice : undefined;
  return (
    <section className="panel-section" aria-labelledby="open-title" data-open-items="">
      <ListDetail
        title={chosenText ? plainTitle(chosenText) : ""}
        titleHref={choice.chosen ? viewHref(recordView("action", choice.chosen)) : undefined}
        onClose={choice.close}
        fit={TODOS_FIT}
        onRoom={setRoom}
        detail={choice.chosen && chosenText ? <RecordPage key={choice.chosen} kind="action" id={choice.chosen} embedded onBack={choice.close} /> : null}
      >
      <div className={styles.page}>
      <PageHeader
        id="open-title"
        title={t("open.title")}
        subtitle={subtitle}
        reserveSubtitle={items.isPending}
        tabs={
          <TabStrip
            label={t("open.tabs")}
            value={tab}
            onChange={choose}
            options={[
              { value: "actions", label: t("open.tab.actions"), count: items.data === undefined ? undefined : tabNumbers.actions },
              { value: "questions", label: t("open.tab.questions"), count: items.data === undefined ? undefined : tabNumbers.questions },
              // A count of finished things is not a need, so this tab has none.
              { value: "done", label: t("open.tab.done") },
            ]}
          />
        }
        filterSheet={{ shown: showWho || showState || showProject || showSide, active: narrowedBy }}
        filters={
          showWho || showState || showProject || showSide ? (
            <>
              {showWho && <Choice id={`${ids}-person`} label={t("open.filter.person")} value={filters.person} onChange={(v) => set({ person: v })} none={t("person.everyone")} options={personChoices.map((p) => [p.id, p.name])} />}
              {showState && (
                <FilterChip
                  label={t("open.filter.state")}
                  value={filters.state}
                  onChange={(v) => set({ state: v })}
                  options={[["", t("open.filter.any_state")], ...stateChoices.map((s) => [s, t(`open.${tab === "actions" ? "state" : "qstate"}.${s}`)] as const)]}
                />
              )}
              {showProject && <Choice id={`${ids}-project`} label={t(justMe ? "open.filter.area" : "open.filter.project")} value={filters.project} onChange={(v) => set({ project: v })} none={t(justMe ? "open.filter.all_areas" : "open.filter.all_projects")} options={projectChoices.map((p) => [p.id, p.name])} />}
              <SideFilter counts={tabCount} canChange={sidesHeld >= 2} />
              {narrowedBy > 0 && (
                <Button variant="quiet" size="sm" data-clear-filters="" onClick={() => { setFilters(NO_FILTERS); side.set("all"); }}>
                  {t("open.filter.clear")}
                </Button>
              )}
            </>
          ) : undefined
        }
      />
      {addTodo.form}
      <div className={styles.column} data-todo-column="">
      {tab === "done" ? (
        <ListState query={finished} failed={t("open.done.load_failed")} row={{ action: "menu", framed: true }}>
          {(data) => <DoneList rows={data.actions} days={data.days} choice={rowChoice} />}
        </ListState>
      ) : (
      <ListState query={items} failed={t("open.load_failed")} row={{ action: "menu", framed: true }}>
        {() =>
          actions.length + questions.length === 0 ? (
            side.choice !== "all" ? (
              <FilteredEmpty card text={t("sides.empty.open", { side: side.named })} label={t("sides.empty.show_all")} onClear={() => side.set("all")} />
            ) : (
              // Nothing open: a brand moment, with the way to add the next thing (its one outlined action) and the way to see what was finished.
              <EmptyState
                card
                title={t("open.empty.title")}
                text={t("open.empty")}
                action={{ label: t("addtodo.open"), onClick: () => addTodo.open(), primary: true }}
                quietAction={{ label: t("open.empty.finished"), onClick: () => choose("done") }}
              />
            )
          ) : (
            <>
              {shown + (tab === "actions" ? needDate.length : 0) === 0 ? (
                // A tab with nothing in it says so; "nothing matches" is only for rows the filters hid.
                (tab === "actions" ? actions.length : questions.length) === 0 ? (
                  <EmptyState text={t(`open.empty.${tab}`)} />
                ) : (
                  <FilteredEmpty card text={filters.state ? t(`open.none.${tab}.${filters.state}`) : t("open.none_match")} onClear={() => setFilters(NO_FILTERS)} />
                )
              ) : tab === "actions" ? (
                // With no row to list (every to-do waits for a date) what is left is the add row and one line, which are not a list.
                <RowList aria-label={shownActions.length > 0 ? t("open.list.actions") : undefined} role={shownActions.length > 0 ? undefined : "presentation"}>
                  <InlineAddTodo onDetails={(words, when) => addTodo.open(words, undefined, undefined, when)} />
                  {sections.map(({ group, rows }) => (
                    <TodoGroupRows key={group} group={group} rows={rows} limit={sectionCap} inlineOrigin={narrow} ticked={tickedIds} choice={rowChoice} onDone={gone} onPressed={pressedNow} onUndone={undone} />
                  ))}
                  <NeedsADateLine rows={needDate} />
                </RowList>
              ) : shown === 0 ? null : (
                <RowList aria-label={t("open.list.questions")}>
                  {shownQuestions.map((q) => (
                    <QuestionRow key={q.id} question={q} inlineOrigin={narrow} />
                  ))}
                </RowList>
              )}
            </>
          )
        }
      </ListState>
      )}
      </div>
      </div>
      </ListDetail>
    </section>
  );
}

/** One group of the to-dos: its label with the count, then its rows (the first `limit`, then "Show N more"; a row just ticked
 * stays where it was). The label is a part of the list, not a row of it. */
function TodoGroupRows(props: { group: string; rows: OpenAction[]; limit: number; inlineOrigin: boolean; ticked: Set<string>; choice?: ListChoice; onDone: (a: OpenAction) => void; onPressed: (a: OpenAction) => void; onUndone: (id: string) => void }) {
  const { t, tn } = useWords();
  const id = useId();
  const [all, setAll] = useState(false);
  const open = props.rows.filter((a) => !props.ticked.has(a.id));
  // Past the limit the rest wait behind one button, except a row just ticked, which keeps its place and its Undo.
  const hidden = all ? new Set<string>() : new Set(open.slice(props.limit).map((a) => a.id));
  const rows = props.rows.filter((a) => !hidden.has(a.id));
  return (
    <>
      <li className={styles.groupItem}>
        <GroupLabel id={id} as="h3" count={open.length} tone={props.group === "overdue" ? "danger" : "plain"} data-todo-group={props.group}>
          {t(`open.group.${props.group}`)}
        </GroupLabel>
      </li>
      {rows.map((a) =>
        props.ticked.has(a.id) ? (
          <DoneRow key={a.id} action={a} onUndone={props.onUndone} />
        ) : (
          <ActionRow key={a.id} action={a} inlineOrigin={props.inlineOrigin} choice={props.choice} onDone={props.onDone} onPressed={props.onPressed} onUndone={props.onUndone} />
        ),
      )}
      {hidden.size > 0 && (
        <li className={styles.showMore}>
          <Button variant="quiet" size="sm" data-show-more={props.group} onClick={() => setAll(true)}>
            {tn("open.show_more_in", hidden.size, { group: t(`open.group.${props.group}`).toLowerCase() })}
          </Button>
        </li>
      )}
    </>
  );
}

function Choice(props: { id: string; label: string; value: string; onChange: (v: string) => void; none: string; options: Array<[string, string]> }) {
  // A filter with fewer than two real choices besides "all" changes nothing; one already set stays so the person can clear it.
  if (props.options.length < 2 && !props.value) return null;
  return <FilterChip label={props.label} value={props.value} onChange={props.onChange} options={[["", props.none], ...props.options]} />;
}

type ActionRowProps = { action: OpenAction; inlineOrigin: boolean; "data-needs-row"?: string; /** The row's one primary, in place of the one its state gives (the date picker of a to-do that needs a date). */ primary?: ReactNode; choice?: ListChoice; onDone?: (a: OpenAction) => void; onPressed?: (a: OpenAction) => void; onUndone?: (id: string) => void };

/** One to-do's row: what is done to it goes one at a time, so a second press while the first is out is ignored. */
export function ActionRow(props: ActionRowProps) {
  return (
    <ActScope.Provider value={`todo:${props.action.id}`}>
      <ActionRowBody {...props} />
    </ActScope.Provider>
  );
}

function ActionRowBody(props: ActionRowProps) {
  const { t, tn } = useWords();
  const place = usePlaceText();
  const act = useAct();
  const noted = useNoted();
  const a = props.action;
  const ref = useRef<HTMLLIElement & HTMLDivElement>(null);
  const focus = () => ref.current?.focus();
  const [noting, setNoting] = useOneEditor(`${a.id}:note`);
  const [asking, setAsking] = useOneEditor(`${a.id}:owner`);
  const hold = useHold(a);
  const drop = useDropAction(a, focus);
  const hand = useHandToAssistant(a, focus);
  const notMine = useNotMineToTrack({ kind: "action", id: a.id }, a.origin);
  const edit = useEditAction(a, focus);
  const remind = useRemindMe(a.id, a.remind_at, focus);
  const stopRepeat = useStopRepeat(a);
  const said = useSaid();
  // The row reads done at once; a save that did not happen puts it back, with the failure named beside it.
  const done = async (note?: string) => {
    props.onPressed?.(a);
    const result = await save(note);
    if (result === undefined) props.onUndone?.(a.id);
    return result;
  };
  const save = (note?: string) =>
    act(
      async () => {
        const result = await api.actionStatus(a.id, "done", note);
        props.onDone?.(a);
        return result;
      },
      (result) => ({ message: noted(t("toast.action_done_named", { text: plainTitle(a.text) }), result.request), undo: () => api.actionStatus(a.id, "open"), undoInRow: true }),
      undefined,
      { fail: { id: a.id, what: plainTitle(a.text) } },
    );
  const twin = a.duplicate;
  const merge: MenuAction | null = twin
    ? {
        id: "merge",
        label: t("open.merge", { text: twin.text }),
        run: () =>
          void act(
            () => api.mergeActions(a.id, { other: twin.id, read_version: a.version, other_version: twin.version }),
            (result) => ({ message: t("open.merged", { text: twin.text }), undo: () => api.undo(result.changeset) }),
          ),
      }
    : null;
  const unowned = a.state === "no_owner";
  useRowKeys(ref, { primary: unowned ? () => setAsking(true) : () => void done(), toggle: props.choice ? () => props.choice?.enter(a.id) : undefined });
  // Escape closes the editor that is open on this row and hands the cursor back to it.
  const escape = (e: React.KeyboardEvent<HTMLElement>) => {
    if (e.key === "Escape" && closeEditorOf(a.id)) {
      e.stopPropagation();
      focus();
      return;
    }
    props.choice?.rowProps(a.id).onKeyDown(e);
  };
  // Beside the list the title shows the to-do in the pane (its link still goes to the page for a new tab or a modified click).
  const showHere = (e: React.MouseEvent) => {
    if (!props.choice || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    props.choice.choose(a.id);
  };
  // The menu's sections: what changes the to-do, then when it comes back, then taking it away (in red, last).
  const menu: MenuAction[] = [
    ...(unowned ? [] : [{ id: "note", label: t("note.add"), run: () => setNoting(true) } satisfies MenuAction]),
    edit.entry,
    ...(merge ? [merge] : []),
    ...(unowned || !hand.entry ? [] : [hand.entry]),
    ...notMine.entries,
  ];
  const timing: MenuAction[] = [...(unowned ? [] : [...remind.entries, hold.entry]), ...(stopRepeat ? [stopRepeat] : [])];
  const inViews = useViewLabels(a.views);
  const people = useQuery({ queryKey: ["people"], queryFn: api.people });
  // A to-do waiting on someone else has Nudge when Follow-ups holds a drafted message that lists it; the same draft opens there.
  const followups = useQuery({ queryKey: ["followups"], queryFn: api.followups, enabled: a.needs_you === false && a.state !== "on_hold" });
  const nudgeTo = followups.data?.find((s) => !s.is_pm && s.nudge && !s.nudge.withheld && s.nudge.action_ids.includes(a.id))?.person;
  const nudge = () => {
    if (nudgeTo && !revealOrKeep("nudge", nudgeTo)) window.location.hash = toHash("work/followups");
  };
  const me = people.data?.find((p) => p.is_pm)?.id;
  const slot = useSideSlot()(a.side);
  // The side comes first in the grey line, as a dot and its name, when the person has more than one side and the list isn't
  // narrowed to one (design 7.12).
  const sideFilter = useSideFilter();
  const sideName = sideFilter.offered && sideFilter.picked === "all" && a.side ? (sideFilter.options.find((o) => o.id === a.side)?.name ?? "") : "";
  const today = todayOn(new Date());
  // The owners are named when one of them is somebody else; a to-do that is the person's own doesn't say so on every line.
  const others = a.owners.filter((o) => o.person !== me).map((o) => o.name);
  const dueWords = a.due
    ? a.due_check
      ? t("op.meta.due_check", { date: day(a.due) })
      : a.state === "overdue"
        ? t("open.due", { date: day(a.due) })
        : clockDay(a.due) === today
          ? t("open.due_today")
          : t("open.due", { date: day(a.due) })
    : null;
  const dueMark =
    dueWords && !a.due_check && a.state === "overdue" ? (
      <span key="d" className={styles.dueLate} data-due="late">
        <Icon name="alert" size={16} />
        <NoBreak>{dueWords}</NoBreak>
      </span>
    ) : dueWords && (a.due ? clockDay(a.due) : "") === today && !a.due_check ? (
      <strong key="d" className={styles.dueToday} data-due="today">
        <NoBreak>{dueWords}</NoBreak>
      </strong>
    ) : dueWords ? (
      <NoBreak key="d">{dueWords}</NoBreak>
    ) : null;
  const placeMark = place({ name: a.project_name, side: a.side_name, parent: a.parent_name }) ? (
    <span key="p" className={styles.placeMark}>
      <ProjectTag name={a.project_name} side={a.side_name} parent={a.parent_name} />
    </span>
  ) : null;
  const meta = joinMeta([
    dueMark,
    sideName && slot !== null && (
      <SideMark key={SIDE_PART} side={a.side} />
    ),
    others.length > 0 && others.join(", "),
    a.to_send && (
      <strong key="s" className={styles.toSend} data-to-send="">
        {t("action.to_send")}
      </strong>
    ),
    a.remind_at && t("today.todo.reminder", { when: dateAndTime(a.remind_at) }),
    a.repeat && (
      <span key="r" data-repeat="" title={said(a.repeat)}>
        {t("repeat.mark")}
      </span>
    ),
    placeMark,
    inViews.length > 0 && <ViewTags key="v" views={a.views} />,
    a.followed_up && <span key="f" data-followed-up="">{t("open.followed_up", { date: day(a.followed_up) })}</span>,
    a.on_hold || a.blocker ? <HoldNote key="h" on_hold={a.on_hold} blocker={a.blocker} due={a.due} /> : null,
  ]);
  // The title opens the to-do's own page.
  const title = (
    <NotesTitle notes={a.notes}>
      <a href={viewHref(recordView("action", a.id))} onClick={showHere}>{fullTitle(a.text, a.due)}</a>
    </NotesTitle>
  );
  return (
    <Row
      ref={ref}
      {...props.choice?.rowProps(a.id)}
      data-needs-row={props["data-needs-row"]}
      onKeyDown={escape}
      failedId={a.id}
      clamp={fullTitle(a.text, a.due)}
      phoneClamp
      state={a.state === "overdue" ? "danger" : undefined}
      className={a.state === "overdue" ? styles.overdueRow : undefined}
      lead={
        // Every to-do has its check; on one waiting for an owner the primary is the picker, so the check is not the row's primary.
        <RoundCheck label={t("today.todo.done_named", { text: plainTitle(a.text) })} tip={t("followups.mark_done")} data-key={unowned ? undefined : "primary"} onClick={() => void done()} />
      }
      pill={pillOf(a, t, tn)}
      title={title}
      meta={
        <>
          {meta}
          <OriginLink origin={a.origin} inline={props.inlineOrigin} />
        </>
      }
      primary={
        props.primary ? (
          props.primary
        ) : unowned && a.owner_question ? (
          <Button variant="primary" data-key="primary" aria-expanded={asking} onClick={() => setAsking(!asking)}>
            {t("queue.act.pick_owner")}
          </Button>
        ) : nudgeTo ? (
          <Button variant="primary" data-nudge="" onClick={nudge}>
            {t("open.nudge")}
          </Button>
        ) : undefined
      }
      menu={
        <RowMenu
          label={plainTitle(a.text)}
          actions={menu}
          groups={[
            { id: "timing", entries: timing },
            { id: "remove", entries: [drop.entry] },
          ]}
        />
      }
    >
      {asking && a.owner_question && <AskChooser ask={{ id: a.owner_question, about: "owner", options: [], suggestion: null }} />}
      {noting && (
        <NoteBox
          sends={[{ label: t("followups.mark_done"), run: done }]}
          onClose={() => {
            setNoting(false);
            focus();
          }}
        />
      )}
      {edit.form}
      {hand.form}
      {remind.form}
      {hold.form}
      {drop.form}
      {hand.line}
      <GuessLine action={a} />
      <LearnedLines records={[a.id]} />
    </Row>
  );
}

/** A to-do whose owners were decided by what was learned for its kind of work, not for this item: who, and the day of the
 * correction it came from, with one click to take the guess back (the usual undo toast; nothing to confirm). */
function GuessLine(props: { action: OpenAction }) {
  const { t } = useWords();
  const act = useAct();
  const a = props.action;
  const guess = a.guess;
  if (!guess) return null;
  const who = a.owners.map((o) => o.name).join(", ");
  return (
    <p className="hint" data-guess="">
      {t("open.guess", { who, date: monthDay(guess.learned_on) })}
      {guess.can_take_back && (
        <>
          {" "}
          <Button
            size="sm"
            variant="quiet"
            data-guess-take-back=""
            aria-label={t("open.guess.take_back_named", { text: plainTitle(a.text) })}
            onClick={() =>
              void act(
                () => api.takeBackGuess(a.id),
                (done) => ({ message: t("toast.guess_taken_back"), undo: () => api.undo(done.changeset) }),
              )
            }
          >
            {t("open.guess.take_back")}
          </Button>
        </>
      )}
    </p>
  );
}

/** A to-do just ticked: it stays where it was, struck through, with when it was done and Undo, until the person moves on. */
function DoneRow(props: { action: OpenAction; onUndone: (id: string) => void }) {
  const { t } = useWords();
  const act = useAct();
  const a = props.action;
  const undo = () =>
    void act(
      async () => {
        const result = await api.actionStatus(a.id, "open");
        props.onUndone(a.id);
        return result;
      },
      undefined,
    );
  return (
    <Row
      data-done-row=""
      failedId={a.id}
      lead={<Icon name="check" size={18} />}
      title={<span className={styles.doneTitle}>{plainTitle(a.text)}</span>}
      meta={
        <>
          {t("open.done_just_now")} · <UndoLink onClick={undo} aria-label={t("open.undo_named", { text: a.text })} />
        </>
      }
    />
  );
}

function pillOf(a: OpenAction, t: T, tn: TN): ReactNode {
  switch (a.state) {
    case "stale":
      // The state and its fact are one pill: how long it has gone untouched, never the same thing said twice on the row.
      return <Pill tone="warn">{a.untouched_days != null ? tn("open.untouched", a.untouched_days) : t("open.state.stale")}</Pill>;
    case "no_owner":
      return <Pill tone="warn">{t("open.state.no_owner")}</Pill>;
    case "on_hold":
      return <Pill tone="neutral">{t("open.state.on_hold")}</Pill>;
    default:
      return undefined;
  }
}

function QuestionRow(props: { question: OpenQuestion; inlineOrigin: boolean }) {
  const { t, tn } = useWords();
  const place = usePlaceText();
  const q = props.question;
  const ref = useRef<HTMLLIElement & HTMLDivElement>(null);
  const focus = () => ref.current?.focus();
  const menu = useQuestionMenu(q, { canMarkSent: q.state === "not_sent", onClosed: focus });
  const change = useChangeThis({ kind: q.kind === "decision" ? "decision" : "question", id: q.id }, focus);
  const notMine = useNotMineToTrack({ kind: "question", id: q.id }, q.origin);
  // An answer not judged yet: the question stays here, being read, or waiting to be read with its reason. Only a waiting
  // answer can be changed, in place.
  const unjudged = q.state === "reading" || q.state === "answer_waiting";
  const act = useAct();
  const noted = useNoted();
  const [changing, setChanging] = useState(false);
  const [again, setAgain] = useState("");
  // The step itself is elsewhere: a question to the person is answered on Today, and the reply and the message are in
  // Follow-ups. The row takes the person to it.
  const open = () => {
    if (unjudged) {
      if (q.state === "answer_waiting") setChanging(true);
      return;
    }
    if (q.state === "yours") {
      openOnToday(q.id);
      return;
    }
    if (!revealOrKeep("person", q.to)) window.location.hash = toHash("work/followups");
  };
  useRowKeys(ref, { primary: open });
  const label = {
    yours: "followups.answer_on_today",
    reading: "open.q.change_answer",
    answer_waiting: "open.q.change_answer",
    waiting: "followups.record_reply",
    not_sent: "open.q.to_send",
    later: "open.q.to_send",
  }[q.state];
  const who =
    q.state === "reading"
      ? t("open.q.reading")
      : q.state === "answer_waiting"
        ? (q.answer_why ?? t("open.q.answer_waiting"))
        : q.state === "yours"
      ? t("open.q.on_you")
      : q.state === "waiting"
        ? t("open.q.waiting_on", { name: q.to_name })
        : q.state === "later"
          ? t(q.yours ? "open.q.held_yours" : "open.q.held", { name: q.to_name, date: q.held_until ? monthDay(q.held_until) : "" })
          : t("open.q.not_sent", { name: q.to_name });
  const inViews = useViewLabels(q.views);
  const meta = joinMeta([
    who,
    q.since && t("open.q.since", { date: monthDay(q.since) }),
    q.waiting_days != null && tn("open.q.days", q.waiting_days),
    q.chases > 0 && tn("open.q.chases", q.chases),
    place({ name: q.project_name, side: q.side_name }) && <ProjectTag key="p" name={q.project_name} side={q.side_name} />,
    inViews.length > 0 && <ViewTags key="v" views={q.views} />,
  ]);
  return (
    <Row
      ref={ref}
      pill={q.state === "waiting" || q.state === "yours" ? undefined : <Pill tone={unjudged ? "need" : "neutral"}>{t(`open.qstate.${q.state}`)}</Pill>}
      title={q.title}
      meta={
        <>
          {meta}
          <OriginLink origin={q.origin} inline={props.inlineOrigin} />
        </>
      }
      primary={
        q.state === "reading" ? undefined : (
          <Button variant="primary" data-key="primary" onClick={open}>
            {t(label)}
          </Button>
        )
      }
      menu={unjudged ? undefined : <RowMenu label={q.title} actions={[...menu.entries, change.entry, ...notMine.entries]} />}
    >
      {menu.form}
      {change.form}
      {changing && q.state === "answer_waiting" && (
        <form
          className="answer-form"
          onSubmit={(e) => {
            e.preventDefault();
            void act(
              () => api.answer(q.id, { text: again }),
              (done) => ({ message: noted(t("toast.answered"), done.request) }),
            );
            setChanging(false);
            setAgain("");
          }}
        >
          <label className="hint" htmlFor={`again-${q.id}`}>
            {t("followups.answer_label")}
          </label>
          <textarea id={`again-${q.id}`} className="short" autoFocus value={again} onChange={(e) => setAgain(e.target.value)} />
          <Button variant="primary" type="submit" disabled={!again.trim()}>
            {t("followups.answer")}
          </Button>
          <Button type="button" onClick={() => setChanging(false)}>
            {t("open.q.keep_answer")}
          </Button>
        </form>
      )}
    </Row>
  );
}

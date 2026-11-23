// The Dropped view of Follow-ups (design 7): the questions the person dropped, newest first, each one row saying who it was for,
// when it was dropped and why, with "Ask again" as its one action. Asking again opens the question again, with Undo.
import { useQuery } from "@tanstack/react-query";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { day } from "../lib/dates";
import { plainTitle } from "../lib/title-dates";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Icon } from "../ui/Icon";
import { ListState } from "../ui/ListState";
import { Row } from "../ui/Row";
import { RowList } from "../ui/RowList";

export const droppedQuestionsKey = ["questions", "dropped"] as const;

/** The questions the person dropped, for the Dropped tab and for whether the tab is offered at all. */
export function useDroppedQuestions() {
  return useQuery({ queryKey: droppedQuestionsKey, queryFn: api.droppedQuestions });
}

export function DroppedQuestions() {
  const { t } = useWords();
  const dropped = useDroppedQuestions();
  return (
    <ListState query={dropped} failed={t("followups.dropped.load_failed")} row={{ lead: true }}>
      {(rows) =>
        rows.length === 0 ? (
          <EmptyState text={t("followups.empty_dropped")} />
        ) : (
          <RowList aria-label={t("followups.dropped.list")} data-dropped-list="">
            {rows.map((q) => (
              <DroppedRow key={q.id} question={q} />
            ))}
          </RowList>
        )
      }
    </ListState>
  );
}

function DroppedRow(props: { question: S["DroppedQuestionView"] }) {
  const { t } = useWords();
  const act = useAct();
  const q = props.question;
  const title = plainTitle(q.title);
  const again = () =>
    void act(
      () => api.askQuestionAgain(q.id),
      (done) => ({ message: t("toast.question_asked_again"), undo: () => api.undo(done.changeset) }),
      undefined,
      { fail: { id: q.id, what: title } },
    );
  return (
    <Row
      data-dropped-item=""
      failedId={q.id}
      clamp={title}
      lead={<Icon name="close" size={18} />}
      title={title}
      meta={
        <>
          {t("followups.dropped.to", { name: q.to_name })}
          {q.dropped_at && <> · {t("followups.dropped.when", { day: day(q.dropped_at) })}</>}
          {" · "}
          {q.reason ? t("followups.dropped.why", { reason: q.reason }) : t("followups.dropped.no_reason")}
        </>
      }
      primary={
        <Button variant="secondary" aria-label={t("followups.dropped.ask_again_named", { title })} onClick={again}>
          {t("followups.dropped.ask_again")}
        </Button>
      }
    />
  );
}

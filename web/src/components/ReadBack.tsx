// The read-back of a rule the person stated (design 6.7): four short lines beside Undo, so a misreading shows before it
// matters. What it applies to, what it doesn't change, which rules it overlaps (each linked) and what it would change
// right now, with the items behind the count a click away. A count of none is said in words, never only by a colour.
import { useState } from "react";
import type { S } from "../lib/api";
import { readableTail, useFieldLabel } from "../lib/records";
import { recordView, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { Definition, DefinitionList } from "../ui/DefinitionList";
import styles from "./ReadBack.module.css";

export function ReadBack(props: { back: S["ReadBackView"] }) {
  const { t, tn, has } = useWords();
  const labelOf = useFieldLabel();
  const [open, setOpen] = useState(false);
  const { back } = props;
  const kindWords = (kind: string, label: string) => (has(`record.kind.${kind}`) ? t(`record.kind.${kind}`) : label).toLowerCase();
  const target = (kind: string, label: string, field?: string | null) => [kindWords(kind, label), field ? labelOf(field).toLowerCase() : ""].filter(Boolean).join(" ");
  const task = (name: string) => (has(`task.${name}`) ? t(`task.${name}`) : readableTail(name).toLowerCase());
  const names = (list: Array<{ name: string }>) => list.map((x) => x.name).join(", ");
  const a = back.applies;
  const [targets, filters, projects, except, people, taskKinds] = [a.targets ?? [], a.filter ?? [], a.projects ?? [], a.except ?? [], a.people ?? [], a.task_kinds ?? []];
  const applies = a.everywhere
    ? t("readback.applies.everywhere")
    : [
        targets.map((x) => target(x.kind, x.kind_label, x.field)).join(", "),
        ...filters.map((f) => t("readback.applies.filter", { field: labelOf(f.field).toLowerCase(), value: f.value })),
        projects.length > 0 ? t("readback.applies.projects", { names: names(projects) }) : "",
        except.length > 0 ? t("readback.applies.except", { names: names(except) }) : "",
        people.length > 0 ? t("readback.applies.people", { names: names(people) }) : "",
        taskKinds.length > 0 ? t("readback.applies.task_kinds", { names: taskKinds.map(task).join(", ") }) : "",
      ]
        .filter(Boolean)
        .join(", ");
  const unchanged = (back.unchanged ?? []).map((n) =>
    n.why === "field"
      ? t("readback.unchanged.field", { kind: kindWords(n.kind ?? "", n.kind_label ?? ""), field: labelOf(n.field ?? "").toLowerCase() })
      : n.why === "project"
        ? t("readback.unchanged.project", { name: n.name ?? "" })
        : t("readback.unchanged.task_kind", { name: task(n.name ?? "") }),
  );
  const items = back.items ?? [];
  const overlaps = back.overlaps ?? [];
  const shown = items.length;
  const count = back.count;
  return (
    <section className={styles.back} aria-label={t("readback.label")}>
      <DefinitionList>
        <Definition>
          <dt>{t("readback.applies")}</dt>
          <dd>{applies}</dd>
        </Definition>
        <Definition>
          <dt>{t("readback.unchanged")}</dt>
          <dd>{unchanged.length > 0 ? unchanged.join("; ") : t("readback.unchanged.none")}</dd>
        </Definition>
        <Definition>
          <dt>{t("readback.overlaps")}</dt>
          <dd>
            {overlaps.length === 0 ? (
              t("readback.overlaps.none")
            ) : (
              <ul className={styles.list}>
                {overlaps.map((o) => (
                  <li key={o.id}>
                    <a href={viewHref(recordView("rule", o.id))}>{o.text || o.name}</a>
                  </li>
                ))}
              </ul>
            )}
          </dd>
        </Definition>
        <Definition>
          <dt>{t("readback.would")}</dt>
          <dd>
            {count === null || count === undefined ? (
              t("readback.would.not_counted")
            ) : count === 0 ? (
              <span className={styles.flag}>{t("readback.would.none")}</span>
            ) : (
              <>
                {tn("readback.would.count", count)}
                {shown > 0 && (
                  <>
                    {" "}
                    <button type="button" className="link-button" aria-expanded={open} onClick={() => setOpen(!open)}>
                      {t(open ? "readback.would.hide" : "readback.would.show")}
                    </button>
                  </>
                )}
                {open && (
                  <ul className={styles.items}>
                    {items.map((i) => (
                      <li key={`${i.kind}:${i.id}`}>
                        <a href={viewHref(recordView(i.kind, i.id))}>{i.title}</a>
                      </li>
                    ))}
                    {count > shown && <li>{t("readback.would.more", { n: count - shown })}</li>}
                  </ul>
                )}
              </>
            )}
          </dd>
        </Definition>
      </DefinitionList>
    </section>
  );
}

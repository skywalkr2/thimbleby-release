// Handled for you, Learned today (design 6.22, 7.20): what the assistant started using on its own today, with no OK asked
// for. One line says how many; opened, each thing is one row with what it means and where it was seen, and "That's wrong"
// as its one action, which stops it at once and records a correction. Nothing is drawn when nothing was learned today.
import { useQuery } from "@tanstack/react-query";
import { useId, useRef } from "react";
import { api, type S } from "../lib/api";
import { useKnowledgeActs } from "../lib/knowledge-acts";
import { learnedLine } from "../lib/knowledge";
import { useReadable } from "../lib/readable";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Row } from "../ui/Row";
import styles from "./Knowledge.module.css";

export function HandledLearned() {
  const words = useWords();
  const { t, tn } = words;
  const found = useQuery({
    queryKey: ["knowledge", "learned-today"],
    queryFn: api.learnedToday,
  });
  const acts = useKnowledgeActs();
  const readable = useReadable();
  const id = useId();
  const page = useRef<HTMLDetailsElement>(null);
  const items: S["KnowledgeView"][] = found.data?.items ?? [];
  if (items.length === 0) return null;
  const outside = items.some((i) => i.trust === "untrusted");
  return (
    <details ref={page} className="more-options" data-learned-today="">
      <summary id={`${id}-title`}>
        {tn("handled.learned.count", items.length)}
      </summary>
      <p className="hint">{t("handled.learned.hint")}</p>
      {outside && <p className={styles.quiet}>{t("knowledge.outside")}</p>}
      <ul className={styles.list} aria-label={t("handled.learned.list")}>
        {items.map((item) => {
          const line = learnedLine(
            {
              term: item.term ?? "",
              meaning: item.meaning ?? "",
              text: item.text,
              activated: item.activated ?? null,
              messages: item.messages ?? 0,
            },
            words,
          );
          return (
            <Row
              key={item.id}
              data-learned-today-row={item.id}
              title={readable(line)}
              primary={
                <Button
                  size="sm"
                  data-key="primary"
                  aria-label={t("knowledge.wrong_named", {
                    text: item.term || item.text,
                  })}
                  onClick={() => void acts.wrong(item)}
                >
                  {t("knowledge.wrong")}
                </Button>
              }
            />
          );
        })}
      </ul>
    </details>
  );
}

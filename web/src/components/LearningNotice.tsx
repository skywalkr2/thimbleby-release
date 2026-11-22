// The notice above Today's lines while a read of older mail is under way: the assistant is still learning from it, so its
// suggestions get better over the next days. It is a notice and not a line (Today's lines are things the person does), it
// goes by itself when the reading ends, and the person can dismiss it for the day.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { todayOn } from "../lib/dates";
import { useWords } from "../lib/wording";
import { Banner } from "../ui/Banner";
import { Button } from "../ui/Button";

const KEY = "learning-notice-dismissed";

function dismissedToday(): boolean {
  try {
    return window.localStorage.getItem(KEY) === todayOn(new Date());
  } catch {
    return false;
  }
}

export function LearningNotice() {
  const { t, tn } = useWords();
  const found = useQuery({ queryKey: ["today", "learning"], queryFn: api.todayLearning });
  const [hidden, setHidden] = useState(dismissedToday);
  if (!found.data?.active || hidden) return null;
  const { read, of } = found.data;
    const dismiss = () => {
    try {
      window.localStorage.setItem(KEY, todayOn(new Date()));
    } catch {
      /* the notice just stays hidden for this visit */
    }
    setHidden(true);
  };
  return (
    <Banner
      role="status"
      tone="info"
      data-learning-notice=""
      action={
        <Button size="sm" variant="quiet" onClick={dismiss}>
          {t("today.learning.dismiss")}
        </Button>
      }
    >
      <strong>{t("today.learning.title", { app: t("app.name") })} </strong>
      {t("today.learning.text")}
      {of > 0 && <> {tn("today.learning.progress", read, { read, total: of })}</>}
    </Banner>
  );
}

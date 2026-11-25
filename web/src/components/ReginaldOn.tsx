// The first go (design 7.8): the assistant's first reading waits for it, and it is given where the AI account is added, in
// setup's AI step and in the AI accounts screen for a person who left that step out. It says what turning the assistant on
// does first and what a typical day of that costs, and one button gives the go. Nothing is read by the AI before it.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, ApiError } from "../lib/api";
import { problemText } from "../lib/problem";
import { useSortingCostWords } from "../lib/sorting-cost";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { FormBlock } from "../ui/FormBlock";
import { Icon } from "../ui/Icon";

/** `hideWhenOn`: nothing is drawn once the go was given (the AI accounts screen asks only a person who hasn't given it). */
export function ReginaldOn(props: { hideWhenOn?: boolean } = {}) {
  const { t } = useWords();
  const client = useQueryClient();
  const setup = useQuery({ queryKey: ["setup"], queryFn: api.setup });
  const cost = useSortingCostWords();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  if (!setup.data) return null;
  const given = setup.data.first_go_given;
  if (given && props.hideWhenOn) return null;
  const turnOn = async () => {
    setBusy(true);
    setProblem("");
    try {
      await api.firstGo();
      await client.invalidateQueries({ queryKey: ["setup"] });
      await client.invalidateQueries({ queryKey: ["today"] });
    } catch (err) {
      setProblem(err instanceof ApiError && err.detail ? err.detail : problemText(err, t));
    }
    setBusy(false);
  };
  return (
    <FormBlock as="section" aria-labelledby="reginald-on-title" data-reginald-on={given ? "on" : "off"}>
      <h3 id="reginald-on-title">{t("reginald_on.title")}</h3>
      {given ? (
        <p className="what">
          <Icon name="check" size={16} /> {t("reginald_on.on")}
        </p>
      ) : (
        <>
          {/* It reads mail and calendar only once one is connected; before that it says what happens when one is. */}
          <p>{t(setup.data.steps.some((s) => s.id === "mail" && s.done) ? "reginald_on.what" : "reginald_on.what_later")}</p>
          {cost && (
            <p className="hint" data-sorting-cost="">
              {cost}
            </p>
          )}
          <p className="hint">{t("reginald_on.nothing")}</p>
          <div>
            <Button variant="primary" loading={busy} onClick={() => void turnOn()}>
              {t("reginald_on.button")}
            </Button>
          </div>
        </>
      )}
      {problem && (
        <p className="problem-note" role="alert">
          {problem}
        </p>
      )}
    </FormBlock>
  );
}

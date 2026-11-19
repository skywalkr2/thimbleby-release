// The reading check of one account (design 6.32, 7.9): a short, paced read of its newest messages through the account's gate,
// then what was sent, refused and waited and the pace the gate settled on, with the same as one line to copy. Nothing is kept and
// nothing is recorded as a read, so the drawer only reports; the one primary action is the copy.
import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { copyPlain } from "../lib/copy";
import { checkLines, type Check } from "../lib/readingCheck";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { Drawer } from "../ui/Drawer";

export function ReadingCheck(props: { sourceId: string; account: string; onClose: () => void }) {
  const { t, tn } = useWords();
  const [check, setCheck] = useState<Check | null>(null);
  const [failed, setFailed] = useState(false);
  const [round, setRound] = useState(0);
  const [copied, setCopied] = useState<"" | "done" | "blocked">("");
  const line = useRef<HTMLElement>(null);
  useEffect(() => {
    let current = true;
    setCheck(null);
    setFailed(false);
    setCopied("");
    api.checkReading(props.sourceId).then(
      (found) => current && setCheck(found),
      () => current && setFailed(true),
    );
    return () => {
      current = false;
    };
  }, [props.sourceId, round]);
  const copy = async () => {
    if (!check) return;
    const result = await copyPlain(check.log_line);
    if (result === "blocked") {
      // The browser refused: the line is selected for a copy by hand.
      const range = document.createRange();
      if (line.current) range.selectNodeContents(line.current);
      window.getSelection()?.removeAllRanges();
      window.getSelection()?.addRange(range);
    }
    setCopied(result === "blocked" ? "blocked" : "done");
  };
  return (
    <Drawer
      open
      title={t("reading_check.title", { account: props.account })}
      onClose={props.onClose}
      footer={
        <>
          <Button variant="quiet" onClick={props.onClose}>
            {t("reading_check.close")}
          </Button>
          <Button variant="quiet" disabled={!check && !failed} onClick={() => setRound((n) => n + 1)}>
            {t("reading_check.again")}
          </Button>
          <Button variant="primary" disabled={!check} onClick={() => void copy()}>
            {t("reading_check.copy")}
          </Button>
        </>
      }
    >
      <div data-reading-check="" aria-live="polite">
        {failed ? (
          <p role="alert">{t("reading_check.failed")}</p>
        ) : !check ? (
          <p role="status">{t("reading_check.running")}</p>
        ) : (
          <>
            <ul data-reading-check-lines="">
              {checkLines(check, t, tn).map((words, i) => (
                <li key={i}>{words}</li>
              ))}
            </ul>
            <p>
              <code ref={line} data-reading-check-line="">
                {check.log_line}
              </code>
            </p>
            {copied && (
              <p className="hint" role="status">
                {t(copied === "done" ? "reading_check.copied" : "reading_check.copy_blocked")}
              </p>
            )}
          </>
        )}
      </div>
    </Drawer>
  );
}

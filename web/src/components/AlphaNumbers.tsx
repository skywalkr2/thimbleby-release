// Your alpha numbers (design 7, Help; 6.32): the five numbers of the first week, worked out on this computer from the person's own
// work. They are only shown here and kept nowhere else. "Share these with the makers" hands the same lines to Report a problem,
// where the person sees exactly what would go and presses Send; nothing is sent from here.
import { useQuery } from "@tanstack/react-query";
import { useId } from "react";
import { Heading } from "react-aria-components";
import { api } from "../lib/api";
import { useAlphaLines } from "../lib/alpha-lines";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { DialogFooter, ModalPanel } from "./ModalPanel";

export function AlphaNumbers(props: { onClose: () => void; /** Absent where no report address is set, so there is nowhere to share. */ onShare?: (words: string) => void }) {
  const { t } = useWords();
  const { range, lines, shared } = useAlphaLines();
  const titleId = useId();
  const found = useQuery({ queryKey: ["alpha-measures"], queryFn: () => api.alphaMeasures(), gcTime: 0 });
  const numbers = found.data;
  const has = numbers !== undefined && numbers.days_so_far > 0;
  return (
    <ModalPanel titleId={titleId} onClose={props.onClose}>
      <Heading slot="title" id={titleId}>
        {t("alpha.title")}
      </Heading>
      <p className="hint">{t("alpha.kept")}</p>
      {found.isError && (
        <p className="problem-note" role="alert">
          {t("alpha.failed")}
        </p>
      )}
      {found.isPending && <p role="status">{t("alpha.loading")}</p>}
      {numbers && !has && <p>{t("alpha.empty")}</p>}
      {numbers && has && (
        <>
          <p>{range(numbers)}</p>
          <ul>
            {lines(numbers).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </>
      )}
      <DialogFooter>
        <Button variant="quiet" onClick={props.onClose}>
          {t("action.close")}
        </Button>
        {props.onShare && (
          <Button variant="primary" disabled={!has} onClick={() => numbers && props.onShare?.(shared(numbers))}>
            {t("alpha.share")}
          </Button>
        )}
      </DialogFooter>
    </ModalPanel>
  );
}

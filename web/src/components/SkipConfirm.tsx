// Leaving a setup step out (design 7.8): a confirmation in plain words of what that gives up and how the steps after it
// change. Nothing is left out until it is confirmed; the safe answer is the one the cursor starts on.
import { useId } from "react";
import { Heading } from "react-aria-components";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { DialogFooter, ModalPanel } from "./ModalPanel";

export function SkipConfirm(props: { step: string; busy?: boolean; onCancel: () => void; onConfirm: () => void; confirmLabel?: string; cancelLabel?: string }) {
  const { t } = useWords();
  const titleId = useId();
  return (
    <ModalPanel titleId={titleId} onClose={props.onCancel}>
      <Heading slot="title" id={titleId}>
        {t(`walkthrough.skip.${props.step}.title`)}
      </Heading>
      <p data-skip-gives-up="">{t(`walkthrough.skip.${props.step}.gives_up`)}</p>
      <p className="hint" data-skip-next="">
        {t(`walkthrough.skip.${props.step}.next`)}
      </p>
      <DialogFooter>
        <Button autoFocus onClick={props.onCancel}>
          {props.cancelLabel ?? t("walkthrough.skip.cancel")}
        </Button>
        <Button variant="primary" loading={props.busy} onClick={props.onConfirm}>
          {props.confirmLabel ?? t("walkthrough.skip.confirm")}
        </Button>
      </DialogFooter>
    </ModalPanel>
  );
}

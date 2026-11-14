// Forgetting a person (design 5.2, 7.14, 12.4): the person's page menu offers it, and it can't be taken back, so it asks first:
// one dialog that names the person and says what goes and what stays, the cursor on Cancel. The
// answer is a toast with no Undo. A refusal says why in words and changes nothing.
import { useId, useState, type ReactNode } from "react";
import { Heading } from "react-aria-components";
import { api, type S } from "../lib/api";
import { useAct } from "../lib/act";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { DialogFooter, ModalPanel } from "./ModalPanel";

export function useForgetPerson(person: { id: string; name: string; version: number | undefined }): { open: () => void; dialog: ReactNode } {
  const { t } = useWords();
  const act = useAct();
  const titleId = useId();
  const [asking, setAsking] = useState(false);
  const { name } = person;

  const forget = async () => {
    setAsking(false);
    if (person.version === undefined) return;
    await act(
      () => api.forgetPerson(person.id, { read_version: person.version ?? 1 }),
      (done: S["PersonForgotten"]) =>
        done.refused || !done.changeset
          ? { message: t(`person.forget.refused.${done.refused ?? "changed"}`, { name }), tone: "warn" as const }
          : { message: t("person.forget.done", { name }) },
    );
  };

  const dialog = asking ? (
    <ModalPanel titleId={titleId} onClose={() => setAsking(false)}>
      <Heading slot="title" id={titleId} level={2}>
        {t("person.forget.title", { name })}
      </Heading>
      <p>{t("person.forget.body")}</p>
      <p>{t("person.forget.reach")}</p>
      <p className="hint">{t("person.forget.final")}</p>
      <DialogFooter>
        <Button autoFocus onClick={() => setAsking(false)}>
          {t("action.cancel")}
        </Button>
        <Button variant="danger" onClick={() => void forget()}>
          {t("person.forget.go")}
        </Button>
      </DialogFooter>
    </ModalPanel>
  ) : null;
  return { open: () => setAsking(true), dialog };
}

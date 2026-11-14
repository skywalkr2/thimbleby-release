// Today's last group, "Finish setting up" (design 7.7): while first-run setup is unfinished it says how far along it is in its
// header ("2 of 6 done"), with a button that opens the setup guide at the next step; the gaps in setup are its rows. It is not
// counted among the things that need the person. Hiding it is remembered in this browser only.
import { useState, type ReactNode } from "react";
import { useNextSetupStep } from "../lib/setup-next";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import { IconButton } from "../ui/IconButton";
import { MenuButton } from "../ui/MenuButton";
import { PaneBox } from "../ui/Panel";
import { QueueGroup } from "../components/QueueGroup";
import { PlainRows } from "../ui/rowContext";
import styles from "./SetupLine.module.css";

const KEY = "start-here-hidden";

function hidden(workspace: string): boolean {
  try {
    return window.localStorage.getItem(`${KEY}:${workspace}`) === "1";
  } catch {
    return false;
  }
}

function remember(workspace: string) {
  try {
    window.localStorage.setItem(`${KEY}:${workspace}`, "1");
  } catch {
    // Storage can be blocked; the line then comes back next time, which is harmless.
  }
}

/** The group: its header carries how far setup is and the button to continue it; `children` are the gaps in setup, one row each.
 * It is left out when nothing is in it: no gap, and setup finished or hidden. */
export function SetupGroup(props: { workspace: string; onOpenGuide: (step: string) => void; gaps: number; /** Drawn as a card of its own (under the list's card), not as a group of a list. */ card?: boolean; children?: ReactNode }) {
  const { t } = useWords();
  const [gone, setGone] = useState(() => hidden(props.workspace));
  // The count is worked out from the steps the server serves, the ones that count: done is done, never skipped or still to do.
  // The group stays while any of them is not done, a skipped one included, so what was passed by is one click away.
  const next = useNextSetupStep();
  const shown = !gone && !!next;
  if (!shown && props.gaps === 0) return null;
  const { done: finished, total } = next ?? { done: 0, total: 0, label: "", id: "" };
  const group = (
    <QueueGroup
      id="queue-group-setup"
      title={t("queue.group.setup")}
      meta={shown ? t("setup_line.count", { done: finished, total }) : undefined}
      actions={
        shown && next ? (
          <>
            <Button size="sm" onClick={() => props.onOpenGuide(next.id)}>
              {t("setup_line.continue")}
            </Button>
            <MenuButton
              groups={[
                {
                  id: "setup",
                  entries: [
                    {
                      id: "hide",
                      label: t("setup_line.hide"),
                      run: () => {
                        remember(props.workspace);
                        setGone(true);
                      },
                    },
                  ],
                },
              ]}
              trigger={<IconButton icon="more" size="sm" label={t("menu.more", { what: t("setup_line.what") })} tooltip={false} />}
            />
          </>
        ) : undefined
      }
    >
      <PlainRows.Provider value={true}>{props.children}</PlainRows.Provider>
    </QueueGroup>
  );
  return props.card ? (
    <div data-setup-card="">
      <PaneBox className={styles.setupCard}>{group}</PaneBox>
    </div>
  ) : (
    group
  );
}

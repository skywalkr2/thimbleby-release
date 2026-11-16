// Settings, Advanced: the card for removing the installed app from a Mac, which has no uninstaller. It says where the work
// stays and offers the two things a person needs: show the folder, and quit the app showing it in Finder, ready to drag to the
// Bin. It shows only for the installed Mac app; anywhere else the server says it is not available and nothing is drawn.
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { useWords } from "../lib/wording";
import { Button } from "../ui/Button";
import styles from "./RemovingTheApp.module.css";

export function RemovingTheApp() {
  const { t } = useWords();
  const card = useQuery({ queryKey: ["removal-card"], queryFn: api.removalCard, staleTime: Infinity });
  const [failed, setFailed] = useState(false);
  if (!card.data?.available) return null;
  const app = t("app.name");
  const run = (call: () => Promise<void>) => async () => {
    setFailed(false);
    try {
      await call();
    } catch {
      setFailed(true);
    }
  };
  return (
    <section className="panel-section removing-the-app" aria-labelledby="removal-title" data-removal="">
      <h3 id="removal-title">{t("removal.title", { app })}</h3>
      <p className="hint">{t("removal.text", { app, folder: card.data.folder })}</p>
      <div className={styles.actions}>
        <Button type="button" onClick={run(api.removalShowApp)}>
          {t("removal.quit_show")}
        </Button>
        <Button type="button" onClick={run(api.removalOpenFolder)}>
          {t("removal.open_folder")}
        </Button>
      </div>
      <div role="status">{failed && <p className="problem-note">{t("removal.failed", { app })}</p>}</div>
    </section>
  );
}

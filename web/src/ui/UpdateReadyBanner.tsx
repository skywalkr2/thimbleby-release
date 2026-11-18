// "An update is ready" (design 7.0): the server now serves a newer version than this page was loaded with. A banner in the screen's
// banner slot, with a button that reloads when the person chooses; the page never reloads by itself, so a review or approval
// that is open stays open.
import { useUpdateReady } from "../lib/update-ready";
import { useWords } from "../lib/wording";
import { Banner } from "./Banner";
import { Button } from "./Button";

export function UpdateReadyBanner() {
  const { t } = useWords();
  if (!useUpdateReady()) return null;
  return (
    <Banner
      role="status"
      data-update-ready=""
      action={
        <Button size="sm" icon="refresh" onClick={() => window.location.reload()}>
          {t("state.update_ready.reload")}
        </Button>
      }
    >
      <strong>{t("state.update_ready.title")} </strong>
      {t("state.update_ready.text")}
    </Banner>
  );
}

// The offline bar (design 7.12, "States"): the app cannot reach its server. It is one banner in the screen's banner slot, drawn from
// the one connection state: it says what is safe (everything is saved on this computer), when what is shown was read, that the app
// reconnects by itself, and Try now looks at once. The header's status chip says "Offline", so the bar does not say it again. It
// goes away when the connection is back.
import { useConnection } from "../lib/connection";
import { time } from "../lib/dates";
import { useWords } from "../lib/wording";
import { Banner } from "./Banner";
import { Button } from "./Button";

/** `words` names a screen's own wording for the same state (its title key, and one text key used with or without the time). */
export function OfflineBanner(props: { words?: { title: string; text: string } }) {
  const { t } = useWords();
  const connection = useConnection();
  if (!connection.offline) return null;
  return (
    <Banner
      role="status"
      data-offline-banner=""
      action={
        <Button size="sm" icon="refresh" onClick={connection.retry}>
          {t("state.offline.try")}
        </Button>
      }
    >
      {props.words && <strong>{t(props.words.title)} </strong>}
      {props.words ? t(props.words.text) : connection.since ? t("state.offline.text", { time: time(connection.since) }) : t("state.offline.text_unknown")}
    </Banner>
  );
}

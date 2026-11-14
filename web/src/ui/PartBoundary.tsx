// One part of a screen that cannot be drawn never takes the screen down: a panel, a card list, a card or a drawer is wrapped,
// and when what it draws throws, only that part is replaced by a short note with Reload (design 7.12). The error is logged;
// the rest of the screen keeps working.
import { useQueryClient } from "@tanstack/react-query";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { useWords } from "../lib/wording";
import { Button } from "./Button";
import { Icon } from "./Icon";
import styles from "./LoadFailed.module.css";
import { refreshEverything } from "../lib/write";

function Fallback(props: { onReload: () => void }) {
  const { t } = useWords();
  const client = useQueryClient();
  return (
    <div className={styles.failed} role="alert" data-part-failed="">
      <div className={styles.line}>
        <p className={styles.message}>
          <Icon name="alert" size={16} />
          {t("state.part_failed")}
        </p>
        <Button
          size="sm"
          variant="primary"
          icon="refresh"
          onClick={() => {
            void refreshEverything(client);
            props.onReload();
          }}
        >
          {t("state.part_failed.reload")}
        </Button>
      </div>
    </div>
  );
}

export class PartBoundary extends Component<{ children?: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("A part of the screen could not be drawn", error, info.componentStack);
  }

  render() {
    if (this.state.failed) return <Fallback onReload={() => this.setState({ failed: false })} />;
    return this.props.children;
  }
}

function ScreenFallback() {
  const { t } = useWords();
  return (
    <div className={styles.failed} role="alert" data-screen-failed="">
      <div className={styles.line}>
        <p className={styles.message}>
          <Icon name="alert" size={16} />
          {t("state.screen_failed")}
        </p>
        <Button size="sm" variant="primary" icon="refresh" onClick={() => window.location.reload()}>
          {t("state.part_failed.reload")}
        </Button>
      </div>
    </div>
  );
}

/** The last net under a whole screen (design 7.12): when what a screen draws throws and no part's own boundary caught it,
 *  the header and the sidebar around it keep working and the screen says so, with Reload for the page. Mount it with a key
 *  that changes with the view, so going elsewhere clears it. */
export class ScreenBoundary extends Component<{ children?: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("A screen could not be drawn", error, info.componentStack);
  }

  render() {
    if (this.state.failed) return <ScreenFallback />;
    return this.props.children;
  }
}

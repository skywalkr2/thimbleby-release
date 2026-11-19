import type { S } from "./api";
import { useWords } from "./wording";

/** The running build as a person reads it: its number and commit when it was stamped at build time, else a plain
 * statement that this is a run from source. Never only the package's version. */
export function useBuildLabel(): (rc: Pick<S["RuntimeConfig"], "version" | "build_number" | "build_commit">) => string {
  const { t } = useWords();
  return (rc) =>
    rc.build_number != null
      ? t("app.version_build", { version: rc.version, number: rc.build_number, commit: rc.build_commit || "?" })
      : t("app.version_source", { version: rc.version });
}

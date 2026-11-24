// The warning beside a project's typed status when what the app sees disagrees with it (design 7.13): a mark and the reasons in
// words ("6 overdue · no change in 6 weeks"), never colour alone. Nothing when the status is not out of step.
import type { S } from "../lib/api";
import { healthWords, statusDisagrees } from "../lib/project-health";
import { useWords } from "../lib/wording";
import { Icon } from "../ui/Icon";

export function ProjectStatusMark(props: { project: S["ProjectView"] }) {
  const { t, tn } = useWords();
  if (!statusDisagrees(props.project)) return null;
  return (
    <span className="hint" data-status-disagrees="">
      <Icon name="alert" size={14} label={t("project.health.mark")} /> {healthWords(props.project, t, tn)}
    </span>
  );
}

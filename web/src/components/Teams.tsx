// Teams (design 5.1, 7.13): the groups of people, one row each with how many are in it; a team's name opens its page, where people
// are put on it and taken off. With no team on file the section is left out: a heading would stand over nothing.
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { recordView, viewHref } from "../lib/views";
import { useWords } from "../lib/wording";
import { ListState } from "../ui/ListState";
import { Row } from "../ui/Row";
import { RowList } from "../ui/RowList";

export function Teams() {
  const { t, tn } = useWords();
  const teams = useQuery({ queryKey: ["teams"], queryFn: api.teams });
  if (teams.isPending || (teams.isSuccess && teams.data.length === 0)) return null;
  return (
    <section className="panel-section" aria-labelledby="teams-title">
      <div className="heading">
        <h2 id="teams-title">{t("teams.title")}</h2>
      </div>
      <ListState query={teams} failed={t("teams.load_failed")} rows={2} row={{ action: "menu", framed: true }}>
        {(rows) => (
          <RowList aria-label={t("teams.title")}>
            {rows.map((x) => (
              <Row
                key={x.id}
                title={<a href={viewHref(recordView("team", x.id))}>{x.name}</a>}
                clamp={x.name}
                meta={x.people.length > 0 ? tn("teams.people", x.people.length) : t("teams.none_in")}
                oneLine
              />
            ))}
          </RowList>
        )}
      </ListState>
    </section>
  );
}

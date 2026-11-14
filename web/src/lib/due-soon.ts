// What is "due soon" in Follow-ups, written once for every grouping (by person, by project, every tab): a to-do that is due soon
// AND still waits on the person. It waits on the person when it has not been sent yet, or when it was sent and its follow-up is
// due. A to-do already sent that only waits on the other person's own date is under Waiting on them and is never counted or listed
// as due soon.
import type { S } from "./api";

type Action = Pick<S["FollowupAction"], "to_send" | "chase_due" | "due_soon">;

/** Whether the to-do still waits on the person: not yet sent, or sent with its follow-up due. */
export const waitsOnYou = (a: Pick<Action, "to_send" | "chase_due">): boolean => (a.to_send ? true : a.chase_due);

/** Whether the to-do belongs under "due soon": due soon, and waiting on the person. */
export const isDueSoon = (a: Action): boolean => !!a.due_soon && waitsOnYou(a);

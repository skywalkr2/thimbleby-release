import { isDueSoon, waitsOnYou } from "./due-soon";

test("a to-do waits on the person when it is not sent yet, or sent with its follow-up due; due soon is that and soon (S-0350)", () => {
  expect(waitsOnYou({ to_send: true, chase_due: false })).toBe(true);
  expect(waitsOnYou({ to_send: false, chase_due: true })).toBe(true);
  expect(waitsOnYou({ to_send: false, chase_due: false })).toBe(false);
  expect(isDueSoon({ to_send: true, chase_due: false, due_soon: true })).toBe(true);
  // Already sent and waiting on the other person's own date: on Waiting on them alone, never due soon.
  expect(isDueSoon({ to_send: false, chase_due: false, due_soon: true })).toBe(false);
  expect(isDueSoon({ to_send: true, chase_due: false, due_soon: false })).toBe(false);
  expect(isDueSoon({ to_send: true, chase_due: false, due_soon: null })).toBe(false);
});

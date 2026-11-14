import { expect, test } from "vitest";
import { domainOf, serverFromAddress } from "./mail-server";

test("an address gets imap and its domain as the usual server, in lower case", () => {
  expect(serverFromAddress("me@work.example.net")).toBe("imap.work.example.net");
  expect(serverFromAddress("Me@Service-B.example.org")).toBe("imap.service-b.example.org");
});

test("an address with no domain yet gets nothing", () => {
  expect(serverFromAddress("me")).toBe("");
  expect(serverFromAddress("me@")).toBe("");
  expect(serverFromAddress("me@nodot")).toBe("");
  expect(domainOf("a b@bad domain.com")).toBe("");
});

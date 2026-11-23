import { render } from "@testing-library/react";
import { AddressText } from "./AddressText";

test("an address may break only after a dot or an @, never inside a word; other words are as given", () => {
  const { container } = render(<p><AddressText text="Buttondown notifications@buttondown.email" /></p>);
  expect(container.textContent).toBe("Buttondown notifications@buttondown.email");
  const parts = Array.from(container.querySelector("p")!.childNodes).map((n) => (n.nodeName === "WBR" ? "|" : n.textContent));
  expect(parts.join("")).toBe("Buttondown notifications@|buttondown.|email");
});

test("plain words get no break marks", () => {
  const { container } = render(<p><AddressText text="Open the original" /></p>);
  expect(container.querySelectorAll("wbr")).toHaveLength(0);
});

// A plain mailbox's incoming server, filled in from the address the person types (they are never asked to look it up): the
// usual name, `imap.` and the address's domain, which the person can still change. A service the app lists by name is
// picked by name instead, and its server is filled in on the server.

/** The domain of an address, lower case, or "" until it has a usable one. */
export function domainOf(address: string): string {
  const at = address.trim().lastIndexOf("@");
  if (at < 0) return "";
  const domain = address
    .trim()
    .slice(at + 1)
    .toLowerCase();
  return /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(domain) ? domain : "";
}

/** The usual incoming server for an address, or "" while the address has no domain yet. */
export function serverFromAddress(address: string): string {
  const domain = domainOf(address);
  return domain ? `imap.${domain}` : "";
}

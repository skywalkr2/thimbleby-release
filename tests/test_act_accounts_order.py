"""The accounts acts can go through are listed in one fixed order (H2-12)."""

from types import SimpleNamespace

from engine import act_accounts


def test_the_accounts_keep_their_order_whichever_was_signed_in_again_last(monkeypatch):
    sign_in = SimpleNamespace(name="mail/account", label="Example mail", plugin="mail")
    store = SimpleNamespace(plugins=SimpleNamespace(sign_ins=lambda: {"mail/account": sign_in}))
    cfg = SimpleNamespace(watch=SimpleNamespace(sources=[], acting=[]))
    addresses = ["avery@example.com", "blake@example.com", "casey@example.com"]
    monkeypatch.setattr(act_accounts, "_signed_in", lambda _store, _sign_in: list(addresses))
    first = [a.label for a in act_accounts.known(store, cfg)]
    # The first is signed in again for the wider access, so its stored sign-in is the newest and a listing by age
    # puts it last.
    addresses.append(addresses.pop(0))
    assert [a.label for a in act_accounts.known(store, cfg)] == first

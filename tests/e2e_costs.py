"""What the browser test of the provider cost report is seeded with (`tests/e2e_server.py --standin-account`), apart
from the server so a test can read it without starting one: an account whose adapter can read its service's report,
with the report already read (so the app never asks any service), and runs of its own on the same days."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml

from engine.ai import cost_report
from engine.ai.task import CostReadout, ProviderCostDay
from engine.storage import WriteContext

ACCOUNT = "billed"
LABEL = "Billed account"
KEY_ID = "apikey_example_one"
CLAIMS = yaml.safe_load((Path(__file__).parent / "fixtures" / "ai" / "catalog-claims.yaml").read_text("utf-8"))[
    "native_adapter"
]
#: The variable the account's keys are read from; the server sets it so the account reads as having both keys.
KEY_VARIABLE = "E2E_BILLING_KEY"
#: Read every this many hours: far longer than a test, so the read that is due never happens.
HOURS = 24


def provider(allowed: list[str]) -> dict:
    """The account's entry in the settings file."""
    return {
        "adapter": CLAIMS["adapter"],
        "label": LABEL,
        "base_url": CLAIMS["base_url"],
        "auth": f"env:{KEY_VARIABLE}",
        "models": {"default": "example-model"},
        "allowed_data": allowed,
        "billing_auth": f"env:{KEY_VARIABLE}",
        "billing_key_id": KEY_ID,
        "cost_report_hours": HOURS,
    }


def seed_costs(store, cfg) -> dict:
    """Keep a read of the report made a moment ago: a settled day well above what the app worked out (Today's line), a
    day still open that is a little above, and today not reported yet; and the app's own runs on those days."""
    now = datetime.now(UTC)
    settled, yesterday = now.date() - timedelta(days=5), now.date() - timedelta(days=1)
    days = [
        ProviderCostDay(settled, Decimal("14.50"), "USD", "key", now, False),
        ProviderCostDay(yesterday, Decimal("3.00"), "USD", "key", now, True),
    ]
    cost_report._keep(store, cfg, ACCOUNT, now, CostReadout(days=days))
    ctx = WriteContext(actor="engine", trust="trusted", op="e2e.costs")
    with store.transaction() as tx:
        for day, cost, task in ((settled, 2.0, "notes"), (yesterday, 2.5, "notes"), (now.date(), 0.4, "notes")):
            at = datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=1) if day != now.date() else now
            tx.create(
                "run",
                {
                    "task": task,
                    "provider": ACCOUNT,
                    "model": "example-model",
                    "tier": "routine",
                    "outcome": "ok",
                    "started_at": at.isoformat(),
                    "cost_usd": cost,
                },
                ctx,
            )
    return {"settled": settled.isoformat(), "yesterday": yesterday.isoformat()}

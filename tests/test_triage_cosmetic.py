import pytest

from engine.triage import cosmetic


def _closed(before: str, now: str) -> bool:
    return cosmetic({"change": "changed", "before": before, "now": now}, {}) is not None


@pytest.mark.parametrize(
    ("before", "now"),
    [
        ("Margin -5%", "Margin 5%"),
        ("Budget $1.5M", "Budget $15M"),
        ("Due 10/1", "Due 1/01"),
        ("Value 12.1", "Value 1.21"),
    ],
)
def test_a_changed_number_or_sign_is_never_closed_as_only_spacing(before, now):
    assert not _closed(before, now)


def test_only_whitespace_and_letter_case_are_ignored():
    assert _closed("Due Friday", "due Friday")
    assert _closed("Due   Friday\n", "Due Friday")

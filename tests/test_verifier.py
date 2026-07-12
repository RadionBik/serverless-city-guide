"""Verifier strip logic — pure and deterministic, no LLM."""

from city_guide.types import Claim, ClaimStatus, VerifyReport
from city_guide.verifier import strip_unsupported


def _report(*claims: tuple[str, ClaimStatus]) -> VerifyReport:
    return VerifyReport(claims=[Claim(claim=text, status=status) for text, status in claims])


def test_strips_sentence_matching_unsupported_claim() -> None:
    story = (
        "The bakery on Main Street opened in 1890. "
        "Hard Wax record shop closed permanently in 2020. "
        "The museum nearby is free on Sundays."
    )
    report = _report(("Hard Wax was closed since 2020", ClaimStatus.UNSUPPORTED))
    result, removed = strip_unsupported(story, report)
    assert removed == 1
    assert "Hard Wax" not in result
    assert "bakery" in result
    assert "museum" in result
    assert "[removed from story]" in report.claims[0].evidence


def test_supported_claims_untouched() -> None:
    story = "The bakery opened in 1890. The museum is free."
    report = _report(("The bakery opened in 1890", ClaimStatus.SUPPORTED))
    result, removed = strip_unsupported(story, report)
    assert removed == 0
    assert result == story


def test_no_confident_match_leaves_story_alone() -> None:
    story = "A quiet street with three cafes and an old clock tower."
    report = _report(("Napoleon visited the harbor fortress in 1805", ClaimStatus.UNSUPPORTED))
    result, removed = strip_unsupported(story, report)
    assert removed == 0
    assert result == story


def test_strip_preserves_other_paragraphs() -> None:
    story = (
        "## Header\n\nFirst paragraph about the gallery and its exhibits.\n\n"
        "The castle dungeon held pirates in 1650. Nice view too."
    )
    report = _report(("The castle dungeon held pirates in 1650", ClaimStatus.UNSUPPORTED))
    result, removed = strip_unsupported(story, report)
    assert removed == 1
    assert "## Header" in result
    assert "gallery" in result
    assert "pirates" not in result
    assert "Nice view too." in result


def test_uncertain_claims_not_stripped() -> None:
    story = "According to local tradition, the well is haunted by a monk."
    report = _report(("The well is haunted by a monk", ClaimStatus.UNCERTAIN))
    result, removed = strip_unsupported(story, report)
    assert removed == 0
    assert result == story

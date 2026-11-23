import pytest

from scripts.repo_skills import active_skills, render_guides
from skillscope.loader import digest
from skillscope.models import Condition, Skill, Stage

SKILLS = (
    Skill(
        id="investigate",
        stages=(Stage.INVESTIGATE,),
        text="Find a cause.",
        sha256=digest("Find a cause."),
    ),
    Skill(
        id="implement",
        stages=(Stage.IMPLEMENT,),
        text="Preserve the contract.",
        sha256=digest("Preserve the contract."),
    ),
)


def test_phase_scoping_order_and_neutral_character_matching():
    scoped = Condition(id="scoped", policy="scoped", skill_ids=("investigate", "implement"))
    assert [s.id for s in active_skills(SKILLS, scoped, Stage.IMPLEMENT)] == ["implement"]
    assert render_guides(SKILLS, scoped, Stage.VERIFY) == ""
    global_ = Condition(id="all", policy="global", skill_ids=("implement", "investigate"))
    text = render_guides(SKILLS, global_, Stage.VERIFY)
    assert text.index("Preserve") < text.index("Find")
    for variant in ("neutral-a", "neutral-b"):
        neutral = render_guides(
            SKILLS, global_.model_copy(update={"control": variant}), Stage.VERIFY
        )
        assert len(neutral) == len(text)
        assert "Preserve the contract." not in neutral and "Find a cause." not in neutral
    assert (
        render_guides(
            SKILLS, Condition(id="baseline", policy="global", skill_ids=()), Stage.INVESTIGATE
        )
        == ""
    )


def test_invalid_guide_selection_is_rejected():
    with pytest.raises(ValueError):
        render_guides(
            SKILLS,
            Condition(id="missing", policy="global", skill_ids=("unknown",)),
            Stage.INVESTIGATE,
        )
    with pytest.raises(ValueError):
        render_guides(
            SKILLS,
            Condition(id="duplicate", policy="global", skill_ids=("implement", "implement")),
            Stage.INVESTIGATE,
        )

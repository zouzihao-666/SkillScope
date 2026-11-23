"""Render frozen skill guides for a repository-agent phase without changing tools."""

from skillscope.models import Condition, Skill, Stage
from skillscope.prompts import neutral_text


def active_skills(skills: tuple[Skill, ...], condition: Condition, stage: Stage) -> list[Skill]:
    lookup = {skill.id: skill for skill in skills}
    if len(lookup) != len(skills) or len(set(condition.skill_ids)) != len(condition.skill_ids):
        raise ValueError("Duplicate skill identifiers")
    if set(condition.skill_ids) - lookup.keys():
        raise ValueError("Condition references an unknown skill")
    return [
        lookup[id_]
        for id_ in condition.skill_ids
        if condition.policy == "global" or stage in lookup[id_].stages
    ]


def render_guides(skills: tuple[Skill, ...], condition: Condition, stage: Stage) -> str:
    blocks = []
    for skill in active_skills(skills, condition, stage):
        text = (
            skill.text
            if condition.control == "none"
            else neutral_text(len(skill.text), condition.control)
        )
        blocks.append(f"\n\n--- Skill guide: {skill.id} ---\n{text}")
    return "".join(blocks)

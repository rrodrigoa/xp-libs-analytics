from evals.agent_skill.skill_loader import REPO, load_skill


def test_skill_is_product_source_and_all_references_load():
    content, digest = load_skill()
    assert len(digest) == 64
    assert (REPO / "skills/generic-analytics/SKILL.md").read_text(encoding="utf-8") in content
    assert "01_count_all.yaml" in content
    assert "references/errors.md" in content

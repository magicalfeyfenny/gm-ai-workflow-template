import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCAL_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)


def markdown_anchor(heading):
    """Return the stable GitHub-style anchor used by repository headings."""
    plain = re.sub(r"[^\w\s-]", "", heading.casefold())
    return re.sub(r"[\s-]+", "-", plain).strip("-")


def local_destinations(source):
    """Resolve local Markdown links into repository paths and fragments."""
    text = source.read_text(encoding="utf-8")
    destinations = []

    for destination in LOCAL_LINK.findall(text):
        if "://" in destination or destination.startswith("mailto:"):
            continue

        path_text, separator, fragment = destination.partition("#")
        target = source if not path_text else source.parent / path_text
        destinations.append((target.resolve(), fragment if separator else ""))

    return destinations


def heading_anchors(path):
    """Collect the anchors exposed by one Markdown file."""
    text = path.read_text(encoding="utf-8")
    return {markdown_anchor(heading) for heading in HEADING.findall(text)}


def governance_fragments(source):
    """Return Governance section fragments linked by one task entrypoint."""
    governance = (ROOT / "GOVERNANCE.md").resolve()
    return {
        fragment
        for target, fragment in local_destinations(source)
        if target == governance and fragment
    }


class GovernanceRoutingTests(unittest.TestCase):
    def test_entrypoint_links_resolve_to_real_sections(self):
        """Protect route destinations without interpreting their prose."""
        entrypoints = (
            ROOT / "AGENTS.md",
            ROOT / "GOVERNANCE.md",
            ROOT / "README.md",
            ROOT / "docs/SETUP.md",
            ROOT / ".agents/skills/asset-production/SKILL.md",
            ROOT / ".agents/skills/gamemaker-production/SKILL.md",
            ROOT / ".agents/skills/governed-change/SKILL.md",
            ROOT / ".agents/skills/project-steward/SKILL.md",
        )

        for source in entrypoints:
            for target, fragment in local_destinations(source):
                with self.subTest(source=source, target=target, fragment=fragment):
                    self.assertTrue(target.is_file())
                    if fragment:
                        self.assertIn(fragment, heading_anchors(target))

    def test_task_entrypoints_route_to_their_scoped_governance_sections(self):
        """Keep normal work on its relevant Governance sections."""
        agents = governance_fragments(ROOT / "AGENTS.md")
        assets = governance_fragments(
            ROOT / ".agents/skills/asset-production/SKILL.md"
        )
        production = governance_fragments(
            ROOT / ".agents/skills/gamemaker-production/SKILL.md"
        )
        governed = governance_fragments(
            ROOT / ".agents/skills/governed-change/SKILL.md"
        )
        steward = governance_fragments(
            ROOT / ".agents/skills/project-steward/SKILL.md"
        )

        agent_targets = {
            target for target, _ in local_destinations(ROOT / "AGENTS.md")
        }

        self.assertTrue(
            {
                "source-structure",
                "releases",
            }.issubset(agents)
        )
        self.assertTrue(
            {
                "production-code",
                "derived-assets",
                "gamemaker-structured-data",
            }.isdisjoint(agents)
        )
        self.assertTrue(
            {
                (
                    ROOT
                    / ".agents/skills/gamemaker-production/SKILL.md"
                ).resolve(),
                (ROOT / ".agents/skills/governed-change/SKILL.md").resolve(),
                (ROOT / ".agents/skills/project-steward/SKILL.md").resolve(),
                (ROOT / "docs/SETUP.md").resolve(),
            }.issubset(agent_targets)
        )
        self.assertEqual(
            production,
            {
                "production-code",
                "source-structure",
                "gamemaker-structured-data",
            },
        )
        self.assertEqual(assets, {"derived-assets"})
        self.assertTrue(
            {
                "issue-authority",
                "branches",
                "unit-of-work",
                "validation-evidence",
                "milestone-commits-and-draft-publication",
                "human-created-changes",
                "risk",
                "completion-transition",
                "low-risk-changes",
                "manual-and-high-risk-changes",
            }.issubset(governed)
        )
        self.assertTrue(
            {
                "production-code",
                "source-structure",
                "derived-assets",
                "gamemaker-structured-data",
            }.isdisjoint(governed)
        )
        self.assertEqual(
            steward,
            {"issue-authority", "human-created-changes"},
        )

        policy = (ROOT / "PROJECT_POLICY.toml").resolve()
        for entrypoint in (
            ROOT / ".agents/skills/asset-production/SKILL.md",
            ROOT / ".agents/skills/gamemaker-production/SKILL.md",
            ROOT / ".agents/skills/governed-change/SKILL.md",
        ):
            with self.subTest(entrypoint=entrypoint):
                linked_paths = {
                    target for target, _ in local_destinations(entrypoint)
                }
                self.assertIn(policy, linked_paths)

    def test_readme_overview_is_structurally_non_normative(self):
        """Keep README as navigation to the two authority files."""
        readme = ROOT / "README.md"
        self.assertIn(
            "governance-overview-non-normative",
            heading_anchors(readme),
        )

        linked_paths = {target for target, _ in local_destinations(readme)}
        for destination in (
            ROOT / "GOVERNANCE.md",
            ROOT / "PROJECT_POLICY.toml",
            ROOT / "AGENTS.md",
            ROOT / "docs/SETUP.md",
        ):
            with self.subTest(destination=destination):
                self.assertIn(destination.resolve(), linked_paths)

    def test_setup_routes_each_scheduled_task_to_its_template(self):
        """Keep scheduled stewardship and implementation as distinct routes."""
        expected = {
            (ROOT / "templates/codex/governed-change.txt").resolve(),
            (ROOT / "templates/codex/project-steward.txt").resolve(),
        }
        setup_targets = {
            target for target, _ in local_destinations(ROOT / "docs/SETUP.md")
        }

        self.assertTrue(expected.issubset(setup_targets))


if __name__ == "__main__":
    unittest.main()

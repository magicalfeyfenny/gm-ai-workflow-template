"""Protect scoped workflow routes for native GameMaker decision cases.

These fixtures establish that each relevant procedure reaches its authority.
They do not interpret policy prose or claim to prove an agent obeys it. Asset
representation acceptance and rejection belong to the asset-checker fixtures.
"""

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from tools.tests.test_governance_routing import LOCAL_LINK, ROOT, markdown_anchor


GOVERNANCE = ROOT / "GOVERNANCE.md"
SKILLS = ROOT / ".agents/skills"
GOVERNED = SKILLS / "governed-change/SKILL.md"
PRODUCTION = SKILLS / "gamemaker-production/SKILL.md"
ASSETS = SKILLS / "asset-production/SKILL.md"
STEWARD = SKILLS / "project-steward/SKILL.md"
HEADINGS = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)


@dataclass(frozen=True)
class WorkflowCase:
    """Name a decision case and the procedure that must reach its authority."""

    name: str
    route: tuple[Path, ...]
    authority: str


CASES = (
    WorkflowCase(
        "existing custom machinery alone is insufficient",
        (GOVERNED, PRODUCTION),
        "custom-implementation-requirements",
    ),
    WorkflowCase(
        "custom renderer conflicts with native functionality",
        (GOVERNED, PRODUCTION),
        "custom-implementation-requirements",
    ),
    WorkflowCase(
        "engine semantics must be established before preserving a substitute",
        (GOVERNED, PRODUCTION),
        "establish-engine-semantics",
    ),
    WorkflowCase(
        "a concrete unmet requirement can justify custom machinery",
        (GOVERNED, PRODUCTION),
        "custom-implementation-requirements",
    ),
    WorkflowCase(
        "custom asset loaders require an unmet native requirement",
        (ASSETS,),
        "custom-implementation-requirements",
    ),
    WorkflowCase(
        "external authorship does not imply Included Files",
        (GOVERNED, PRODUCTION, ASSETS),
        "runtime-asset-representation",
    ),
    WorkflowCase(
        "an adequate native resource is preferred",
        (GOVERNED, PRODUCTION, ASSETS),
        "runtime-asset-representation",
    ),
    WorkflowCase(
        "runtime data files can legitimately use Included Files",
        (ASSETS,),
        "runtime-asset-representation",
    ),
    WorkflowCase(
        "a concrete file contract can justify a file representation",
        (ASSETS,),
        "runtime-asset-representation",
    ),
    WorkflowCase(
        "existing custom machinery alone does not create backlog",
        (STEWARD,),
        "native-adoption-scope",
    ),
    WorkflowCase(
        "existing external runtime assets alone do not create backlog",
        (STEWARD,),
        "native-adoption-scope",
    ),
    WorkflowCase(
        "audits can report inappropriate runtime resource choices",
        (STEWARD,),
        "runtime-asset-representation",
    ),
)


def local_links(source: Path, text: str) -> list[tuple[Path, str]]:
    """Resolve local workflow links without interpreting their labels."""
    links = []
    for destination in LOCAL_LINK.findall(text):
        if "://" in destination or destination.startswith("mailto:"):
            continue
        path, _, fragment = destination.partition("#")
        target = source.parent / path if path else source
        links.append((target.resolve(), fragment))
    return links


def authority_sections(text: str, authority: str) -> set[str]:
    """Find the authority heading and containing Markdown sections."""
    ancestors: list[tuple[int, str]] = []
    for heading in HEADINGS.finditer(text):
        level = len(heading.group(1))
        anchor = markdown_anchor(heading.group(2))
        while ancestors and ancestors[-1][0] >= level:
            ancestors.pop()
        ancestors.append((level, anchor))
        if anchor == authority:
            return {anchor for level, anchor in ancestors if level > 1}
    return set()


def reaches_authority(case: WorkflowCase, documents: dict[Path, str]) -> bool:
    """Follow only the declared skill route and its scoped Governance link."""
    for source, target in zip(case.route, case.route[1:]):
        linked_paths = {
            path for path, _ in local_links(source, documents[source])
        }
        if target.resolve() not in linked_paths:
            return False

    permitted_sections = authority_sections(
        documents[GOVERNANCE], case.authority
    )
    endpoint = case.route[-1]
    return any(
        target == GOVERNANCE.resolve() and fragment in permitted_sections
        for target, fragment in local_links(endpoint, documents[endpoint])
    )


class NativeGameMakerPolicyRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = {
            path: path.read_text(encoding="utf-8")
            for path in (GOVERNANCE, GOVERNED, PRODUCTION, ASSETS, STEWARD)
        }

    def test_decision_cases_reach_their_scoped_authority(self):
        """Protect all relevant cases without matching the authority prose."""
        for case in CASES:
            with self.subTest(case=case.name):
                self.assertTrue(reaches_authority(case, self.documents))

    def test_unrelated_governance_links_do_not_cover_missing_authority(self):
        """Removing an authority route must fail despite other valid routes."""
        for case in CASES:
            documents = self.documents.copy()
            endpoint = case.route[-1]
            permitted = authority_sections(documents[GOVERNANCE], case.authority)

            def remove_authority_link(match):
                """Remove only the scoped route covered by this fixture."""
                links = local_links(endpoint, match.group(0))
                if not links:
                    return match.group(0)
                target, fragment = links[0]
                if target == GOVERNANCE.resolve() and fragment in permitted:
                    return ""
                return match.group(0)

            documents[endpoint] = LOCAL_LINK.sub(
                remove_authority_link, documents[endpoint]
            )
            with self.subTest(case=case.name):
                self.assertFalse(reaches_authority(case, documents))

    def test_cases_require_each_cross_skill_route(self):
        """Authority cannot be reached through an absent skill handoff."""
        for case in CASES:
            for source, destination in zip(case.route, case.route[1:]):
                documents = self.documents.copy()

                def remove_skill_link(match):
                    """Remove this required workflow edge from the fixture."""
                    links = local_links(source, match.group(0))
                    if links and links[0][0] == destination.resolve():
                        return ""
                    return match.group(0)

                documents[source] = LOCAL_LINK.sub(
                    remove_skill_link, documents[source]
                )
                with self.subTest(case=case.name, source=source):
                    self.assertFalse(reaches_authority(case, documents))


if __name__ == "__main__":
    unittest.main()

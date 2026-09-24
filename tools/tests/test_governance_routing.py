import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LOCAL_LINK = re.compile(r"\[[^]]+\]\(([^)]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)
VALIDATION_SURFACES = (
    ROOT / "GOVERNANCE.md",
    ROOT / ".agents/skills/gamemaker-production/SKILL.md",
    ROOT / ".agents/skills/governed-change/SKILL.md",
    ROOT / ".agents/skills/project-steward/SKILL.md",
    ROOT / ".github/ISSUE_TEMPLATE/work-item.yml",
    ROOT / ".github/pull_request_template.md",
    ROOT / "templates/codex/governed-change.txt",
    ROOT / "templates/codex/project-steward.txt",
)
SUPERSEDED_VALIDATION_PATTERNS = (
    re.compile(r"manual-and-live-validation-availability", re.IGNORECASE),
    re.compile(r"manual\s+and\s+live\s+validation", re.IGNORECASE),
    re.compile(
        r"manual\s+or\s+live\s+(?:validation|evidence|play(?:test)?)",
        re.IGNORECASE,
    ),
    re.compile(r"manual/live\s+(?:validation|evidence)", re.IGNORECASE),
    re.compile(r"interactive\s+desktop", re.IGNORECASE),
    re.compile(r"manually\s+verified", re.IGNORECASE),
)


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
    return {markdown_anchor(heading) for _, heading in HEADING.findall(text)}


def section_descendant_anchors(text, section):
    """Read a section's nested headings up to its next peer or ancestor."""
    headings = [
        (len(level), markdown_anchor(heading))
        for level, heading in HEADING.findall(text)
    ]
    for index, (level, anchor) in enumerate(headings):
        if anchor != section:
            continue
        descendants = set()
        for child_level, child_anchor in headings[index + 1:]:
            if child_level <= level:
                break
            descendants.add(child_anchor)
        return descendants
    raise ValueError(f"Missing Markdown section: {section}")


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
            ROOT / "docs/ADOPTION.md",
            ROOT / "docs/POLICY_UPDATE.md",
            ROOT / "docs/CI.md",
            ROOT / ".agents/skills/asset-production/SKILL.md",
            ROOT / ".agents/skills/gamemaker-production/SKILL.md",
            ROOT / ".agents/skills/governed-change/SKILL.md",
            ROOT / ".agents/skills/project-steward/SKILL.md",
            ROOT / ".github/ISSUE_TEMPLATE/work-item.yml",
            ROOT / ".github/pull_request_template.md",
            ROOT / "templates/codex/governed-change.txt",
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
        issue_template = governance_fragments(
            ROOT / ".github/ISSUE_TEMPLATE/work-item.yml"
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
                (ROOT / ".agents/skills/asset-production/SKILL.md").resolve(),
                (ROOT / "docs/SETUP.md").resolve(),
                (ROOT / "docs/ADOPTION.md").resolve(),
            }.issubset(agent_targets)
        )
        self.assertTrue(
            {
                "native-gamemaker-functionality",
                "production-code",
                "compatibility-obligations",
                "source-structure",
                "gamemaker-structured-data",
                "validation-coverage-allocation",
                "interactive-runtime-validation",
            }.issubset(production),
        )
        self.assertTrue(
            {
                "native-gamemaker-functionality",
                "asset-completion-and-authority",
                "derived-assets",
                "placeholder-backed-mixed-work",
                "validation-coverage-allocation",
                "interactive-runtime-validation",
            }.issubset(assets),
        )
        self.assertTrue(
            {
                "issue-authority",
                "branches",
                "unit-of-work",
                "asset-completion-and-authority",
                "placeholder-backed-mixed-work",
                "compatibility-obligations",
                "scheduled-continuation",
                "contract-oriented-validation",
                "validation-coverage-allocation",
                "interactive-runtime-validation",
                "validation-evidence",
                "milestone-commits-and-draft-publication",
                "adversarial-review-and-adjudication",
                "human-created-changes",
                "risk",
                "completion-transition",
                "issue-contract-evidence",
                "low-risk-and-medium-risk-changes",
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
        self.assertTrue(
            {
                "native-gamemaker-functionality",
                "runtime-asset-representation",
                "issue-authority",
                "asset-completion-and-authority",
                "placeholder-backed-mixed-work",
                "compatibility-obligations",
                "validation-coverage-allocation",
                "interactive-runtime-validation",
                "human-created-changes",
            }.issubset(steward),
        )
        self.assertEqual(
            issue_template,
            {
                "validation-coverage-allocation",
                "interactive-runtime-validation",
            },
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

    def test_section_descendants_stop_at_peers_and_ancestors(self):
        """Check the boundary helper without depending on repository prose."""
        text = "\n".join((
            "# Document", "## First", "### Child", "#### Grandchild",
            "### Other child", "## Peer", "### Peer child", "# Next root",
        ))
        self.assertEqual(
            section_descendant_anchors(text, "first"),
            {"child", "grandchild", "other-child"},
        )
        self.assertEqual(
            section_descendant_anchors(text, "other-child"), set(),
        )
        self.assertEqual(
            section_descendant_anchors(text, "peer"), {"peer-child"},
        )

    def test_common_sections_do_not_contain_specialized_routes(self):
        """Keep specialist obligations reachable without loading them by default."""
        governance = ROOT / "GOVERNANCE.md"
        text = governance.read_text(encoding="utf-8")
        anchors = heading_anchors(governance)
        boundaries = {
            "authority": {"inventory-authority", "policy-updates"},
            "issue-authority": {
                "compatibility-obligations", "scheduled-claim-eligibility",
                "placeholder-backed-mixed-work", "scheduled-continuation",
            },
            "unit-of-work": {
                "contract-oriented-validation", "validation-coverage-allocation",
                "policy-correction-boundary-evidence",
                "interactive-runtime-validation",
            },
            "validation-coverage-allocation": {
                "policy-correction-boundary-evidence",
            },
        }
        for section, specialized in boundaries.items():
            with self.subTest(section=section):
                self.assertIn(section, anchors)
                self.assertTrue(specialized.issubset(anchors))
                self.assertTrue(specialized.isdisjoint(
                    section_descendant_anchors(text, section),
                ))

    def test_derived_asset_route_includes_representation_and_export_contracts(self):
        """Keep the asset route's coupled obligations in its selected section."""
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        self.assertTrue({
            "runtime-asset-representation", "export-topology",
        }.issubset(section_descendant_anchors(governance, "derived-assets")))

    def test_governed_procedure_routes_assets_and_contract_attestation_directly(self):
        """Reach the relevant procedures without loading unrelated production work."""
        destinations = local_destinations(
            ROOT / ".agents/skills/governed-change/SKILL.md"
        )
        self.assertIn(
            ((ROOT / ".agents/skills/asset-production/SKILL.md").resolve(), ""),
            destinations,
        )
        self.assertIn(
            ((ROOT / "docs/CI.md").resolve(), "issue-contract-attestation"),
            destinations,
        )

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

    def test_policy_update_route_reaches_existing_authority_and_evidence(self):
        """Check update-route reachability, without interpreting policy prose."""
        procedure = (ROOT / "docs/POLICY_UPDATE.md").resolve()
        for source in (
            ROOT / "AGENTS.md",
            ROOT / "docs/SETUP.md",
            ROOT / "docs/ADOPTION.md",
            ROOT / ".agents/skills/governed-change/SKILL.md",
        ):
            with self.subTest(source=source):
                self.assertIn(
                    procedure, {target for target, _ in local_destinations(source)},
                )

        self.assertIn(
            "policy-updates",
            governance_fragments(ROOT / ".agents/skills/governed-change/SKILL.md"),
        )
        self.assertTrue({
            "policy-updates", "compatibility-obligations",
            "validation-coverage-allocation",
        }.issubset(governance_fragments(procedure)))
        targets = {target for target, _ in local_destinations(procedure)}
        self.assertTrue({
            (ROOT / "docs/ADOPTION.md").resolve(),
            (ROOT / ".agents/skills/governed-change/SKILL.md").resolve(),
        }.issubset(targets))

    def test_adoption_comparison_routes_to_shared_authority_and_existing_update(self):
        """Prove route reachability, leaving lineage interpretation to evidence."""
        adoption = ROOT / "docs/ADOPTION.md"
        update = ROOT / "docs/POLICY_UPDATE.md"
        for source in (adoption, update):
            with self.subTest(source=source):
                self.assertIn("framework-adoption-lineage", governance_fragments(source))
        self.assertTrue({
            "validation-evidence", "issue-contract-evidence", "risk",
        }.issubset(governance_fragments(adoption)))
        self.assertIn(
            (adoption.resolve(), "establish-the-framework-comparison"),
            local_destinations(update),
        )
        self.assertIn(update.resolve(), {path for path, _ in local_destinations(adoption)})

    def test_policy_correction_evidence_is_reachable_from_work_and_pr_routes(self):
        """Check authority reachability, not interpretation or future obedience."""
        for source in (
            ROOT / ".agents/skills/governed-change/SKILL.md",
            ROOT / ".github/pull_request_template.md",
        ):
            with self.subTest(source=source):
                self.assertIn(
                    "policy-correction-boundary-evidence",
                    governance_fragments(source),
                )

    def test_adversarial_review_route_is_reachable_from_work_and_pr_routes(self):
        """Keep the bounded review stage on every completion-facing route."""
        for source in (
            ROOT / ".agents/skills/governed-change/SKILL.md",
            ROOT / "templates/codex/governed-change.txt",
            ROOT / ".github/pull_request_template.md",
        ):
            with self.subTest(source=source):
                self.assertIn(
                    "adversarial-review-and-adjudication",
                    governance_fragments(source),
                )

    def test_review_obligation_policy_has_one_authoritative_route(self):
        """Route review policy to Governance, not copied policy text."""
        governance = ROOT / "GOVERNANCE.md"
        review = heading_anchors(governance)
        self.assertIn("review-obligations", review)
        self.assertIn(
            "review-obligations",
            section_descendant_anchors(
                governance.read_text(encoding="utf-8"),
                "adversarial-review-and-adjudication",
            ),
        )
        for source in (
            ROOT / ".agents/skills/governed-change/SKILL.md",
            ROOT / "templates/codex/governed-change.txt",
        ):
            with self.subTest(source=source):
                self.assertIn(
                    "adversarial-review-and-adjudication",
                    governance_fragments(source),
                )

        destinations = {
            target for target, _ in local_destinations(
                ROOT / ".agents/skills/governed-change/SKILL.md"
            )
        }
        self.assertIn(governance.resolve(), destinations)

    def test_setup_label_inventory_routes_to_its_authorities(self):
        """Link setup to the shared rule and executable label inventory."""
        setup = ROOT / "docs/SETUP.md"
        self.assertIn("inventory-authority", governance_fragments(setup))
        self.assertIn(
            "inventory-authority",
            heading_anchors(ROOT / "GOVERNANCE.md"),
        )
        self.assertIn(
            (ROOT / "tools/setup_github.py").resolve(),
            {target for target, _ in local_destinations(setup)},
        )

    def test_scheduled_claim_policy_has_one_implementation_owner(self):
        """Route scheduled claims through Governed Change, not stewardship."""
        governed = governance_fragments(
            ROOT / "templates/codex/governed-change.txt"
        )
        steward = governance_fragments(
            ROOT / "templates/codex/project-steward.txt"
        )

        self.assertTrue(
            {
                "scheduled-claim-eligibility",
                "scheduled-continuation",
                "interactive-runtime-validation",
            }.issubset(governed)
        )
        self.assertNotIn("scheduled-claim-eligibility", steward)

    def test_active_validation_surfaces_reject_superseded_policy(self):
        """Prevent generic manual/live validation policy from returning."""
        for surface in VALIDATION_SURFACES:
            text = surface.read_text(encoding="utf-8")
            for pattern in SUPERSEDED_VALIDATION_PATTERNS:
                with self.subTest(surface=surface, pattern=pattern.pattern):
                    self.assertIsNone(pattern.search(text))

    def test_manual_handoff_separates_authority_from_validation(self):
        """Route high-risk handoff details to the central risk policy."""
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        completion = " ".join(
            governance.split("## Completion transition", 1)[1].split(
                "## Low-risk and medium-risk changes", 1
            )[0].casefold().split()
        )
        for marker in (
            "human review, readiness, and merge",
            "authority actions",
            "not validation evidence",
            "accepted issue contract",
            "no manual or experiential validation requirement",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, completion)

        self.assertIn(
            "risk",
            governance_fragments(ROOT / ".github/pull_request_template.md"),
        )

    def test_scheduled_continuation_rejects_invented_manual_blockers(self):
        """Do not let handoff text turn authority into continuation blocking."""
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        continuation = " ".join(
            governance.split("## Scheduled continuation", 1)[1].split(
                "## Branches", 1
            )[0].casefold().split()
        )
        for marker in (
            "accepted issue contract",
            "pr body",
            "handoff",
            "risk label",
            "manual-path authority gate",
            "cannot create that requirement",
            "agent-authored",
            "valid completion blocker",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, continuation)

        scheduled = " ".join(
            (
                ROOT / "templates/codex/governed-change.txt"
            ).read_text(encoding="utf-8").casefold().split()
        )
        for marker in (
            "accepted issue contract requires",
            "authority actions, not validation blockers",
            "agent-authored pr body or handoff",
        ):
                with self.subTest(marker=marker):
                    self.assertIn(marker, scheduled)

    def test_scheduled_completion_continuation_reaches_the_existing_boundaries(self):
        """Keep scheduled completion in evidence flow and existing authority lanes."""
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        continuation = " ".join(
            governance.split("## Scheduled continuation", 1)[1].split(
                "## Asset completion and authority", 1
            )[0].casefold().split()
        )
        for marker in (
            "implementation completion",
            "not terminal states",
            "whole-issue stage 2 evidence",
            "issue-contract revision",
            "immediate pre-transition re-fetch",
            "fresh stage 3 hosted evidence",
            "eligible low- or medium-risk continuation",
            "existing automatic readiness and squash auto-merge automation",
            "high-risk and manual-path continuations",
            "authority boundaries",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, continuation)

        agents = " ".join(
            (ROOT / "AGENTS.md").read_text(encoding="utf-8")
            .casefold()
            .split()
        )
        for marker in (
            "completion metadata remains an evidence-backed transition",
            "scheduled worker may carry eligible low- or medium-risk work",
            "whole-issue stage 2 evidence",
            "immediate pre-transition issue re-fetch",
            "fresh stage 3 evidence",
            "existing automatic low/medium automation owns readiness and squash auto-merge",
            "high-risk and manual-path work waits for human review, readiness, and merge",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, agents)

    def test_release_verification_names_concrete_machine_evidence(self):
        """Keep release verification tied to source, artifacts, and integrity."""
        governance = (ROOT / "GOVERNANCE.md").read_text(encoding="utf-8")
        release = governance.split("## Releases", 1)[1].split(
            "## Derived assets", 1
        )[0].casefold()

        for marker in (
            "source commit",
            "source tree",
            "build provenance",
            "artifact contents",
            "artifact digests",
            "machine-verifiable evidence",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, release)


if __name__ == "__main__":
    unittest.main()

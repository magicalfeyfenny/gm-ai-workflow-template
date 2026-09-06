import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.ci.check_repo import (
    SourceLineViolation,
    collect_errors,
    new_policy_errors,
)


class SourceBaselineTests(unittest.TestCase):
    def setUp(self):
        """Collect inherited violations from real tracked source files."""
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = "source/legacy.gml"
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.write_policy()
        (self.root / "assets").mkdir()
        (self.root / "assets/exports.json").write_text(
            json.dumps({"version": 1, "exports": []}), encoding="utf-8"
        )
        self.write_source(self.source, 4006)
        self.track()
        self.baseline = collect_errors(self.root)

    def write_policy(self, limit: int = 800):
        """Keep the line threshold explicit in the fixture's rule identity."""
        (self.root / "PROJECT_POLICY.toml").write_text(
            f"""[structure]
max_source_lines = {limit}
source_extensions = [".gml"]
forbidden_generic_stems = []
large_file_exceptions = []
[assets]
manifest = "assets/exports.json"
plain_runtime_svg = true
[assets.pipelines]
""",
            encoding="utf-8",
        )

    def write_source(self, name: str, count: int, content: str = "original"):
        """Change source contents without relying on rendered diagnostic text."""
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"// {content}\n" * count, encoding="utf-8")

    def track(self):
        """Make the fixture inventory match the checker's tracked-file contract."""
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True)

    def source_errors(self, errors):
        """Select the one supported ordered violation by its concrete type."""
        return [error for error in errors if isinstance(error, SourceLineViolation)]

    def test_collection_exposes_source_identity_threshold_and_count(self):
        self.assertEqual(
            self.baseline,
            [SourceLineViolation(self.source, limit=800, count=4006)],
        )

    def test_unchanged_source_and_same_line_count_edit_are_inherited(self):
        for content in ("original", "edited"):
            with self.subTest(content=content):
                self.write_source(self.source, 4006, content)
                candidate = collect_errors(self.root)
                self.assertEqual(new_policy_errors(candidate, self.baseline), [])

    def test_reduction_still_above_threshold_is_inherited(self):
        self.write_source(self.source, 3900)
        candidate = collect_errors(self.root)
        self.assertTrue(self.source_errors(candidate))
        self.assertEqual(new_policy_errors(candidate, self.baseline), [])

    def test_reduction_to_or_below_threshold_resolves_violation(self):
        for count in (800, 799, 0):
            with self.subTest(count=count):
                self.write_source(self.source, count)
                candidate = collect_errors(self.root)
                self.assertEqual(candidate, [])
                self.assertEqual(new_policy_errors(candidate, self.baseline), [])

    def test_growth_is_rejected(self):
        self.write_source(self.source, 4007)
        candidate = collect_errors(self.root)
        self.assertEqual(new_policy_errors(candidate, self.baseline), candidate)

    def test_new_over_limit_source_is_rejected(self):
        added = "source/introduced.gml"
        self.write_source(added, 801)
        self.track()
        introduced = new_policy_errors(collect_errors(self.root), self.baseline)
        self.assertEqual(
            introduced, [SourceLineViolation(added, limit=800, count=801)]
        )

    def test_removed_source_resolves_violation(self):
        (self.root / self.source).unlink()
        self.track()
        candidate = collect_errors(self.root)
        self.assertEqual(candidate, [])
        self.assertEqual(new_policy_errors(candidate, self.baseline), [])

    def test_renamed_source_does_not_inherit_another_paths_violation(self):
        renamed = "source/renamed.gml"
        (self.root / self.source).rename(self.root / renamed)
        self.track()
        candidate = collect_errors(self.root)
        self.assertEqual(new_policy_errors(candidate, self.baseline), candidate)

    def test_threshold_change_is_a_different_rule_even_with_fewer_lines(self):
        for limit in (700, 900):
            with self.subTest(limit=limit):
                self.write_policy(limit)
                self.write_source(self.source, 3900)
                candidate = collect_errors(self.root)
                self.assertTrue(self.source_errors(candidate))
                self.assertEqual(new_policy_errors(candidate, self.baseline), candidate)

    def test_new_threshold_obligation_has_no_baseline_allowance(self):
        self.write_source(self.source, 750)
        baseline = collect_errors(self.root)
        self.assertEqual(baseline, [])
        self.write_policy(700)
        candidate = collect_errors(self.root)
        self.assertTrue(self.source_errors(candidate))
        self.assertEqual(new_policy_errors(candidate, baseline), candidate)

    def test_additional_ordered_duplicate_is_rejected(self):
        inherited = self.baseline[0]
        self.assertEqual(
            new_policy_errors([inherited, inherited], [inherited]), [inherited]
        )

    def test_ordered_duplicate_matching_is_independent_of_input_order(self):
        larger = SourceLineViolation(self.source, limit=800, count=4006)
        smaller = SourceLineViolation(self.source, limit=800, count=3900)
        improved = SourceLineViolation(self.source, limit=800, count=3800)
        for baseline in ([smaller, larger], [larger, smaller]):
            for candidate in ([larger, improved], [improved, larger]):
                with self.subTest(baseline=baseline, candidate=candidate):
                    self.assertEqual(new_policy_errors(candidate, baseline), [])

    def test_worsened_duplicate_preserves_allowance_for_other_occurrences(self):
        larger = SourceLineViolation(self.source, limit=800, count=4006)
        smaller = SourceLineViolation(self.source, limit=800, count=3900)
        worsened = SourceLineViolation(self.source, limit=800, count=4007)
        for candidate in ([worsened, larger], [larger, worsened]):
            with self.subTest(candidate=candidate):
                self.assertEqual(
                    new_policy_errors(candidate, [smaller, larger]), [worsened]
                )

    def test_unordered_diagnostics_preserve_exact_identity_and_duplicates(self):
        inherited = "assets/runtime/shared.png: runtime export mapped more than once"
        self.assertEqual(new_policy_errors([inherited], [inherited]), [])
        self.assertEqual(
            new_policy_errors([inherited, inherited], [inherited]), [inherited]
        )
        changed = "assets/exports.json: export 1 has unknown kind legacy"
        baseline = "assets/exports.json: export 0 has unknown kind legacy"
        self.assertEqual(new_policy_errors([changed], [baseline]), [changed])

    def test_changed_json_diagnostics_have_no_inferred_severity(self):
        path = self.root / "content/legacy.json"
        path.parent.mkdir()
        path.write_text("{invalid", encoding="utf-8")
        self.track()
        baseline = collect_errors(self.root)
        path.write_text("{\ninvalid", encoding="utf-8")
        candidate = collect_errors(self.root)
        introduced = new_policy_errors(candidate, baseline)
        self.assertTrue(introduced)
        self.assertFalse(self.source_errors(introduced))

    def test_text_resembling_source_diagnostic_does_not_gain_ordering(self):
        baseline = f"{self.source}: 4006 lines exceeds limit 800"
        candidate = f"{self.source}: 3900 lines exceeds limit 800"
        self.assertEqual(new_policy_errors([candidate], [baseline]), [candidate])

    def test_strict_comparison_preserves_only_exact_historical_diagnostics(self):
        historical = [str(error) for error in self.baseline]
        self.assertEqual(new_policy_errors(self.baseline, historical, strict=True), [])
        self.write_source(self.source, 3900)
        candidate = collect_errors(self.root)
        self.assertEqual(
            new_policy_errors(candidate, historical, strict=True), candidate
        )

    def test_strict_comparison_still_preserves_duplicate_accounting(self):
        inherited = self.baseline[0]
        self.assertEqual(
            new_policy_errors(
                [inherited, inherited], [str(inherited)], strict=True
            ),
            [inherited],
        )


if __name__ == "__main__":
    unittest.main()

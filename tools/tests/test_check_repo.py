import json
import tempfile
import unittest
from pathlib import Path

from tools.ci.check_repo import new_policy_errors, validate_assets

ROOT = Path(__file__).resolve().parents[2]


class RepositoryPolicyTests(unittest.TestCase):
    def test_inherited_errors_do_not_block(self):
        inherited = "source/legacy.gml: 900 lines exceeds limit 800"

        self.assertEqual(
            new_policy_errors([inherited], [inherited]),
            [],
        )

    def test_new_errors_still_block(self):
        inherited = "source/legacy.gml: 900 lines exceeds limit 800"
        introduced = "content/new.json: invalid JSON"

        self.assertEqual(
            new_policy_errors(
                [inherited, introduced],
                [inherited],
            ),
            [introduced],
        )

    def test_an_additional_duplicate_error_still_blocks(self):
        repeated = "assets/runtime/shared.png: runtime export mapped more than once"

        self.assertEqual(
            new_policy_errors([repeated, repeated], [repeated]),
            [repeated],
        )

    def test_asset_validation_reads_the_selected_root(self):
        policy = {
            "assets": {
                "source_root": "assets/source",
                "runtime_root": "assets/runtime",
                "manifest": "assets/exports.json",
                "plain_runtime_svg": True,
                "pipelines": {},
            }
        }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = root / "assets/exports.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                json.dumps({"version": 2, "exports": []}),
                encoding="utf-8",
            )
            errors: list[str] = []

            validate_assets(
                root,
                policy,
                [Path("assets/exports.json")],
                errors,
            )

        self.assertEqual(
            errors,
            ["assets/exports.json: version must be 1"],
        )

    def test_ci_compares_repository_policy_to_exact_base(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text(
            encoding="utf-8"
        )
        repository_job = text.split(
            "  repository-policy:",
            1,
        )[1].split("\n  tests:", 1)[0]

        self.assertIn(
            "--baseline-ref \"$BASE_SHA\"",
            repository_job,
        )
        self.assertIn(
            "BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            repository_job,
        )
        self.assertIn("fetch-depth: 0", repository_job)
        self.assertNotIn("ref:", repository_job)


if __name__ == "__main__":
    unittest.main()

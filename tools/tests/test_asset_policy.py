"""Semantic asset ownership, runtime destination, and stored-content fixtures."""

import copy
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.ci.check_repo import (
    baseline_policy_errors,
    new_policy_errors,
    validate_assets,
    validate_json,
)


ROOT = Path(__file__).resolve().parents[2]


LFS_POINTER = (
    "version https://git-lfs.github.com/spec/v1\n"
    f"oid sha256:{'a' * 64}\n"
    "size 1024\n"
)
LFS_EXTENDED_POINTER = LFS_POINTER.replace(
    "oid sha256:",
    f"ext-0-compress sha256:{'b' * 64}\next-1-encrypt sha256:{'c' * 64}\noid sha256:",
)


class AssetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.files: list[Path] = []
        self.policy = {
            "assets": {
                "manifest": "assets/exports.json",
                "plain_runtime_svg": True,
                "pipelines": {
                    "raster": {
                        "source_roots": ["assets/source"],
                        "runtime_roots": ["assets/runtime"],
                        "native_resource_roots": ["project/sprites"],
                        "source_extensions": [".kra", ".ora"],
                        "runtime_extensions": [".png", ".webp"],
                    },
                },
            },
        }
        self.entry = {
            "kind": "raster",
            "completion": "authored-placeholder",
            "sources": ["assets/source/badge.kra"],
            "runtime": ["project/sprites/spr_badge/frame.png"],
            "destination": {
                "kind": "native-resource",
                "resource": "project/sprites/spr_badge/spr_badge.yy",
            },
        }
        self.write_file(self.entry["sources"][0])
        self.write_file(self.entry["runtime"][0])
        self.write_file(self.entry["destination"]["resource"], "{}")

    def write_file(self, name: str, content="asset", *, tracked=True):
        path = Path(name)
        full_path = self.root / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        if tracked and path not in self.files:
            self.files.append(path)

    def validate(self, entries=None):
        self.write_file(
            "assets/exports.json",
            json.dumps({"version": 1, "exports": entries or [self.entry]}),
        )
        errors: list[str] = []
        validate_assets(self.root, self.policy, self.files, errors)
        return errors

    def use_included_file(self, name="assets/runtime/badge.png"):
        self.entry["runtime"] = [name]
        self.entry["destination"] = {
            "kind": "included-file",
            "file_contract": "Runtime enumerates user-replaceable image files.",
        }
        self.write_file(name)

    def assert_rejected(self, errors, path=None):
        self.assertTrue(errors, "Invalid asset contract was accepted")
        if path is not None:
            self.assertTrue(any(path in error for error in errors), errors)

    def test_native_embedded_output_accepts_editable_external_source(self):
        self.assertEqual(self.validate(), [])

    def test_unrelated_native_resources_do_not_enter_export_inventory(self):
        self.write_file("project/sprites/spr_native/spr_native.yy", "{}")
        self.write_file("project/sprites/spr_native/frame.png")
        self.assertEqual(self.validate(), [])

    def test_pipeline_extension_lists_allow_alternative_formats(self):
        self.entry["sources"] = ["assets/source/badge.ora"]
        self.entry["runtime"] = ["project/sprites/spr_badge/frame.webp"]
        self.write_file(self.entry["sources"][0])
        self.write_file(self.entry["runtime"][0])
        self.assertEqual(self.validate(), [])

    def test_multiple_source_and_runtime_roots_are_pipeline_specific(self):
        raster = self.policy["assets"]["pipelines"]["raster"]
        raster["source_roots"].append("art/paint")
        raster["runtime_roots"].append("game/datafiles/images")
        self.entry["sources"] = ["art/paint/badge.ora"]
        self.write_file(self.entry["sources"][0])
        self.use_included_file("game/datafiles/images/badge.webp")
        self.policy["assets"]["pipelines"]["audio"] = {
            "source_roots": ["music/compositions"],
            "runtime_roots": ["game/datafiles/music"],
            "native_resource_roots": ["project/sounds"],
            "source_extensions": [".mid"],
            "runtime_extensions": [".ogg"],
        }
        audio = {
            "kind": "audio",
            "completion": "final",
            "sources": ["music/compositions/theme.mid"],
            "runtime": ["project/sounds/snd_theme/theme.ogg"],
            "destination": {
                "kind": "native-resource",
                "resource": "project/sounds/snd_theme/snd_theme.yy",
            },
        }
        for name in audio["sources"] + audio["runtime"]:
            self.write_file(name)
        self.write_file(audio["destination"]["resource"], "{}")
        self.assertEqual(self.validate([self.entry, audio]), [])

    def test_wrong_pipeline_source_location_is_rejected(self):
        self.entry["sources"] = ["other/source/badge.kra"]
        self.write_file(self.entry["sources"][0])
        self.assert_rejected(self.validate(), self.entry["sources"][0])

    def test_wrong_included_runtime_location_is_rejected(self):
        self.use_included_file("other/runtime/badge.png")
        self.assert_rejected(self.validate(), self.entry["runtime"][0])

    def test_included_file_cannot_claim_a_native_embedded_output(self):
        self.entry["destination"] = {
            "kind": "included-file",
            "file_contract": "Runtime reads image bytes for user edits.",
        }
        self.assert_rejected(self.validate(), self.entry["runtime"][0])

    def test_native_descriptor_must_be_in_the_pipeline_native_roots(self):
        resource = "project/sounds/spr_badge/spr_badge.yy"
        self.entry["destination"]["resource"] = resource
        self.write_file(resource, "{}")
        self.assert_rejected(self.validate(), resource)

    def test_native_output_must_belong_to_the_named_resource(self):
        for name in (
            "project/sprites/spr_other/frame.png",
            "project/sprites/spr_badge_extra/frame.png",
            "assets/runtime/badge.png",
        ):
            with self.subTest(name=name):
                self.entry["runtime"] = [name]
                self.write_file(name)
                self.assert_rejected(self.validate(), name)

    def test_native_resource_descriptor_can_itself_be_the_export(self):
        self.policy["assets"]["pipelines"]["raster"][
            "runtime_extensions"
        ].append(".yy")
        self.entry["runtime"] = [self.entry["destination"]["resource"]]
        self.assertEqual(self.validate(), [])

    def test_native_resource_descriptor_requires_yy_extension(self):
        resource = "project/sprites/spr_badge/metadata.json"
        self.entry["destination"]["resource"] = resource
        self.write_file(resource, "{}")
        self.assert_rejected(self.validate(), resource)

    def test_native_resource_descriptor_must_exist_and_be_tracked(self):
        resource = self.entry["destination"]["resource"]
        (self.root / resource).unlink()
        self.assert_rejected(self.validate(), resource)
        self.write_file(resource, "{}")
        self.files.remove(Path(resource))
        self.assert_rejected(self.validate(), resource)

    def test_destination_requires_an_explicit_known_representation(self):
        for destination in (None, {}, "native-resource", {"kind": "external"}):
            with self.subTest(destination=destination):
                self.entry["destination"] = destination
                self.assert_rejected(self.validate())

    def test_destinations_reject_ambiguous_or_unrecognized_fields(self):
        native = copy.deepcopy(self.entry["destination"])
        included = {
            "kind": "included-file",
            "file_contract": "Runtime reads image bytes for user edits.",
        }
        for destination in (
            {**native, "file_contract": "Runtime reads image bytes."},
            {**native, "other": "unrecognized"},
            {**included, "resource": native["resource"]},
        ):
            with self.subTest(destination=destination):
                self.entry["destination"] = destination
                self.assert_rejected(self.validate())

    def test_included_files_require_a_nonempty_file_contract_reason(self):
        self.use_included_file()
        for reason in (None, "", "  \n", 12, []):
            with self.subTest(reason=reason):
                self.entry["destination"] = {"kind": "included-file"}
                if reason is not None:
                    self.entry["destination"]["file_contract"] = reason
                self.assert_rejected(self.validate())

    def test_file_contracts_allow_data_beyond_json_and_vbuff(self):
        pipeline = self.policy["assets"]["pipelines"]["raster"]
        pipeline["runtime_extensions"] = [".json", ".vbuff", ".csv", ".bin"]
        for suffix in pipeline["runtime_extensions"]:
            with self.subTest(suffix=suffix):
                name = "assets/runtime/data" + suffix
                self.use_included_file(name)
                self.entry["destination"]["file_contract"] = (
                    "The runtime reads this modifiable data file by path."
                )
                self.assertEqual(self.validate(), [])
                self.files.remove(Path(name))
                (self.root / name).unlink()

    def test_unsupported_source_and_runtime_extensions_are_rejected(self):
        for field, name in (
            ("sources", "assets/source/badge.txt"),
            ("runtime", "project/sprites/spr_badge/frame.txt"),
        ):
            with self.subTest(field=field):
                original = self.entry[field]
                self.entry[field] = [name]
                self.write_file(name)
                self.assert_rejected(self.validate())
                self.entry[field] = original

    def test_required_source_companions_are_explicit(self):
        pipeline = self.policy["assets"]["pipelines"]["raster"]
        pipeline["source_extensions"] = [".blend", ".obj", ".mtl"]
        pipeline["required_source_extensions"] = [".obj", ".mtl"]
        self.entry["sources"] = ["assets/source/shape.obj"]
        self.write_file(self.entry["sources"][0])
        self.assert_rejected(self.validate())
        self.entry["sources"].append("assets/source/shape.mtl")
        self.write_file(self.entry["sources"][1])
        self.assertEqual(self.validate(), [])

    def test_required_runtime_companions_are_explicit(self):
        pipeline = self.policy["assets"]["pipelines"]["raster"]
        pipeline["runtime_extensions"] = [".png", ".json"]
        pipeline["required_runtime_extensions"] = [".png", ".json"]
        self.assert_rejected(self.validate())
        self.entry["runtime"].append("project/sprites/spr_badge/atlas.json")
        self.write_file(self.entry["runtime"][1], "{}")
        self.assertEqual(self.validate(), [])

    def test_sources_and_runtime_paths_reject_absolute_and_parent_traversal(self):
        for field, paths in (
            ("sources", ["/outside/badge.kra", "assets/source/../badge.kra"]),
            ("runtime", ["/outside/badge.png", "assets/runtime/../badge.png"]),
        ):
            for name in paths:
                with self.subTest(field=field, name=name):
                    original = self.entry[field]
                    self.entry[field] = [name]
                    self.assert_rejected(self.validate(), name)
                    self.entry[field] = original

    def test_native_descriptor_rejects_absolute_and_parent_traversal(self):
        for resource in (
            "/outside/spr_badge.yy",
            "project/sprites/../spr_badge/spr_badge.yy",
        ):
            with self.subTest(resource=resource):
                self.entry["destination"]["resource"] = resource
                self.assert_rejected(self.validate(), resource)

    def test_source_and_runtime_files_must_exist_and_be_tracked(self):
        for field in ("sources", "runtime"):
            with self.subTest(field=field):
                name = self.entry[field][0]
                (self.root / name).unlink()
                self.assert_rejected(self.validate(), name)
                self.write_file(name)
                self.files.remove(Path(name))
                self.assert_rejected(self.validate(), name)
                self.files.append(Path(name))

    def test_export_cannot_map_the_same_runtime_output_twice(self):
        self.assert_rejected(self.validate([self.entry, copy.deepcopy(self.entry)]))

    def test_unmapped_files_in_each_dedicated_runtime_root_are_rejected(self):
        self.policy["assets"]["pipelines"]["raster"][
            "runtime_roots"
        ].append("extra/exports")
        for name in ("assets/runtime/unmapped.png", "extra/exports/unmapped.png"):
            with self.subTest(name=name):
                self.write_file(name)
                self.assert_rejected(self.validate(), name)
                self.files.remove(Path(name))
                (self.root / name).unlink()

    def test_undeclared_pipeline_is_rejected(self):
        self.entry["kind"] = "unknown"
        self.assert_rejected(self.validate())

    def test_source_directory_packages_accept_fully_tracked_descendants(self):
        pipeline = self.policy["assets"]["pipelines"]["raster"]
        pipeline["source_extensions"].append(".logicx")
        self.entry["sources"] = ["assets/source/theme.logicx"]
        self.write_file("assets/source/theme.logicx/Alternatives/000/ProjectData")
        self.write_file("assets/source/theme.logicx/Media/instrument.aif")
        self.assertEqual(self.validate(), [])

    def test_source_packages_reject_untracked_descendants(self):
        self.test_source_directory_packages_accept_fully_tracked_descendants()
        name = "assets/source/theme.logicx/Media/untracked.aif"
        self.write_file(name, tracked=False)
        self.assert_rejected(self.validate(), "theme.logicx")

    def test_source_packages_reject_missing_tracked_descendants(self):
        self.test_source_directory_packages_accept_fully_tracked_descendants()
        (self.root / "assets/source/theme.logicx/Media/instrument.aif").unlink()
        self.assert_rejected(self.validate(), "theme.logicx")

    def test_empty_or_untracked_source_packages_are_rejected(self):
        self.policy["assets"]["pipelines"]["raster"][
            "source_extensions"
        ].append(".logicx")
        self.entry["sources"] = ["assets/source/theme.logicx"]
        (self.root / self.entry["sources"][0]).mkdir(parents=True)
        self.assert_rejected(self.validate(), "theme.logicx")
        self.write_file("assets/source/theme.logicx/ProjectData", tracked=False)
        self.assert_rejected(self.validate(), "theme.logicx")

    def test_package_prefix_sibling_does_not_count_as_a_tracked_descendant(self):
        self.policy["assets"]["pipelines"]["raster"][
            "source_extensions"
        ].append(".logicx")
        self.entry["sources"] = ["assets/source/theme.logicx"]
        (self.root / self.entry["sources"][0]).mkdir(parents=True)
        self.write_file("assets/source/theme.logicx-backup/ProjectData")
        self.assert_rejected(self.validate(), "theme.logicx")

    def test_nested_lfs_json_pointer_is_opaque_but_materialized_json_is_checked(self):
        name = "assets/source/theme.logicx/Media/cache.json"
        self.write_file(name, LFS_POINTER)
        errors: list[str] = []
        validate_json(self.root, [Path(name)], errors)
        self.assertEqual(errors, [])
        self.write_file(name, '{"tracks": [1, 2]}')
        validate_json(self.root, [Path(name)], errors)
        self.assertEqual(errors, [])
        self.write_file(name, '{"tracks": [}')
        validate_json(self.root, [Path(name)], errors)
        self.assert_rejected(errors, name)

    def test_malformed_lfs_pointer_does_not_bypass_json_validation(self):
        name = "content/data.json"
        for content in (
            LFS_POINTER.replace("a" * 64, "a" * 63),
            LFS_POINTER.replace("size 1024", "size unknown"),
            LFS_POINTER.replace("oid sha256:", "oid sha1:"),
            LFS_POINTER + "unrecognized trailing contents\n",
            LFS_POINTER.rstrip("\n"),
            LFS_POINTER.replace("\n", "\r\n"),
            LFS_EXTENDED_POINTER.replace("ext-1-encrypt", "ext-0-encrypt"),
            LFS_EXTENDED_POINTER.replace("ext-0-compress", "ext-2-compress"),
            LFS_EXTENDED_POINTER.replace("ext-0-compress", "ext-0-Compress"),
            LFS_EXTENDED_POINTER.replace("b" * 64, "b" * 63),
            LFS_EXTENDED_POINTER.replace("ext-0-compress", "ext-0-" + "x" * 1024),
        ):
            with self.subTest(content=content):
                self.write_file(name, content)
                errors: list[str] = []
                validate_json(self.root, [Path(name)], errors)
                self.assert_rejected(errors, name)

    def test_valid_lfs_extensions_are_not_interpreted_as_json_or_svg(self):
        name = "assets/source/theme.logicx/Media/cache.json"
        self.write_file(name, LFS_EXTENDED_POINTER)
        errors: list[str] = []
        validate_json(self.root, [Path(name)], errors)
        self.assertEqual(errors, [])
        self.policy["assets"]["pipelines"]["raster"]["runtime_extensions"] = [".svg"]
        name = "project/sprites/spr_badge/frame.svg"
        self.entry["runtime"] = [name]
        self.write_file(name, LFS_EXTENDED_POINTER)
        self.assertEqual(self.validate(), [])

    def test_malformed_lfs_pointer_is_not_accepted_as_plain_runtime_svg(self):
        self.policy["assets"]["pipelines"]["raster"]["runtime_extensions"] = [".svg"]
        name = "project/sprites/spr_badge/frame.svg"
        self.entry["runtime"] = [name]
        self.write_file(name, LFS_POINTER.replace("size 1024", "size unknown"))
        self.assert_rejected(self.validate(), name)

    def test_runtime_svg_lfs_pointer_and_materialized_content(self):
        pipeline = self.policy["assets"]["pipelines"]["raster"]
        pipeline["runtime_extensions"] = [".svg"]
        name = "project/sprites/spr_badge/frame.svg"
        self.entry["runtime"] = [name]
        self.write_file(name, LFS_POINTER)
        self.assertEqual(self.validate(), [])
        self.write_file(name, '<svg xmlns="http://www.w3.org/2000/svg"/>')
        self.assertEqual(self.validate(), [])
        self.write_file(name, '<svg xmlns:inkscape="http://www.inkscape.org"/>')
        self.assert_rejected(self.validate(), name)

    def test_lfs_runtime_pointer_still_requires_ownership_and_tracking(self):
        name = self.entry["runtime"][0]
        self.write_file(name, LFS_POINTER)
        self.files.remove(Path(name))
        self.assert_rejected(self.validate(), name)
        self.files.append(Path(name))
        self.assert_rejected(self.validate([self.entry, copy.deepcopy(self.entry)]))

    def test_pointer_and_materialized_packages_preserve_the_same_asset_contract(self):
        self.test_source_directory_packages_accept_fully_tracked_descendants()
        name = "assets/source/theme.logicx/Media/cache.json"
        for content in (LFS_POINTER, '{"tracks": []}'):
            with self.subTest(content=content):
                self.write_file(name, content)
                errors = self.validate()
                validate_json(self.root, self.files, errors)
                self.assertEqual(errors, [])

    def test_new_asset_format_restriction_is_not_an_inherited_error(self):
        self.assertEqual(self.validate(), [])
        checker = self.root / "tools/ci/check_repo.py"
        checker.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / "tools/ci/check_repo.py", checker)
        self.write_file(
            "PROJECT_POLICY.toml",
            '''[structure]
max_source_lines = 800
source_extensions = []
forbidden_generic_stems = []
large_file_exceptions = []
[assets]
manifest = "assets/exports.json"
plain_runtime_svg = true
[assets.pipelines.raster]
source_roots = ["assets/source"]
runtime_roots = ["assets/runtime"]
native_resource_roots = ["project/sprites"]
source_extensions = [".kra"]
runtime_extensions = [".png"]
''',
        )
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        subprocess.run(["git", "add", "."], cwd=self.root, check=True)
        baseline = baseline_policy_errors(self.root)
        self.assertEqual(baseline, [])

        self.policy["assets"]["pipelines"]["raster"]["runtime_extensions"] = [".webp"]
        candidate = self.validate()
        self.assert_rejected(candidate)
        self.assertEqual(
            new_policy_errors(candidate, baseline, {"PROJECT_POLICY.toml"}, strict=True),
            candidate,
        )


if __name__ == "__main__":
    unittest.main()

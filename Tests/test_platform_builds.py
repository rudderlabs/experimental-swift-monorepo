"""Release-time platform builds, with only swift and xcodebuild modeled."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ["GIT_CONFIG_GLOBAL"] = os.devnull  # ignore personal git settings such as tag.gpgsign
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import common
from common import NAMES, git, write_json
from publish import platform_builds, publish

FOUR = ["iOS 15", "macOS 12", "tvOS 15", "watchOS 8"]


class PlatformBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls, self.failing = [], None

    def run_command(self, args, cwd=common.ROOT, env=None):
        if args[0] not in ("swift", "xcodebuild"):
            return common.run(args, cwd=cwd, env=env)
        self.calls.append((args, cwd, env))
        if args[0] == "xcodebuild" and args[args.index("-destination") + 1] == self.failing:
            raise RuntimeError("Command failed: xcodebuild ['build', '-quiet']\n\nerror: no such module")
        return ""

    def builds(self, platforms):
        with patch("publish.run", side_effect=self.run_command):
            platform_builds(self.root / "export", {"target": "Kit", "platforms": platforms}, self.root / "state")
        return [args[args.index("-destination") + 1] for args, _, _ in self.calls]

    def test_ios_only_package_builds_once_without_credentials(self):
        self.assertEqual(self.builds(["iOS 15"]), ["generic/platform=iOS"])
        args, cwd, env = self.calls[0]
        self.assertEqual(args[:5], ["xcodebuild", "build", "-quiet", "-scheme", "Kit"])
        for flag, value in [("-scmProvider", "system"), ("-clonedSourcePackagesDirPath", self.root / "state/xcode-packages"),
                            ("-packageCachePath", self.root / "state/xcode-cache"),
                            ("-derivedDataPath", self.root / "state/xcode-build")]:
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertIn("CODE_SIGNING_ALLOWED=NO", args)
        self.assertEqual(cwd, self.root / "export")
        self.assertEqual(env["GIT_CONFIG_VALUE_0"], "")
        self.assertNotIn("GH_TOKEN", env)

    def test_every_declared_platform_builds_in_order(self):
        self.assertEqual(self.builds(FOUR), ["generic/platform=iOS", "generic/platform=macOS",
                                             "generic/platform=tvOS", "generic/platform=watchOS"])
        self.assertEqual(self.builds(["macCatalyst 15", "visionOS 1"])[4:],
                         ["generic/platform=macOS,variant=Mac Catalyst", "generic/platform=visionOS"])

    def test_failing_platform_stops_publication_before_writes(self):
        remotes = self.root / "remotes"
        remote = remotes / (NAMES["sprig"] + ".git")
        common.run(["git", "init", "--bare", "--initial-branch=main", remote])
        write_json(self.root / "source/release/packages.json", {"schemaVersion": 1, "packages": {
            "sprig": {"repository": NAMES["sprig"], "target": "Kit", "platforms": FOUR}}})
        def export(key, version, stage, root):
            stage.mkdir(parents=True)
            (stage / "Package.swift").write_text("// swift-tools-version: 5.9\n")
            return {"version": version, "sourceCommit": "a" * 40}
        self.failing = "generic/platform=tvOS"
        with patch("publish.export", side_effect=export), patch("publish.mirrors"), \
             patch("publish.run", side_effect=self.run_command):
            with self.assertRaisesRegex(RuntimeError, r"Release build failed for tvOS 15 \(generic/platform=tvOS\)"):
                publish("sprig", "1.0.0", remotes, root=self.root / "source")
        self.assertEqual([args[0] for args, _, _ in self.calls], ["swift", "xcodebuild", "xcodebuild", "xcodebuild"])
        self.assertEqual(git(remote, "for-each-ref"), "")
        self.assertFalse((self.root / "modeled-github-releases").exists())


if __name__ == "__main__":
    unittest.main()

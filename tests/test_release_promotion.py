import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ReleasePromotionTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.stable = {
            "tagName": "v0.35.0-beta",
            "publishedAt": "2026-09-10T12:00:00Z",
            "assets": [
                {"name": "org.opentubex.app-0.35.0-alpha.apk"},
                {"name": "opentubex-0.35.0-android-universal.apk"},
            ],
        }
        self.nightly = {
            "tagName": "v0.35.0-nightly-1234",
            "publishedAt": "2026-09-09T12:00:00Z",
            "createdAt": "2026-09-09T12:00:00Z",
            "isPrerelease": True,
            "assets": [{"name": "opentubex-0.35.0-nightly-1234-android-universal.apk"}],
        }
        mock = self.directory / "gh"
        mock.write_text('''#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
releases = json.loads(Path("releases.json").read_text())
if args[:2] == ["release", "list"]:
    result = releases[1:]
elif args[:2] == ["release", "view"]:
    tag = args[2] if not args[2].startswith("--") else releases[0]["tagName"]
    result = next(release for release in releases if release["tagName"] == tag)
elif args[:2] == ["release", "download"]:
    release = next(release for release in releases if release["tagName"] == args[2])
    name = args[args.index("--pattern") + 1]
    if name not in [asset["name"] for asset in release["assets"]]:
        sys.exit(1)
    (Path(args[args.index("--dir") + 1]) / name).write_text(release["tagName"])
    sys.exit(0)
else:
    raise AssertionError(args)
if "--jq" in args:
    process = subprocess.run(["jq", "-r", args[args.index("--jq") + 1]],
                             input=json.dumps(result), text=True)
    sys.exit(process.returncode)
print(json.dumps(result))
''')
        mock.chmod(0o755)

    def publish(self, tag=""):
        releases = [self.stable] + ([self.nightly] if self.nightly else [])
        (self.directory / "releases.json").write_text(json.dumps(releases))
        workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
        steps = workflow["jobs"]["publish"]["steps"]
        resolve = next(step for step in steps if step.get("name") == "Resolve releases")
        download = next(step for step in steps if step.get("name") == "Download Android APKs")
        output = self.directory / "output"
        env = dict(os.environ, PATH=f"{self.directory}:{os.environ['PATH']}",
                   INPUT_TAG=tag, GITHUB_OUTPUT=str(output))
        result = subprocess.run(["bash", "-c", resolve["run"]], cwd=self.directory,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        for key, value in download["env"].items():
            env[key] = outputs[value.removeprefix("${{ steps.release.outputs.").removesuffix(" }}")]
        result = subprocess.run(["bash", "-c", download["run"]], cwd=self.directory,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return {file.name: file.read_text() for file in (self.directory / "incoming").iterdir()}

    def test_stable_dispatch_updates_existing_nightly_installations(self):
        files = self.publish(self.stable["tagName"])
        self.assertEqual(files, {
            "org.opentubex.app-0.35.0-alpha.apk": self.stable["tagName"],
            "opentubex-0.35.0-android-universal.apk": self.stable["tagName"],
        })

    def test_refresh_preserves_stable_promotion(self):
        self.assertIn("opentubex-0.35.0-android-universal.apk", self.publish())

    def test_refresh_keeps_a_newer_nightly(self):
        self.nightly["publishedAt"] = "2026-09-11T12:00:00Z"
        self.assertIn(self.nightly["assets"][0]["name"], self.publish())

    def test_new_nightly_dispatch_updates_the_nightly_package(self):
        self.nightly["publishedAt"] = "2026-09-11T12:00:00Z"
        self.assertIn(self.nightly["assets"][0]["name"], self.publish(self.nightly["tagName"]))

    def test_stable_can_supply_the_first_nightly_package(self):
        self.nightly = None
        self.assertIn("opentubex-0.35.0-android-universal.apk", self.publish(self.stable["tagName"]))

    def test_old_stable_without_promotion_apk_keeps_existing_nightly(self):
        self.stable["assets"].pop()
        self.assertIn(self.nightly["assets"][0]["name"], self.publish())


if __name__ == "__main__":
    unittest.main()

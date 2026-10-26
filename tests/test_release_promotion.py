import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class ReleasePromotionTest(unittest.TestCase):
    def test_promotion_provisions_native_build_dependencies(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
        steps = workflow["jobs"]["publish"]["steps"]
        checkout = next(step for step in steps if step.get("name") == "Check out stable Android source")
        build = next(step for step in steps if step.get("name") == "Build stable code for nightly installations")
        setup = next(step for step in steps
                     if step.get("uses", "").startswith("android-actions/setup-android@"))
        self.assertIn("ndk;28.2.13676358", setup["with"]["packages"].split())
        go = next(step for step in steps
                  if step.get("uses", "").startswith("actions/setup-go@"))
        self.assertEqual(go["with"]["go-version-file"], "source/_scripts/cast-sender/go.mod")
        self.assertFalse(go["with"]["cache"])
        self.assertIn("steps.release.outputs.promote_stable == 'true'", go["if"])
        self.assertIn("hashFiles('source/_scripts/cast-sender/go.mod') != ''", go["if"])
        packer = next(step for step in steps if step.get("name") == "Install Android runtime packer")
        self.assertEqual(packer["if"], "steps.release.outputs.promote_stable == 'true'")
        self.assertIn("install --yes 7zip", packer["run"])
        for dependency in (setup, go, packer):
            self.assertLess(steps.index(checkout), steps.index(dependency))
            self.assertLess(steps.index(dependency), steps.index(build))

    def test_android_setup_does_not_request_removed_tools_package(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
        steps = workflow["jobs"]["publish"]["steps"]
        setup = next(step for step in steps
                     if step.get("uses", "").startswith("android-actions/setup-android@"))
        # The pinned action defaults to "tools platform-tools", but Google
        # no longer serves the legacy "tools" package.
        packages = setup.get("with", {}).get("packages", "tools platform-tools").split()
        self.assertNotIn("tools", packages)
        self.assertIn("platform-tools", packages)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)
        self.stable = {
            "tagName": "v0.35.0-beta",
            "publishedAt": "2026-09-10T12:00:00Z",
            "assets": [
                {"name": "org.opentubex.app-0.35.0-beta.apk"},
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
import fnmatch
import json
from pathlib import Path
import subprocess
import sys

args = sys.argv[1:]
releases = json.loads(Path("releases.json").read_text())
assert args[args.index("--repo") + 1] == "OpenTubeX/OpenTubeX"
if args[:2] == ["release", "list"]:
    result = releases[1:]
elif args[:2] == ["release", "view"]:
    tag = args[2] if not args[2].startswith("--") else releases[0]["tagName"]
    result = next(release for release in releases if release["tagName"] == tag)
elif args[:2] == ["release", "download"]:
    release = next(release for release in releases if release["tagName"] == args[2])
    pattern = args[args.index("--pattern") + 1]
    names = [asset["name"] for asset in release["assets"] if fnmatch.fnmatchcase(asset["name"], pattern)]
    if not names:
        sys.exit(1)
    for name in names:
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
        if outputs.get("promote_stable") == "true":
            checkout = next(step for step in steps if step.get("name") == "Check out stable Android source")
            self.assertEqual(checkout["with"]["repository"], "OpenTubeX/OpenTubeX")
            self.assertEqual(checkout["with"]["ref"], "${{ steps.release.outputs.stable_tag }}")
            self.assertEqual(checkout["with"]["fetch-depth"], 0)
            build = next(step for step in steps if step.get("name") == "Build stable code for nightly installations")
            source = self.directory / "source"
            (source / "android").mkdir(parents=True)
            (source / "bin").mkdir()
            stubs = {
                "bin/git": "#!/bin/sh\necho 12345\n",
                "bin/pnpm": "#!/bin/sh\nexit 0\n",
                "android/gradlew": '#!/bin/sh\nprintf "%s|%s|%s\\n" "$*" "$ANDROID_VERSION_CODE" "$ANDROID_VERSION_NAME" >> gradle.log\n',
                "bin/python3": '''#!/bin/sh
if [ "$1" = "-m" ]; then
    test "$*" = "-m unittest discover -s tests/android" || exit 1
    test ! -f gradle.log || exit 1
    touch packaging-tests-passed
    exit 0
fi
test -f packaging-tests-passed || exit 1
mkdir "$3"
flavor=""
test "$4" = "--lite" && flavor="lite-"
for abi in arm64-v8a armeabi-v7a x86 x86_64 universal; do
    printf "%s" "$STABLE_TAG" > "$3/opentubex-$ANDROID_VERSION_NAME-android-$flavor$abi.apk"
done
''',
            }
            for name, script in stubs.items():
                (source / name).write_text(script)
                (source / name).chmod(0o755)
            env.update(PATH=f"{source / 'bin'}:{env['PATH']}", GITHUB_WORKSPACE=str(self.directory))
            for key, value in build.get("env", {}).items():
                env[key] = outputs[value.removeprefix("${{ steps.release.outputs.").removesuffix(" }}")]
            result = subprocess.run(["bash", "-c", build["run"]], cwd=source,
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            gradle = (source / "gradle.log").read_text().splitlines()
            self.assertEqual(len(gradle), 2 if outputs["stable_has_lite"] == "true" else 1)
            for invocation in gradle:
                self.assertIn(":app:assembleNightly -PsplitApks", invocation)
                self.assertNotIn(":app:assembleRelease", invocation)
                self.assertTrue(invocation.endswith("|24691|0.35.0"), invocation)
            self.assertNotIn("-Plite", gradle[0])
            if len(gradle) == 2:
                self.assertIn("-Plite", gradle[1])
        return {file.name: file.read_text() for file in (self.directory / "incoming").iterdir()}

    def test_stable_dispatch_updates_existing_nightly_installations(self):
        files = self.publish(self.stable["tagName"])
        self.assertEqual(files, {
            "org.opentubex.app-0.35.0-beta.apk": self.stable["tagName"],
            **{f"opentubex-0.35.0-android-{abi}.apk": self.stable["tagName"]
               for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64", "universal")},
        })

    def test_stable_dispatch_publishes_lite_apps(self):
        lite = [f"org.opentubex.app-0.35.0-beta-lite{suffix}.apk"
                for suffix in ("", "-arm64-v8a", "-armeabi-v7a", "-x86", "-x86_64")]
        self.stable["assets"] += [{"name": name} for name in lite]
        files = self.publish(self.stable["tagName"])
        self.assertEqual(files, {
            "org.opentubex.app-0.35.0-beta.apk": self.stable["tagName"],
            **{name: self.stable["tagName"] for name in lite},
            **{f"opentubex-0.35.0-android-{flavor}{abi}.apk": self.stable["tagName"]
               for flavor in ("", "lite-")
               for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64", "universal")},
        })

    def test_downloads_all_stable_and_nightly_architectures(self):
        self.nightly["publishedAt"] = "2026-09-11T12:00:00Z"
        for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64"):
            self.stable["assets"].append({"name": f"org.opentubex.app-0.35.0-beta-{abi}.apk"})
            self.nightly["assets"].append({"name": f"opentubex-0.35.0-nightly-1234-android-{abi}.apk"})
        for abi in ("arm64-v8a", "armeabi-v7a", "x86", "x86_64", "universal"):
            self.nightly["assets"].append({"name": f"opentubex-0.35.0-nightly-1234-android-lite-{abi}.apk"})
        expected = {asset["name"]: release["tagName"]
                    for release in (self.stable, self.nightly) for asset in release["assets"]}
        self.stable["assets"].append({"name": "org.opentubex.app-0.35.0-beta.apk.sha256"})
        self.nightly["assets"].append({"name": "opentubex-0.35.0-nightly-1234-android-arm64-v8a.apk.sha256"})
        self.assertEqual(self.publish(self.nightly["tagName"]), expected)

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

    def test_stable_without_android_apk_keeps_existing_nightly(self):
        self.stable["assets"] = []
        self.assertIn(self.nightly["assets"][0]["name"], self.publish())


    def test_skips_lite_apks_without_a_lite_app_id(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
        steps = workflow["jobs"]["publish"]["steps"]
        skip = next(step for step in steps if step.get("name") == "Skip lite APKs without a Lite app ID")
        build = next(step for step in steps if step.get("name") == "Build signed F-Droid index and landing page")
        self.assertLess(steps.index(skip), steps.index(build))
        package = self.directory / "fdroidserver"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "common.py").write_text(
            "from pathlib import Path\n"
            "config = None\n"
            "def get_apk_id(path):\n"
            "    return Path(path).read_text(), 1, '1'\n"
        )
        incoming = self.directory / "incoming"
        incoming.mkdir()
        apks = {
            "opentubex-0.35.0-nightly-1234-android-arm64-v8a.apk": "org.opentubex.app.nightly",
            "opentubex-0.35.0-nightly-1234-android-lite-arm64-v8a.apk": "org.opentubex.app.nightly",
            "opentubex-0.35.0-nightly-1235-android-lite-x86.apk": "org.opentubex.app.nightly.lite",
            "org.opentubex.app-0.35.0-beta-lite.apk": "org.opentubex.app",
            "org.opentubex.app-0.35.1-beta-lite.apk": "org.opentubex.app.lite",
        }
        for name, app_id in apks.items():
            (incoming / name).write_text(app_id)
        env = dict(os.environ, PYTHONPATH=str(self.directory))
        result = subprocess.run(["bash", "-c", skip["run"].replace("python -", f"{sys.executable} -")],
                                cwd=self.directory, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(file.name for file in incoming.iterdir()), [
            "opentubex-0.35.0-nightly-1234-android-arm64-v8a.apk",
            "opentubex-0.35.0-nightly-1235-android-lite-x86.apk",
            "org.opentubex.app-0.35.1-beta-lite.apk",
        ])


class StableReleaseNotesTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        mock = self.directory / "gh"
        mock.write_text("""#!/bin/sh
test "$1 $2 $3" = "api --header Accept: application/vnd.github.raw" || exit 2
test "$4" = "repos/OpenTubeX/OpenTubeX/contents/fastlane/metadata/android/en-US/changelogs/default.txt?ref=v0.38.0-beta" || exit 2
test -f notes.txt || exit 1
cat notes.txt
""")
        mock.chmod(0o755)

    def add_notes(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
        steps = workflow["jobs"]["publish"]["steps"]
        notes = next(step for step in steps if step.get("name") == "Add stable release notes")
        build = next(step for step in steps if step.get("name") == "Build signed F-Droid index and landing page")
        self.assertLess(steps.index(notes), steps.index(build))
        self.assertEqual(notes["env"]["STABLE_TAG"], "${{ steps.release.outputs.stable_tag }}")
        env = dict(os.environ, PATH=f"{self.directory}:{os.environ['PATH']}", STABLE_TAG="v0.38.0-beta")
        result = subprocess.run(["bash", "-c", notes["run"]], cwd=self.directory,
                                env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_copies_the_stable_changelog_to_the_stable_apps(self):
        (self.directory / "notes.txt").write_text("Highlights\n• Added groups\n")
        self.add_notes()
        for app_id in ("org.opentubex.app", "org.opentubex.app.lite"):
            changelog = self.directory / "metadata" / app_id / "en-US" / "changelogs" / "default.txt"
            self.assertEqual(changelog.read_text(), "Highlights\n• Added groups\n")
        self.assertFalse((self.directory / "metadata" / "org.opentubex.app.nightly").exists())

    def test_skips_releases_without_a_changelog(self):
        result = self.add_notes()
        self.assertIn("has no F-Droid changelog", result.stdout)
        self.assertFalse((self.directory / "metadata").exists())

if __name__ == "__main__":
    unittest.main()

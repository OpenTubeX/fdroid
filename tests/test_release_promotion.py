import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
ABIS = ("arm64-v8a", "armeabi-v7a", "x86", "x86_64")


def step(job, name):
    return next(step for step in WORKFLOW["jobs"][job]["steps"] if step.get("name") == name)


def outputs_env(step_env, outputs):
    return {key: outputs[value.split(".")[-1].removesuffix(" }}")]
            for key, value in step_env.items() if "steps." in value}


class ReleasePromotionTest(unittest.TestCase):
    def test_promotion_provisions_native_build_dependencies(self):
        steps = WORKFLOW["jobs"]["prepare"]["steps"]
        checkout = step("prepare", "Check out OpenTubeX")
        build = step("prepare", "Build stable code for nightly installations")
        setup = next(item for item in steps
                     if item.get("uses", "").startswith("android-actions/setup-android@"))
        self.assertIn("ndk;28.2.13676358", setup["with"]["packages"].split())
        go = next(item for item in steps if item.get("uses", "").startswith("actions/setup-go@"))
        self.assertEqual(go["with"]["go-version-file"], "source/_scripts/cast-sender/go.mod")
        self.assertFalse(go["with"]["cache"])
        packer = step("prepare", "Install Android runtime packer")
        self.assertIn("install --yes 7zip", packer["run"])
        for dependency in (setup, go, packer):
            self.assertEqual(dependency["if"], "steps.promotion.outputs.promote_stable == 'true'")
            self.assertLess(steps.index(checkout), steps.index(dependency))
            self.assertLess(steps.index(dependency), steps.index(build))

    def test_android_setup_does_not_request_removed_tools_package(self):
        setup = next(item for item in WORKFLOW["jobs"]["prepare"]["steps"]
                     if item.get("uses", "").startswith("android-actions/setup-android@"))
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
            "commits": 12345,
            "assets": [{"name": f"org.opentubex.app-0.35.0-beta{flavor}{abi}.apk"}
                       for flavor in ("", "-lite") for abi in ("", *(f"-{abi}" for abi in ABIS))],
        }
        self.nightly = {
            "tagName": "v0.35.0-nightly-1234",
            "publishedAt": "2026-09-09T12:00:00Z",
            "createdAt": "2026-09-09T12:00:00Z",
            "isPrerelease": True,
            "commits": 12340,
            "assets": [{"name": f"opentubex-0.35.0-nightly-1234-android-{flavor}{abi}.apk"}
                       for flavor in ("", "lite-") for abi in (*ABIS, "universal")],
        }
        bin_directory = self.directory / "bin"
        bin_directory.mkdir()
        mocks = {
            "gh": '''#!/usr/bin/env python3
import fnmatch
import json
from pathlib import Path
import os
import subprocess
import sys

args = sys.argv[1:]
releases = json.loads(Path(os.environ["RELEASES"]).read_text())
assert args[args.index("--repo") + 1] == "OpenTubeX/OpenTubeX"
if args[:2] == ["release", "list"]:
    result = releases[1:]
elif args[:2] == ["release", "view"]:
    result = releases[0]
elif args[:2] == ["release", "download"]:
    release = next(release for release in releases if release["tagName"] == args[2])
    patterns = [args[index + 1] for index, arg in enumerate(args) if arg == "--pattern"]
    names = [asset["name"] for asset in release["assets"]
             if any(fnmatch.fnmatchcase(asset["name"], pattern) for pattern in patterns)]
    if not names:
        sys.exit(1)
    directory = Path(args[args.index("--dir") + 1])
    directory.mkdir(exist_ok=True)
    for name in names:
        (directory / name).write_text(release["tagName"])
    sys.exit(0)
else:
    raise AssertionError(args)
process = subprocess.run(["jq", "-r", args[args.index("--jq") + 1]],
                         input=json.dumps(result), text=True)
sys.exit(process.returncode)
''',
            "git": '''#!/usr/bin/env python3
import json
from pathlib import Path
import os
import sys

assert sys.argv[1:3] == ["rev-list", "--count"], sys.argv
tag = sys.argv[3].removeprefix("refs/tags/")
releases = json.loads(Path(os.environ["RELEASES"]).read_text())
print(next(release["commits"] for release in releases if release["tagName"] == tag))
''',
            "pnpm": "#!/bin/sh\nexit 0\n",
            "python3": '''#!/bin/sh
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
    printf "%s" promoted > "$3/opentubex-$ANDROID_VERSION_NAME-android-$flavor$abi.apk"
done
''',
        }
        for name, script in mocks.items():
            # The python3 mock shadows the interpreter for the Python mocks.
            (bin_directory / name).write_text(script.replace("/usr/bin/env python3", sys.executable))
            (bin_directory / name).chmod(0o755)

    def run_step(self, step, env, cwd):
        result = subprocess.run(["bash", "-c", step["run"]], cwd=cwd, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def prepare(self, tag=""):
        releases = self.directory / "releases.json"
        releases.write_text(json.dumps([self.stable, self.nightly]))
        output = self.directory / "output"
        env = dict(os.environ, PATH=f"{self.directory / 'bin'}:{os.environ['PATH']}",
                   RELEASES=str(releases), INPUT_TAG=tag, GITHUB_OUTPUT=str(output),
                   GITHUB_WORKSPACE=str(self.directory))
        source = self.directory / "source"
        (source / "android").mkdir(parents=True)
        (source / "android/gradlew").write_text(
            '#!/bin/sh\nprintf "%s|%s|%s\\n" "$*" "$ANDROID_VERSION_CODE" "$ANDROID_VERSION_NAME" >> gradle.log\n')
        (source / "android/gradlew").chmod(0o755)

        self.run_step(step("prepare", "Resolve releases"), env, self.directory)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        compare = step("prepare", "Compare version codes")
        self.run_step(compare, env | outputs_env(compare["env"], outputs), source)
        outputs = dict(line.split("=", 1) for line in output.read_text().splitlines())
        download = step("prepare", "Download Android APKs")
        self.run_step(download, env | outputs_env(download["env"], outputs), self.directory)

        build = step("prepare", "Build stable code for nightly installations")
        self.assertEqual(build["if"], "steps.promotion.outputs.promote_stable == 'true'")
        self.promoted = outputs["promote_stable"] == "true"
        if self.promoted:
            self.run_step(build, env | outputs_env(build["env"], outputs), source)
            gradle = (source / "gradle.log").read_text().splitlines()
            # The first call only downloads the Gradle distribution.
            self.assertTrue(gradle.pop(0).startswith("--project-dir android --version|"))
            self.assertEqual(len(gradle), 2)
            for invocation in gradle:
                self.assertIn(":app:assembleNightly -PsplitApks", invocation)
                self.assertNotIn(":app:assembleRelease", invocation)
                self.assertTrue(invocation.endswith("|24691|0.35.0"), invocation)
            self.assertNotIn("-Plite", gradle[0])
            self.assertIn("-Plite", gradle[1])
        return {file.name: file.read_text() for file in (self.directory / "incoming").iterdir()}

    def expected_stable(self):
        return {f"org.opentubex.app-0.35.0-beta{flavor}-{abi}.apk": self.stable["tagName"]
                for flavor in ("", "-lite") for abi in ABIS}

    def test_stable_with_a_higher_version_code_updates_nightly_installations(self):
        self.assertEqual(self.prepare(self.stable["tagName"]), self.expected_stable() | {
            f"opentubex-0.35.0-android-{flavor}{abi}.apk": "promoted"
            for flavor in ("", "lite-") for abi in ABIS})
        self.assertTrue(self.promoted)

        sign = step("publish", "Sign promoted APKs with the nightly key")
        self.assertEqual(sign["if"], "needs.prepare.outputs.promote_stable == 'true'")
        script = self.directory / "signing/_scripts/sign-nightly-apks.sh"
        script.parent.mkdir(parents=True)
        script.write_text('#!/bin/sh\nprintf "%s\\n" "$(cat "$ANDROID_NIGHTLY_KEYSTORE")" "$@" > signed.log\n')
        script.chmod(0o755)
        (self.directory / "incoming").rename(self.directory / "repo")
        keystore = self.directory / "nightly-release.keystore"
        env = dict(os.environ, ANDROID_NIGHTLY_KEYSTORE=str(keystore),
                   ANDROID_NIGHTLY_KEYSTORE_BASE64="Zml4dHVyZQ==", ANDROID_NIGHTLY_STORE_PASSWORD="fixture")
        self.run_step(sign, env, self.directory)
        # Stable APKs keep the release key, and the private key leaves no copy behind.
        keystore_contents, *signed = (self.directory / "signed.log").read_text().splitlines()
        self.assertEqual(keystore_contents, "fixture")
        self.assertEqual(set(signed), {f"repo/opentubex-0.35.0-android-{flavor}{abi}.apk"
                                       for flavor in ("", "lite-") for abi in ABIS})
        self.assertFalse(keystore.exists())
        self.assertFalse((self.directory / "signing").exists())

        unconfigured = subprocess.run(["bash", "-c", sign["run"]], cwd=self.directory, capture_output=True, text=True,
                                      env=env | {"ANDROID_NIGHTLY_KEYSTORE_BASE64": ""})
        self.assertNotEqual(unconfigured.returncode, 0)

    def test_newer_nightly_keeps_its_own_apks(self):
        self.nightly["commits"] = 12346
        self.assertEqual(self.prepare(self.nightly["tagName"]), self.expected_stable() | {
            f"opentubex-0.35.0-nightly-1234-android-{flavor}{abi}.apk": self.nightly["tagName"]
            for flavor in ("", "lite-") for abi in ABIS})
        self.assertFalse(self.promoted)

    def test_newer_nightly_code_wins_over_a_later_stable_publication(self):
        # Development can move past the release commit before the release is published.
        self.stable["publishedAt"] = "2026-09-11T12:00:00Z"
        self.nightly["commits"] = 12350
        self.prepare()
        self.assertFalse(self.promoted)

    def test_higher_stable_code_wins_over_a_later_nightly_publication(self):
        self.nightly["publishedAt"] = "2026-09-11T12:00:00Z"
        self.prepare()
        self.assertTrue(self.promoted)


class StableReleaseNotesTest(unittest.TestCase):
    def test_copies_the_stable_changelog_to_the_stable_apps(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            mock = directory / "gh"
            mock.write_text("""#!/bin/sh
test "$1 $2 $3" = "api --header Accept: application/vnd.github.raw" || exit 2
test "$4" = "repos/OpenTubeX/OpenTubeX/contents/fastlane/metadata/android/en-US/changelogs/default.txt?ref=v0.38.0-beta" || exit 2
printf 'Highlights\\n• Added groups\\n'
""")
            mock.chmod(0o755)
            notes = step("publish", "Add stable release notes")
            self.assertEqual(notes["env"]["STABLE_TAG"], "${{ needs.prepare.outputs.stable_tag }}")
            env = dict(os.environ, PATH=f"{directory}:{os.environ['PATH']}", STABLE_TAG="v0.38.0-beta")
            result = subprocess.run(["bash", "-c", notes["run"]], cwd=directory,
                                    env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for app_id in ("org.opentubex.app", "org.opentubex.app.lite"):
                changelog = directory / "metadata" / app_id / "en-US" / "changelogs" / "default.txt"
                self.assertEqual(changelog.read_text(), "Highlights\n• Added groups\n")
            self.assertFalse((directory / "metadata" / "org.opentubex.app.nightly").exists())


class WhatsNewTest(unittest.TestCase):
    def test_adds_whats_new_to_index_v2_and_updates_its_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory, "repo")
            repo.mkdir()
            (repo / "index-v1.json").write_text(json.dumps({"apps": [
                {"packageName": "org.opentubex.app", "localized": {"en-US": {"whatsNew": "Highlights"}}},
                {"packageName": "org.opentubex.app.nightly", "localized": {"en-US": {"name": "Nightly"}}},
            ]}))
            (repo / "index-v2.json").write_text(json.dumps({"packages": {
                "org.opentubex.app": {"versions": {"a": {"file": {}}, "b": {"file": {}}}},
                "org.opentubex.app.nightly": {"versions": {"c": {"file": {}}}},
            }}))
            (repo / "entry.json").write_text(json.dumps({"timestamp": 1, "index": {
                "name": "/index-v2.json", "sha256": "stale", "size": 1, "numPackages": 2}}))
            result = subprocess.run([sys.executable, ROOT / "scripts/add-whats-new.py", repo],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)

            index = json.loads((repo / "index-v2.json").read_text())
            versions = index["packages"]["org.opentubex.app"]["versions"]
            self.assertEqual([version["whatsNew"] for version in versions.values()],
                             [{"en-US": "Highlights"}] * 2)
            self.assertNotIn("whatsNew", index["packages"]["org.opentubex.app.nightly"]["versions"]["c"])
            entry = json.loads((repo / "entry.json").read_text())
            data = (repo / "index-v2.json").read_bytes()
            self.assertEqual(entry["index"], {"name": "/index-v2.json", "numPackages": 2,
                                              "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})


if __name__ == "__main__":
    unittest.main()

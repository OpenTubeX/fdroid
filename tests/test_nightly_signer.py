import hashlib
import importlib.util
from pathlib import Path
import unittest

from fdroidserver import common


ROOT = Path(__file__).resolve().parents[1]
# A minimal APK signed like the nightlies: public nightly key in v2, private
# nightly key rotated from it in v3.
ROTATED_APK = str(ROOT / "tests/fixtures/rotated-nightly.apk")


class NightlySignerTest(unittest.TestCase):
    def test_rotated_nightlies_keep_the_public_signer_in_the_index(self):
        original = common.get_first_signer_certificate
        self.assertIsNone(original(ROTATED_APK))

        spec = importlib.util.spec_from_file_location("fdroid_wrapper", ROOT / "scripts/fdroid.py")
        wrapper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(wrapper)
        self.addCleanup(setattr, common, "get_first_signer_certificate", original)

        # F-Droid clients read rotated apps' oldest certificate, the public one.
        self.assertEqual(common.apk_signer_fingerprint(ROTATED_APK), wrapper.PUBLIC_NIGHTLY)
        self.assertEqual(hashlib.sha256(common.get_first_signer_certificate(ROTATED_APK)).hexdigest(),
                         wrapper.PUBLIC_NIGHTLY)

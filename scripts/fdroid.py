"""Run fdroid with support for the OpenTubeX nightly signing key rotation.

Nightly APKs carry the public nightly key in their v2 signature and the private
nightly key, rotated from it, in their v3 signature. fdroidserver skips APKs
whose signatures have different certificates. For exactly this pair, report the
original certificate as the signer: Android's GET_SIGNATURES, which F-Droid
clients compare with the index, returns the oldest certificate of a rotated app.
`fdroid update` still verifies the signatures with apksigner.
"""

import hashlib
import sys

from fdroidserver import common
from fdroidserver.__main__ import main

PUBLIC_NIGHTLY = "6f6f12235fdfa80c7feb06da0d40cdd80d8de6455a3009b736e6458e1e14d596"
PRIVATE_NIGHTLY = "ae70934782cd4f6183777e3fbabcfe4cdcb6a51b404afff727c90c49e6907b5a"

first_signer_certificate = common.get_first_signer_certificate


def get_first_signer_certificate(apkpath):
    apk = common.get_androguard_APK(apkpath)
    v2 = apk.get_certificates_der_v2()
    v3 = apk.get_certificates_der_v3()
    if (len(v2) == len(v3) == 1
            and hashlib.sha256(v2[0]).hexdigest() == PUBLIC_NIGHTLY
            and hashlib.sha256(v3[0]).hexdigest() == PRIVATE_NIGHTLY):
        return v2[0]
    return first_signer_certificate(apkpath)


common.get_first_signer_certificate = get_first_signer_certificate

if __name__ == "__main__":
    sys.exit(main())

# OpenTubeX F-Droid repository

This repository publishes signed Android packages at
[fdroid.opentubex.org](https://fdroid.opentubex.org). It contains the stable
alpha package and a separately installable nightly package.

## Add the repository

Scan the QR code or add the signed URL to F-Droid:

<p align="center">
  <img src="static/repository-qr.svg" width="232" height="232" alt="QR code for the signed OpenTubeX F-Droid repository">
</p>

```text
https://fdroid.opentubex.org/repo?fingerprint=99BCBB15868B41FE7263E409746D4ABCFC4D32262BEF2AB0B494BBA0929347CD
```

## How publishing works

Stable and nightly releases in `OpenTubeX/OpenTubeX` dispatch their exact tag
to this repository. The publish workflow downloads any Android APKs for the
latest stable and nightly releases, builds a signed F-Droid index, and deploys
the index with the landing page to GitHub Pages.

The APKs keep their original OpenTubeX signatures. F-Droid signs only the
repository index, using a dedicated key stored in GitHub Actions secrets.

The stable app's catalog icon lives in
`metadata/org.opentubex.app/en-US/images/icon.png` because extracting it from
the stable APK produces no icon. Keep this PNG in sync with the app's branding.
Publishing checks that every app has a valid icon in the generated index using
`python scripts/check-app-icons.py`.

## Maintainer setup

The repository expects these Actions secrets:

- `FDROID_KEYSTORE_BASE64`, containing the base64-encoded PKCS#12 repository key
- `FDROID_KEYSTORE_PASSWORD`, containing the password for that key

Configure GitHub Pages to use GitHub Actions, set `fdroid.opentubex.org` as the
custom domain, and add a DNS `CNAME` from that name to `opentubex.github.io`.
The `PUSH_TOKEN` used by the OpenTubeX application repository must have write
access to this repository so it can send release dispatches.

Back up the repository key and password before the first public deployment.
Replacing the key changes the fingerprint and makes existing F-Droid clients
distrust future index updates.

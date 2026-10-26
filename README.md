# OpenTubeX F-Droid repository

This repository publishes signed Android packages at
[fdroid.opentubex.org](https://fdroid.opentubex.org). It contains the stable
beta package and a separately installable nightly package, plus a Lite package
for each channel without yt-dlp and FFmpeg.

## Add the repository

Scan the QR code or add the signed URL to F-Droid:

<p align="center">
  <img src="static/repository-qr.svg" width="320" height="320" alt="QR code for the signed OpenTubeX F-Droid repository">
</p>

```text
https://fdroid.opentubex.org/repo?fingerprint=99BCBB15868B41FE7263E409746D4ABCFC4D32262BEF2AB0B494BBA0929347CD
```

## How publishing works

Stable and nightly releases in `OpenTubeX/OpenTubeX` dispatch their exact tag
to this repository. The publish workflow downloads any Android APKs for the
latest stable and nightly releases, builds a signed F-Droid index, and deploys
the index with the landing page to GitHub Pages. When stable is newer than nightly,
the workflow builds the stable tag with the nightly app ID and signing key, so
existing nightly users receive the stable code without switching apps. Stable
releases with lite APKs also promote OpenTubeX Nightly Lite this way. Explicit
stable dispatches also promote that tag. The promoted APK is published directly
in the signed F-Droid repository, without creating a GitHub release or adding
extra assets to the application's stable release. Repository refreshes rebuild
that APK until a newer nightly is published.

The APKs keep their original OpenTubeX signatures. F-Droid signs only the
repository index, using a dedicated key stored in GitHub Actions secrets.

The catalog icons live in `metadata/<package>/en-US/images/icon.png` because
extracting icons from these APKs produces no usable catalog icon. The Lite
packages reuse the stable and nightly icons. Keep all four PNGs in sync with the
app's branding. Render the nightly PNG from the application's
`_scripts/brand/icon-nightly.svg` at 512 × 512 pixels to preserve its wrench badge.
Publishing checks that every app has a valid icon and phone screenshots in the
generated index using `python scripts/check-app-icons.py`.

The phone screenshots live in `metadata/<package>/en-US/images/phoneScreenshots/`.
All four packages use the same three images, copied from the dark
`OpenTubeX{1,2,3}-mobile-dark.png` captures in the application's
`docs/screenshots`. To refresh them, run `pnpm run screenshots:android` in the
application repository and copy the new captures here.

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

"""Check that every published app has a usable icon before deployment."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("repo", nargs="?", type=Path, default=Path("repo"))
args = parser.parse_args()

index = json.loads((args.repo / "index-v2.json").read_text())
for package_name, package in index["packages"].items():
    icon = package["metadata"].get("icon", {}).get("en-US")
    if not icon:
        raise SystemExit(f"{package_name}: repository metadata has no app icon")

    path = args.repo / icon["name"].lstrip("/")
    data = path.read_bytes()
    if len(data) != icon["size"] or hashlib.sha256(data).hexdigest() != icon["sha256"]:
        raise SystemExit(f"{package_name}: app icon does not match the index")

    with Image.open(path) as image:
        image.verify()
    print(f"{package_name}: app icon OK")

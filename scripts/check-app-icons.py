"""Check that every published app has a usable icon and phone screenshots before deployment."""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("repo", nargs="?", type=Path, default=Path("repo"))
args = parser.parse_args()


def check_file(package_name, label, entry):
    path = args.repo / entry["name"].lstrip("/")
    data = path.read_bytes()
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise SystemExit(f"{package_name}: {label} does not match the index")
    with Image.open(path) as image:
        image.verify()


index = json.loads((args.repo / "index-v2.json").read_text())
for package_name, package in index["packages"].items():
    icon = package["metadata"].get("icon", {}).get("en-US")
    if not icon:
        raise SystemExit(f"{package_name}: repository metadata has no app icon")

    check_file(package_name, "app icon", icon)
    print(f"{package_name}: app icon OK")

    screenshots = package["metadata"].get("screenshots", {}).get("phone", {}).get("en-US", [])
    if not screenshots:
        raise SystemExit(f"{package_name}: repository metadata has no phone screenshots")
    for screenshot in screenshots:
        check_file(package_name, f"phone screenshot {screenshot['name']}", screenshot)
    print(f"{package_name}: {len(screenshots)} phone screenshots OK")

"""Copy "What's new" from index-v1 into the unsigned index-v2 before `fdroid signindex`.

fdroidserver only adds it to index-v2 versions for apps built from source, so
binary repositories need this step for current F-Droid clients.
"""

import argparse
import hashlib
import json
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("repo", nargs="?", type=Path, default=Path("repo"))
args = parser.parse_args()

index_v1 = json.loads((args.repo / "index-v1.json").read_text(encoding="utf-8"))
index_v2_path = args.repo / "index-v2.json"
index_v2 = json.loads(index_v2_path.read_text(encoding="utf-8"))

for app in index_v1["apps"]:
    whats_new = {locale: text["whatsNew"]
                 for locale, text in app.get("localized", {}).items() if "whatsNew" in text}
    if not whats_new:
        continue
    for version in index_v2["packages"][app["packageName"]]["versions"].values():
        version["whatsNew"] = whats_new
    print(f"{app['packageName']}: added What's new")

data = json.dumps(index_v2, indent=2, ensure_ascii=False).encode()
index_v2_path.write_bytes(data)

entry_path = args.repo / "entry.json"
entry = json.loads(entry_path.read_text(encoding="utf-8"))
entry["index"].update(sha256=hashlib.sha256(data).hexdigest(), size=len(data))
entry_path.write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")

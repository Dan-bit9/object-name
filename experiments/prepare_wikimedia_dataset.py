"""Download a small, license-documented Wikimedia Commons benchmark."""
from __future__ import annotations

import csv
import json
import random
import re
import time
from urllib.error import HTTPError
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "experiments" / "wikimedia_data"
OUT = ROOT / "experiments" / "wikimedia_manifest.csv"
USER_AGENT = "object-learning-benchmark/1.0 (educational; contact repository owner)"
API = "https://commons.wikimedia.org/w/api.php"
THUMB_WIDTH = 256
SEED = 20261109

# Search terms deliberately use Commons' English category vocabulary.
IN_LIST = {
    "cup": 3, "bottle": 3, "chair": 3, "ball": 3, "shoe": 3, "backpack": 3,
    "umbrella": 3, "banana": 3, "apple": 3, "orange fruit": 3, "book": 3,
    "pencil": 2, "pen": 2, "mobile phone": 3, "laptop": 3, "computer keyboard": 2,
    "computer mouse": 2, "clock": 3, "wristwatch": 2, "sunglasses": 2,
    "hat": 2, "jeans": 2, "t-shirt": 2, "teddy bear": 2, "dog": 3, "cat": 3,
    "bicycle": 2, "television": 2, "remote control": 2, "toilet paper": 2,
    "fork": 2, "spatula": 2,
}
OUT_LIST = {"adhesive tape": 4, "hammer": 4, "scissors": 4, "spoon": 4, "plate": 4}


def api(params):
    query = urlencode({"format": "json", "origin": "*", **params})
    req = Request(f"{API}?{query}", headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def candidates(term):
    result = api({"action": "query", "generator": "search", "gsrsearch": f"{term} filetype:bitmap",
                  "gsrnamespace": 6, "gsrlimit": 20,
                  "prop": "imageinfo", "iiprop": "url|extmetadata|size", "iiurlwidth": THUMB_WIDTH})
    for page in result.get("query", {}).get("pages", {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})
        license_name = clean((meta.get("LicenseShortName") or {}).get("value"))
        license_url = clean((meta.get("LicenseUrl") or {}).get("value"))
        source = info.get("descriptionurl")
        thumb = info.get("thumburl")
        if not (thumb and source and license_name and license_name.lower() not in {"unknown", "none"}):
            continue
        yield {"title": page.get("title", ""), "source_url": source, "thumb_url": thumb,
               "license": license_name, "license_url": license_url or source,
               "author": clean((meta.get("Artist") or {}).get("value")),
               "width": info.get("thumbwidth"), "height": info.get("thumbheight")}


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    random.seed(SEED)
    rows, seen = [], set()
    if OUT.exists():
        with OUT.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                if (ROOT / row["path"]).exists():
                    row["bytes"] = int(row["bytes"]); rows.append(row); seen.add(row["source_url"])
    failures = []
    for group, terms in (("in", IN_LIST), ("out", OUT_LIST)):
        for term, wanted in terms.items():
            got = sum(r["label"] == term and r["group"] == group for r in rows)
            if got >= wanted:
                continue
            try:
                time.sleep(4)
                for item in candidates(term):
                    if item["source_url"] in seen:
                        continue
                    safe = re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")
                    path = DATA / f"{group}-{safe}-{got + 1:02d}.jpg"
                    try:
                        req = Request(item["thumb_url"], headers={"User-Agent": USER_AGENT})
                        with urlopen(req, timeout=30) as response:
                            content = response.read()
                        if not content or len(content) > 2_000_000:
                            continue
                        path.write_bytes(content)
                    except Exception:
                        continue
                    item.update({"group": group, "label": term, "path": str(path.relative_to(ROOT)),
                                 "bytes": len(content)})
                    rows.append(item); seen.add(item["source_url"]); got += 1
                    if got >= wanted:
                        break
                    time.sleep(0.15)
            except HTTPError as exc:
                if exc.code == 429:
                    # Wikimedia asks clients to back off; the next run reuses all
                    # successful files and only retries this missing label.
                    time.sleep(30)
                failures.append({"label": term, "error": f"HTTP {exc.code}; retry later"})
            except Exception as exc:
                failures.append({"label": term, "error": str(exc)})
            if got < wanted:
                failures.append({"label": term, "requested": wanted, "downloaded": got})

    random.shuffle(rows)
    # Keep both groups in both splits: 24/6 tuning and 56/14 final evaluation.
    in_rows = [r for r in rows if r["group"] == "in"]
    out_rows = [r for r in rows if r["group"] == "out"]
    tuning = set(id(r) for r in in_rows[:24] + out_rows[:6])
    for row in rows:
        row["split"] = "tuning" if id(row) in tuning else "final"
    fields = ["split", "group", "label", "path", "bytes", "title", "source_url", "thumb_url", "license", "license_url", "author", "width", "height"]
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    summary = {"total": len(rows), "in_list": len(in_rows), "out_of_list": len(out_rows),
               "tuning": sum(r["split"] == "tuning" for r in rows),
               "final": sum(r["split"] == "final" for r in rows),
               "bytes": sum(r["bytes"] for r in rows), "failures": failures}
    (ROOT / "experiments" / "wikimedia_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md = ["# Wikimedia Commons benchmark", "", "Images are Wikimedia Commons thumbnails (256px). "
          "The image files and manifest are intentionally Git-ignored.", "",
          f"- Total: {summary['total']} ({summary['in_list']} in-list, {summary['out_of_list']} out-of-list)",
          f"- Split: {summary['tuning']} tuning, {summary['final']} final evaluation",
          f"- Downloaded bytes: {summary['bytes']} (under 100 MB)",
          "- API: https://commons.wikimedia.org/w/api.php", "- Terms: https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia",
          "", "Each row records the Commons file page, detected license metadata, and author metadata.", "",
          "| Split | Group | Label | File page | License | License URL | Author |", "|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda x: (x["split"], x["group"], x["label"], x["path"])):
        esc = lambda s: str(s or "").replace("|", "\\|").replace("\n", " ")
        md.append(f"| {r['split']} | {r['group']} | {esc(r['label'])} | [{esc(r['title'])}]({r['source_url']}) | {esc(r['license'])} | {r['license_url']} | {esc(r['author'])} |")
    (ROOT / "experiments" / "DATASET.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

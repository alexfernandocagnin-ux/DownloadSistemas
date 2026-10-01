"""Merge source catalogs without losing newer releases or concurrent writes."""
import json
import re
import tempfile
from pathlib import Path
from threading import RLock

CATALOG_LOCK = RLock()


def release_rank(release):
    return (str(release.get("competence", "")), tuple(int(n) for n in re.findall(r"\d+", str(release.get("name", "")))), str(release.get("name", "")).lower())


def normalize_catalog(saved, releases, monthly=False):
    known = [saved.get("latest") or {}, saved.get("current") or {}]
    if monthly:
        for month, entry in (saved.get("competences") or {}).items():
            known.append({**entry, "competence": month})
        known += saved.get("available_releases") or []
    withdrawn = {str(name).lower() for release in releases for name in release.get("withdrawn_names", [])}
    merged = {}
    for release in known + list(releases):
        if not release.get("name") or not release.get("url") or str(release["name"]).lower() in withdrawn:
            continue
        identity = str(release.get("competence", "")) if monthly else release["name"]
        if monthly and not identity:
            continue
        previous = merged.get(identity)
        if previous is None or release_rank(release) >= release_rank(previous):
            merged[identity] = {**(previous or {}), **{k: v for k, v in release.items() if v is not None}}
    rank = release_rank if monthly else lambda release: release_rank(release)[1:]
    ordered = sorted(merged.values(), key=rank, reverse=True)
    return ordered if monthly else ordered[:1]


def atomic_write(path, snapshot):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix="catalog-", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            json.dump(snapshot, output, ensure_ascii=False, indent=2)
            output.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)

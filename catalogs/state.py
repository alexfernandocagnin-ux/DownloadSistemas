"""Merge source catalogs without losing newer releases or concurrent writes."""
import json
import re
import tempfile
from pathlib import Path
from threading import RLock

from catalogs.mirrors import matching_mirror
from catalogs.updates import merge_updates

CATALOG_LOCK = RLock()


def release_rank(release):
    return (str(release.get("competence", "")), tuple(int(n) for n in re.findall(r"\d+", str(release.get("name", "")))), str(release.get("name", "")).lower())


def normalize_catalog(saved, releases, monthly=False):
    releases = list(releases)
    known = [saved.get("latest") or {}, saved.get("current") or {}]
    if monthly:
        for month, entry in (saved.get("competences") or {}).items():
            known.append({**entry, "competence": month})
        known += saved.get("available_releases") or []
    withdrawn = {str(name).lower() for release in known + releases for name in release.get("withdrawn_names", [])}
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
    if ordered and withdrawn:
        ordered[0] = {**ordered[0], "withdrawn_names": sorted(withdrawn)}
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


def merge_catalogs(remote, local):
    """Combine source discoveries and verified copies without rolling back releases."""
    systems = {}
    remote_systems = remote.get("systems") or {}
    local_systems = local.get("systems") or {}
    for key in dict.fromkeys([*remote_systems, *local_systems]):
        old, new = remote_systems.get(key, {}), local_systems.get(key, {})
        if not old and not new:
            continue
        monthly = key in {"bdsia", "sigtap", "cnes_base"}
        by_attempt = lambda info: (str(info.get("catalog_attempt_at") or info.get("catalog_checked_at") or info.get("checked_at") or ""), str(info.get("checked_at") or ""))
        earlier, newer = sorted([old, new], key=by_attempt)
        info = dict(newer)
        successful_dates = [str(item.get("catalog_checked_at") or "") for item in [old, new]]
        if any(successful_dates):
            info["catalog_checked_at"] = max(successful_dates)
        releases = normalize_catalog(earlier, normalize_catalog(newer, [], monthly), monthly)
        if releases:
            info["latest"] = releases[0]
        if monthly:
            info["available_releases"] = releases
            entries = {}
            for collection in [old.get("competences") or {}, new.get("competences") or {}]:
                for month, entry in collection.items():
                    previous = entries.get(month)
                    rank = lambda value: (release_rank(value)[1:], bool(matching_mirror(value.get("name"), value.get("mirror"))), str((value.get("mirror") or {}).get("verified_at", "")))
                    if previous is None or rank(entry) >= rank(previous):
                        entries[month] = dict(entry)
            info["competences"] = entries
            failures = {}
            for collection in [old.get("download_failures") or {}, new.get("download_failures") or {}]:
                for month, failure in collection.items():
                    if str(failure.get("attempted_at", "")) >= str(failures.get(month, {}).get("attempted_at", "")):
                        failures[month] = dict(failure)
            for month, entry in entries.items():
                failure = failures.get(month)
                mirror = matching_mirror(entry.get("name"), entry.get("mirror")) or {}
                if failure and failure.get("name") == entry.get("name") and str(mirror.get("verified_at", "")) >= str(failure.get("attempted_at", "")):
                    failures.pop(month)
            if failures or "download_failures" in old or "download_failures" in new:
                info["download_failures"] = failures
        else:
            withdrawn = {str(name).lower() for name in (info.get("latest") or {}).get("withdrawn_names", [])}
            copies = [entry for entry in [old, new] if (entry.get("current") or {}).get("name") and str(entry["current"]["name"]).lower() not in withdrawn]
            if copies:
                copy = max(copies, key=lambda entry: (release_rank(entry["current"])[1:], bool(matching_mirror(entry["current"]["name"], entry.get("mirror"))), str((entry.get("mirror") or {}).get("verified_at", ""))))
                info["current"], info["mirror"] = copy["current"], copy.get("mirror")
            else:
                info.pop("current", None)
                info.pop("mirror", None)
            latest = info.get("latest") or {}
            info["pending_download"] = not matching_mirror(latest.get("name"), info.get("mirror"))
        systems[key] = info
    result = {"updated_at": max(str(remote.get("updated_at") or ""), str(local.get("updated_at") or "")),
              "systems": systems, "updates": merge_updates(remote.get("updates", []), local.get("updates", []))}
    checks = [check for check in [remote.get("last_check"), local.get("last_check")] if check]
    if checks:
        result["last_check"] = max(checks, key=lambda check: str(check.get("completed_at") or ""))
    return result

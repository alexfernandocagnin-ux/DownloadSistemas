"""Publish only the catalog, merging against the current GitHub revision."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from catalogs.state import normalize_catalog, release_rank
from catalogs.updates import merge_updates
from catalogs.mirrors import matching_mirror
from scripts.sync_catalog import SINGLE_VERSION_SYSTEMS, COMPETENCE_SYSTEMS


def merge_catalogs(remote, local):
    systems = {}
    remote_systems = remote.get("systems") or {}
    local_systems = local.get("systems") or {}
    for key in (*SINGLE_VERSION_SYSTEMS, *COMPETENCE_SYSTEMS):
        old, new = remote_systems.get(key, {}), local_systems.get(key, {})
        if not old and not new:
            continue
        monthly = key in COMPETENCE_SYSTEMS
        newer = max([old, new], key=lambda info: str(info.get("catalog_checked_at", info.get("checked_at", ""))))
        info = dict(newer)
        releases = normalize_catalog(old, normalize_catalog(new, [], monthly), monthly)
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
        else:
            withdrawn = (info.get("latest") or {}).get("withdrawn_names", [])
            copies = [entry for entry in [old, new] if (entry.get("current") or {}).get("name") and entry["current"]["name"] not in withdrawn]
            if copies:
                copy = max(copies, key=lambda entry: (release_rank(entry["current"])[1:], bool(matching_mirror(entry["current"]["name"], entry.get("mirror"))), str((entry.get("mirror") or {}).get("verified_at", ""))))
                info["current"], info["mirror"] = copy["current"], copy.get("mirror")
            else:
                info.pop("current", None)
                info.pop("mirror", None)
            latest = info.get("latest") or {}
            info["pending_download"] = not matching_mirror(latest.get("name"), info.get("mirror"))
        systems[key] = info
    return {"updated_at": max(str(remote.get("updated_at", "")), str(local.get("updated_at", ""))),
            "systems": systems, "updates": merge_updates(remote.get("updates", []), local.get("updates", []))}


def gh_api(endpoint, body=None):
    args = ["gh", "api", endpoint]
    if body is None:
        return json.loads(subprocess.run(args, capture_output=True, text=True, check=True, timeout=120).stdout)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as output:
        json.dump(body, output)
        path = Path(output.name)
    try:
        return json.loads(subprocess.run(args + ["--method", "PUT", "--input", str(path)], capture_output=True, text=True, check=True, timeout=120).stdout)
    finally:
        path.unlink(missing_ok=True)


def publish(local, repository):
    endpoint = f"repos/{repository}/contents/data/catalog.json"
    for attempt in range(5):
        current = gh_api(endpoint + "?ref=master")
        blob = current if current.get("encoding") == "base64" else gh_api(f"repos/{repository}/git/blobs/{current['sha']}")
        remote = json.loads(base64.b64decode(blob["content"]).decode("utf-8"))
        merged = merge_catalogs(remote, local)
        if merged == remote:
            print("Catálogo já atualizado.")
            return
        content = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
        try:
            gh_api(endpoint, {"message": "Atualizar catálogo de versões e espelhos confirmados",
                             "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                             "sha": current["sha"], "branch": "master",
                             "committer": {"name": "github-actions[bot]", "email": "41898282+github-actions[bot]@users.noreply.github.com"}})
            print("Catálogo publicado sem alterar os arquivos de código.")
            return
        except subprocess.CalledProcessError as exc:
            if "409" not in (exc.stderr or "") or attempt == 4:
                raise
            time.sleep(1 + attempt)


if __name__ == "__main__":
    publish(json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8")), os.environ["GITHUB_REPOSITORY"])

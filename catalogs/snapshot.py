"""Read the published catalog and detect changes beyond the verification time."""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from time import time
from urllib.request import Request, urlopen

from catalogs._common import USER_AGENT
from catalogs.mirrors import REPOSITORY

MAX_CATALOG_BYTES = 3_000_000


def read_published_catalog():
    # Public data only. One URL per minute avoids an outdated CDN response;
    # Streamlit shares the cached result across all visitors.
    url = f"https://raw.githubusercontent.com/{REPOSITORY}/master/data/catalog.json?v={int(time() // 60)}"
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
        with urlopen(request, timeout=10) as response:
            payload = response.read(MAX_CATALOG_BYTES + 1)
        if len(payload) > MAX_CATALOG_BYTES:
            return None
        snapshot = json.loads(payload.decode("utf-8"))
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("systems"), dict):
            return None
        if snapshot.get("last_check") is not None and not isinstance(snapshot["last_check"], dict):
            return None
        check = snapshot.get("last_check") or {}
        for field in ["succeeded", "total"]:
            if field in check and (not isinstance(check[field], int) or check[field] < 0):
                return None
        for info in snapshot["systems"].values():
            if not isinstance(info, dict):
                return None
            for field in ["latest", "current", "mirror", "competences", "download_failures"]:
                if info.get(field) is not None and not isinstance(info[field], dict):
                    return None
            if any(not isinstance(entry, dict) for field in ["competences", "download_failures"] for entry in (info.get(field) or {}).values()):
                return None
            releases = info.get("available_releases") or []
            if not isinstance(releases, list) or any(not isinstance(entry, dict) for entry in releases):
                return None
        return snapshot
    except (OSError, ValueError):
        return None


def catalog_revision(snapshot):
    # A newly available mirror may have the same updated_at as its discovery.
    payload = json.dumps(snapshot, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def verification_notice(snapshot, current_time=None):
    current_time = current_time or datetime.now(timezone.utc)
    check = snapshot.get("last_check") or {}
    if check and check.get("succeeded", 0) < check.get("total", 0):
        succeeded, total = check.get("succeeded", 0), check.get("total", 0)
        return f"A última verificação consultou {succeeded} de {total} fontes. Os arquivos e versões já confirmados continuam disponíveis."
    value = check.get("completed_at") or snapshot.get("updated_at")
    try:
        checked_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return "O catálogo ainda não possui uma verificação concluída."
    if current_time - checked_at > timedelta(hours=3):
        return "A verificação programada está atrasada. Os downloads continuam disponíveis pelo último catálogo confirmado."
    return None

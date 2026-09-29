"""Helpers for the persistent feed of newly discovered system releases."""

from __future__ import annotations


def make_update_event(system_key, system, name, found_at, competence=None, catalog_source=None):
    identity = competence or name
    event = {
        "id": f"{system_key}:{identity}:{name}",
        "system_key": system_key,
        "system": system,
        "name": name,
        "found_at": found_at,
    }
    if competence:
        event["competence"] = competence
    if catalog_source:
        event["catalog_source"] = catalog_source
    return event


def merge_updates(*collections, limit=24):
    """Deduplicate events by release and keep the newest announcements first."""
    events = {}
    for collection in collections:
        if not isinstance(collection, (list, tuple)):
            continue
        for item in collection:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            events.setdefault(str(item["id"]), dict(item))
    return sorted(events.values(), key=lambda item: str(item.get("found_at", "")), reverse=True)[:limit]

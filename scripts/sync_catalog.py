"""Consulta as fontes oficiais e prepara o espelho próprio em dist/.

Nunca executa nem abre os pacotes baixados. Quando uma versão muda (ou ainda
não foi publicada como Release), baixa o arquivo oficial e atualiza
data/catalog.json. O workflow do GitHub Actions é quem de fato sobe cada
arquivo de dist/ como asset de uma Release (gh release upload) e comita o
catalog.json atualizado.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from time import monotonic
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogs import apac_portal, bpa_portal, ciha_portal, cnes_portal, fpo_portal, sia_portal, sigtap_portal, sihd_portal  # noqa: E402
from catalogs.state import atomic_write, normalize_catalog  # noqa: E402
from catalogs.mirrors import probe_mirror  # noqa: E402
from catalogs.updates import make_update_event, merge_updates  # noqa: E402

CATALOG_PATH = ROOT / "data" / "catalog.json"
DIST_DIR = ROOT / "dist"
PUBLISH = False
CATALOG_ONLY = False
MIRROR_ONLY = False

SINGLE_VERSION_SYSTEMS = {
    "apac": {
        "label": "APAC Magnético", "official_page": apac_portal.INDEX_URL,
        "fetch": apac_portal.fetch_apac_catalog, "download": apac_portal.download_release,
        "tag": "apac-latest",
    },
    "ciha02": {
        "label": "CIHA02 · atualização", "official_page": ciha_portal.PAGES["02"],
        "fetch": ciha_portal.fetch_ciha02_catalog, "download": ciha_portal.download_release,
        "tag": "ciha02-latest",
    },
    "ciha02_installer": {
        "label": "CIHA02 · instalação inicial", "official_page": ciha_portal.PAGES["02"],
        "fetch": ciha_portal.fetch_ciha02_installer_catalog, "download": ciha_portal.download_release,
        "tag": "ciha02-installer-latest",
    },
    "bpa": {
        "label": "BPA Magnético",
        "official_page": bpa_portal.INDEX_URL,
        "fetch": bpa_portal.fetch_bpa_catalog,
        "download": bpa_portal.download_release,
        "tag": "bpa-latest",
    },
    "sia": {
        "label": "SIA (instalador)",
        "official_page": sia_portal.INDEX_URL,
        "fetch": sia_portal.fetch_sia_catalog,
        "download": sia_portal.download_release,
        "tag": "sia-latest",
    },
    "fpo_installer": {
        "label": "FPO Magnético (instalador)",
        "official_page": fpo_portal.INDEX_URL,
        "fetch": fpo_portal.fetch_fpo_installer_catalog,
        "download": fpo_portal.download_release,
        "tag": "fpo-installer-latest",
    },
    "fpo_update": {
        "label": "FPO Magnético (atualização)",
        "official_page": fpo_portal.INDEX_URL,
        "fetch": fpo_portal.fetch_fpo_update_catalog,
        "download": fpo_portal.download_release,
        "tag": "fpo-update-latest",
    },
    "sihd2": {
        "label": "SIHD2 (instalador)",
        "official_page": sihd_portal.INDEX_URL,
        "fetch": sihd_portal.fetch_sihd2_catalog,
        "download": sihd_portal.download_release,
        "tag": "sihd2-latest",
    },
    "cnes_app": {
        "label": "CNES · SCNES (atualização)",
        "official_page": cnes_portal.APLICATIVOS_PAGE,
        "fetch": cnes_portal.fetch_cnes_app_catalog,
        "download": cnes_portal.download_app_release,
        "tag": "cnes-app-latest",
    },
    "cnes_complete": {
        "label": "CNES · SCNES completo",
        "official_page": cnes_portal.APLICATIVOS_PAGE,
        "fetch": cnes_portal.fetch_cnes_complete_catalog,
        "download": cnes_portal.download_app_release,
        "tag": "cnes-complete-latest",
    },
}

COMPETENCE_SYSTEMS = {
    "bdsia": {
        "label": "Tabela mensal do SIA (BDSIA)",
        "official_page": sia_portal.INDEX_URL,
        "fetch": sia_portal.fetch_bdsia_catalog,
        "download": sia_portal.download_release,
    },
    "sigtap": {
        "label": "SIGTAP · Tabela Unificada",
        "official_page": sigtap_portal.DOWNLOAD_PAGE,
        "fetch": sigtap_portal.fetch_sigtap_catalog,
        "download": sigtap_portal.download_release,
    },
    "cnes_base": {
        "label": "CNES · Base de dados mensal",
        "official_page": cnes_portal.BASE_DADOS_PAGE,
        "fetch": cnes_portal.fetch_cnes_base_catalog,
        "download": cnes_portal.download_base_release,
        "new_packages_per_run": 2,
        # Removed from the public portal: retain existing copies, stop backfilling.
        "enabled": False,
    },
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gh(*args):
    timeout = 600 if args[:2] == ("release", "upload") else 120
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True, timeout=timeout).stdout


def remote_asset(tag, name):
    """Nunca presume que uma URL no catálogo representa um upload concluído."""
    try:
        release = json.loads(gh("release", "view", tag, "--repo", os.environ["GITHUB_REPOSITORY"], "--json", "assets,isDraft"))
    except subprocess.CalledProcessError:
        return None
    if release.get("isDraft"):
        return None
    return next((a for a in release["assets"] if a["name"] == name and a["size"] > 0), None)


def confirmed_previous(entry):
    mirror = (entry or {}).get("mirror") or {}
    if not mirror.get("asset_url") or mirror.get("asset_name") != (entry or {}).get("name"):
        return None
    if not PUBLISH:
        return mirror
    asset = remote_asset(mirror["tag"], mirror["asset_name"])
    if not asset:
        return None
    if mirror.get("size") and mirror["size"] != asset["size"]:
        return None
    digest = asset.get("digest") or ""
    if mirror.get("sha256") and digest.startswith("sha256:") and mirror["sha256"] != digest.removeprefix("sha256:"):
        return None
    return {**mirror, "size": asset["size"], "verified_at": now()}


def store_package(key, release, config, tag, expected_sha256=None):
    name = str(release["name"])
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Nome de arquivo inválido.")
    if PUBLISH:
        existing = remote_asset(tag, name)
        digest = (existing or {}).get("digest") or ""
        if (existing and (not release.get("size") or existing["size"] == release["size"])
                and (not expected_sha256 or digest == "sha256:" + expected_sha256)):
            # Recupera uploads concluídos antes de uma interrupção do workflow.
            mirror = {"tag": tag, "asset_name": name, "asset_url": existing["url"],
                      "size": existing["size"], "verified_at": now()}
            if digest.startswith("sha256:"):
                mirror["sha256"] = digest.removeprefix("sha256:")
            try:
                probe_mirror(name, mirror)
            except (OSError, ValueError):
                pass  # A stale asset must be replaced from the source, not republished as verified.
            else:
                return mirror
    package = config["download"](release)
    target = DIST_DIR / key / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(package)
    if not PUBLISH:
        return None
    repo = os.environ["GITHUB_REPOSITORY"]
    try:
        gh("release", "view", tag, "--repo", repo)
    except subprocess.CalledProcessError:
        gh("release", "create", tag, "--repo", repo, "--title", tag,
           "--notes", "Espelho de arquivos oficiais do DATASUS. Arquivos preservados para uso durante indisponibilidades.")
    # Reenvio recupera uploads incompletos; outros nomes de versão são preservados.
    gh("release", "upload", tag, str(target), "--repo", repo, "--clobber")
    asset = remote_asset(tag, name)
    if not asset or asset["size"] != len(package):
        raise ValueError(f"A publicação de {name} não foi confirmada.")
    digest = asset.get("digest") or ""
    if digest.startswith("sha256:") and digest.removeprefix("sha256:") != hashlib.sha256(package).hexdigest():
        raise ValueError(f"O hash publicado de {name} diverge do arquivo baixado.")
    return {"tag": tag, "asset_name": name, "asset_url": asset["url"],
            "size": len(package), "sha256": hashlib.sha256(package).hexdigest(), "verified_at": now()}


def _load_previous():
    if not CATALOG_PATH.is_file():
        return {"systems": {}}
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"systems": {}}


def failed(previous, config, checked_at, exc):
    result = dict(previous or {"label": config["label"], "official_page": config["official_page"]})
    # checked_at é a tentativa; last_success_at conserva a idade real da cópia.
    if previous and "last_success_at" not in result:
        result["last_success_at"] = previous.get("checked_at") if previous.get("official_reachable") else None
    result.update(official_reachable=False, checked_at=checked_at, catalog_attempt_at=checked_at,
                  catalog_check_error=type(exc).__name__, error=type(exc).__name__)
    causes = []
    cause = exc
    while cause is not None and len(causes) < 3:
        causes.append(f"{type(cause).__name__}: {' '.join(str(cause).split())[:180]}")
        cause = cause.__cause__
    detail = " <- ".join(causes).replace("%", "%25")
    print(f'::warning::{config["label"]}: falha ao consultar a fonte oficial ({detail}); cópia anterior preservada.')
    return result


def mirror_failed(previous, config, checked_at, exc):
    result = {"label": config["label"], "official_page": config["official_page"], **(previous or {})}
    result.update(checked_at=checked_at, download_error=type(exc).__name__)
    print(f'::warning::{config["label"]}: falha ao preparar cópia ({type(exc).__name__}); catálogo preservado.')
    return result


def sync_single_version_system(key, config, previous):
    checked_at = now()
    old = previous.get("systems", {}).get(key, {})
    announcements = []
    try:
        releases = normalize_catalog(old, [], key in COMPETENCE_SYSTEMS) if MIRROR_ONLY else config["fetch"]()
        if not releases:
            raise ValueError("Nenhuma versão encontrada.")
    except (OSError, ValueError) as exc:
        return mirror_failed(old, config, checked_at, exc) if MIRROR_ONLY else failed(old, config, checked_at, exc)
    releases = normalize_catalog(old, releases)
    catalog_checked_at = old.get("catalog_checked_at") if MIRROR_ONLY else checked_at
    catalog_attempt_at = old.get("catalog_attempt_at", catalog_checked_at) if MIRROR_ONLY else checked_at
    latest = dict(releases[0])
    name = latest["name"]
    old_current = old.get("current") or {}
    old_latest = old.get("latest") or old_current
    if not latest.get("release_date") and old_latest.get("name") == name:
        latest["release_date"] = old_latest.get("release_date")
    if not MIRROR_ONLY and old_latest.get("name") and old_latest["name"] != name:
        announcements.append(make_update_event(key, config["label"], name, checked_at))
    if CATALOG_ONLY:
        result = {**old, "label": config["label"], "official_page": config["official_page"],
                  "latest": latest, "catalog_checked_at": catalog_checked_at,
                  "catalog_attempt_at": catalog_attempt_at, "catalog_check_error": None,
                  "checked_at": checked_at, "official_reachable": True,
                  "pending_download": old_current.get("name") != name or not old.get("mirror")}
        if str(old_current.get("name", "")).lower() in {str(name).lower() for name in latest.get("withdrawn_names", [])}:
            result.pop("current", None)
            result.pop("mirror", None)
        result.pop("error", None)
        if announcements:
            result["_announcements"] = announcements
        return result
    try:
        previous_entry = {**(old.get("current") or {}), "mirror": old.get("mirror")}
        mirror = confirmed_previous(previous_entry) if previous_entry.get("name") == name else None
        if not mirror:
            mirror = store_package(key, latest, config, config["tag"],
                                   expected_sha256=(old.get("mirror") or {}).get("sha256") if old_current.get("name") == name else None)
        print(f'[{key}] {name}: {"espelho confirmado" if mirror else "somente arquivo local"}')
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        # A mirror failure is not a failure to query the source catalog.
        result = {**old, "label": config["label"], "official_page": config["official_page"]}
        result.update(latest=latest, official_reachable=old.get("official_reachable", True) if MIRROR_ONLY else True,
                      catalog_checked_at=catalog_checked_at, catalog_attempt_at=catalog_attempt_at,
                      catalog_check_error=old.get("catalog_check_error") if MIRROR_ONLY else None,
                      checked_at=checked_at, pending_download=True, download_error=type(exc).__name__)
        print(f'::warning::{key}: {type(exc).__name__}; cópia anterior preservada.')
        if announcements:
            result["_announcements"] = announcements
        return result
    release_date = latest.get("release_date")
    if not release_date and old_current.get("name") == name:
        release_date = old_current.get("release_date")
    result = {"label": config["label"], "official_page": config["official_page"],
              "latest": latest, "catalog_checked_at": catalog_checked_at,
              "catalog_attempt_at": catalog_attempt_at,
              "catalog_check_error": old.get("catalog_check_error") if MIRROR_ONLY else None, "pending_download": False,
              "current": {"name": name, "size": latest.get("size"), "url": latest["url"],
                          "release_date": release_date},
              "mirror": mirror, "checked_at": checked_at, "last_success_at": checked_at,
              "official_reachable": old.get("official_reachable", True) if MIRROR_ONLY else True}
    if announcements:
        result["_announcements"] = announcements
    return result


def sync_competence_system(key, config, previous, on_progress=None):
    checked_at = now()
    old = previous.get("systems", {}).get(key, {})
    try:
        releases = normalize_catalog(old, [], key in COMPETENCE_SYSTEMS) if MIRROR_ONLY else config["fetch"]()
        if not releases:
            raise ValueError("Nenhuma competência encontrada.")
    except (OSError, ValueError) as exc:
        return mirror_failed(old, config, checked_at, exc) if MIRROR_ONLY else failed(old, config, checked_at, exc)
    releases = normalize_catalog(old, releases, monthly=True)
    catalog_checked_at = old.get("catalog_checked_at") if MIRROR_ONLY else checked_at
    catalog_attempt_at = old.get("catalog_attempt_at", catalog_checked_at) if MIRROR_ONLY else checked_at
    updated = dict(old.get("competences") or {})
    announcements = []
    known_latest = old.get("latest") or {}
    old_latest_month = max([*updated, str(known_latest.get("competence", ""))], default="") or None
    latest_release = max(releases, key=lambda item: str(item.get("competence", "")))
    latest_release = dict(latest_release)
    latest_month = str(latest_release["competence"])
    if old_latest_month and not MIRROR_ONLY:
        old_latest = known_latest if str(known_latest.get("competence", "")) == old_latest_month else updated[old_latest_month]
        if latest_month > old_latest_month or (
            latest_month == old_latest_month and old_latest.get("name") != latest_release["name"]
        ):
            announcements.append(make_update_event(
                key, config["label"], latest_release["name"], checked_at,
                competence=latest_month, catalog_source=latest_release.get("catalog_source"),
            ))
    # Salva o índice inteiro antes dos downloads. O limite é de trabalho por execução,
    # nunca de idade: qualquer competência catalogada aparece ao abrir o portal.
    by_month = {}
    for release in releases:
        by_month.setdefault(str(release["competence"]), dict(release))
    months = sorted(by_month, reverse=True)
    available_releases = [by_month[month] for month in months]
    package_budget = int(config.get("new_packages_per_run", 16))
    deadline = monotonic() + int(config.get("download_seconds_per_run", 480))
    attempts = 0
    errors = []
    failures = dict(old.get("download_failures") or {})

    def result():
        data = {"label": config["label"], "official_page": config["official_page"],
                "latest": latest_release, "catalog_checked_at": catalog_checked_at,
                "catalog_attempt_at": catalog_attempt_at,
                "catalog_check_error": old.get("catalog_check_error") if MIRROR_ONLY else None,
                "available_releases": available_releases,
                "competences": dict(updated), "checked_at": checked_at, "last_success_at": checked_at,
                "official_reachable": old.get("official_reachable", latest_release.get("catalog_source") != "community") if MIRROR_ONLY else latest_release.get("catalog_source") != "community",
                "pending_competences": list(errors), "download_failures": dict(failures)}
        if announcements:
            data["_announcements"] = announcements
        return data

    if on_progress:
        on_progress(key, result())
    if CATALOG_ONLY:
        return result()
    for month in months:
        release = by_month[month]
        entry = updated.get(month, {})
        if month != latest_month and entry.get("name") == release["name"] and entry.get("mirror"):
            continue
        try:
            mirror = None
            if entry.get("name") == release["name"]:
                # Cópias históricas já confirmadas não precisam de centenas de consultas
                # ao GitHub a cada execução. A competência atual é reconferida.
                mirror = entry.get("mirror") if month != latest_month else confirmed_previous(entry)
            if not mirror:
                failure = failures.get(month) or {}
                # Latest versions retry every run. Missing historical files get a
                # cooldown so they cannot consume the same batch indefinitely.
                if month != latest_month and failure.get("name") == release["name"] and str(failure.get("retry_after", "")) > checked_at:
                    continue
                if attempts >= package_budget or monotonic() >= deadline:
                    break
                attempts += 1
                mirror = store_package(key, release, config, f"{key.replace('_', '-')}-{month}",
                                       expected_sha256=(entry.get("mirror") or {}).get("sha256") if entry.get("name") == release["name"] else None)
            release_date = release.get("release_date")
            if not release_date and entry.get("name") == release["name"]:
                release_date = entry.get("release_date")
            updated[month] = {"name": release["name"], "size": release.get("size"),
                              "url": release["url"], "mirror": mirror,
                              "catalog_source": release.get("catalog_source"),
                              "release_date": release_date}
            failures.pop(month, None)
            if on_progress:
                on_progress(key, result())
        except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            errors.append(month)
            failures[month] = {"name": release["name"], "error": type(exc).__name__, "attempted_at": now(),
                               "retry_after": (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat(timespec="seconds")}
            if on_progress:
                on_progress(key, result())
            print(f'::warning::{key} {month}: {type(exc).__name__}; cópia anterior preservada.')
    return result()


def save_catalog(systems, updates=None, last_check=None, previous_updated_at=""):
    ordered = {key: systems[key] for key in (*SINGLE_VERSION_SYSTEMS, *COMPETENCE_SYSTEMS) if key in systems}
    confirmed_at = max((str(info.get("catalog_checked_at") or "") for key, info in ordered.items()
                        if (SINGLE_VERSION_SYSTEMS.get(key) or COMPETENCE_SYSTEMS[key]).get("enabled", True)), default="")
    catalog = {"updated_at": max(confirmed_at, str(previous_updated_at or "")), "systems": ordered, "updates": merge_updates(updates or [])}
    if last_check:
        catalog["last_check"] = last_check
    atomic_write(CATALOG_PATH, catalog)


def main():
    global PUBLISH, CATALOG_ONLY, MIRROR_ONLY
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Publicar e verificar cada arquivo antes de atualizar o catálogo")
    parser.add_argument("--catalog-only", action="store_true", help="Salvar versões encontradas sem aguardar downloads")
    parser.add_argument("--mirror-only", action="store_true", help="Publicar cópias do catálogo salvo sem alterar o horário da consulta")
    args = parser.parse_args()
    if args.mirror_only and (not args.publish or args.catalog_only):
        parser.error("--mirror-only requer --publish e não aceita --catalog-only")
    PUBLISH = args.publish
    CATALOG_ONLY = args.catalog_only
    MIRROR_ONLY = args.mirror_only
    if PUBLISH:
        if not os.environ.get("GITHUB_REPOSITORY"):
            parser.error("--publish requer GITHUB_REPOSITORY")
        gh("auth", "status")
    started_at = now()
    previous = _load_previous()
    systems = dict(previous.get("systems", {}))
    updates = list(previous.get("updates", []))
    catalog_lock = Lock()
    active = {key: config for key, config in {**SINGLE_VERSION_SYSTEMS, **COMPETENCE_SYSTEMS}.items() if config.get("enabled", True)}

    def record(key, info):
        info = dict(info)
        announcements = info.pop("_announcements", [])
        with catalog_lock:
            systems[key] = info
            updates[:] = merge_updates(updates, announcements)
            save_catalog(systems, updates, previous.get("last_check"), previous.get("updated_at"))

    # Uma fonte lenta não impede os demais sistemas de publicar seus arquivos.
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = {executor.submit(sync_single_version_system, key, config, previous): key
                 for key, config in SINGLE_VERSION_SYSTEMS.items() if key in active}
        tasks.update({executor.submit(sync_competence_system, key, config, previous, record): key
                      for key, config in COMPETENCE_SYSTEMS.items() if key in active})
        for task in as_completed(tasks):
            key = tasks[task]
            try:
                info = task.result()
            except Exception as exc:
                config = SINGLE_VERSION_SYSTEMS.get(key) or COMPETENCE_SYSTEMS[key]
                failure_handler = mirror_failed if MIRROR_ONLY else failed
                info = failure_handler(previous.get("systems", {}).get(key, {}), config, now(), exc)
            record(key, info)
    last_check = previous.get("last_check")
    if not MIRROR_ONLY:
        failed_sources = [key for key in active if systems[key].get("catalog_check_error")]
        last_check = {"started_at": started_at, "completed_at": now(), "source": "automatic",
                      "total": len(active), "succeeded": len(active) - len(failed_sources),
                      "failed_systems": failed_sources}
    save_catalog(systems, updates, last_check, previous.get("updated_at"))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("## Espelhos DATASUS\n\n")
            if last_check:
                summary.write(f"Consulta concluída em {last_check['completed_at']}: {last_check['succeeded']} de {last_check['total']} fontes responderam.\n\n")
            for key in active:
                info = systems[key]
                entries = list(info.get("competences", {}).values()) if key in COMPETENCE_SYSTEMS else [{"mirror": info.get("mirror")}]
                count = sum(bool((e.get("mirror") or {}).get("verified_at")) for e in entries)
                summary.write(f"- {info['label']}: {count} arquivo(s) com publicação confirmada nesta versão do catálogo.\n")

    if not MIRROR_ONLY and active and not last_check["succeeded"]:
        raise SystemExit("Nenhuma fonte respondeu; catálogo anterior preservado e tentativa registrada.")


if __name__ == "__main__":
    main()

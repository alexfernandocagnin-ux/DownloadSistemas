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
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogs import bpa_portal, cnes_portal, sia_portal, sigtap_portal, sihd_portal  # noqa: E402

CATALOG_PATH = ROOT / "data" / "catalog.json"
DIST_DIR = ROOT / "dist"
COMPETENCE_LIMIT = 6
PUBLISH = False

SINGLE_VERSION_SYSTEMS = {
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
    },
}


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gh(*args):
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


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
    return {**mirror, "size": asset["size"], "verified_at": now()}


def store_package(key, release, config, tag):
    name = str(release["name"])
    if Path(name).name != name or "/" in name or "\\" in name:
        raise ValueError("Nome de arquivo inválido.")
    if PUBLISH:
        existing = remote_asset(tag, name)
        if existing and (not release.get("size") or existing["size"] == release["size"]):
            # Recupera uploads concluídos antes de uma interrupção do workflow.
            mirror = {"tag": tag, "asset_name": name, "asset_url": existing["url"],
                      "size": existing["size"], "verified_at": now()}
            digest = existing.get("digest") or ""
            if digest.startswith("sha256:"):
                mirror["sha256"] = digest.removeprefix("sha256:")
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
    result.update(official_reachable=False, checked_at=checked_at, error=type(exc).__name__)
    print(f'::warning::{config["label"]}: falha na consulta, download ou publicação ({type(exc).__name__}); cópia anterior preservada.')
    return result


def sync_single_version_system(key, config, previous):
    checked_at = now()
    old = previous.get("systems", {}).get(key, {})
    try:
        releases = config["fetch"]()
        if not releases:
            raise ValueError("Nenhuma versão encontrada.")
        latest = releases[0]
        name = latest["name"]
        previous_entry = {**(old.get("current") or {}), "mirror": old.get("mirror")}
        mirror = confirmed_previous(previous_entry) if previous_entry.get("name") == name else None
        if not mirror:
            mirror = store_package(key, latest, config, config["tag"])
        print(f'[{key}] {name}: {"espelho confirmado" if mirror else "somente arquivo local"}')
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        return failed(old, config, checked_at, exc)
    return {"label": config["label"], "official_page": config["official_page"],
            "current": {"name": name, "size": latest.get("size"), "url": latest["url"]},
            "mirror": mirror, "checked_at": checked_at, "last_success_at": checked_at, "official_reachable": True}


def sync_competence_system(key, config, previous, on_progress=None):
    checked_at = now()
    old = previous.get("systems", {}).get(key, {})
    try:
        releases = config["fetch"]()
        if not releases:
            raise ValueError("Nenhuma competência encontrada.")
    except (OSError, ValueError) as exc:
        return failed(old, config, checked_at, exc)
    updated = dict(old.get("competences") or {})
    # Todas as cópias antigas ficam disponíveis; apenas os seis meses recentes são baixados.
    months = sorted({str(item["competence"]) for item in releases}, reverse=True)[:COMPETENCE_LIMIT]
    if not updated:
        # Primeiro garante a competência atual; o histórico entra nas próximas execuções.
        months = months[:1]
    errors = []

    def result():
        return {"label": config["label"], "official_page": config["official_page"],
                "competences": dict(updated), "checked_at": checked_at, "last_success_at": checked_at,
                "official_reachable": True, "pending_competences": list(errors)}

    for month in months:
        release = next(item for item in releases if item["competence"] == month)
        entry = updated.get(month, {})
        try:
            mirror = confirmed_previous(entry) if entry.get("name") == release["name"] else None
            if not mirror:
                mirror = store_package(key, release, config, f"{key.replace('_', '-')}-{month}")
            updated[month] = {"name": release["name"], "size": release.get("size"),
                              "url": release["url"], "mirror": mirror}
            if on_progress:
                on_progress(key, result())
        except (OSError, ValueError, subprocess.CalledProcessError) as exc:
            errors.append(month)
            print(f'::warning::{key} {month}: {type(exc).__name__}; cópia anterior preservada.')
    return result()


def save_catalog(systems):
    ordered = {key: systems[key] for key in (*SINGLE_VERSION_SYSTEMS, *COMPETENCE_SYSTEMS) if key in systems}
    catalog = {"updated_at": now(), "systems": ordered}
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CATALOG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(CATALOG_PATH)


def main():
    global PUBLISH
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--publish", action="store_true", help="Publicar e verificar cada arquivo antes de atualizar o catálogo")
    PUBLISH = parser.parse_args().publish
    if PUBLISH:
        if not os.environ.get("GITHUB_REPOSITORY"):
            parser.error("--publish requer GITHUB_REPOSITORY")
        gh("auth", "status")
    previous = _load_previous()
    systems = dict(previous.get("systems", {}))
    catalog_lock = Lock()

    def record(key, info):
        with catalog_lock:
            systems[key] = info
            save_catalog(systems)

    # Uma fonte lenta não impede os demais sistemas de publicar seus arquivos.
    with ThreadPoolExecutor(max_workers=4) as executor:
        tasks = {executor.submit(sync_single_version_system, key, config, previous): key
                 for key, config in SINGLE_VERSION_SYSTEMS.items()}
        tasks.update({executor.submit(sync_competence_system, key, config, previous, record): key
                      for key, config in COMPETENCE_SYSTEMS.items()})
        for task in as_completed(tasks):
            record(tasks[task], task.result())
    systems = {key: systems[key] for key in (*SINGLE_VERSION_SYSTEMS, *COMPETENCE_SYSTEMS)}
    save_catalog(systems)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as summary:
            summary.write("## Espelhos DATASUS\n\n")
            for key, info in systems.items():
                entries = list(info.get("competences", {}).values()) if key in COMPETENCE_SYSTEMS else [{"mirror": info.get("mirror")}]
                count = sum(bool((e.get("mirror") or {}).get("verified_at")) for e in entries)
                summary.write(f"- {info['label']}: {count} arquivo(s) com publicação confirmada nesta versão do catálogo.\n")


if __name__ == "__main__":
    main()

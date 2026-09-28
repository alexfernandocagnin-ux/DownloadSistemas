"""Consulta as fontes oficiais e prepara o espelho próprio em dist/.

Nunca executa nem abre os pacotes baixados. Quando uma versão muda (ou ainda
não foi publicada como Release), baixa o arquivo oficial e atualiza
data/catalog.json. O workflow do GitHub Actions é quem de fato sobe cada
arquivo de dist/ como asset de uma Release (gh release upload) e comita o
catalog.json atualizado.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogs import bpa_portal, cnes_portal, sia_portal, sigtap_portal, sihd_portal  # noqa: E402

CATALOG_PATH = ROOT / "data" / "catalog.json"
DIST_DIR = ROOT / "dist"
COMPETENCE_LIMIT = 6

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


def _asset_url(tag: str, asset_name: str) -> str | None:
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        return None
    return f"https://github.com/{repo}/releases/download/{tag}/{asset_name}"


def _load_previous() -> dict[str, object]:
    if not CATALOG_PATH.is_file():
        return {"systems": {}}
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"systems": {}}


def _unreachable_fallback(previous_system: dict[str, object] | None, config: dict[str, object], checked_at: str) -> dict[str, object]:
    if previous_system:
        result = dict(previous_system)
    else:
        result = {"label": config["label"], "official_page": config["official_page"], "current": None, "mirror": None}
    result["official_reachable"] = False
    result["checked_at"] = checked_at
    return result


def sync_single_version_system(key: str, config: dict[str, object], previous: dict[str, object]) -> dict[str, object]:
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous_system = previous.get("systems", {}).get(key)
    try:
        latest = config["fetch"]()[0]
        name = str(latest["name"])
        previous_name = ((previous_system or {}).get("current") or {}).get("name")
        previous_asset_url = ((previous_system or {}).get("mirror") or {}).get("asset_url")
        if name != previous_name or not previous_asset_url:
            print(f"[{key}] versão nova ou ainda não espelhada: {name} (antes: {previous_name or 'nenhuma'})")
            package = config["download"](latest)
            target_dir = DIST_DIR / key
            target_dir.mkdir(parents=True, exist_ok=True)
            (target_dir / name).write_bytes(package)
        else:
            print(f"[{key}] sem mudança: {name}")
    except (OSError, ValueError) as exc:
        print(f"[{key}] consulta ou download oficial falhou: {type(exc).__name__}: {exc}")
        return _unreachable_fallback(previous_system, config, checked_at)

    return {
        "label": config["label"],
        "official_page": config["official_page"],
        "current": {"name": name, "size": latest.get("size"), "url": latest["url"]},
        "mirror": {"tag": config["tag"], "asset_name": name, "asset_url": _asset_url(str(config["tag"]), name)},
        "checked_at": checked_at,
        "official_reachable": True,
    }


def sync_competence_system(key: str, config: dict[str, object], previous: dict[str, object]) -> dict[str, object]:
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous_system = previous.get("systems", {}).get(key, {})
    previous_competences = previous_system.get("competences", {}) if isinstance(previous_system, dict) else {}
    try:
        releases = config["fetch"]()
    except (OSError, ValueError) as exc:
        print(f"[{key}] consulta oficial falhou: {type(exc).__name__}: {exc}")
        result = dict(previous_system) if previous_system else {
            "label": config["label"], "official_page": config["official_page"], "competences": {},
        }
        result["official_reachable"] = False
        result["checked_at"] = checked_at
        return result

    competences = sorted({str(item["competence"]) for item in releases})[-COMPETENCE_LIMIT:]
    latest_by_competence = {
        competence: next(item for item in releases if item["competence"] == competence)
        for competence in competences
    }

    updated_competences = dict(previous_competences)
    for competence, release in latest_by_competence.items():
        name = str(release["name"])
        tag = f"{key.replace('_', '-')}-{competence}"
        previous_entry = previous_competences.get(competence, {})
        already_mirrored = previous_entry.get("name") == name and (previous_entry.get("mirror") or {}).get("asset_url")
        if already_mirrored:
            print(f"[{key}] {competence}: sem mudança ({name})")
            continue
        print(f"[{key}] {competence}: versão nova ou ainda não espelhada: {name}")
        try:
            package = config["download"](release)
        except (OSError, ValueError) as exc:
            print(f"[{key}] {competence}: download falhou, mantendo o pacote anterior: {type(exc).__name__}: {exc}")
            continue
        target_dir = DIST_DIR / key
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / name).write_bytes(package)
        updated_competences[competence] = {
            "name": name, "size": release.get("size"), "url": release["url"],
            "mirror": {"tag": tag, "asset_name": name, "asset_url": _asset_url(tag, name)},
        }

    return {
        "label": config["label"],
        "official_page": config["official_page"],
        "competences": updated_competences,
        "checked_at": checked_at,
        "official_reachable": True,
    }


def main() -> None:
    previous = _load_previous()
    systems: dict[str, object] = {}
    for key, config in SINGLE_VERSION_SYSTEMS.items():
        systems[key] = sync_single_version_system(key, config, previous)
    for key, config in COMPETENCE_SYSTEMS.items():
        systems[key] = sync_competence_system(key, config, previous)

    catalog = {"updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "systems": systems}
    CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CATALOG_PATH.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if DIST_DIR.is_dir() and any(DIST_DIR.rglob("*")):
        print("Arquivos novos para publicar em dist/:")
        for path in sorted(DIST_DIR.rglob("*")):
            if path.is_file():
                print(" -", path.relative_to(ROOT))
    else:
        print("Nenhum arquivo novo para espelhar.")


if __name__ == "__main__":
    main()

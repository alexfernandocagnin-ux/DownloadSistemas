"""Consulta as quatro fontes oficiais e prepara o espelho próprio em dist/.

Nunca executa os instaladores baixados. Quando uma versão muda, baixa o
arquivo oficial (com os mesmos limites de tamanho/host dos módulos de
catálogo) para dist/<sistema>/<arquivo> e atualiza data/catalog.json. O
workflow do GitHub Actions é quem de fato sobe cada arquivo de dist/ como
asset de uma Release (gh release upload) e comita o catalog.json atualizado.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogs import bpa_portal, sia_portal, sihd_portal  # noqa: E402

CATALOG_PATH = ROOT / "data" / "catalog.json"
DIST_DIR = ROOT / "dist"
BDSIA_COMPETENCE_LIMIT = 6

SINGLE_VERSION_SYSTEMS = {
    "bpa": {
        "label": "BPA Magnético",
        "official_page": "https://sia.datasus.gov.br/versao/listar_ftp_bpa.php",
        "fetch": bpa_portal.fetch_bpa_catalog,
        "download": bpa_portal.download_release,
        "tag": "bpa-latest",
    },
    "sia": {
        "label": "SIA (instalador)",
        "official_page": "https://sia.datasus.gov.br/versao/listar_ftp_sia.php",
        "fetch": sia_portal.fetch_sia_catalog,
        "download": sia_portal.download_release,
        "tag": "sia-latest",
    },
    "sihd2": {
        "label": "SIHD2 (instalador)",
        "official_page": "http://sihd.datasus.gov.br/versao/versao_sihd2.php",
        "fetch": sihd_portal.fetch_sihd2_catalog,
        "download": sihd_portal.download_release,
        "tag": "sihd2-latest",
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
        if name != previous_name:
            print(f"[{key}] versão nova: {name} (antes: {previous_name or 'nenhuma'})")
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


def sync_bdsia(previous: dict[str, object]) -> dict[str, object]:
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    previous_system = previous.get("systems", {}).get("bdsia", {})
    previous_competences = previous_system.get("competences", {}) if isinstance(previous_system, dict) else {}
    try:
        releases = sia_portal.fetch_bdsia_catalog()
    except (OSError, ValueError) as exc:
        print(f"[bdsia] consulta oficial falhou: {type(exc).__name__}: {exc}")
        result = dict(previous_system) if previous_system else {
            "label": "Tabela mensal do SIA (BDSIA)", "official_page": sia_portal.INDEX_URL, "competences": {},
        }
        result["official_reachable"] = False
        result["checked_at"] = checked_at
        return result

    competences = sorted({str(item["competence"]) for item in releases})[-BDSIA_COMPETENCE_LIMIT:]
    latest_by_competence = {}
    for competence in competences:
        latest_by_competence[competence] = next(item for item in releases if item["competence"] == competence)

    updated_competences = dict(previous_competences)
    for competence, release in latest_by_competence.items():
        name = str(release["name"])
        tag = f"bdsia-{competence}"
        if previous_competences.get(competence, {}).get("name") == name:
            print(f"[bdsia] {competence}: sem mudança ({name})")
            continue
        print(f"[bdsia] {competence}: versão nova {name}")
        try:
            package = sia_portal.download_release(release)
        except (OSError, ValueError) as exc:
            print(f"[bdsia] {competence}: download falhou, mantendo o pacote anterior: {type(exc).__name__}: {exc}")
            continue
        target_dir = DIST_DIR / "bdsia"
        target_dir.mkdir(parents=True, exist_ok=True)
        (target_dir / name).write_bytes(package)
        updated_competences[competence] = {
            "name": name, "size": release.get("size"), "url": release["url"],
            "mirror": {"tag": tag, "asset_name": name, "asset_url": _asset_url(tag, name)},
        }

    return {
        "label": "Tabela mensal do SIA (BDSIA)",
        "official_page": sia_portal.INDEX_URL,
        "competences": updated_competences,
        "checked_at": checked_at,
        "official_reachable": True,
    }


def main() -> None:
    previous = _load_previous()
    systems: dict[str, object] = {}
    for key, config in SINGLE_VERSION_SYSTEMS.items():
        systems[key] = sync_single_version_system(key, config, previous)
    systems["bdsia"] = sync_bdsia(previous)

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

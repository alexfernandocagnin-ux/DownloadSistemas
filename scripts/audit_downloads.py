"""Confere fontes e arquivos do portal sem executar instaladores.

Use --full para verificar por streaming também os pacotes grandes.
Use --output caminho.json para salvar o relatório da conferência.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogs._common import USER_AGENT
from catalogs.mirrors import MAX_PACKAGE_SIZE, matching_mirror, probe_mirror
from catalogs import sigtap_portal
from scripts.sync_catalog import COMPETENCE_SYSTEMS, SINGLE_VERSION_SYSTEMS, now


def check_file(entry, *, full):
    name, mirror = entry.get("name"), entry.get("mirror")
    result = {"name": name}
    if not matching_mirror(name, mirror):
        return {**result, "error": "Nenhuma cópia publicada para este arquivo."}
    try:
        result["url"] = probe_mirror(name, mirror)
        if not full and mirror.get("size", MAX_PACKAGE_SIZE) > 50_000_000:
            return {**result, "check": "Assinatura e tamanho; conteúdo completo não conferido."}
        digest, size = hashlib.sha256(), 0
        request = Request(result["url"], headers={"User-Agent": USER_AGENT})
        with urlopen(request, timeout=90) as response:
            while block := response.read(1024 * 1024):
                size += len(block)
                if size > MAX_PACKAGE_SIZE:
                    raise ValueError("Arquivo excedeu o limite de tamanho.")
                digest.update(block)
        result.update(size=size, sha256=digest.hexdigest())
        if size != mirror.get("size"):
            raise ValueError("Tamanho completo diferente do catálogo.")
        if mirror.get("sha256") and result["sha256"] != mirror["sha256"]:
            raise ValueError("SHA-256 diferente do catálogo.")
        result["check"] = "SHA-256 confere com o catálogo." if mirror.get("sha256") else "Arquivo completo lido; catálogo sem SHA-256 de referência."
    except (OSError, ValueError) as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def audit_system(key, config, saved, *, full):
    result = {"system": key, "label": config["label"]}
    try:
        releases = config["fetch"]()
        latest = releases[0]
        result["catalog_latest"] = latest
        result["catalog_source"] = latest.get("catalog_source") or "official"
    except (OSError, ValueError, IndexError) as exc:
        latest = None
        releases = []
        result["catalog_error"] = f"{type(exc).__name__}: {exc}"
    if key in COMPETENCE_SYSTEMS:
        entries = list(saved.get("competences", {}).values())
    else:
        entries = [{**(saved.get("current") or {}), "mirror": saved.get("mirror")}]
    result["files"] = [check_file(entry, full=full) for entry in entries]
    if latest:
        result["latest_mirrored"] = any(item["name"] == latest["name"] and not item.get("error") for item in result["files"])
    for current_check in result["files"]:
        release = next((item for item in releases if item["name"] == current_check["name"]), None)
        if release and current_check.get("sha256") and current_check.get("size", MAX_PACKAGE_SIZE) <= 50_000_000:
            try:
                if key == "sigtap":
                    package, source = sigtap_portal.download_release_with_source(release)
                else:
                    package, source = config["download"](release), "Fonte oficial DATASUS"
                official_hash = hashlib.sha256(package).hexdigest()
                current_check["source"] = source
                current_check["source_sha256"] = official_hash
                current_check["source_matches_mirror"] = official_hash == current_check["sha256"]
                if not current_check["source_matches_mirror"]:
                    current_check["error"] = "O conteúdo do espelho difere do arquivo obtido na origem."
            except (OSError, ValueError) as exc:
                current_check["source_download_error"] = f"{type(exc).__name__}: {exc}"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snapshot = json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8"))
    configs = {**SINGLE_VERSION_SYSTEMS, **COMPETENCE_SYSTEMS}
    results = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {pool.submit(audit_system, key, cfg, snapshot.get("systems", {}).get(key, {}), full=args.full): key for key, cfg in configs.items()}
        for task in as_completed(tasks):
            key = tasks[task]
            results[key] = task.result()
            errors = sum("error" in item for item in results[key]["files"])
            print(f"{key}: {len(results[key]['files'])} arquivo(s), {errors} falha(s)", flush=True)
    report = {"checked_at": now(), "full": args.full, "systems": results}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Relatório: {args.output}", flush=True)
    return int(any("error" in item for result in results.values() for item in result["files"]) or any(result.get("latest_mirrored") is False or result.get("catalog_error") for result in results.values()))


if __name__ == "__main__":
    sys.exit(main())

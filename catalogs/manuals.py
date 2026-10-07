"""Biblioteca de documentação oficial; downloads são preparados sob demanda."""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

from catalogs._common import download_via_ftp, download_via_http, looks_like_zip, safe_official_url
from catalogs.cnes_portal import safe_url as safe_cnes_url

MANUALS = json.loads((Path(__file__).parent.parent / "data" / "manuals.json").read_text(encoding="utf-8"))
SYSTEMS = {
    "bpa": ("BPA Magnético", "🧾"),
    "apac": ("APAC Magnético", "📝"),
    "sia": ("SIA / BDSIA", "🏥"),
    "fpo": ("FPO Magnético", "🧮"),
    "sihd2": ("SIHD2", "🏨"),
    "cnes": ("CNES / SCNES", "🗂️"),
    "ciha02": ("CIHA02", "🏛️"),
    "sigtap": ("SIGTAP", "💊"),
}
MAX_MANUAL_SIZE = 50_000_000
FTP_DIRECTORIES = {
    "arpoador.datasus.gov.br": "/siasus/Documentos/",
    "ftp2.datasus.gov.br": "/public/sistemas/dsweb/SIHD/Manuais/",
}


def search_text(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                   if not unicodedata.combining(char))


def filter_manuals(query="", system="", category=""):
    words = search_text(query).split()
    return [manual for manual in MANUALS
            if (not system or manual["system"] == system)
            and (not category or manual["category"] == category)
            and all(word in search_text(" ".join((manual["title"], manual["description"],
                                                 SYSTEMS[manual["system"]][0], manual["category"])))
                    for word in words)]


def download_manual(manual_id: str) -> bytes:
    manual = next(item for item in MANUALS if item["id"] == manual_id)
    if manual["format"] == "Online":
        raise ValueError("Este manual está disponível para leitura online.")
    name, url = manual["name"], manual["url"]
    parsed = urlsplit(url)
    if parsed.scheme == "ftp" and safe_official_url(
        url, name, ftp_hosts=frozenset(FTP_DIRECTORIES),
        ftp_path_prefix=FTP_DIRECTORIES.get(parsed.hostname, ""),
    ):
        package = download_via_ftp(parsed.hostname, unquote(parsed.path.rsplit("/", 1)[0]), name,
                                   max_size=MAX_MANUAL_SIZE, timeout=15, max_seconds=60)
    elif safe_cnes_url(url, name):
        package = download_via_http(url, name, max_size=MAX_MANUAL_SIZE, timeout=15, max_seconds=60)
    else:
        raise ValueError("O documento não possui um endereço oficial permitido.")
    if len(package) > MAX_MANUAL_SIZE:
        raise ValueError("O documento excedeu o limite de tamanho.")
    if manual["format"] == "PDF":
        valid = package.startswith(b"%PDF-") and b"%%EOF" in package[-1024:]
    else:
        valid = looks_like_zip(package, min_size=20)
    if not valid:
        raise ValueError("A fonte não entregou um documento válido. Tente novamente mais tarde.")
    return package

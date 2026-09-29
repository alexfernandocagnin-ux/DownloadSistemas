"""Catálogo do instalador do BPA Magnético (sia.datasus.gov.br/versao/listar_ftp_bpa.php)."""

from __future__ import annotations

import re
from ftplib import Error as FTPError

from catalogs._common import (
    download_release as _download_release, fetch_ftp_names, fetch_index_entries, resolve_href, safe_official_url,
)

MAX_PACKAGE_SIZE = 50_000_000

HTTPS_HOST = "sia.datasus.gov.br"
FTP_HOSTS = frozenset({"ftp.datasus.gov.br", "arpoador.datasus.gov.br"})
# Caminho FTP por analogia ao do BDSIA; não confirmado ao vivo (a página HTML já responde).
FTP_PATH_PREFIX = "/siasus/bpa/"
FTP_DIRECTORY = "/siasus/BPA"
INDEX_URL = f"https://{HTTPS_HOST}/versao/listar_ftp_bpa.php"

BPA_PATTERN = re.compile(r"BPAMAG(\d{4})\.exe", re.IGNORECASE)


def safe_url(url: str, name: str) -> bool:
    return safe_official_url(
        url, name, https_hosts=frozenset({HTTPS_HOST}), ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_PATH_PREFIX,
    )


def _entries_from_index() -> list[dict[str, object]]:
    entries = []
    for item in fetch_index_entries(INDEX_URL):
        href_url = resolve_href(INDEX_URL, str(item["url"]))
        name = item.get("name") or href_url.rsplit("/", 1)[-1]
        entries.append({"name": name, "url": href_url, "size": item.get("size"),
                        "release_date": item.get("release_date")})
    return entries


def _entries_from_ftp() -> list[dict[str, object]]:
    names = []
    for host in sorted(FTP_HOSTS):
        try:
            names = fetch_ftp_names(host, FTP_DIRECTORY)
            break
        except (OSError, FTPError):
            continue
    else:
        raise OSError("Nenhum servidor FTP oficial do BPA respondeu.")
    return [{"name": name, "url": f"ftp://{host}{FTP_DIRECTORY}/{name}", "size": None} for name in names]


def fetch_bpa_catalog() -> list[dict[str, object]]:
    """Instalador do BPA Magnético (versão única), mais recente primeiro."""
    try:
        entries = _entries_from_index()
    except (OSError, ValueError):
        entries = _entries_from_ftp()
    releases = []
    for entry in entries:
        name = entry.get("name")
        match = BPA_PATTERN.fullmatch(str(name)) if isinstance(name, str) else None
        url = entry.get("url")
        if not match or not isinstance(url, str) or not safe_url(url, str(name)):
            continue
        releases.append({"name": name, "url": url, "size": entry.get("size"), "version": match.group(1),
                         "release_date": entry.get("release_date")})
    if not releases:
        raise ValueError("Nenhum instalador do BPA Magnético foi encontrado.")
    return sorted(releases, key=lambda item: item["version"], reverse=True)


def download_release(release: dict[str, object]) -> bytes:
    """Baixa o instalador do BPA Magnético já catalogado, sem executá-lo."""
    return _download_release(
        str(release["url"]), str(release["name"]), safe_url_fn=safe_url, max_size=MAX_PACKAGE_SIZE, ftp_hosts=FTP_HOSTS,
    )

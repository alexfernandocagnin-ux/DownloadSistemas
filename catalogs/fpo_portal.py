"""Catálogo oficial dos instaladores e atualizações do FPO Magnético."""

from __future__ import annotations

import re
from ftplib import Error as FTPError

from catalogs._common import (
    download_release as _download_release,
    fetch_ftp_names,
    fetch_index_links,
    resolve_href,
    safe_official_url,
)

HTTPS_HOST = "sia.datasus.gov.br"
FTP_HOSTS = frozenset({"ftp.datasus.gov.br", "arpoador.datasus.gov.br"})
FTP_PATH_PREFIX = "/siasus/fpo/"
FTP_DIRECTORY = "/siasus/FPO"
INDEX_URL = f"https://{HTTPS_HOST}/versao/listar_ftp_fpo.php"

INSTALLER_PATTERN = re.compile(r"FPOMAG_Instalador_(\d{4})\.exe", re.IGNORECASE)
UPDATE_PATTERN = re.compile(r"FPOMAG_Atualiza_(\d{4})\.exe", re.IGNORECASE)
MAX_PACKAGE_SIZE = 50_000_000


def safe_url(url: str, name: str) -> bool:
    return safe_official_url(
        url,
        name,
        https_hosts=frozenset({HTTPS_HOST}),
        ftp_hosts=FTP_HOSTS,
        ftp_path_prefix=FTP_PATH_PREFIX,
    )


def _entries_from_index() -> list[dict[str, object]]:
    entries = []
    for text, href in fetch_index_links(INDEX_URL):
        url = resolve_href(INDEX_URL, href)
        name = text or url.rsplit("/", 1)[-1]
        entries.append({"name": name, "url": url, "size": None})
    return entries


def _entries_from_ftp() -> list[dict[str, object]]:
    for host in sorted(FTP_HOSTS):
        try:
            names = fetch_ftp_names(host, FTP_DIRECTORY)
        except (OSError, FTPError):
            continue
        return [
            {"name": name, "url": f"ftp://{host}{FTP_DIRECTORY}/{name}", "size": None}
            for name in names
        ]
    raise OSError("Nenhum diretório FTP oficial da FPO respondeu.")


def _matching_releases(entries: list[dict[str, object]], pattern: re.Pattern[str]) -> list[dict[str, object]]:
    releases = []
    for entry in entries:
        name = entry.get("name")
        match = pattern.fullmatch(str(name)) if isinstance(name, str) else None
        url = entry.get("url")
        if not match or not isinstance(url, str) or not safe_url(url, str(name)):
            continue
        releases.append({"name": name, "url": url, "size": entry.get("size"), "version": match.group(1)})
    return releases


def _fetch_catalog(pattern: re.Pattern[str], description: str) -> list[dict[str, object]]:
    try:
        releases = _matching_releases(_entries_from_index(), pattern)
    except (OSError, ValueError):
        releases = []
    if not releases:
        try:
            releases = _matching_releases(_entries_from_ftp(), pattern)
        except (OSError, ValueError):
            releases = []
    if not releases:
        raise ValueError(f"Nenhum {description} oficial do FPO foi encontrado.")
    return sorted(releases, key=lambda item: item["version"], reverse=True)


def fetch_fpo_installer_catalog() -> list[dict[str, object]]:
    """Instalador inicial do FPO, mais recente primeiro."""
    return _fetch_catalog(INSTALLER_PATTERN, "instalador")


def fetch_fpo_update_catalog() -> list[dict[str, object]]:
    """Atualizações do FPO, mais recente primeiro."""
    return _fetch_catalog(UPDATE_PATTERN, "atualizador")


def download_release(release: dict[str, object]) -> bytes:
    """Baixa um instalador ou atualizador catalogado sem executá-lo."""
    return _download_release(
        str(release["url"]),
        str(release["name"]),
        safe_url_fn=safe_url,
        max_size=MAX_PACKAGE_SIZE,
        ftp_hosts=FTP_HOSTS,
    )

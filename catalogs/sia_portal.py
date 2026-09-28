"""Catálogo de pacotes hospedados em sia.datasus.gov.br: BDSIA e o instalador do SIA.

As duas famílias de arquivo (BDSIA<competência><rev>.exe e SIA<versão>.exe)
vivem na mesma página oficial, então o fetch é compartilhado e cada função
pública filtra pelo padrão de nome que interessa.
"""

from __future__ import annotations

import re
from ftplib import Error as FTPError

from catalogs._common import (
    download_release as _download_release, fetch_ftp_names, fetch_index_links, resolve_href, safe_official_url,
)

HTTPS_HOST = "sia.datasus.gov.br"
FTP_HOSTS = frozenset({"ftp.datasus.gov.br", "arpoador.datasus.gov.br"})
FTP_PATH_PREFIX = "/siasus/sia/"
FTP_DIRECTORY = "/siasus/SIA"
INDEX_URL = f"https://{HTTPS_HOST}/versao/listar_ftp_sia.php"

BDSIA_PATTERN = re.compile(r"BDSIA(20\d{2})(0[1-9]|1[0-2])([a-z])\.exe", re.IGNORECASE)
SIA_PATTERN = re.compile(r"(?:INST)?SIA(\d{4})\.exe", re.IGNORECASE)
MAX_PACKAGE_SIZE = 50_000_000


def safe_url(url: str, name: str) -> bool:
    return safe_official_url(
        url, name, https_hosts=frozenset({HTTPS_HOST}), ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_PATH_PREFIX,
    )


def _entries_from_index() -> list[dict[str, object]]:
    """Read every filename+link on the shared SIA download index page."""
    entries = []
    for text, href in fetch_index_links(INDEX_URL):
        href_url = resolve_href(INDEX_URL, href)
        name = text if text else href_url.rsplit("/", 1)[-1]
        entries.append({"name": name, "url": href_url, "size": None})
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
        raise OSError("Nenhum servidor FTP oficial do SIA respondeu.")
    return [{"name": name, "url": f"ftp://{host}{FTP_DIRECTORY}/{name}", "size": None} for name in names]


def _fetch_raw_entries() -> list[dict[str, object]]:
    try:
        return _entries_from_index()
    except (OSError, ValueError):
        return _entries_from_ftp()


def _filter_and_validate(
    entries: list[dict[str, object]], pattern: re.Pattern[str],
) -> list[dict[str, object]]:
    releases = []
    for entry in entries:
        name = entry.get("name")
        match = pattern.fullmatch(str(name)) if isinstance(name, str) else None
        url = entry.get("url")
        if not match or not isinstance(url, str) or not safe_url(url, str(name)):
            continue
        releases.append({"name": name, "url": url, "size": entry.get("size"), "match": match})
    return releases


def fetch_bdsia_catalog() -> list[dict[str, object]]:
    """Pacotes mensais BDSIA, mais recentes primeiro."""
    releases = _filter_and_validate(_fetch_raw_entries(), BDSIA_PATTERN)
    if not releases:
        raise ValueError("Nenhum pacote BDSIA oficial foi encontrado.")
    result = [
        {
            "name": item["name"], "url": item["url"], "size": item["size"],
            "competence": item["match"].group(1) + item["match"].group(2),
            "revision": item["match"].group(3).lower(),
        }
        for item in releases
    ]
    return sorted(result, key=lambda item: (item["competence"], item["revision"]), reverse=True)


def fetch_sia_catalog() -> list[dict[str, object]]:
    """Instalador do SIA (versão única, sem competência), mais recente primeiro."""
    releases = _filter_and_validate(_fetch_raw_entries(), SIA_PATTERN)
    if not releases:
        raise ValueError("Nenhum instalador do SIA foi encontrado.")
    result = [
        {"name": item["name"], "url": item["url"], "size": item["size"], "version": item["match"].group(1)}
        for item in releases
    ]
    return sorted(result, key=lambda item: item["version"], reverse=True)


def download_release(release: dict[str, object]) -> bytes:
    """Baixa um pacote BDSIA ou SIA já catalogado, sem executá-lo."""
    return _download_release(
        str(release["url"]), str(release["name"]), safe_url_fn=safe_url, max_size=MAX_PACKAGE_SIZE, ftp_hosts=FTP_HOSTS,
    )

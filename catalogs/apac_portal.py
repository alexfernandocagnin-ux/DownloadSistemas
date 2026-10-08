"""Instalador do APAC Magnético na listagem oficial do SIA."""

import re
from urllib.parse import unquote, urlsplit

from catalogs._common import (
    download_release as _download_release, fetch_ftp_names, fetch_index_entries,
    resolve_href, safe_official_url,
)

INDEX_URL = "https://sia.datasus.gov.br/versao/listar_ftp_apac.php"
FTP_HOSTS = frozenset({"arpoador.datasus.gov.br", "ftp.datasus.gov.br"})
FTP_DIRECTORY = "/siasus/APAC"
FILE_PATTERN = re.compile(r"APACMAG_(\d{4})\.exe", re.IGNORECASE)


def safe_url(url, name):
    return safe_official_url(url, name, https_hosts=frozenset({"sia.datasus.gov.br"}),
                             ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_DIRECTORY + "/")


def _matching_releases(entries):
    releases = []
    for entry in entries:
        try:
            url = resolve_href(INDEX_URL, str(entry.get("url", "")))
            name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        except ValueError:
            continue
        match = FILE_PATTERN.fullmatch(name)
        if match and safe_url(url, name):
            releases.append({"name": name, "url": url, "size": entry.get("size"),
                             "version": match.group(1), "release_date": entry.get("release_date")})
    return releases


def fetch_apac_catalog():
    try:
        releases = _matching_releases(fetch_index_entries(INDEX_URL))
    except (OSError, ValueError):
        releases = []
    if not releases:
        last_error = None
        for host in sorted(FTP_HOSTS):
            try:
                entries = [{"name": name, "url": f"ftp://{host}{FTP_DIRECTORY}/{name}"}
                           for name in fetch_ftp_names(host, FTP_DIRECTORY)]
            except OSError as exc:
                last_error = exc
                continue
            releases = _matching_releases(entries)
            if releases:
                break
        if not releases and last_error is not None:
            raise OSError("Não foi possível obter instaladores oficiais do APAC pelos servidores FTP.") from last_error
    if not releases:
        raise ValueError("Nenhum instalador oficial do APAC foi encontrado.")
    return sorted(releases, key=lambda item: item["version"], reverse=True)


def download_release(release):
    return _download_release(str(release["url"]), str(release["name"]), safe_url_fn=safe_url,
                             max_size=50_000_000, ftp_hosts=FTP_HOSTS)

"""Instalação inicial e atualização do RAAS na listagem oficial do SIA.

Desde o RAAS 3 o DATASUS publica um instalador (RAAS3_SETUP_<versão>.exe) e
uma atualização a aplicar sobre ele (RAAS3_ATUALIZA_<versão>.exe). A mesma
pasta guarda o antigo RAAS_<versão>.exe e versões "Mob"/"AD" de 2012–2013,
que ficam fora do catálogo.
"""

import re
from urllib.parse import unquote, urlsplit

from catalogs._common import (
    download_release as _download_release, fetch_ftp_names, fetch_index_entries,
    resolve_href, safe_official_url,
)

INDEX_URL = "https://sia.datasus.gov.br/versao/listar_ftp_raas.php"
FTP_HOSTS = frozenset({"arpoador.datasus.gov.br", "ftp.datasus.gov.br"})
FTP_DIRECTORY = "/siasus/raas"
INSTALLER_PATTERN = re.compile(r"RAAS(\d+)_SETUP_(\d{4})\.exe", re.IGNORECASE)
UPDATE_PATTERN = re.compile(r"RAAS(\d+)_ATUALIZA_(\d{4})\.exe", re.IGNORECASE)


def safe_url(url, name):
    return safe_official_url(url, name, https_hosts=frozenset({"sia.datasus.gov.br"}),
                             ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_DIRECTORY + "/")


def _matching_releases(entries, pattern):
    releases = []
    for entry in entries:
        try:
            # A listagem oficial deixa um espaço no fim de cada link.
            url = resolve_href(INDEX_URL, str(entry.get("url", "")).strip())
            name = unquote(urlsplit(url).path.rsplit("/", 1)[-1])
        except ValueError:
            continue
        match = pattern.fullmatch(name)
        if match and safe_url(url, name):
            releases.append({"name": name, "url": url, "size": entry.get("size"), "major": int(match.group(1)),
                             "version": match.group(2), "release_date": entry.get("release_date")})
    return releases


def _fetch_catalog(pattern, kind):
    try:
        releases = _matching_releases(fetch_index_entries(INDEX_URL), pattern)
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
            releases = _matching_releases(entries, pattern)
            if releases:
                break
        if not releases and last_error is not None:
            raise OSError(f"Não foi possível obter {kind} oficial do RAAS pelos servidores FTP.") from last_error
    if not releases:
        raise ValueError(f"Nenhum(a) {kind} oficial do RAAS foi encontrado(a).")
    return sorted(releases, key=lambda item: (item["major"], item["version"]), reverse=True)


def fetch_raas_installer_catalog():
    return _fetch_catalog(INSTALLER_PATTERN, "instalador")


def fetch_raas_update_catalog():
    return _fetch_catalog(UPDATE_PATTERN, "atualização")


def download_release(release):
    return _download_release(str(release["url"]), str(release["name"]), safe_url_fn=safe_url,
                             max_size=50_000_000, ftp_hosts=FTP_HOSTS)

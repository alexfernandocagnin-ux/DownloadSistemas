"""Instalador do APAC Magnético na listagem oficial do SIA."""

import re

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


def fetch_apac_catalog():
    try:
        entries = fetch_index_entries(INDEX_URL)
        if not any(FILE_PATTERN.fullmatch(str(entry.get("name", ""))) for entry in entries):
            raise ValueError("A página não entregou instaladores APAC.")
    except (OSError, ValueError):
        for host in sorted(FTP_HOSTS):
            try:
                entries = [{"name": name, "url": f"ftp://{host}{FTP_DIRECTORY}/{name}"}
                           for name in fetch_ftp_names(host, FTP_DIRECTORY)]
                break
            except OSError:
                continue
        else:
            raise OSError("Nenhuma fonte oficial do APAC respondeu.")
    releases = []
    for entry in entries:
        name = str(entry.get("name", ""))
        match = FILE_PATTERN.fullmatch(name)
        url = resolve_href(INDEX_URL, str(entry["url"]))
        if match and safe_url(url, name):
            releases.append({"name": name, "url": url, "size": entry.get("size"),
                             "version": match.group(1), "release_date": entry.get("release_date")})
    if not releases:
        raise ValueError("Nenhum instalador oficial do APAC foi encontrado.")
    return sorted(releases, key=lambda item: item["version"], reverse=True)


def download_release(release):
    return _download_release(str(release["url"]), str(release["name"]), safe_url_fn=safe_url,
                             max_size=50_000_000, ftp_hosts=FTP_HOSTS)

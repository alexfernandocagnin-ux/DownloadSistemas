"""CIHA01 e CIHA02: atualização e primeira instalação, sem executar arquivos."""

import re
from urllib.parse import urlsplit

from catalogs._common import download_release as _download_release, fetch_index_entries, safe_official_url

PAGES = {"01": "http://ciha.saude.gov.br/versao/versao_ciha1.php",
         "02": "http://ciha.saude.gov.br/versao/versao_ciha2.php"}
FTP_HOSTS = frozenset({"ftp2.datasus.gov.br"})
FTP_DIRECTORY = "/public/sistemas/dsweb/SIHD/CIHA/Programas/"
FILE_PATTERN = re.compile(r"CIHA(01|02)_(VER(\d{4})|SETUP_(\d{2})\.(\d{2}))\.exe", re.IGNORECASE)


def safe_url(url, name):
    return safe_official_url(url, name, ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_DIRECTORY)


def fetch_ciha_catalog(module, installer=False):
    releases = []
    try:
        entries = fetch_index_entries(PAGES[module])
    except OSError:
        entries = fetch_index_entries(PAGES[module].replace("http://", "https://", 1))
    for entry in entries:
        url = "".join(str(entry["url"]).split())
        name = urlsplit(url).path.rsplit("/", 1)[-1]
        match = FILE_PATTERN.fullmatch(name)
        if not match or match.group(1) != module or not safe_url(url, name):
            continue
        is_installer = match.group(4) is not None
        if is_installer != installer:
            continue
        version = match.group(3) or match.group(4) + match.group(5)
        releases.append({"name": name, "url": url, "size": None, "version": version,
                         "release_date": entry.get("release_date")})
    if not releases:
        raise ValueError(f"Nenhum pacote oficial CIHA{module} foi encontrado.")
    return sorted(releases, key=lambda item: item["version"], reverse=True)


def fetch_ciha01_catalog():
    return fetch_ciha_catalog("01")


def fetch_ciha02_catalog():
    return fetch_ciha_catalog("02")


def fetch_ciha01_installer_catalog():
    return fetch_ciha_catalog("01", installer=True)


def fetch_ciha02_installer_catalog():
    return fetch_ciha_catalog("02", installer=True)


def download_release(release):
    return _download_release(str(release["url"]), str(release["name"]), safe_url_fn=safe_url,
                             max_size=100_000_000, ftp_hosts=FTP_HOSTS)

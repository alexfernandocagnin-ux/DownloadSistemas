"""Catálogo da Tabela Unificada (SIGTAP), via o RSS oficial de competências.

O feed é mais estável que raspar a tela JSF de download.jsp (que usa
jsessionid e formulários) e já traz o link FTP de cada competência.
"""

from __future__ import annotations

import gzip
import re
from urllib.request import Request, urlopen

from catalogs._common import (
    USER_AGENT, download_release as _download_release, looks_like_zip, safe_official_url,
)

RSS_URL = "http://sigtap.datasus.gov.br/tabela-unificada/competencias.rss"
DOWNLOAD_PAGE = "http://sigtap.datasus.gov.br/tabela-unificada/app/download.jsp"
FTP_HOSTS = frozenset({"ftp2.datasus.gov.br"})
FTP_PATH_PREFIX = "/pub/sistemas/tup/downloads/"
FILE_PATTERN = re.compile(r"TabelaUnificada_(20\d{2})(0[1-9]|1[0-2])_v(\d+)\.zip", re.IGNORECASE)
LINK_PATTERN = re.compile(r"<link>(ftp://[^<]+)</link>")
MAX_FEED_BYTES = 2_000_000
MAX_PACKAGE_SIZE = 50_000_000


def safe_url(url: str, name: str) -> bool:
    return safe_official_url(url, name, ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_PATH_PREFIX)


def fetch_sigtap_catalog() -> list[dict[str, object]]:
    """Pacotes mensais da Tabela Unificada, mais recentes primeiro."""
    request = Request(RSS_URL, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    with urlopen(request, timeout=15) as response:
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("O feed de competências do SIGTAP excedeu o tamanho esperado.")
    document = gzip.decompress(payload) if payload[:2] == b"\x1f\x8b" else payload
    text = document.decode("utf-8", "replace")

    releases = []
    for url in LINK_PATTERN.findall(text):
        name = url.rsplit("/", 1)[-1]
        match = FILE_PATTERN.fullmatch(name)
        if not match or not safe_url(url, name):
            continue
        releases.append({
            "name": name, "url": url, "size": None,
            "competence": match.group(1) + match.group(2), "revision": match.group(3),
        })
    if not releases:
        raise ValueError("Nenhum pacote SIGTAP válido foi encontrado no feed.")
    return sorted(releases, key=lambda item: (item["competence"], int(item["revision"])), reverse=True)


def download_release(release: dict[str, object]) -> bytes:
    """Baixa um pacote SIGTAP já catalogado, sem abri-lo."""
    return _download_release(
        str(release["url"]), str(release["name"]), safe_url_fn=safe_url,
        max_size=MAX_PACKAGE_SIZE, looks_valid_fn=looks_like_zip,
    )

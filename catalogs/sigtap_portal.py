"""Catálogo da Tabela Unificada (SIGTAP), via o RSS oficial de competências.

O feed é mais estável que raspar a tela JSF de download.jsp (que usa
jsessionid e formulários) e já traz o link FTP de cada competência.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import re
from urllib.request import Request, urlopen

from catalogs._common import (
    USER_AGENT, download_release as _download_release, download_via_http, looks_like_zip,
    safe_official_url,
)

RSS_URL = "http://sigtap.datasus.gov.br/tabela-unificada/competencias.rss"
DOWNLOAD_PAGE = "http://sigtap.datasus.gov.br/tabela-unificada/app/download.jsp"
FTP_HOSTS = frozenset({"ftp2.datasus.gov.br"})
FTP_PATH_PREFIX = "/pub/sistemas/tup/downloads/"
FILE_PATTERN = re.compile(r"TabelaUnificada_(20\d{2})(0[1-9]|1[0-2])_v(\d+)\.zip", re.IGNORECASE)
LINK_PATTERN = re.compile(r"<link>(ftp://[^<]+)</link>")
MAX_FEED_BYTES = 2_000_000
MAX_PACKAGE_SIZE = 50_000_000
COMMUNITY_MIRROR = "https://raw.githubusercontent.com/RenatoKR/SIGTAP/main/tabelas"
COMMUNITY_API = "https://api.github.com/repos/RenatoKR/SIGTAP/contents/tabelas?ref=main"


def safe_url(url: str, name: str) -> bool:
    return safe_official_url(url, name, ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_PATH_PREFIX)


def fetch_sigtap_catalog() -> list[dict[str, object]]:
    """Pacotes mensais da Tabela Unificada, mais recentes primeiro."""
    releases = []
    try:
        request = Request(RSS_URL, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
        with urlopen(request, timeout=15) as response:
            payload = response.read(MAX_FEED_BYTES + 1)
        if len(payload) > MAX_FEED_BYTES:
            raise ValueError("O feed de competências do SIGTAP excedeu o tamanho esperado.")
        if payload[:2] == b"\x1f\x8b":
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as feed:
                document = feed.read(MAX_FEED_BYTES + 1)
        else:
            document = payload
        if len(document) > MAX_FEED_BYTES:
            raise ValueError("O feed descompactado excedeu o tamanho esperado.")
        for url in LINK_PATTERN.findall(document.decode("utf-8", "replace")):
            name = url.rsplit("/", 1)[-1]
            match = FILE_PATTERN.fullmatch(name)
            if match and safe_url(url, name):
                releases.append({
                    "name": name, "url": url, "size": None,
                    "competence": match.group(1) + match.group(2), "revision": match.group(3),
                })
    except (OSError, ValueError, EOFError):
        releases = []
    if not releases:
        releases = _fetch_community_catalog()
    return sorted(releases, key=lambda item: (item["competence"], int(item["revision"])), reverse=True)


def _fetch_community_catalog() -> list[dict[str, object]]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"}
    if token := os.environ.get("GH_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    request = Request(COMMUNITY_API, headers=headers)
    with urlopen(request, timeout=15) as response:
        payload = response.read(MAX_FEED_BYTES + 1)
    if len(payload) > MAX_FEED_BYTES:
        raise ValueError("O catálogo comunitário do SIGTAP excedeu o tamanho esperado.")
    items = json.loads(payload.decode("utf-8", "replace"))
    if not isinstance(items, list):
        raise ValueError("O catálogo comunitário do SIGTAP não é uma lista.")

    releases = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        match = FILE_PATTERN.fullmatch(name) if isinstance(name, str) else None
        expected_url = f"{COMMUNITY_MIRROR}/{name}"
        if not match or item.get("download_url") != expected_url:
            continue
        releases.append({
            "name": name,
            "url": f"ftp://ftp2.datasus.gov.br{FTP_PATH_PREFIX}{name}",
            "size": item.get("size"),
            "competence": match.group(1) + match.group(2),
            "revision": match.group(3),
            "catalog_source": "community",
        })
    if not releases:
        raise ValueError("Nenhum pacote SIGTAP válido foi encontrado no catálogo comunitário.")
    return releases


def download_release_with_source(release: dict[str, object]) -> tuple[bytes, str]:
    """Baixa do DATASUS ou, se o FTP cair, do espelho comunitário identificado."""
    url, name = str(release["url"]), str(release["name"])
    if not safe_url(url, name):
        raise ValueError(f"Link oficial inválido para {name}.")
    try:
        package = _download_release(
            url, name, safe_url_fn=safe_url, max_size=MAX_PACKAGE_SIZE,
            looks_valid_fn=looks_like_zip,
        )
        return package, "FTP oficial do DATASUS"
    except (OSError, ValueError) as official_error:
        if not FILE_PATTERN.fullmatch(name):
            raise
        package = download_via_http(
            f"{COMMUNITY_MIRROR}/{name}", name, max_size=MAX_PACKAGE_SIZE,
        )
        if not looks_like_zip(package, min_size=100_000):
            raise ValueError(f"O espelho comunitário não entregou um ZIP válido para {name}.") from official_error
        return package, "cópia comunitária RenatoKR/SIGTAP"


def download_release(release: dict[str, object]) -> bytes:
    """Baixa pacote SIGTAP, mantendo compatibilidade com o sincronizador."""
    return download_release_with_source(release)[0]

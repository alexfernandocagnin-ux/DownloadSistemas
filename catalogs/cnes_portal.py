"""Catálogo do CNES: instalador do SCNES e a base de dados mensal.

Ambos vêm de uma API JSON por trás da tela Angular do CNES (não documentada,
mas estável), servida em cnes.datasus.gov.br/services/arquivos-download/.
O download real também é por HTTPS, via /EstatisticasServlet?path=<arquivo>
— por isso a validação de link aqui é por host+path+parâmetro, não por FTP.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit, parse_qs, unquote
from urllib.request import Request, urlopen

from catalogs._common import USER_AGENT, download_via_http, looks_like_zip

HOST = "cnes.datasus.gov.br"
APLICATIVOS_PAGE = f"https://{HOST}/pages/downloads/aplicativos.jsp"
BASE_DADOS_PAGE = f"https://{HOST}/pages/downloads/arquivosBaseDados.jsp"
VERSOES_API = f"https://{HOST}/services/arquivos-download/versoes/"
BASE_DADOS_API = f"https://{HOST}/services/arquivos-download/base-dados/"
DOWNLOAD_PATH = "/EstatisticasServlet"

APP_FILE_PATTERN = re.compile(r"SCNES(\d{3,4})-ATUALIZACAO\.ZIP", re.IGNORECASE)
BASE_FILE_PATTERN = re.compile(r"BASE_DE_DADOS_CNES_(20\d{2})(0[1-9]|1[0-2])\.ZIP", re.IGNORECASE)
MAX_API_BYTES = 500_000
MAX_PACKAGE_SIZE = 300_000_000


def _download_url(name: str) -> str:
    return f"https://{HOST}{DOWNLOAD_PATH}?path={name}"


def safe_url(url: str, name: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != HOST or parsed.path != DOWNLOAD_PATH:
        return False
    query_path = parse_qs(parsed.query).get("path", [None])[0]
    return query_path is not None and unquote(query_path).lower() == name.lower()


def _fetch_json(url: str, referer: str) -> object:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Referer": referer, "Accept": "application/json"})
    with urlopen(request, timeout=15) as response:
        payload = response.read(MAX_API_BYTES + 1)
    if len(payload) > MAX_API_BYTES:
        raise ValueError(f"A resposta de {url} excedeu o tamanho esperado.")
    return json.loads(payload.decode("utf-8", "replace"))


def fetch_cnes_app_catalog() -> list[dict[str, object]]:
    """Instalador de atualização do SCNES (versão única), mais recente primeiro."""
    payload = _fetch_json(VERSOES_API, APLICATIVOS_PAGE)
    if not isinstance(payload, list):
        raise ValueError("O catálogo de aplicativos do CNES não é uma lista.")
    releases = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("nomeArquivo")
        match = APP_FILE_PATTERN.fullmatch(str(name)) if isinstance(name, str) else None
        if not match:
            continue
        releases.append({
            "name": name, "url": _download_url(str(name)), "size": None, "version": match.group(1),
        })
    if not releases:
        raise ValueError("Nenhum instalador de atualização do SCNES foi encontrado.")
    return sorted(releases, key=lambda item: item["version"], reverse=True)


def fetch_cnes_base_catalog() -> list[dict[str, object]]:
    """Base de dados mensal do CNES, mais recente primeiro."""
    payload = _fetch_json(BASE_DADOS_API, BASE_DADOS_PAGE)
    if not isinstance(payload, list):
        raise ValueError("O catálogo de base de dados do CNES não é uma lista.")
    releases = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        name = item.get("nomeArquivo")
        match = BASE_FILE_PATTERN.fullmatch(str(name)) if isinstance(name, str) else None
        if not match:
            continue
        releases.append({
            "name": name, "url": _download_url(str(name)), "size": None,
            "competence": match.group(1) + match.group(2),
        })
    if not releases:
        raise ValueError("Nenhum pacote de base de dados do CNES foi encontrado.")
    return sorted(releases, key=lambda item: item["competence"], reverse=True)


def _download(release: dict[str, object]) -> bytes:
    url, name = str(release["url"]), str(release["name"])
    if not safe_url(url, name):
        raise ValueError(f"Link de download do CNES não permitido para {name}.")
    package = download_via_http(url, name, max_size=MAX_PACKAGE_SIZE, timeout=90)
    if not looks_like_zip(package, min_size=100_000):
        raise ValueError(f"O download de {name} não parece ser um pacote válido.")
    return package


def download_app_release(release: dict[str, object]) -> bytes:
    return _download(release)


def download_base_release(release: dict[str, object]) -> bytes:
    return _download(release)

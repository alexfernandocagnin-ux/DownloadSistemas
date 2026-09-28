"""Downloads do espelho publicado, com limites e verificação de integridade."""

import hashlib
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
from catalogs._common import USER_AGENT

from catalogs._common import download_via_http

REPOSITORY = "alexfernandocagnin-ux/DownloadSistemas"
MAX_PACKAGE_SIZE = 1_000_000_000


def matching_mirror(name, mirror):
    if not isinstance(mirror, dict) or mirror.get("asset_name") != name:
        return None
    url = mirror.get("asset_url", "")
    parsed = urlsplit(url)
    prefix = f"/{REPOSITORY}/releases/download/"
    if (parsed.scheme != "https" or parsed.hostname != "github.com"
            or not parsed.path.startswith(prefix)
            or unquote(parsed.path.rsplit("/", 1)[-1]) != name):
        return None
    return mirror


def download_mirror(name, mirror):
    mirror = matching_mirror(name, mirror)
    if not mirror:
        raise ValueError("O espelho não corresponde ao arquivo selecionado.")
    package = download_via_http(mirror["asset_url"], name, max_size=MAX_PACKAGE_SIZE, timeout=90)
    if len(package) < 100_000 or package[:2] not in (b"MZ", b"PK"):
        raise ValueError("O espelho não entregou um instalador ou ZIP válido.")
    if mirror.get("size") and len(package) != mirror["size"]:
        raise ValueError("O arquivo do espelho está incompleto.")
    if mirror.get("sha256") and hashlib.sha256(package).hexdigest() != mirror["sha256"]:
        raise ValueError("A integridade do arquivo do espelho não foi confirmada.")
    return package


def probe_mirror(name, mirror):
    """Verifica a entrega sem carregar instaladores grandes na memória do portal."""
    mirror = matching_mirror(name, mirror)
    if not mirror:
        raise ValueError("O espelho não corresponde ao arquivo selecionado.")
    request = Request(mirror["asset_url"], headers={"User-Agent": USER_AGENT, "Range": "bytes=0-1"})
    with urlopen(request, timeout=20) as response:
        signature = response.read(2)
        content_range = response.headers.get("Content-Range", "")
        total = content_range.rsplit("/", 1)[-1] if "/" in content_range else response.headers.get("Content-Length")
    if signature not in (b"MZ", b"PK"):
        raise ValueError("O espelho não entregou um instalador ou ZIP válido.")
    if total and total.isdigit():
        size = int(total)
        if size < 100_000 or size > MAX_PACKAGE_SIZE:
            raise ValueError("Tamanho de arquivo inesperado.")
        if mirror.get("size") and size != mirror["size"]:
            raise ValueError("O tamanho do arquivo diverge do catálogo.")
    return mirror["asset_url"]

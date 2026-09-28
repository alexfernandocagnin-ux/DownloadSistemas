"""Downloads do espelho publicado, com limites e verificação de integridade."""

import hashlib
from urllib.parse import unquote, urlsplit

from catalogs._common import download_via_http

REPOSITORY = "alexfernandocagnin-ux/DownloadSistemas"
MAX_PACKAGE_SIZE = 300_000_000


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

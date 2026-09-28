"""Ferramentas comuns de catálogo: só lê páginas/FTP oficiais, nunca executa."""

from __future__ import annotations

from ftplib import FTP
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

USER_AGENT = "PortalDownloadsDATASUS/1.0"


class LinkParser(HTMLParser):
    """Coleta pares (texto do link, href) de uma página de listagem simples."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "a":
            self._href = next((value for key, value in attrs if key.lower() == "href"), None)
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        self.links.append(("".join(self._text).strip(), self._href))
        self._href = None
        self._text = []


def fetch_index_links(url: str, *, timeout: int = 15, max_bytes: int = 2_000_000) -> list[tuple[str, str]]:
    """Baixa uma página de listagem e devolve os links encontrados nela."""
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        document = response.read(max_bytes + 1)
    if len(document) > max_bytes:
        raise ValueError(f"A página {url} excedeu o tamanho esperado.")
    parser = LinkParser()
    parser.feed(document.decode("utf-8", "replace"))
    return parser.links


def safe_official_url(
    url: str,
    name: str,
    *,
    https_hosts: frozenset[str] = frozenset(),
    ftp_hosts: frozenset[str] = frozenset(),
    ftp_path_prefix: str = "",
) -> bool:
    """Confere se um link aponta mesmo para o arquivo esperado, num host oficial conhecido."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if unquote(Path(parsed.path).name).lower() != name.lower():
        return False
    if parsed.scheme == "ftp":
        return bool(ftp_hosts) and parsed.hostname in ftp_hosts and parsed.path.lower().startswith(ftp_path_prefix.lower())
    return parsed.scheme == "https" and parsed.hostname in https_hosts


def fetch_ftp_names(host: str, directory: str, *, timeout: int = 15) -> list[str]:
    """Lista os nomes de arquivo de um diretório FTP público, sem baixar nada."""
    with FTP(host, timeout=timeout) as server:
        server.login()
        server.cwd(directory)
        return [Path(raw_name).name for raw_name in server.nlst()]


def download_via_http(url: str, name: str, *, max_size: int, timeout: int = 45) -> bytes:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        chunks: list[bytes] = []
        total = 0
        while block := response.read(1024 * 1024):
            total += len(block)
            if total > max_size:
                raise ValueError(f"O download de {name} excedeu o limite de tamanho.")
            chunks.append(block)
    return b"".join(chunks)


def download_via_ftp(host: str, directory: str, name: str, *, max_size: int, timeout: int = 45) -> bytes:
    chunks: list[bytes] = []
    total = 0

    def collect(block: bytes) -> None:
        nonlocal total
        total += len(block)
        if total > max_size:
            raise ValueError(f"O download de {name} excedeu o limite de tamanho.")
        chunks.append(block)

    with FTP(host, timeout=timeout) as server:
        server.login()
        server.cwd(directory)
        server.retrbinary(f"RETR {name}", collect, blocksize=1024 * 1024)
    return b"".join(chunks)


def resolve_href(base_url: str, href: str) -> str:
    return urljoin(base_url, href)


def looks_like_windows_executable(package: bytes, *, min_size: int = 1_000_000) -> bool:
    return len(package) >= min_size and package[:2] == b"MZ"


def looks_like_zip(package: bytes, *, min_size: int = 1_000_000) -> bool:
    return len(package) >= min_size and package[:2] == b"PK"


def download_release(
    url: str,
    name: str,
    *,
    safe_url_fn,
    max_size: int,
    min_size: int = 1_000_000,
    looks_valid_fn=looks_like_windows_executable,
) -> bytes:
    """Baixa um pacote já catalogado, sem executá-lo, revalidando o link antes."""
    if not safe_url_fn(url, name):
        raise ValueError(f"Link de download não permitido para {name}.")
    parsed = urlsplit(url)
    if parsed.scheme == "ftp":
        directory, _, filename = unquote(parsed.path).rpartition("/")
        package = download_via_ftp(parsed.hostname or "", directory, filename, max_size=max_size)
    else:
        package = download_via_http(url, name, max_size=max_size)
    if not looks_valid_fn(package, min_size=min_size):
        raise ValueError(f"O download de {name} não parece ser um pacote válido.")
    return package

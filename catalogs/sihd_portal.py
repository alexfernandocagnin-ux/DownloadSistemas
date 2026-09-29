"""Catálogo do instalador do SIHD2 (sihd.datasus.gov.br/versao/versao_sihd2.php).

A página lista o histórico de versões como texto solto ("Versão 23.40", às
vezes seguido de "(Cancelada)") com um link por versão apontando para o FTP
oficial. Usa um parser dedicado, porque precisa saber se o texto logo depois
de um link marca aquela versão como cancelada.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.request import Request, urlopen

from catalogs._common import (
    USER_AGENT, download_release as _download_release, resolve_href, safe_official_url,
)

INDEX_URL = "http://sihd.datasus.gov.br/versao/versao_sihd2.php"
FTP_HOSTS = frozenset({"ftp2.datasus.gov.br"})
FTP_PATH_PREFIX = "/public/sistemas/dsweb/sihd/programas/"
VERSION_TEXT_PATTERN = re.compile(r"Vers[aã]o\s+(\d+\.\d+)", re.IGNORECASE)
FILE_PATTERN = re.compile(r"SIHD2_(\d{3,4})\.exe", re.IGNORECASE)
COMPETENCE_PATTERN = re.compile(r"CMPT\s+(0[1-9]|1[0-2])/(20\d{2})", re.IGNORECASE)
MAX_INDEX_BYTES = 3_000_000
MAX_PACKAGE_SIZE = 100_000_000


class _SihdVersionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[dict[str, object]] = []
        self._href: str | None = None
        self._text: list[str] = []
        self._competence: str | None = None
        self._last_version: dict[str, object] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "li":
            self._competence = None
            self._last_version = None
        if tag.lower() == "a":
            href = next((value for key, value in attrs if key.lower() == "href"), None)
            # A página quebra o href em várias linhas; um FTP URL nunca leva espaço/quebra de linha.
            self._href = re.sub(r"\s+", "", href) if href else href
            self._text = []

    def handle_data(self, data: str) -> None:
        competence = COMPETENCE_PATTERN.search(data)
        if competence:
            self._competence = competence.group(2) + competence.group(1)
        if self._href is not None:
            self._text.append(data)
        elif self._last_version is not None and "cancelada" in data.lower():
            self._last_version["cancelled"] = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        text = "".join(self._text).strip()
        entry = {"text": text, "href": self._href, "cancelled": "cancelada" in text.lower(),
                 "competence": self._competence}
        self.entries.append(entry)
        if FILE_PATTERN.fullmatch(self._href.rsplit("/", 1)[-1]):
            self._last_version = entry
        self._href = None
        self._text = []


def safe_url(url: str, name: str) -> bool:
    return safe_official_url(url, name, ftp_hosts=FTP_HOSTS, ftp_path_prefix=FTP_PATH_PREFIX)


def fetch_sihd2_catalog() -> list[dict[str, object]]:
    """Instalador do SIHD2 (versão única, ignorando versões marcadas como canceladas)."""
    request = Request(INDEX_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=15) as response:
        document = response.read(MAX_INDEX_BYTES + 1)
    if len(document) > MAX_INDEX_BYTES:
        raise ValueError("A página de versões do SIHD2 excedeu o tamanho esperado.")
    parser = _SihdVersionParser()
    # A página declara charset=iso-8859-15; em utf-8 os acentos de "Versão" viram
    # U+FFFD e quebram VERSION_TEXT_PATTERN.
    parser.feed(document.decode("iso-8859-15", "replace"))

    releases = []
    for entry in parser.entries:
        if entry["cancelled"]:
            continue
        text_match = VERSION_TEXT_PATTERN.search(str(entry["text"]))
        href_url = resolve_href(INDEX_URL, str(entry["href"]))
        name = href_url.rsplit("/", 1)[-1]
        file_match = FILE_PATTERN.fullmatch(name)
        if not text_match or not file_match or not safe_url(href_url, name):
            continue
        major, minor = (int(part) for part in text_match.group(1).split("."))
        if int(file_match.group(1)) != major * 100 + minor:
            continue
        releases.append({"name": name, "url": href_url, "size": None, "version": text_match.group(1),
                         "competence": entry.get("competence")})
    if not releases:
        raise ValueError("Nenhuma versão vigente do SIHD2 foi encontrada.")
    return sorted(releases, key=lambda item: [int(part) for part in item["version"].split(".")], reverse=True)


def download_release(release: dict[str, object]) -> bytes:
    """Baixa o instalador do SIHD2 já catalogado, sem executá-lo."""
    return _download_release(
        str(release["url"]), str(release["name"]),
        safe_url_fn=safe_url, max_size=MAX_PACKAGE_SIZE, min_size=500_000,
    )

"""Confere se os manuais mudaram na fonte, sem alterar as cópias do portal.

Arquivos (FTP/HTTPS) são baixados e comparados pelo SHA-256 da cópia salva.
Páginas da Wiki Saúde são comparadas pela data da última edição. O resultado
vai para um relatório em Markdown; a troca de um manual continua manual,
porque título, edição e descrição também precisam ser revistos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from catalogs._common import USER_AGENT, download_via_ftp, download_via_http  # noqa: E402
from catalogs.manuals import MANUALS_PATH, MAX_MANUAL_SIZE  # noqa: E402


def source_sha256(url: str) -> str:
    parsed = urlsplit(url)
    name = unquote(parsed.path.rsplit("/", 1)[-1])
    if parsed.scheme == "ftp":
        directory = unquote(parsed.path).rpartition("/")[0]
        package = download_via_ftp(parsed.hostname or "", directory, name, max_size=MAX_MANUAL_SIZE)
    elif parsed.scheme == "https":
        package = download_via_http(url, name, max_size=MAX_MANUAL_SIZE)
    else:
        raise ValueError(f"Endereço não suportado: {url}")
    return hashlib.sha256(package).hexdigest()


def wiki_last_edit(url: str) -> datetime:
    """Data da última edição de uma página da Wiki Saúde (API do MediaWiki)."""
    parsed = urlsplit(url)
    base, _, title = parsed.path.partition("/index.php/")
    if not title:
        raise ValueError(f"Página da Wiki não reconhecida: {url}")
    query = urlencode({"action": "query", "prop": "revisions", "titles": unquote(title),
                       "rvprop": "timestamp", "format": "json"})
    api = f"{parsed.scheme}://{parsed.netloc}{base}/api.php?{query}"
    with urlopen(Request(api, headers={"User-Agent": USER_AGENT}), timeout=30) as response:
        pages = json.loads(response.read(1_000_000))["query"]["pages"]
    page = next(iter(pages.values()))
    if "revisions" not in page:
        raise ValueError(f"Página da Wiki não encontrada: {url}")
    return datetime.fromisoformat(page["revisions"][0]["timestamp"].replace("Z", "+00:00"))


def check(manuals, *, fetch_sha256=source_sha256, fetch_last_edit=wiki_last_edit):
    """Devolve (alterados, indisponíveis) como listas de (manual, detalhe)."""
    changed, unreachable = [], []
    hashes: dict[str, str] = {}  # Dois cartões podem apontar para o mesmo arquivo.
    for manual in manuals:
        try:
            if manual.get("source_format") == "Online":
                edited = fetch_last_edit(manual["url"])
                copied = datetime.fromisoformat(manual["copied_at"])
                if copied.tzinfo is None:
                    copied = copied.replace(tzinfo=timezone.utc)
                if edited > copied:
                    changed.append((manual, f"página editada em {edited:%d/%m/%Y}, depois da cópia"))
            else:
                if manual["url"] not in hashes:
                    hashes[manual["url"]] = fetch_sha256(manual["url"])
                # Cópias que são trechos de um documento maior guardam o hash do original.
                if hashes[manual["url"]] != manual.get("source_sha256", manual["sha256"]):
                    changed.append((manual, "o arquivo da fonte é diferente da cópia do portal"))
        except Exception as exc:  # Uma fonte fora do ar não impede as demais conferências.
            unreachable.append((manual, type(exc).__name__))
    return changed, unreachable


def report(changed, unreachable, total):
    lines = []
    if changed:
        lines.append(f"{len(changed)} de {total} manuais mudaram na fonte e precisam ser revistos:\n")
        lines += [f"- **{m['title']}** (`{m['id']}`): {detail}. Fonte: {m['url']}" for m, detail in changed]
        lines.append("\nPara atualizar, substitua a cópia em `static/manuals/` e revise tamanho, SHA-256, "
                     "data e descrição em `data/manuals.json`.")
    else:
        lines.append(f"Nenhum dos {total} manuais mudou na fonte.")
    if unreachable:
        lines.append(f"\nNão foi possível conferir {len(unreachable)} manual(is) nesta execução "
                     "(fonte fora do ar); a próxima conferência tenta de novo:\n")
        lines += [f"- {m['title']} (`{m['id']}`): {error}" for m, error in unreachable]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True, help="Arquivo Markdown com o resultado")
    args = parser.parse_args()
    manuals = json.loads(MANUALS_PATH.read_text(encoding="utf-8"))
    changed, unreachable = check(manuals)
    text = report(changed, unreachable, len(manuals))
    args.report.write_text(text, encoding="utf-8")
    print(text)
    # O workflow abre ou fecha o aviso de acordo com esta saída.
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"changed={'true' if changed else 'false'}\n")


if __name__ == "__main__":
    main()

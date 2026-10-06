"""Publish only the catalog, merging against the current GitHub revision."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from catalogs.state import merge_catalogs


def gh_api(endpoint, body=None):
    args = ["gh", "api", endpoint]
    if body is None:
        return json.loads(subprocess.run(args, capture_output=True, text=True, check=True, timeout=120).stdout)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8", delete=False) as output:
        json.dump(body, output)
        path = Path(output.name)
    try:
        return json.loads(subprocess.run(args + ["--method", "PUT", "--input", str(path)], capture_output=True, text=True, check=True, timeout=120).stdout)
    finally:
        path.unlink(missing_ok=True)


def publish(local, repository):
    endpoint = f"repos/{repository}/contents/data/catalog.json"
    for attempt in range(5):
        current = gh_api(endpoint + "?ref=master")
        blob = current if current.get("encoding") == "base64" else gh_api(f"repos/{repository}/git/blobs/{current['sha']}")
        remote = json.loads(base64.b64decode(blob["content"]).decode("utf-8"))
        merged = merge_catalogs(remote, local)
        if merged == remote:
            print("Catálogo já atualizado.")
            return
        content = json.dumps(merged, ensure_ascii=False, indent=2) + "\n"
        try:
            gh_api(endpoint, {"message": "Atualizar catálogo de versões e espelhos confirmados",
                             "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
                             "sha": current["sha"], "branch": "master",
                             "committer": {"name": "github-actions[bot]", "email": "41898282+github-actions[bot]@users.noreply.github.com"}})
            print("Catálogo publicado sem alterar os arquivos de código.")
            return
        except subprocess.CalledProcessError as exc:
            if "409" not in (exc.stderr or "") or attempt == 4:
                raise
            time.sleep(1 + attempt)


if __name__ == "__main__":
    publish(json.loads((ROOT / "data/catalog.json").read_text(encoding="utf-8")), os.environ["GITHUB_REPOSITORY"])

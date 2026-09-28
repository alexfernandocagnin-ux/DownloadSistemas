"""Portal de download dos instaladores e tabelas oficiais do DATASUS.

Consulta o site do Ministério a cada visita; quando ele está fora do ar,
mostra o último snapshot conferido (data/catalog.json) e o botão de download
continua funcionando pelo espelho próprio em GitHub Releases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import streamlit as st

from catalogs import bpa_portal, sia_portal, sihd_portal

CATALOG_PATH = Path(__file__).parent / "data" / "catalog.json"
LIVE_CHECK_TTL = 15 * 60

FETCHERS: dict[str, Callable[[], list[dict[str, object]]]] = {
    "bpa": bpa_portal.fetch_bpa_catalog,
    "sia": sia_portal.fetch_sia_catalog,
    "sihd2": sihd_portal.fetch_sihd2_catalog,
    "bdsia": sia_portal.fetch_bdsia_catalog,
}
DOWNLOADERS: dict[str, Callable[[dict[str, object]], bytes]] = {
    "bpa": bpa_portal.download_release,
    "sia": sia_portal.download_release,
    "sihd2": sihd_portal.download_release,
    "bdsia": sia_portal.download_release,
}
SINGLE_VERSION_SYSTEMS = ("bpa", "sia", "sihd2")

st.set_page_config(page_title="DownloadSistemas", page_icon="⬇️", layout="centered")


def load_snapshot() -> dict[str, object]:
    if not CATALOG_PATH.is_file():
        return {"systems": {}}
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {"systems": {}}


@st.cache_data(ttl=LIVE_CHECK_TTL, show_spinner=False)
def live_catalog(system_key: str) -> tuple[list[dict[str, object]] | None, str | None]:
    try:
        return FETCHERS[system_key](), None
    except (OSError, ValueError) as exc:
        return None, type(exc).__name__


@st.cache_data(ttl=LIVE_CHECK_TTL, max_entries=8, show_spinner=False)
def cached_official_download(system_key: str, name: str, url: str) -> bytes:
    return DOWNLOADERS[system_key]({"name": name, "url": url})


def render_download_button(system_key: str, name: str, url: str, mirror: dict[str, object] | None) -> None:
    """Baixa do espelho próprio quando publicado; senão, prepara ao vivo do DATASUS."""
    asset_url = (mirror or {}).get("asset_url")
    if asset_url:
        st.link_button(f"⬇️ Baixar {name}", str(asset_url), width="stretch")
        return

    state_key = f"official_download_{system_key}"
    error_key = f"official_download_error_{system_key}"
    cached = st.session_state.get(state_key)
    if cached and cached.get("name") != name:
        st.session_state.pop(state_key, None)
        cached = None

    if st.button(f"Preparar download de {name}", key=f"prep_{system_key}_{name}", width="stretch"):
        try:
            with st.spinner("Baixando direto do DATASUS..."):
                data = cached_official_download(system_key, name, url)
            st.session_state[state_key] = {"name": name, "data": data}
            st.session_state.pop(error_key, None)
        except (OSError, ValueError) as exc:
            st.session_state[error_key] = type(exc).__name__

    cached = st.session_state.get(state_key)
    if cached and cached.get("name") == name:
        st.download_button(
            f"⬇️ Baixar {name}", data=cached["data"], file_name=name,
            mime="application/vnd.microsoft.portable-executable",
            width="stretch", key=f"dl_{system_key}_{name}",
        )
    elif st.session_state.get(error_key):
        st.warning("Não consegui baixar agora. Tente de novo em instantes ou use o portal oficial abaixo.")


def render_single_version_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    info = snapshot_systems.get(system_key, {})
    with st.container(border=True):
        st.subheader(info.get("label", system_key.upper()))
        releases, error = live_catalog(system_key)
        current = info.get("current")
        if releases:
            name, url = releases[0]["name"], releases[0]["url"]
            st.success(f"✅ Confirmado agora: {name}")
        elif current:
            name, url = current["name"], current["url"]
            st.warning(f"⚠️ Não consegui confirmar agora ({error}). Mostrando a última versão conferida em {info.get('checked_at', '?')}.")
        else:
            st.error("Ainda não há nenhuma versão conhecida deste sistema.")
            name = url = None
        if name:
            render_download_button(system_key, str(name), str(url), info.get("mirror"))
        st.link_button("Conferir no portal oficial", info.get("official_page", "#"), width="stretch")


def render_bdsia_card(snapshot_systems: dict[str, object]) -> None:
    info = snapshot_systems.get("bdsia", {})
    saved_competences = info.get("competences", {}) if isinstance(info.get("competences"), dict) else {}
    with st.container(border=True):
        st.subheader(info.get("label", "Tabela mensal do SIA (BDSIA)"))
        releases, error = live_catalog("bdsia")
        if releases:
            st.success("✅ Confirmado agora no DATASUS.")
            available = sorted({str(item["competence"]) for item in releases}, reverse=True)
        else:
            st.warning(f"⚠️ Não consegui confirmar agora ({error}). Mostrando o último snapshot.")
            available = sorted(saved_competences.keys(), reverse=True)

        if not available:
            st.error("Nenhuma competência BDSIA disponível ainda.")
            st.link_button("Conferir no portal oficial", sia_portal.INDEX_URL, width="stretch")
            return

        def release_for(month: str) -> dict[str, object] | None:
            if releases:
                return next((item for item in releases if item["competence"] == month), None)
            return None

        def competence_label(month: str) -> str:
            release = release_for(month)
            name = release["name"] if release else saved_competences.get(month, {}).get("name", "pacote local")
            return f"{month[4:6]}/{month[:4]} · {name}"

        competence = st.selectbox(
            "Competência para acompanhar/baixar", options=available, format_func=competence_label,
            key="bdsia_competence",
        )
        release = release_for(competence)
        saved_entry = saved_competences.get(competence, {})
        if release:
            name, url, mirror = release["name"], release["url"], saved_entry.get("mirror")
        else:
            name, url, mirror = saved_entry.get("name"), saved_entry.get("url"), saved_entry.get("mirror")
        if name and url:
            render_download_button("bdsia", str(name), str(url), mirror)
        else:
            st.caption("Ainda não há pacote espelhado para esta competência.")
        st.link_button("Conferir no portal oficial", sia_portal.INDEX_URL, width="stretch")


st.title("DownloadSistemas")
st.caption(
    "BPA · SIA · BDSIA · SIHD2 — espelho próprio dos instaladores e tabelas oficiais do "
    "DATASUS. O botão de download funciona mesmo quando o site do Ministério está fora do ar."
)

snapshot = load_snapshot()
systems = snapshot.get("systems", {}) if isinstance(snapshot.get("systems"), dict) else {}

for key in SINGLE_VERSION_SYSTEMS:
    render_single_version_card(key, systems)
render_bdsia_card(systems)

st.caption(f"Último snapshot do espelho: {snapshot.get('updated_at', 'ainda não sincronizado')}.")

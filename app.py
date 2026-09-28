"""Portal de download dos instaladores e tabelas oficiais do DATASUS.

Consulta o site do Ministério a cada visita; quando ele está fora do ar,
mostra o último snapshot conferido (data/catalog.json) e o botão de download
continua funcionando pelo espelho próprio em GitHub Releases.
"""

from __future__ import annotations

import json
from pathlib import Path
from html import escape
from datetime import datetime

import streamlit as st

from catalogs.mirrors import matching_mirror, probe_mirror
from catalogs import bpa_portal, cnes_portal, sia_portal, sigtap_portal, sihd_portal

CATALOG_PATH = Path(__file__).parent / "data" / "catalog.json"
LIVE_CHECK_TTL = 15 * 60

SINGLE_VERSION_SYSTEMS = ("bpa", "sia", "sihd2", "cnes_app")
COMPETENCE_SYSTEMS = ("bdsia", "sigtap", "cnes_base")

SYSTEM_META: dict[str, dict[str, object]] = {
    "bpa": {
        "label": "BPA Magnético", "icon": "🧾",
        "fetch": bpa_portal.fetch_bpa_catalog, "download": bpa_portal.download_release,
        "official_page": bpa_portal.INDEX_URL,
    },
    "sia": {
        "label": "SIA (instalador)", "icon": "🏥",
        "fetch": sia_portal.fetch_sia_catalog, "download": sia_portal.download_release,
        "official_page": sia_portal.INDEX_URL,
    },
    "sihd2": {
        "label": "SIHD2 (instalador)", "icon": "🏨",
        "fetch": sihd_portal.fetch_sihd2_catalog, "download": sihd_portal.download_release,
        "official_page": sihd_portal.INDEX_URL,
    },
    "cnes_app": {
        "label": "CNES · SCNES (atualização)", "icon": "🗂️",
        "fetch": cnes_portal.fetch_cnes_app_catalog, "download": cnes_portal.download_app_release,
        "official_page": cnes_portal.APLICATIVOS_PAGE,
    },
    "bdsia": {
        "label": "Tabela mensal do SIA (BDSIA)", "icon": "📊",
        "fetch": sia_portal.fetch_bdsia_catalog, "download": sia_portal.download_release,
        "official_page": sia_portal.INDEX_URL,
    },
    "sigtap": {
        "label": "SIGTAP · Tabela Unificada", "icon": "💊",
        "fetch": sigtap_portal.fetch_sigtap_catalog, "download": sigtap_portal.download_release,
        "official_page": sigtap_portal.DOWNLOAD_PAGE,
    },
    "cnes_base": {
        "label": "CNES · Base de dados mensal", "icon": "🗃️",
        "fetch": cnes_portal.fetch_cnes_base_catalog, "download": cnes_portal.download_base_release,
        "official_page": cnes_portal.BASE_DADOS_PAGE,
    },
}

st.set_page_config(page_title="DownloadSistemas", page_icon="⬇️", layout="wide")

CUSTOM_CSS = """
<style>
.ds-hero {
    background: linear-gradient(120deg, #08776A 0%, #0BA893 100%);
    color: #F4F7F5;
    padding: 2rem 2.2rem;
    border-radius: 18px;
    margin-bottom: 1.6rem;
    box-shadow: 0 10px 30px rgba(8, 119, 106, 0.25);
}
.ds-hero h1 { margin: 0 0 0.3rem 0; font-size: 2.1rem; }
.ds-hero p { margin: 0; opacity: 0.92; font-size: 1.02rem; }
.ds-badge {
    display: inline-block; padding: 0.15rem 0.65rem; border-radius: 999px;
    font-size: 0.82rem; font-weight: 600; margin-bottom: 0.6rem;
}
.ds-badge-ok { background: #DCF3EC; color: #08776A; }
.ds-badge-warn { background: #FCEFD6; color: #8A5A00; }
.ds-badge-error { background: #FBE2E1; color: #A3261D; }
.ds-card-title { font-size: 1.15rem; font-weight: 700; margin-bottom: 0.4rem; }
div[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: 14px !important;
    box-shadow: 0 2px 10px rgba(22, 50, 45, 0.06);
    transition: box-shadow 0.15s ease;
}
div[data-testid="stVerticalBlockBorderWrapper"]:hover {
    box-shadow: 0 6px 18px rgba(22, 50, 45, 0.12);
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def load_snapshot() -> dict[str, object]:
    if not CATALOG_PATH.is_file():
        return {"systems": {}}
    try:
        data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        st.warning("O catálogo salvo não pôde ser lido. Consulte as fontes oficiais abaixo.")
        return {"systems": {}}
    return data if isinstance(data, dict) else {"systems": {}}


@st.cache_data(ttl=LIVE_CHECK_TTL, show_spinner=False)
def live_catalog(system_key: str) -> tuple[list[dict[str, object]] | None, str | None]:
    try:
        return SYSTEM_META[system_key]["fetch"](), None
    except (OSError, ValueError) as exc:
        return None, type(exc).__name__


@st.cache_data(ttl=5 * 60, max_entries=64, show_spinner=False)
def cached_mirror_probe(name, mirror):
    return probe_mirror(name, mirror)


def prepare_download(system_key, name, url, mirror):
    mirror_error = False
    if matching_mirror(name, mirror):
        try:
            return {"url": cached_mirror_probe(name, mirror)}, "Espelho independente", False
        except (OSError, ValueError):
            mirror_error = True
    data = SYSTEM_META[system_key]["download"]({"name": name, "url": url})
    return {"data": data}, "Fonte oficial", mirror_error


def badge(kind, text):
    css_class = {"ok": "ds-badge-ok", "warn": "ds-badge-warn", "error": "ds-badge-error"}[kind]
    st.markdown(f'<span class="ds-badge {css_class}">{escape(text)}</span>', unsafe_allow_html=True)


def readable_date(value):
    if not value:
        return "ainda não confirmada"
    try:
        return datetime.fromisoformat(value).strftime("%d/%m/%Y às %H:%M UTC")
    except (TypeError, ValueError):
        return str(value)


def render_download_button(system_key, name, url, mirror):
    mirror = matching_mirror(name, mirror)
    if mirror and mirror.get("verified_at"):
        badge("ok", "Espelho publicado · disponível sem o DATASUS")
    elif mirror:
        badge("warn", "Espelho antigo · será verificado ao preparar")
    else:
        badge("warn", "Ainda depende da fonte oficial")
    if mirror and mirror.get("size"):
        st.caption(f'{mirror["size"] / 1_000_000:.1f} MB · arquivo conferido')

    state_key = f"official_download_{system_key}"
    cached = st.session_state.get(state_key)
    identity = (name, url, (mirror or {}).get("asset_url"), (mirror or {}).get("sha256"))
    if cached and cached.get("identity") != identity:
        st.session_state.pop(state_key, None)
        cached = None
    if not cached and st.button("Preparar arquivo para baixar", key=f"prep_{system_key}_{name}", width="stretch", type="primary"):
        try:
            with st.spinner("Preparando o arquivo; arquivos grandes podem levar alguns minutos..."):
                data, source, fallback = prepare_download(system_key.removesuffix("_backup"), name, url, mirror)
            # Mantém apenas um fallback oficial por sessão; espelhos usam URL, não bytes.
            for other_key in list(st.session_state):
                if other_key.startswith("official_download_") and other_key != state_key:
                    st.session_state.pop(other_key, None)
            cached = {"identity": identity, **data, "source": source}
            st.session_state[state_key] = cached
            if fallback:
                st.warning("O espelho não respondeu. Recuperamos este arquivo da fonte oficial.")
        except (OSError, ValueError):
            st.error("O arquivo não está disponível agora. Tente novamente mais tarde. Os demais downloads continuam disponíveis.")
    if cached:
        st.caption(f'Arquivo pronto · {cached["source"]}')
        if cached.get("url"):
            st.link_button(f"⬇️ Baixar {name}", cached["url"], width="stretch", type="primary")
        else:
            st.download_button(f"⬇️ Baixar {name}", data=cached["data"], file_name=name,
                               mime="application/zip" if name.lower().endswith(".zip") else "application/octet-stream",
                               width="stretch", key=f"dl_{system_key}_{name}", on_click="ignore")


def render_status(releases, error, checked_at):
    if releases:
        badge("ok", "Versões consultadas na fonte oficial (cache de 15 min)")
    elif error:
        badge("warn", "Fonte oficial indisponível · usando catálogo salvo")
    elif checked_at:
        st.caption(f"Última confirmação: {readable_date(checked_at)}")
    else:
        st.caption("Nenhuma versão salva. Ative a consulta oficial para procurar arquivos.")


def card_catalog(system_key):
    return live_catalog(system_key) if check_official else (None, None)


def render_single_version_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    meta = SYSTEM_META[system_key]
    info = snapshot_systems.get(system_key, {})
    with st.container(border=True):
        st.markdown(f'<div class="ds-card-title">{meta["icon"]} {meta["label"]}</div>', unsafe_allow_html=True)
        releases, error = card_catalog(system_key)
        current = info.get("current")
        render_status(releases, error, info.get("last_success_at", info.get("checked_at")) if current and not releases else None)
        if releases:
            name, url = releases[0]["name"], releases[0]["url"]
        elif current:
            name, url = current["name"], current["url"]
        else:
            name = url = None
        if name:
            st.caption(name)
            render_download_button(system_key, str(name), str(url), info.get("mirror"))
            if current and current.get("name") != name and matching_mirror(current["name"], info.get("mirror")):
                with st.expander("Versão anterior preservada no espelho"):
                    render_download_button(system_key + "_backup", current["name"], current["url"], info["mirror"])
        st.link_button("Conferir no portal oficial", meta["official_page"], width="stretch")


def render_competence_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    meta = SYSTEM_META[system_key]
    info = snapshot_systems.get(system_key, {})
    saved_competences = info.get("competences", {}) if isinstance(info.get("competences"), dict) else {}
    with st.container(border=True):
        st.markdown(f'<div class="ds-card-title">{meta["icon"]} {meta["label"]}</div>', unsafe_allow_html=True)
        releases, error = card_catalog(system_key)
        render_status(releases, error, info.get("last_success_at", info.get("checked_at")) if not releases else None)
        available = sorted(set(saved_competences) | {str(item["competence"]) for item in (releases or [])}, reverse=True)

        if not available:
            st.error("Nenhuma competência disponível ainda.")
            st.link_button("Conferir no portal oficial", meta["official_page"], width="stretch")
            return

        def release_for(month: str) -> dict[str, object] | None:
            return next((item for item in releases if item["competence"] == month), None) if releases else None

        def competence_label(month: str) -> str:
            release = release_for(month)
            name = release["name"] if release else saved_competences.get(month, {}).get("name", "pacote local")
            return f"{month[4:6]}/{month[:4]} · {name}"

        competence = st.selectbox(
            "Competência para acompanhar/baixar", options=available, format_func=competence_label,
            key=f"competence_{system_key}",
        )
        release = release_for(competence)
        saved_entry = saved_competences.get(competence, {})
        if release:
            name, url, mirror = release["name"], release["url"], saved_entry.get("mirror")
        else:
            name, url, mirror = saved_entry.get("name"), saved_entry.get("url"), saved_entry.get("mirror")
        if name and url:
            render_download_button(system_key, str(name), str(url), mirror)
            if saved_entry.get("name") and saved_entry["name"] != name and matching_mirror(saved_entry["name"], saved_entry.get("mirror")):
                with st.expander("Revisão anterior preservada no espelho"):
                    render_download_button(system_key + "_backup", saved_entry["name"], saved_entry["url"], saved_entry["mirror"])
        else:
            st.caption("Ainda não há pacote espelhado para esta competência.")
        st.link_button("Conferir no portal oficial", meta["official_page"], width="stretch")


snapshot = load_snapshot()
systems = snapshot.get("systems", {}) if isinstance(snapshot.get("systems"), dict) else {}
updated_at = snapshot.get("updated_at", "ainda não sincronizado")

st.markdown(
    f"""
    <div class="ds-hero">
        <h1>⬇️ DownloadSistemas</h1>
        <p>BPA · SIA · BDSIA · SIHD2 · CNES · SIGTAP — espelho próprio dos instaladores e
        tabelas oficiais do DATASUS. Arquivos com espelho publicado podem ser baixados mesmo
        quando o Ministério está fora do ar. Catálogo atualizado: {escape(readable_date(updated_at))}.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

check_official = st.checkbox("Consultar versões nas fontes oficiais agora", value=False,
                             help="Os downloads do espelho não precisam desta consulta. As fontes oficiais podem demorar ou estar fora do ar.")
st.caption("Escolha o sistema, prepare o arquivo e baixe aqui mesmo, sem abrir uma página do GitHub.")
single_cols = st.columns(2)
for index, key in enumerate(SINGLE_VERSION_SYSTEMS):
    with single_cols[index % 2]:
        render_single_version_card(key, systems)

st.write("")
for key in COMPETENCE_SYSTEMS:
    render_competence_card(key, systems)

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

SINGLE_VERSION_SYSTEMS = ("bpa", "sia", "sihd2", "cnes_complete", "cnes_app")
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
    "cnes_complete": {
        "label": "SCNES · completo", "icon": "⬇",
        "fetch": cnes_portal.fetch_cnes_complete_catalog, "download": cnes_portal.download_app_release,
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
        "download_with_source": sigtap_portal.download_release_with_source,
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
.stApp { background: #f5f4ef; color: #172c32; }
.block-container { max-width: 1480px; padding-top: 2.2rem; padding-bottom: 4rem; }
.ds-hero { position: relative; overflow: hidden; display: grid; grid-template-columns: 1fr auto;
    align-items: end; gap: 2rem; background: #16343a; color: #f8f7f0; padding: 2.7rem 3rem;
    border-radius: 22px; margin: 0 0 1.4rem; box-shadow: 0 18px 42px rgba(22,52,58,.12); }
.ds-hero:after { content: ''; position: absolute; width: 280px; height: 280px; right: 16%; top: -185px;
    border: 1px solid rgba(170,222,204,.24); border-radius: 50%;
    box-shadow: 0 0 0 34px rgba(170,222,204,.04), 0 0 0 68px rgba(170,222,204,.04); }
.ds-hero-copy, .ds-hero-meta { position: relative; z-index: 1; }
.ds-eyebrow { color: #a8d8c3; font-size: .73rem; font-weight: 750; letter-spacing: .16em;
    text-transform: uppercase; margin: 0 0 .7rem; }
.ds-hero h1 { font-family: Georgia, 'Times New Roman', serif; font-size: clamp(2.35rem,4vw,3.55rem);
    letter-spacing: -.045em; line-height: 1; margin: 0 0 .85rem; }
.ds-hero p { color: #d2dfd9; font-size: 1rem; line-height: 1.6; max-width: 680px; margin: 0; }
.ds-hero-meta { min-width: 205px; border-left: 1px solid rgba(255,255,255,.2); padding-left: 1.35rem; }
.ds-hero-meta strong { display: block; color: #b8e2ce; font-size: .77rem; letter-spacing: .06em;
    text-transform: uppercase; margin-bottom: .4rem; }
.ds-hero-meta span { color: #edf2ee; font-size: .9rem; }
.ds-toolbar { background: #fff; border: 1px solid #e1e3dc; border-radius: 15px; padding: .25rem .85rem; margin-bottom: 2.3rem; }
.ds-section { margin: 2.2rem 0 1rem; }
.ds-section h2 { font-family: Georgia, 'Times New Roman', serif; color: #17343a; font-size: 1.7rem;
    letter-spacing: -.025em; margin: 0; }
.ds-section p { color: #637277; font-size: .92rem; margin: .25rem 0 0; }
.ds-card-title { display: flex; gap: .55rem; align-items: center; color: #18353a; font-size: 1.04rem;
    font-weight: 750; letter-spacing: -.015em; margin: .15rem 0 .75rem; }
.ds-badge { display: inline-block; padding: .28rem .68rem; border-radius: 999px; font-size: .74rem;
    font-weight: 700; line-height: 1.25; margin: .05rem 0 .6rem; }
.ds-badge-ok { background: #e1f2e9; color: #176347; }
.ds-badge-warn { background: #fbefd9; color: #805514; }
.ds-badge-error { background: #f8e4df; color: #8d3428; }
div[data-testid="stVerticalBlockBorderWrapper"] { background: #fff; border-color: #e1e3dc !important;
    border-radius: 17px !important; box-shadow: 0 5px 17px rgba(30,49,47,.045);
    transition: transform .18s ease, box-shadow .18s ease; }
div[data-testid="stVerticalBlockBorderWrapper"]:hover { transform: translateY(-2px);
    box-shadow: 0 12px 27px rgba(30,49,47,.09); }
div[data-testid="stButton"] button[kind="primary"], div[data-testid="stLinkButton"] a[kind="primary"] {
    background: #126b59; border-color: #126b59; color: #fff; border-radius: 10px; font-weight: 700; }
div[data-testid="stButton"] button[kind="primary"]:hover, div[data-testid="stLinkButton"] a[kind="primary"]:hover {
    background: #0d594a; border-color: #0d594a; }
div[data-testid="stLinkButton"] a { border-radius: 10px; }
div[data-testid="stCaptionContainer"] { color: #69797b; }
@media (max-width: 760px) { .ds-hero { grid-template-columns: 1fr; gap: 1.3rem; padding: 2rem 1.5rem; }
    .ds-hero-meta { border-left: 0; border-top: 1px solid rgba(255,255,255,.2); padding: .8rem 0 0; } }
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
    if system_key in {"cnes_base", "cnes_complete"}:
        raise OSError("Este pacote CNES grande precisa de um espelho publicado para evitar sobrecarga do portal.")
    release = {"name": name, "url": url}
    download_with_source = SYSTEM_META[system_key].get("download_with_source")
    if download_with_source:
        data, source = download_with_source(release)
        return {"data": data}, source, mirror_error
    data = SYSTEM_META[system_key]["download"](release)
    return {"data": data}, "Fonte oficial DATASUS", mirror_error


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
    if not mirror and system_key.removesuffix("_backup") in {"cnes_base", "cnes_complete"}:
        st.info("Este pacote grande aguarda publicação no espelho. A sincronização automática fará novas tentativas; o portal oficial está disponível abaixo.")
        return
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
            if system_key == "cnes_complete":
                st.caption("Instalação nova do SCNES")
            elif system_key == "cnes_app":
                st.caption("Atualização para o SCNES já instalado")
            elif system_key == "sihd2" and not matching_mirror(name, info.get("mirror")):
                st.caption("O portal oficial lista esta versão; o arquivo ainda aguarda uma cópia de espelho.")
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
        if system_key == "sigtap" and releases and releases[0].get("catalog_source") == "community":
            badge("warn", "Catálogo comunitário de apoio · cópias identificadas")
        else:
            render_status(releases, error, info.get("last_success_at", info.get("checked_at")) if not releases else None)
        if system_key == "sigtap":
            st.caption("Se o DATASUS falhar, consultamos o catálogo e as cópias comunitárias do SIGTAP.")
        available = sorted(set(saved_competences) | {str(item["competence"]) for item in (releases or [])}, reverse=True)

        if not available:
            st.info("Nenhuma competência disponível ainda. Consulte o catálogo oficial ou tente novamente mais tarde.")
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
        if system_key == "sigtap" and saved_entry.get("catalog_source") == "community":
            badge("warn", "Competência encontrada em catálogo comunitário")
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


def render_grid(keys, snapshot_systems, renderer):
    for start in range(0, len(keys), 3):
        columns = st.columns(3, gap="medium")
        for column, key in zip(columns, keys[start:start + 3]):
            with column:
                renderer(key, snapshot_systems)


snapshot = load_snapshot()
systems = snapshot.get("systems", {}) if isinstance(snapshot.get("systems"), dict) else {}
updated_at = snapshot.get("updated_at", "ainda não sincronizado")
readable_updated_at = readable_date(updated_at)

st.markdown(
    f"""
    <div class="ds-hero">
        <div class="ds-hero-copy">
            <div class="ds-eyebrow">DATASUS &nbsp;·&nbsp; CENTRAL DE ARQUIVOS</div>
            <h1>Downloads sem rodeios.</h1>
            <p>Instaladores e tabelas oficiais do SUS em um só lugar. Quando o portal do Ministério
            oscila, os arquivos já espelhados continuam disponíveis para baixar.</p>
        </div>
        <div class="ds-hero-meta">
            <strong>Catálogo conferido</strong>
            <span>{escape(readable_updated_at)}</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.container(border=True):
    note, control = st.columns([1.6, 1])
    with note:
        st.markdown("**Baixe pelo arquivo confirmado**")
        st.caption("A consulta ao portal oficial é opcional e pode demorar durante instabilidades.")
    with control:
        check_official = st.checkbox(
            "Consultar versões oficiais agora", value=False,
            help="Os downloads já espelhados não precisam desta consulta.",
        )

st.markdown(
    '<div class="ds-section"><div class="ds-eyebrow">01 &nbsp;·&nbsp; APLICATIVOS</div>'
    '<h2>Instaladores</h2><p>Programas e atualizações para processamento das informações do SUS.</p></div>',
    unsafe_allow_html=True,
)
st.info("No SCNES, use **completo** para uma nova instalação e **atualização** se já tiver o sistema. O Firebird é necessário.", icon="ℹ️")
render_grid(SINGLE_VERSION_SYSTEMS, systems, render_single_version_card)

st.markdown(
    '<div class="ds-section"><div class="ds-eyebrow">02 &nbsp;·&nbsp; COMPETÊNCIAS</div>'
    '<h2>Tabelas e bases</h2><p>Selecione o mês que você precisa e baixe o pacote correspondente.</p></div>',
    unsafe_allow_html=True,
)
render_grid(COMPETENCE_SYSTEMS, systems, render_competence_card)

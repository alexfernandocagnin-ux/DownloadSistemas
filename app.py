"""Portal de download dos instaladores e tabelas oficiais do DATASUS.

Abre pelo catálogo salvo e permite uma consulta manual às fontes.
As cópias confirmadas em GitHub Releases permitem baixar arquivos
quando o servidor de origem está indisponível.
"""

from __future__ import annotations

import json
from pathlib import Path
from html import escape
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

import streamlit as st

from catalogs.mirrors import download_mirror, matching_mirror, probe_mirror
from catalogs import apac_portal, bpa_portal, ciha_portal, cnes_portal, fpo_portal, sia_portal, sigtap_portal, sihd_portal
from catalogs.updates import make_update_event, merge_updates, recent_updates
from catalogs.state import CATALOG_LOCK, atomic_write, normalize_catalog

CATALOG_PATH = Path(__file__).parent / "data" / "catalog.json"

SINGLE_VERSION_SYSTEMS = ("bpa", "apac", "sia", "fpo_update", "sihd2", "ciha02", "cnes_complete", "cnes_app")
COMPETENCE_SYSTEMS = ("bdsia", "sigtap", "cnes_base")
DIRECT_DOWNLOAD_LIMIT = 50_000_000

SYSTEM_META: dict[str, dict[str, object]] = {
    "apac": {
        "label": "APAC Magnético", "icon": "📝",
        "fetch": apac_portal.fetch_apac_catalog, "download": apac_portal.download_release,
        "official_page": apac_portal.INDEX_URL,
    },
    "ciha02": {
        "label": "CIHA02 · atualização", "icon": "🏛️",
        "fetch": ciha_portal.fetch_ciha02_catalog, "download": ciha_portal.download_release,
        "official_page": ciha_portal.PAGES["02"],
    },
    "ciha02_installer": {
        "label": "CIHA02 · instalação inicial", "icon": "📦",
        "fetch": ciha_portal.fetch_ciha02_installer_catalog, "download": ciha_portal.download_release,
        "official_page": ciha_portal.PAGES["02"],
    },
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
    "fpo_installer": {
        "label": "FPO · instalador base (primeira instalação)", "icon": "🧮",
        "fetch": fpo_portal.fetch_fpo_installer_catalog, "download": fpo_portal.download_release,
        "official_page": fpo_portal.INDEX_URL,
    },
    "fpo_update": {
        "label": "FPO Magnético · atualização atual", "icon": "🔄",
        "fetch": fpo_portal.fetch_fpo_update_catalog, "download": fpo_portal.download_release,
        "official_page": fpo_portal.INDEX_URL,
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

st.set_page_config(page_title="Downloads Sistemas", page_icon="📦", layout="wide")

CUSTOM_CSS = """
<style>
:root { --ds-ink:#172f3d; --ds-muted:#596c78; --ds-green:#087568; --ds-line:#dce5e9; }
.stApp { background:#f3f6f8; color:var(--ds-ink); }
.block-container { max-width:1440px; padding-top:1.6rem; padding-bottom:3rem; }
.ds-hero { display:grid; grid-template-columns:minmax(0,1fr) 290px; gap:2rem;
    position:relative; overflow:hidden; padding:2.15rem 2.4rem; margin-bottom:1.2rem;
    background:#132f3b; border:1px solid #234550; border-radius:20px; color:#fff; }
.ds-hero:after { content:''; position:absolute; width:360px; height:360px; right:180px; top:-250px;
    border:1px solid #41606a; border-radius:50%; box-shadow:0 0 0 45px #1b3945,0 0 0 90px #183440;
    pointer-events:none; }
.ds-hero-copy,.ds-hero-meta { position:relative; z-index:1; }
.ds-eyebrow { color:#a8dbce; font-size:.7rem; font-weight:750; letter-spacing:.16em; text-transform:uppercase; margin:0 0 .65rem; }
.ds-hero h1 { font-family:Georgia,'Times New Roman',serif; font-size:clamp(2rem,3.3vw,3rem);
    font-weight:700; letter-spacing:-.045em; line-height:1.12; margin:0 0 .7rem; }
.ds-hero p { color:#d5e3e9; font-size:.96rem; line-height:1.6; max-width:680px; margin:0; }
.ds-hero-meta { align-self:center; padding:1.1rem 1.2rem; border:1px solid #46616b; border-radius:12px; background:#1c3b46; }
.ds-hero-meta strong { display:block; color:#b8e8d8; font-size:.69rem; text-transform:uppercase; letter-spacing:.1em; margin-bottom:.55rem; }
.ds-hero-meta span { display:block; color:#f7fafb; font-size:.85rem; line-height:1.5; }
.ds-hero-meta small { display:block; margin-top:.55rem; color:#c4d9df; font-size:.73rem; }
.ds-overview { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:1px; margin:0 0 1.25rem;
    border:1px solid var(--ds-line); border-radius:12px; overflow:hidden; background:var(--ds-line); }
.ds-overview-item { background:#fff; padding:1rem 1.3rem; display:flex; align-items:center; gap:.9rem; }
.ds-overview-number { font-family:Georgia,serif; color:#096c61; font-size:1.65rem; font-weight:700; line-height:1; }
.ds-overview-item strong { display:block; font-size:.84rem; color:#193b49; }
.ds-overview-item span { display:block; font-size:.74rem; color:var(--ds-muted); margin-top:.15rem; }
.ds-section { margin:1.3rem 0 1rem; }
.ds-section .ds-eyebrow { color:#547583; font-size:.67rem; }
.ds-section h2 { font-family:Georgia,serif; color:#183a49; font-size:1.7rem; letter-spacing:-.025em; margin:0; }
.ds-section p { color:var(--ds-muted); font-size:.89rem; margin:.3rem 0 0; }
.ds-card-title { display:flex; align-items:center; gap:.7rem; min-height:44px; font-size:1rem;
    font-weight:750; color:#173849; line-height:1.35; margin:.1rem 0 .7rem; }
.ds-card-icon { display:grid; place-items:center; width:38px; height:38px; flex:0 0 38px;
    background:#edf4f5; border:1px solid #e0ebef; border-radius:10px; font-size:1.1rem; }
.ds-badge { display:inline-block; padding:.26rem .65rem; border-radius:6px; font-size:.72rem; font-weight:700;
    line-height:1.35; margin:0 0 .55rem; }
.ds-badge-ok { background:#e8f5ef; color:#116144; border:1px solid #d3eade; }
.ds-badge-warn { background:#fff4df; color:#775114; border:1px solid #efdcb2; }
.ds-badge-error { background:#fbecea; color:#933c35; border:1px solid #f1d3ce; }
div[data-testid="stVerticalBlockBorderWrapper"] { background:#fff; border-color:var(--ds-line) !important;
    border-radius:14px !important; box-shadow:0 3px 10px #15303b06; }
div[data-testid="stButton"] button, div[data-testid="stDownloadButton"] button, div[data-testid="stLinkButton"] a {
    border-radius:9px; min-height:42px; font-weight:650; transition:background .15s ease,border-color .15s ease; }
div[data-testid="stButton"] button[kind="primary"], div[data-testid="stLinkButton"] a[kind="primary"] {
    background:#087568; border-color:#087568; color:#fff; }
div[data-testid="stButton"] button[kind="primary"]:hover, div[data-testid="stLinkButton"] a[kind="primary"]:hover {
    background:#075e54; border-color:#075e54; }
/* A mesma cor para arquivos prontos, servidos pelo app ou por link direto. */
[class*="st-key-ready_download_"] [data-testid="stDownloadButton"] button,
[class*="st-key-ready_download_"] [data-testid="stLinkButton"] a {
    background:#175b91 !important; border-color:#175b91 !important; color:#fff !important;
    box-shadow:0 3px 8px #175b9120; }
[class*="st-key-ready_download_"] [data-testid="stDownloadButton"] button:hover,
[class*="st-key-ready_download_"] [data-testid="stLinkButton"] a:hover {
    background:#104570 !important; border-color:#104570 !important; color:#fff !important; }
[class*="st-key-ready_download_"] [data-testid="stDownloadButton"] button p,
[class*="st-key-ready_download_"] [data-testid="stLinkButton"] a p { color:#fff !important; }
div[data-testid="stCaptionContainer"] { color:#607580; font-size:.78rem; }
button:focus-visible, a:focus-visible { outline:3px solid #46a996 !important; outline-offset:3px; }
[role="tablist"] { gap:.7rem; background:transparent; border-bottom:0;
    padding:.3rem .2rem .65rem; }
[role="tab"] { --tab-color:#087568; --tab-soft:#e8f5ef; --tab-border:#c9e5da;
    min-height:46px; padding:.65rem 1.15rem; font-size:.94rem; font-weight:700;
    border:1px solid var(--tab-border) !important; border-radius:12px;
    background:var(--tab-soft) !important; color:var(--tab-color) !important;
    transition:background .15s ease,box-shadow .15s ease; }
[role="tab"]:nth-child(2) { --tab-color:#175b91; --tab-soft:#eaf2fa; --tab-border:#ccdeef; }
[role="tab"]:nth-child(3) { --tab-color:#654393; --tab-soft:#f1ecf8; --tab-border:#ded2ee; }
[role="tab"] p { color:inherit !important; font-weight:700; }
[role="tab"]:hover { box-shadow:0 3px 9px #15303b16; }
[role="tab"][aria-selected="true"] { background:var(--tab-color) !important;
    border-color:var(--tab-color) !important; color:#fff !important; box-shadow:0 3px 9px #15303b20; }
[data-baseweb="tab-highlight"], [data-baseweb="tab-border"] { display:none; }
.ds-update-heading { display:flex; align-items:center; gap:.8rem; padding:.15rem 0; }
.ds-update-icon { width:40px; height:40px; flex:0 0 40px; display:grid; place-items:center; background:#e7f3ef;
    color:#087568; border-radius:10px; font-size:1.1rem; }
.ds-update-heading strong { display:block; font-size:.99rem; color:#173a48; }
.ds-update-heading span { display:block; font-size:.8rem; color:var(--ds-muted); margin-top:.2rem; }
.ds-update-panel { margin:.4rem 0 .2rem; }
.ds-update-list { display:grid; gap:.55rem; }
.ds-update-item { display:grid; grid-template-columns:minmax(140px,1fr) minmax(160px,1.2fr) auto; align-items:center;
    gap:.8rem; background:#f6fbf9; padding:.8rem 1rem; border:1px solid #e0ece6; border-left:3px solid #4b9b83; border-radius:8px; }
.ds-update-system { color:#1f463d; font-size:.84rem; font-weight:750; }
.ds-update-file { color:#526c70; font-size:.8rem; overflow-wrap:anywhere; }
.ds-update-date { color:#536f6b; font-size:.74rem; white-space:nowrap; }
.ds-update-empty { background:#f5f8fa; color:#536a76; padding:.85rem 1rem; border-radius:9px; font-size:.86rem; }
.ds-loading-card { background:#f1f8f5; border:1px solid #d5e9df; border-radius:10px; padding:.85rem 1rem; margin:.5rem 0; }
.ds-loading-copy { display:flex; align-items:center; gap:.7rem; color:#173849; }
.ds-loading-copy strong { display:block; font-size:.88rem; }
.ds-loading-copy span { display:block; color:#566e76; font-size:.8rem; margin-top:.2rem; }
.ds-loading-dot { width:12px; height:12px; flex:0 0 auto; border:2px solid #bbdacf; border-top-color:#087568;
    border-radius:50%; animation:ds-spin .85s linear infinite; }
.ds-progress-track { height:4px; overflow:hidden; background:#daeae2; border-radius:9px; margin-top:.8rem; }
.ds-progress-track span { display:block; width:34%; height:100%; background:#087568; animation:ds-slide 1.3s ease-in-out infinite; }
.ds-footer { border-top:1px solid var(--ds-line); margin-top:2rem; padding-top:1rem; color:#536d79; font-size:.77rem; }
@keyframes ds-spin { to { transform:rotate(360deg); } }
@keyframes ds-slide { from { transform:translateX(-120%); } to { transform:translateX(330%); } }
@media (prefers-reduced-motion:reduce) { .ds-loading-dot,.ds-progress-track span { animation:none; } }
@media (max-width:760px) {
    .block-container { padding-top:1rem; padding-left:1rem; padding-right:1rem; }
    .ds-hero { grid-template-columns:1fr; padding:1.5rem; gap:1.2rem; }
    .ds-overview { grid-template-columns:1fr; }
    .ds-overview-item { padding:.8rem 1rem; }
    .ds-update-item { grid-template-columns:1fr; gap:.25rem; }
    .ds-update-date { white-space:normal; }
    [role="tablist"] { gap:.65rem; }
    [role="tab"] { font-size:.8rem; padding:.6rem .8rem; }
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


@st.cache_data(ttl=5 * 60, max_entries=64, show_spinner=False)
def cached_mirror_probe(name, mirror):
    return probe_mirror(name, mirror)


def prepare_download(system_key, name, url, mirror, on_progress=None):
    mirror_error = False
    if matching_mirror(name, mirror):
        if on_progress:
            on_progress("Conferindo o arquivo no espelho.")
        try:
            size = mirror.get("size")
            if isinstance(size, int) and 0 < size <= DIRECT_DOWNLOAD_LIMIT:
                if on_progress:
                    on_progress("Baixando e validando o arquivo completo antes de liberar o download.")
                package = download_mirror(name, mirror)
                expected_signature = b"PK" if name.lower().endswith(".zip") else b"MZ"
                if len(package) > DIRECT_DOWNLOAD_LIMIT or package[:2] != expected_signature:
                    raise ValueError("O arquivo entregue não corresponde ao download selecionado.")
                return {"data": package}, "Espelho independente · arquivo validado", False
            return {"url": cached_mirror_probe(name, mirror)}, "Espelho independente", False
        except (OSError, ValueError):
            mirror_error = True
            if on_progress:
                on_progress("O espelho falhou; tentando recuperar o arquivo na fonte oficial.")
    if system_key in {"cnes_base", "cnes_complete"}:
        raise OSError("Este pacote CNES grande precisa de um espelho publicado para evitar sobrecarga do portal.")
    if on_progress and not mirror_error:
        on_progress("Preparando o arquivo pela fonte oficial; aguarde a conferência.")
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


def render_loading_card(placeholder, message):
    placeholder.markdown(
        f'<div class="ds-loading-card" role="status" aria-live="polite">'
        f'<div class="ds-loading-copy"><span class="ds-loading-dot" aria-hidden="true"></span>'
        f'<div><strong>Preparando arquivo</strong><span>{escape(message)}</span></div></div>'
        f'<div class="ds-progress-track" role="progressbar" aria-label="Preparação do arquivo" '
        f'aria-valuetext="Em andamento"><span></span></div></div>',
        unsafe_allow_html=True,
    )


def readable_date(value):
    if not value:
        return "ainda não confirmada"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone(timedelta(hours=-3)))
        return parsed.strftime("%d/%m/%Y às %H:%M (horário de Brasília)")
    except (TypeError, ValueError):
        return str(value)


def update_day(value):
    if not value:
        return "data não informada"
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo:
            parsed = parsed.astimezone(timezone(timedelta(hours=-3)))
        return parsed.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(value)


def fetch_official_catalog(system_key):
    try:
        releases = SYSTEM_META[system_key]["fetch"]()
        return (system_key, releases, None) if releases else (system_key, None, "EmptyCatalog")
    except Exception as exc:
        # Uma fonte instável não interrompe a consulta dos demais sistemas.
        return system_key, None, type(exc).__name__


def find_live_updates(snapshot_systems, catalogs, found_at):
    events = []
    for system_key, (releases, error) in catalogs.items():
        if not releases:
            continue
        saved = snapshot_systems.get(system_key, {})
        meta = SYSTEM_META[system_key]
        if system_key in COMPETENCE_SYSTEMS:
            competences = saved.get("competences", {})
            competences = competences if isinstance(competences, dict) else {}
            known_latest = saved.get("latest") or {}
            old_month = max([*competences, str(known_latest.get("competence", ""))], default="") or None
            latest = max(releases, key=lambda item: str(item.get("competence", "")))
            month = str(latest.get("competence", ""))
            previous_name = (known_latest if str(known_latest.get("competence", "")) == old_month else competences.get(old_month, {})).get("name") if old_month else None
            if old_month and (month > old_month or (month == old_month and previous_name != latest.get("name"))):
                events.append(make_update_event(
                    system_key, meta["label"], latest["name"], found_at,
                    competence=month, catalog_source=latest.get("catalog_source"),
                ))
        else:
            previous_name = (saved.get("latest") or saved.get("current") or {}).get("name")
            latest = releases[0]
            if previous_name and previous_name != latest.get("name"):
                events.append(make_update_event(system_key, meta["label"], latest["name"], found_at))
    return events


def force_check_all_systems(snapshot_systems):
    total = len(SYSTEM_META)
    progress = st.progress(0, text=f"Consultando 0 de {total} sistemas…")
    status = st.empty()
    catalogs = {}
    with ThreadPoolExecutor(max_workers=min(6, total)) as executor:
        tasks = {executor.submit(fetch_official_catalog, key): key for key in SYSTEM_META}
        for completed, future in enumerate(as_completed(tasks), start=1):
            key, releases, error = future.result()
            catalogs[key] = (releases, error)
            progress.progress(completed / total, text=f"Consultando {completed} de {total} sistemas…")
            status.caption(f"Conferido: {SYSTEM_META[key]['label']}")
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with CATALOG_LOCK:
        snapshot = load_snapshot()
        saved_systems = snapshot.setdefault("systems", {})
        catalogs = {key: (normalize_catalog(saved_systems.get(key, {}), releases, key in COMPETENCE_SYSTEMS), error)
                    if releases else (releases, error) for key, (releases, error) in catalogs.items()}
        events = find_live_updates(saved_systems, catalogs, checked_at)
        for key, (releases, error) in catalogs.items():
            if not releases:
                continue
            info = saved_systems.setdefault(key, {})
            info.update(latest=dict(releases[0]), catalog_checked_at=checked_at,
                        official_reachable=releases[0].get("catalog_source") != "community")
            info.pop("error", None)
            if key not in COMPETENCE_SYSTEMS:
                info["pending_download"] = not matching_mirror(releases[0]["name"], info.get("mirror"))
            if key in COMPETENCE_SYSTEMS:
                info["available_releases"] = releases
        snapshot["updates"] = merge_updates(snapshot.get("updates", []), events)
        if any(releases for releases, _ in catalogs.values()):
            snapshot["updated_at"] = checked_at
        try:
            if any(releases for releases, _ in catalogs.values()):
                atomic_write(CATALOG_PATH, snapshot)
        except OSError:
            st.warning("A consulta foi concluída, mas não foi possível salvar o catálogo neste servidor.")
    st.session_state["forced_live_catalogs"] = catalogs
    st.session_state["forced_live_checked_at"] = checked_at
    st.session_state["forced_live_updates"] = events
    progress.empty()
    status.empty()
    errors = sum(error is not None for _, error in catalogs.values())
    community = sum(bool(releases and releases[0].get("catalog_source") == "community") for releases, _ in catalogs.values())
    if errors:
        st.warning(f"Consulta concluída: {total - errors} de {total} fontes responderam. As demais podem estar temporariamente fora do ar.")
    elif community:
        st.info(f"Consulta concluída: {total - community} fontes oficiais e {community} catálogo(s) comunitário(s) de apoio responderam.")
    else:
        st.success(f"Consulta concluída: os {total} sistemas foram verificados nas fontes oficiais.")
    if events:
        st.info(f"Encontramos {len(events)} atualização(ões) desde o último catálogo. Elas já aparecem no painel de novidades abaixo.")


def render_download_button(system_key, name, url, mirror):
    mirror = matching_mirror(name, mirror)
    if mirror and mirror.get("verified_at"):
        badge("ok", "Download disponível · cópia verificada")
    elif mirror:
        badge("warn", "Cópia disponível · validação ao preparar")
    else:
        badge("warn", "Download pelo servidor DATASUS")
    if not mirror and system_key.removesuffix("_backup") in {"cnes_base", "cnes_complete"}:
        st.info("A cópia deste pacote grande está sendo incluída no espelho. Enquanto isso, o download direto depende da disponibilidade do CNES.")
        if cnes_portal.safe_url(url, name):
            st.link_button(f"Baixar na fonte oficial: {name}", url, width="stretch")
        return
    if mirror and mirror.get("size"):
        st.caption(f'{mirror["size"] / 1_000_000:.1f} MB · arquivo conferido')

    state_key = f"official_download_{system_key}"
    cached = st.session_state.get(state_key)
    identity = (name, url, (mirror or {}).get("asset_url"), (mirror or {}).get("sha256"))
    if cached and cached.get("identity") != identity:
        st.session_state.pop(state_key, None)
        cached = None
    action = {"fpo_update": "atualização FPO", "fpo_installer": "instalador base FPO"}.get(system_key.removesuffix("_backup"), "arquivo")
    if not cached and st.button(f"Preparar {action} para baixar", key=f"prep_{system_key}_{name}", width="stretch", type="primary"):
        loading = st.empty()
        render_loading_card(loading, "Iniciando a verificação do arquivo.")
        try:
            data, source, fallback = prepare_download(
                system_key.removesuffix("_backup"), name, url, mirror,
                on_progress=lambda message: render_loading_card(loading, message),
            )
            loading.empty()
            # Mantém apenas um arquivo preparado por sessão.
            for other_key in list(st.session_state):
                if other_key.startswith("official_download_") and other_key != state_key:
                    st.session_state.pop(other_key, None)
            cached = {"identity": identity, **data, "source": source}
            st.session_state[state_key] = cached
            if fallback:
                st.warning("O espelho não respondeu. Recuperamos este arquivo da fonte oficial.")
        except (OSError, ValueError):
            loading.empty()
            st.error("O arquivo não está disponível agora. Tente novamente mais tarde. Os demais downloads continuam disponíveis.")
            if system_key.removesuffix("_backup") in {"cnes_base", "cnes_complete"} and cnes_portal.safe_url(url, name):
                st.link_button(f"Tentar download na fonte oficial: {name}", url, width="stretch")
    if cached:
        st.caption(f'Arquivo pronto · {cached["source"]}')
        with st.container(key=f"ready_download_{system_key}"):
            if cached.get("url"):
                st.link_button(f"⬇️ Baixar {action}: {name}", cached["url"], width="stretch", type="primary")
            else:
                st.download_button(f"⬇️ Baixar {action}: {name}", data=cached["data"], file_name=name,
                                   mime="application/zip" if name.lower().endswith(".zip") else "application/octet-stream",
                                   width="stretch", key=f"dl_{system_key}_{name}", on_click="ignore", type="primary")


def render_status(releases, error, checked_at):
    if releases:
        badge("ok", "Versões consultadas na fonte oficial")
    elif error:
        badge("warn", "Fonte oficial indisponível · usando catálogo salvo")
    elif checked_at:
        st.caption(f"Última confirmação: {readable_date(checked_at)}")
    else:
        st.caption("Nenhuma versão salva. Use o botão de verificação para consultar a fonte oficial.")


def card_catalog(system_key, saved):
    releases, error = st.session_state.get("forced_live_catalogs", {}).get(system_key, (None, None))
    if releases:
        releases = normalize_catalog(saved, releases, system_key in COMPETENCE_SYSTEMS)
    return releases, error


def render_single_version_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    meta = SYSTEM_META[system_key]
    info = snapshot_systems.get(system_key, {})
    with st.container(border=True):
        st.markdown(f'<div class="ds-card-title"><span class="ds-card-icon" aria-hidden="true">{meta["icon"]}</span><span>{meta["label"]}</span></div>', unsafe_allow_html=True)
        releases, error = card_catalog(system_key, info)
        if not releases and info.get("official_reachable") is False:
            error = error or info.get("error") or "SourceUnavailable"
        current = info.get("current")
        latest = info.get("latest") or current
        render_status(releases, error, info.get("catalog_checked_at", info.get("last_success_at", info.get("checked_at"))) if latest and not releases else None)
        if releases:
            name, url = releases[0]["name"], releases[0]["url"]
        elif latest:
            name, url = latest["name"], latest["url"]
        else:
            name = url = None
        if name:
            st.caption(name)
            if system_key == "cnes_complete":
                st.caption("Instalação nova do SCNES")
            elif system_key == "cnes_app":
                st.caption("Atualização para o SCNES já instalado")
            elif system_key == "fpo_installer":
                st.caption("Use na primeira instalação e, em seguida, aplique a atualização atual no cartão principal.")
            elif system_key == "fpo_update":
                st.caption("Este é o arquivo de atualização atual. Use com o FPO já instalado.")
            elif system_key == "ciha02":
                st.caption("Atualização para o sistema já instalado. A primeira instalação fica na seção abaixo.")
            elif system_key == "ciha02_installer":
                st.caption("Primeira instalação: inclui banco de dados vazio. Não substitua o banco de uma instalação existente.")
            render_download_button(system_key, str(name), str(url), info.get("mirror"))
            if current and current.get("name") not in (latest or {}).get("withdrawn_names", []) and current.get("name") != name and matching_mirror(current["name"], info.get("mirror")):
                with st.expander("Versão anterior preservada no espelho"):
                    render_download_button(system_key + "_backup", current["name"], current["url"], info["mirror"])
        st.link_button("Conferir no portal oficial", meta["official_page"], width="stretch")
        if system_key == "fpo_update":
            with st.expander("Primeira instalação? Abra o instalador base do FPO"):
                render_single_version_card("fpo_installer", snapshot_systems)
        if system_key == "ciha02":
            with st.expander(f"Primeira instalação do {system_key.upper()}"):
                render_single_version_card(system_key + "_installer", snapshot_systems)


def render_competence_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    meta = SYSTEM_META[system_key]
    info = snapshot_systems.get(system_key, {})
    saved_competences = info.get("competences", {}) if isinstance(info.get("competences"), dict) else {}
    saved_latest = info.get("latest") or {}
    stored_releases = info.get("available_releases") or []
    with st.container(border=True):
        st.markdown(f'<div class="ds-card-title"><span class="ds-card-icon" aria-hidden="true">{meta["icon"]}</span><span>{meta["label"]}</span></div>', unsafe_allow_html=True)
        releases, error = card_catalog(system_key, info)
        source = (releases[0] if releases else saved_latest).get("catalog_source") if releases or saved_latest else None
        if system_key == "sigtap" and source == "community":
            badge("warn", "Catálogo comunitário de apoio · cópias identificadas")
        else:
            render_status(releases, error, info.get("last_success_at", info.get("checked_at")) if not releases else None)
        if system_key == "sigtap":
            st.caption("Se o DATASUS falhar, consultamos o catálogo e as cópias comunitárias do SIGTAP.")
        latest_months = {str(saved_latest["competence"])} if saved_latest.get("competence") else set()
        available = sorted(set(saved_competences) | latest_months | {str(item["competence"]) for item in (releases or []) + stored_releases}, reverse=True)

        if not available:
            st.info("Nenhuma competência disponível ainda. Consulte o catálogo oficial ou tente novamente mais tarde.")
            st.link_button("Conferir no portal oficial", meta["official_page"], width="stretch")
            return

        def release_for(month: str) -> dict[str, object] | None:
            live = next((item for item in releases if item["competence"] == month), None) if releases else None
            stored = next((item for item in stored_releases if item["competence"] == month), None)
            return live or stored or (saved_latest if saved_latest.get("competence") == month else None)

        def competence_label(month: str) -> str:
            release = release_for(month)
            name = release["name"] if release else saved_competences.get(month, {}).get("name", "pacote local")
            return f"{month[4:6]}/{month[:4]} · {name}"

        competence = st.selectbox(
            "Competência para acompanhar/baixar", options=available, format_func=competence_label,
            key=f"competence_{system_key}",
        )
        st.caption(f"{len(available)} competências no histórico · sem limite de meses")
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


def release_date_value(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def latest_release_rows(snapshot_systems):
    live_catalogs = st.session_state.get("forced_live_catalogs", {})
    rows = []
    for system_key, meta in SYSTEM_META.items():
        if system_key in {"fpo_installer", "ciha02_installer"}:
            continue
        saved = snapshot_systems.get(system_key, {})
        releases, _error = live_catalogs.get(system_key, (None, None))
        releases = normalize_catalog(saved, releases or [], system_key in COMPETENCE_SYSTEMS)
        release = None
        version = "—"
        if system_key in COMPETENCE_SYSTEMS:
            competences = saved.get("competences", {})
            competences = competences if isinstance(competences, dict) else {}
            saved_month = max(competences, default=None)
            saved_release = competences.get(saved_month, {}) if saved_month else {}
            live_release = max(
                releases or [], key=lambda item: str(item.get("competence", "")), default=None,
            )
            live_release = live_release or saved.get("latest")
            if live_release and (not saved_month or str(live_release.get("competence", "")) >= saved_month):
                release = dict(live_release)
                month = str(live_release.get("competence", ""))
                if not release.get("release_date") and saved_release.get("name") == release.get("name"):
                    release["release_date"] = saved_release.get("release_date")
            elif saved_release:
                release = saved_release
                month = str(saved_month)
            else:
                month = ""
            if release:
                period = f"{month[4:6]}/{month[:4]} · " if len(month) == 6 else ""
                version = f"{period}{release.get('name', '—')}"
        else:
            current = saved.get("latest") or saved.get("current") or {}
            release = dict(releases[0]) if releases else current
            if releases and not release.get("release_date") and current.get("name") == release.get("name"):
                release["release_date"] = current.get("release_date")
            if release:
                version = str(release.get("name", "-"))
        mirror_entry = saved_release if system_key in COMPETENCE_SYSTEMS else saved
        has_mirror = matching_mirror(str((release or {}).get("name", "")), mirror_entry.get("mirror"))
        rows.append({
            "Sistema": str(meta["label"]),
            "Última versão": version,
            "Data do lançamento": release_date_value((release or {}).get("release_date")),
            "Download": "Disponível no espelho" if has_mirror else "Download pelo DATASUS",
        })
    return rows


def render_latest_releases_table(snapshot_systems):
    st.markdown(
        '<div class="ds-section"><div class="ds-eyebrow">ACOMPANHAMENTO</div>'
        '<h2>Últimos lançamentos</h2>'
        '<p>A versão mais recente identificada em cada catálogo e a data publicada pela fonte oficial.</p></div>',
        unsafe_allow_html=True,
    )
    st.dataframe(
        latest_release_rows(snapshot_systems),
        hide_index=True,
        width="stretch",
        height=410,
        column_config={
            "Sistema": st.column_config.TextColumn("Sistema"),
            "Última versão": st.column_config.TextColumn("Última versão"),
            "Download": st.column_config.TextColumn("Download"),
            "Data do lançamento": st.column_config.DateColumn(
                "Data do lançamento", format="DD/MM/YYYY",
                help="Data indicada na listagem oficial. Quando ela não é publicada, o campo fica em branco.",
            ),
        },
        key="latest_releases_table",
    )
    st.caption("Data em branco significa que a fonte oficial consultada não informou quando o arquivo foi publicado.")


def render_updates_panel(snapshot):
    left, action = st.columns([2.4, 1], vertical_alignment="center")
    with left:
        st.markdown(
            '<div class="ds-update-heading"><div class="ds-update-icon">✦</div>'
            '<div><strong>Novidades dos sistemas</strong>'
            '<span>Atualizações identificadas nos últimos 7 dias.</span></div></div>',
            unsafe_allow_html=True,
        )
    with action:
        check_now = st.button(
            "🔄 Verificar todos os sistemas", key="force_catalog_check",
            type="primary", width="stretch",
            help="Consulta agora, sem cache, os catálogos oficiais de todos os sistemas.",
        )
    if check_now:
        force_check_all_systems(snapshot.get("systems", {}))

    stored = snapshot.get("updates", [])
    live = st.session_state.get("forced_live_updates", [])
    updates = recent_updates(merge_updates(stored, live))
    if updates:
        items = []
        for event in updates:
            source_note = " · catálogo comunitário" if event.get("catalog_source") == "community" else ""
            items.append(
                '<div class="ds-update-item">'
                f'<span class="ds-update-system">{escape(str(event.get("system", "Sistema")))}</span>'
                f'<span class="ds-update-file">{escape(str(event.get("name", "Nova versão")))}{source_note}</span>'
                f'<span class="ds-update-date">Encontrada em {escape(update_day(event.get("found_at")))}</span>'
                '</div>'
            )
        extra = ""
        content = f'<div class="ds-update-list">{"".join(items)}</div>{extra}'
    else:
        checked_at = st.session_state.get("forced_live_checked_at")
        if checked_at:
            message = f"Nenhuma versão nova encontrada na última verificação de {update_day(checked_at)}."
        else:
            message = "Nenhuma atualização identificada nos últimos 7 dias. A consulta automática é realizada a cada duas horas."
        content = f'<div class="ds-update-empty">{escape(message)}</div>'

    st.markdown(
        f'<div class="ds-update-panel">{content}</div>',
        unsafe_allow_html=True,
    )
    checked_at = st.session_state.get("forced_live_checked_at")
    if checked_at:
        st.caption(f"Última verificação manual, sem cache: {readable_date(checked_at)}")


snapshot = load_snapshot()
systems = snapshot.get("systems", {}) if isinstance(snapshot.get("systems"), dict) else {}
updated_at = snapshot.get("updated_at", "ainda não sincronizado")
readable_updated_at = readable_date(updated_at)

st.markdown(
    f"""
    <div class="ds-hero">
        <div class="ds-hero-copy">
            <div class="ds-eyebrow">SISTEMAS DE INFORMAÇÃO DO SUS</div>
            <h1>Downloads Sistemas</h1>
            <p>Acesso centralizado a instaladores, atualizações e tabelas dos sistemas de informação do SUS.
            Apoio às atividades de gestão, processamento e envio de dados em saúde.</p>
        </div>
        <div class="ds-hero-meta">
            <strong>Catálogo conferido</strong>
            <span>{escape(readable_updated_at)}</span>
            <small>Consulta automática a cada duas horas</small>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f'<div class="ds-overview">'
    f'<div class="ds-overview-item"><div class="ds-overview-number">{len(SYSTEM_META)}</div><div><strong>Pacotes acompanhados</strong><span>Instaladores, atualizações e tabelas</span></div></div>'
    '<div class="ds-overview-item"><div class="ds-overview-number">2h</div><div><strong>Consulta automática</strong><span>Inclui 06:50, no horário de Brasília</span></div></div>'
    '<div class="ds-overview-item"><div class="ds-overview-number">7d</div><div><strong>Novidades em destaque</strong><span>Avisos disponíveis por sete dias</span></div></div>'
    '</div>', unsafe_allow_html=True,
)

with st.container(border=True):
    render_updates_panel(snapshot)

with st.container(border=True):
    note, control = st.columns([1.6, 1])
    with note:
        st.markdown("**Baixe pelo arquivo confirmado**")
        st.caption("Os downloads espelhados continuam disponíveis mesmo durante falhas nos portais oficiais.")
    with control:
        st.caption("Consulta automática a cada duas horas, incluindo 06:50 (horário de Brasília). O botão permite antecipar a consulta.")


programs_tab, tables_tab, releases_tab = st.tabs(["Programas e instaladores", "Tabelas e bases", "Últimos lançamentos"])

with programs_tab:
    st.markdown(
        '<div class="ds-section"><div class="ds-eyebrow">01 &nbsp;·&nbsp; APLICATIVOS</div>'
        '<h2>Instaladores</h2><p>Programas e atualizações para processamento das informações do SUS.</p></div>',
        unsafe_allow_html=True,
    )
    st.info("**SCNES:** use **completo** para uma nova instalação ou **atualização** se já tiver o sistema; o Firebird é necessário. **FPO:** faça a instalação inicial e depois aplique a atualização mais recente.", icon="ℹ️")
    render_grid(SINGLE_VERSION_SYSTEMS, systems, render_single_version_card)

with tables_tab:
    st.markdown(
        '<div class="ds-section"><div class="ds-eyebrow">02 &nbsp;·&nbsp; COMPETÊNCIAS</div>'
        '<h2>Tabelas e bases</h2><p>Selecione o mês que você precisa e baixe o pacote correspondente.</p></div>',
        unsafe_allow_html=True,
    )
    render_grid(COMPETENCE_SYSTEMS, systems, render_competence_card)

with releases_tab:
    render_latest_releases_table(systems)

st.markdown('<div class="ds-footer">Downloads Sistemas · Central de acesso a arquivos dos sistemas de informação do SUS</div>', unsafe_allow_html=True)

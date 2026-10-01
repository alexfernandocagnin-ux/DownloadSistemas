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
from catalogs.updates import make_update_event, merge_updates

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
.ds-loading-card { background: #f7fbf8; border: 1px solid #dce9e1; border-radius: 12px;
    padding: .85rem 1rem; margin: .65rem 0 .9rem; }
.ds-loading-copy { display: flex; align-items: center; gap: .7rem; color: #17343a; }
.ds-loading-dot { width: 11px; height: 11px; flex: 0 0 auto; border: 2px solid #c6ded2;
    border-top-color: #126b59; border-radius: 50%; animation: ds-spin .85s linear infinite; }
.ds-loading-copy strong { display: block; font-size: .91rem; }
.ds-loading-copy span { display: block; color: #647477; font-size: .82rem; margin-top: .15rem; }
.ds-update-panel { position: relative; overflow: hidden; padding: 1.2rem 1.35rem;
    background: linear-gradient(120deg, #edf7f1 0%, #f8fbf8 58%, #fff 100%);
    border: 1px solid #d9e8de; border-radius: 16px; margin: .3rem 0 1.2rem; }
.ds-update-heading { display: flex; align-items: center; gap: .8rem; margin-bottom: .85rem; }
.ds-update-icon { display: grid; place-items: center; width: 42px; height: 42px; flex: 0 0 auto;
    color: #126b59; background: #dcefe4; border-radius: 13px; font-size: 1.2rem; }
.ds-update-heading strong { display: block; color: #17343a; font-size: 1.02rem; }
.ds-update-heading span { color: #637477; display: block; font-size: .82rem; margin-top: .12rem; }
.ds-update-list { display: grid; gap: .48rem; }
.ds-update-item { display: grid; grid-template-columns: minmax(135px,.8fr) minmax(180px,1.5fr) auto;
    align-items: center; gap: .7rem; padding: .62rem .75rem; background: rgba(255,255,255,.78);
    border: 1px solid #e4ece6; border-radius: 10px; }
.ds-update-system { color: #173c35; font-size: .86rem; font-weight: 750; }
.ds-update-file { color: #536467; font-size: .81rem; overflow-wrap: anywhere; }
.ds-update-date { color: #71817e; font-size: .76rem; white-space: nowrap; }
.ds-update-empty { color: #47665c; font-size: .88rem; padding: .8rem .9rem;
    background: rgba(255,255,255,.72); border: 1px solid #e4ece6; border-radius: 10px; }
.ds-toolbar { display: flex; align-items: center; }
.ds-progress-track { position: relative; height: 5px; margin-top: .85rem; overflow: hidden;
    background: #e1ece5; border-radius: 999px; }
.ds-progress-track span { display: block; width: 34%; height: 100%; border-radius: inherit;
    background: #126b59; animation: ds-progress-slide 1.3s ease-in-out infinite; }
@keyframes ds-spin { to { transform: rotate(360deg); } }
@keyframes ds-progress-slide { from { transform: translateX(-120%); } to { transform: translateX(330%); } }
@media (prefers-reduced-motion: reduce) {
    .ds-loading-dot, .ds-progress-track span { animation: none; }
    .ds-progress-track span { transform: translateX(80%); }
}
@media (max-width: 760px) { .ds-hero { grid-template-columns: 1fr; gap: 1.3rem; padding: 2rem 1.5rem; }
    .ds-hero-meta { border-left: 0; border-top: 1px solid rgba(255,255,255,.2); padding: .8rem 0 0; }
    .ds-update-item { grid-template-columns: 1fr; gap: .2rem; }
    .ds-update-date { white-space: normal; } }
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
    st.session_state["forced_live_catalogs"] = catalogs
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    events = find_live_updates(snapshot_systems, catalogs, checked_at)
    st.session_state["forced_live_checked_at"] = checked_at
    st.session_state["forced_live_updates"] = events
    snapshot = load_snapshot()
    saved_systems = snapshot.setdefault("systems", {})
    for key, (releases, error) in catalogs.items():
        if not releases:
            continue
        info = saved_systems.setdefault(key, {})
        info.update(latest=dict(releases[0]), catalog_checked_at=checked_at)
        if key in COMPETENCE_SYSTEMS:
            info["available_releases"] = releases
    snapshot["updates"] = merge_updates(snapshot.get("updates", []), events)
    snapshot["updated_at"] = checked_at
    try:
        temporary = CATALOG_PATH.with_suffix(".tmp")
        temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(CATALOG_PATH)
    except OSError:
        st.warning("A consulta foi concluída, mas não foi possível salvar o catálogo neste servidor.")
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
        badge("ok", "Espelho publicado · disponível sem o DATASUS")
    elif mirror:
        badge("warn", "Espelho antigo · será verificado ao preparar")
    else:
        badge("warn", "Ainda depende da fonte oficial")
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
    if cached:
        st.caption(f'Arquivo pronto · {cached["source"]}')
        if cached.get("url"):
            st.link_button(f"⬇️ Baixar {action}: {name}", cached["url"], width="stretch", type="primary")
        else:
            st.download_button(f"⬇️ Baixar {action}: {name}", data=cached["data"], file_name=name,
                               mime="application/zip" if name.lower().endswith(".zip") else "application/octet-stream",
                               width="stretch", key=f"dl_{system_key}_{name}", on_click="ignore")


def render_status(releases, error, checked_at):
    if releases:
        badge("ok", "Versões consultadas na fonte oficial")
    elif error:
        badge("warn", "Fonte oficial indisponível · usando catálogo salvo")
    elif checked_at:
        st.caption(f"Última confirmação: {readable_date(checked_at)}")
    else:
        st.caption("Nenhuma versão salva. Use o botão de verificação para consultar a fonte oficial.")


def card_catalog(system_key):
    return st.session_state.get("forced_live_catalogs", {}).get(system_key, (None, None))


def render_single_version_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    meta = SYSTEM_META[system_key]
    info = snapshot_systems.get(system_key, {})
    with st.container(border=True):
        st.markdown(f'<div class="ds-card-title">{meta["icon"]} {meta["label"]}</div>', unsafe_allow_html=True)
        releases, error = card_catalog(system_key)
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
            if system_key == "sihd2" and not matching_mirror(name, info.get("mirror")):
                st.warning("Versão identificada na página oficial, mas o arquivo ainda não pôde ser baixado do servidor DATASUS. Download indisponível até a cópia ser confirmada.")
            else:
                render_download_button(system_key, str(name), str(url), info.get("mirror"))
            if current and current.get("name") != name and matching_mirror(current["name"], info.get("mirror")):
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
        st.markdown(f'<div class="ds-card-title">{meta["icon"]} {meta["label"]}</div>', unsafe_allow_html=True)
        releases, error = card_catalog(system_key)
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
            "Download": "Disponível no espelho" if has_mirror else "Cópia ainda indisponível",
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
            '<span>Novas versões encontradas, organizadas pela data em que foram descobertas.</span></div></div>',
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
    updates = merge_updates(stored, live)
    if updates:
        items = []
        for event in updates[:6]:
            source_note = " · catálogo comunitário" if event.get("catalog_source") == "community" else ""
            items.append(
                '<div class="ds-update-item">'
                f'<span class="ds-update-system">{escape(str(event.get("system", "Sistema")))}</span>'
                f'<span class="ds-update-file">{escape(str(event.get("name", "Nova versão")))}{source_note}</span>'
                f'<span class="ds-update-date">Encontrada em {escape(update_day(event.get("found_at")))}</span>'
                '</div>'
            )
        extra = f"<p>Exibindo as 6 novidades mais recentes de {len(updates)} registradas.</p>" if len(updates) > 6 else ""
        content = f'<div class="ds-update-list">{"".join(items)}</div>{extra}'
    else:
        checked_at = st.session_state.get("forced_live_checked_at")
        if checked_at:
            message = f"Nenhuma versão nova encontrada na última verificação de {update_day(checked_at)}."
        else:
            message = "Ainda não há uma versão nova registrada desde o início do histórico. A verificação automática confere os sistemas ao longo do dia."
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
            <div class="ds-eyebrow">DATASUS &nbsp;·&nbsp; CENTRAL DE ARQUIVOS</div>
            <h1>Downloads Sistemas</h1>
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
    render_updates_panel(snapshot)

with st.container(border=True):
    note, control = st.columns([1.6, 1])
    with note:
        st.markdown("**Baixe pelo arquivo confirmado**")
        st.caption("Os downloads espelhados continuam disponíveis mesmo durante falhas nos portais oficiais.")
    with control:
        scan_time = st.session_state.get("forced_live_checked_at")
        st.caption(f"Última busca manual: {update_day(scan_time)}" if scan_time else "A consulta dos sistemas é sob demanda.")

render_latest_releases_table(systems)

st.markdown(
    '<div class="ds-section"><div class="ds-eyebrow">01 &nbsp;·&nbsp; APLICATIVOS</div>'
    '<h2>Instaladores</h2><p>Programas e atualizações para processamento das informações do SUS.</p></div>',
    unsafe_allow_html=True,
)
st.info("**SCNES:** use **completo** para uma nova instalação ou **atualização** se já tiver o sistema; o Firebird é necessário. **FPO:** faça a instalação inicial e depois aplique a atualização mais recente.", icon="ℹ️")
render_grid(SINGLE_VERSION_SYSTEMS, systems, render_single_version_card)

st.markdown(
    '<div class="ds-section"><div class="ds-eyebrow">02 &nbsp;·&nbsp; COMPETÊNCIAS</div>'
    '<h2>Tabelas e bases</h2><p>Selecione o mês que você precisa e baixe o pacote correspondente.</p></div>',
    unsafe_allow_html=True,
)
render_grid(COMPETENCE_SYSTEMS, systems, render_competence_card)

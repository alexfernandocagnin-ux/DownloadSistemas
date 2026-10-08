"""Portal de download dos instaladores e tabelas oficiais do DATASUS.

Abre pelo catálogo salvo e permite uma consulta manual às fontes.
As cópias confirmadas em GitHub Releases permitem baixar arquivos
quando o servidor de origem está indisponível.
"""

from __future__ import annotations

import json
import base64
from pathlib import Path
from html import escape
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import streamlit as st

from catalogs.mirrors import download_mirror, matching_mirror, probe_mirror
from catalogs import apac_portal, bpa_portal, ciha_portal, cnes_portal, fpo_portal, sia_portal, sigtap_portal, sihd_portal
from catalogs.updates import make_update_event, merge_updates, recent_updates
from catalogs.state import CATALOG_LOCK, atomic_write, normalize_catalog, merge_catalogs
from catalogs.snapshot import read_published_catalog, catalog_revision, verification_notice
from catalogs.manuals import load_manuals, SYSTEMS as MANUAL_SYSTEMS, download_manual, filter_manuals

CATALOG_PATH = Path(__file__).parent / "data" / "catalog.json"

COMPETENCE_SYSTEMS = ("bdsia", "sigtap")
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
}

st.set_page_config(page_title="Downloads Sistemas", page_icon="📦", layout="wide")

UI_DIR = Path(__file__).parent / "ui"
font = Path(__file__).parent / "static" / "fonts" / "Manrope-Latin.woff2"
font_css = ""
if font.is_file():
    encoded_font = base64.b64encode(font.read_bytes()).decode("ascii")
    font_css = (
        "@font-face{font-family:Manrope;src:url(data:font/woff2;base64,"
        + encoded_font + ") format('woff2');font-weight:200 800;font-display:swap;}"
    )
st.markdown("<style>" + font_css + (UI_DIR / "download-focus.css").read_text(encoding="utf-8") + "</style>",
            unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def cached_published_catalog():
    return read_published_catalog()


def load_snapshot() -> dict[str, object]:
    published = cached_published_catalog()
    with CATALOG_LOCK:
        try:
            data = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.is_file() else {"systems": {}}
        except (OSError, ValueError):
            data = {"systems": {}}
            if not published:
                st.warning("O catálogo salvo não pôde ser lido. Consulte as fontes oficiais abaixo.")
        snapshot = data if isinstance(data, dict) and isinstance(data.get("systems", {}), dict) else {"systems": {}}
        if published:
            # Preserve newer local discoveries while importing the automation's
            # persisted versions and mirrors, without waiting for a redeploy.
            merged = merge_catalogs(published, snapshot)
            if merged != snapshot:
                try:
                    atomic_write(CATALOG_PATH, merged)
                except OSError:
                    pass  # Still render the published catalog if the disk is read-only.
            return merged
        return snapshot


@st.cache_data(ttl=5 * 60, max_entries=64, show_spinner=False)
def cached_mirror_probe(name, mirror):
    return probe_mirror(name, mirror)


def prepare_download(system_key, name, url, mirror, on_progress=None, manual_id=None):
    if manual_id:
        if on_progress:
            on_progress("Conferindo a cópia do manual salva no portal.")
        return {"data": download_manual(manual_id)}, "Cópia do manual verificada no portal", False
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


def readable_size(size):
    return f"{size / 1_000_000:.1f} MB" if size >= 1_000_000 else f"{size / 1_000:.1f} KB"


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
            info = saved_systems.setdefault(key, {})
            info["catalog_attempt_at"] = checked_at
            info["catalog_check_error"] = error
            if not releases:
                info.update(official_reachable=False, error=error)
                continue
            info.update(latest=dict(releases[0]), catalog_checked_at=checked_at,
                        official_reachable=releases[0].get("catalog_source") != "community")
            info.pop("error", None)
            if key not in COMPETENCE_SYSTEMS:
                info["pending_download"] = not matching_mirror(releases[0]["name"], info.get("mirror"))
            if key in COMPETENCE_SYSTEMS:
                info["available_releases"] = releases
        snapshot["updates"] = merge_updates(snapshot.get("updates", []), events)
        failed_sources = [key for key, (releases, error) in catalogs.items() if not releases]
        snapshot["last_check"] = {"completed_at": checked_at, "source": "manual", "total": total,
                                  "succeeded": total - len(failed_sources), "failed_systems": failed_sources}
        if any(releases for releases, _ in catalogs.values()):
            snapshot["updated_at"] = checked_at
        try:
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


def render_download_button(system_key, name, url, mirror, manual=None):
    mirror = matching_mirror(name, mirror)
    if manual or (mirror and mirror.get("verified_at")):
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
    if manual:
        st.caption(f'{readable_size(manual["size"])} · arquivo conferido')
    elif system_key in COMPETENCE_SYSTEMS and mirror and mirror.get("size"):
        st.caption(f'{readable_size(mirror["size"])} · arquivo conferido')

    state_key = f"official_download_{system_key}"
    cached = st.session_state.get(state_key)
    identity = (name, url, (mirror or {}).get("asset_url"), (manual or mirror or {}).get("sha256"))
    if cached and cached.get("identity") != identity:
        st.session_state.pop(state_key, None)
        cached = None
    action = "manual" if manual else {"fpo_update": "atualização FPO", "fpo_installer": "instalador base FPO"}.get(system_key.removesuffix("_backup"), "arquivo")
    if not cached and st.button(f"Preparar {action} para baixar", key=f"prep_{system_key}_{name}", width="stretch", type="primary"):
        loading = st.empty()
        render_loading_card(loading, "Iniciando a verificação do arquivo.")
        try:
            data, source, fallback = prepare_download(
                system_key.removesuffix("_backup"), name, url, mirror,
                on_progress=lambda message: render_loading_card(loading, message),
                manual_id=manual["id"] if manual else None,
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
                                   mime="application/pdf" if name.lower().endswith(".pdf") else "application/zip" if name.lower().endswith(".zip") else "application/octet-stream",
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


PACKAGE_COPY = {
    "cnes_complete": ("Instalação completa", "Para uma nova instalação do SCNES."),
    "cnes_app": ("Atualização", "Para quem já possui o SCNES instalado."),
    "fpo_installer": ("Instalação inicial", "Instale a base do FPO e depois aplique a atualização atual."),
    "fpo_update": ("Atualização", "Para o FPO Magnético já instalado."),
    "ciha02_installer": ("Instalação inicial", "Inclui banco de dados vazio. Preserve a base de uma instalação existente."),
    "ciha02": ("Atualização", "Para quem já possui o CIHA02 instalado."),
}


def latest_release(system_key, snapshot_systems):
    saved = snapshot_systems.get(system_key, {})
    releases, _ = card_catalog(system_key, saved)
    return releases[0] if releases else saved.get("latest") or saved.get("current") or {}


def release_version(release):
    # Use the catalog's version codes rather than invent versions from filenames.
    version = str(release.get("version") or "")
    return "Versão " + version if version else ""


def render_file_details(release, mirror=None):
    name = str(release.get("name") or "")
    mirror = matching_mirror(name, mirror)
    size = (mirror or {}).get("size") or release.get("size")
    size_text = readable_size(size) if isinstance(size, (int, float)) and size > 0 else "Não informado"
    date = release.get("release_date")
    date_text = update_day(date) if date else "Não informada pela fonte"
    st.markdown(
        '<dl class="ds-file-details">'
        f'<div><dt>{ui_icon("file")}Arquivo</dt><dd>{escape(name)}</dd></div>'
        f'<div><dt>{ui_icon("drive")}Tamanho</dt><dd>{escape(size_text)}</dd></div>'
        f'<div><dt>{ui_icon("calendar")}Data na fonte</dt><dd>{escape(date_text)}</dd></div>'
        '</dl>', unsafe_allow_html=True,
    )


def render_single_version_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    meta = SYSTEM_META[system_key]
    info = snapshot_systems.get(system_key, {})
    with st.container(border=True, key=f"system_card_{system_key}"):
        latest = latest_release(system_key, snapshot_systems)
        title, description = PACKAGE_COPY.get(system_key, ("Arquivo para instalação", "Baixe o instalador disponível no catálogo."))
        st.markdown(
            f'<div class="ds-package-heading"><h3>{escape(title)}</h3>'
            f'<span class="ds-version">{escape(release_version(latest))}</span></div>'
            f'<p class="ds-package-description">{escape(description)}</p>',
            unsafe_allow_html=True,
        )
        releases, error = card_catalog(system_key, info)
        if not releases and info.get("official_reachable") is False:
            error = error or info.get("error") or "SourceUnavailable"
        current = info.get("current")
        render_status(releases, error, info.get("catalog_checked_at", info.get("last_success_at", info.get("checked_at"))) if latest and not releases else None)
        if releases:
            name, url = releases[0]["name"], releases[0]["url"]
        elif latest:
            name, url = latest["name"], latest["url"]
        else:
            name = url = None
        if name:
            render_file_details(latest, info.get("mirror"))
            render_download_button(system_key, str(name), str(url), info.get("mirror"))
            if current and str(current.get("name", "")).lower() not in {str(item).lower() for item in (latest or {}).get("withdrawn_names", [])} and current.get("name") != name and matching_mirror(current["name"], info.get("mirror")):
                with st.expander("Versão anterior preservada no espelho"):
                    render_download_button(system_key + "_backup", current["name"], current["url"], info["mirror"])
        st.link_button("Conferir no portal oficial", meta["official_page"], width="stretch")


def render_competence_card(system_key: str, snapshot_systems: dict[str, object]) -> None:
    meta = SYSTEM_META[system_key]
    info = snapshot_systems.get(system_key, {})
    saved_competences = info.get("competences", {}) if isinstance(info.get("competences"), dict) else {}
    saved_latest = info.get("latest") or {}
    stored_releases = info.get("available_releases") or []
    with st.container(border=True, key=f"system_card_{system_key}"):
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
            render_file_details(release or saved_entry, mirror)
            render_download_button(system_key, str(name), str(url), mirror)
            if saved_entry.get("name") and saved_entry["name"] != name and matching_mirror(saved_entry["name"], saved_entry.get("mirror")):
                with st.expander("Revisão anterior preservada no espelho"):
                    render_download_button(system_key + "_backup", saved_entry["name"], saved_entry["url"], saved_entry["mirror"])
        else:
            st.caption("Ainda não há pacote espelhado para esta competência.")
        st.link_button("Conferir no portal oficial", meta["official_page"], width="stretch")


def render_manual_card(manual):
    manual_id = manual["id"]
    role = manual["role"]
    label = "ORIGINAL / OFICIAL" if role == "original" else manual["guide_label"] if role == "guide" else "DOCUMENTO COMPLEMENTAR"
    with st.container(border=True, key=f"system_card_manual_{manual_id}"):
        st.markdown(
            f'<div class="ds-manual-role ds-manual-role-{role}">{escape(label)}</div>'
            f'<div class="ds-manual-type"><span>{escape(manual["format"])}</span> {escape(manual["category"])}</div>'
            f'<h4 class="ds-manual-title">{escape(manual["title"])}</h4>'
            f'<p class="ds-manual-description">{escape(manual["description"])}</p>',
            unsafe_allow_html=True,
        )
        st.caption(f"Publicado por: {manual['publisher']}")
        publication_date = manual.get("publication_date")
        if manual.get("source_format") == "Online":
            st.caption(f"Wiki Saúde · cópia em PDF de {update_day(manual['copied_at'])}")
        else:
            st.caption(f"Data na fonte: {update_day(publication_date)}" if publication_date else "Data não informada na fonte")
        render_download_button(f"manual_{manual_id}", manual["name"], manual["url"], None, manual=manual)
        st.link_button("Ler na Wiki Saúde ↗" if manual.get("source_format") == "Online" else "Consultar fonte oficial ↗",
                       manual["source_page"], width="stretch")


def ui_icon(name):
    paths = {
        "monitor": '<rect x="3" y="3" width="18" height="13" rx="1"/><path d="M8 21h8m-4-5v5"/>',
        "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8m-8 4h5"/>',
        "chart": '<path d="M4 20V12m5 8V4m6 16V8m5 12V2"/>',
        "hospital": '<path d="M4 22V7h6V2h10v20M2 22h20M8 11h.01M8 15h.01M14 6h.01M14 10h.01M14 14h.01M18 6h.01M18 10h.01M18 14h.01M12 22v-4h4v4"/>',
        "grid": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 10h18M10 3v18"/>',
        "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 4 18 4 18 0V5M3 12c0 4 18 4 18 0"/>',
        "book": '<path d="M12 5v16M3 3h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3z"/>',
        "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
        "megaphone": '<path d="m3 10 13-6v16L3 14zM3 10v4M7 16l1 6h3l-2-5M20 7v10"/>',
        "calendar": '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 11h18"/>',
        "drive": '<path d="m4 3-2 9v7a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-7l-2-9zM2 12h20M6 16h.01M10 16h.01"/>',
        "info": '<circle cx="12" cy="12" r="10"/><path d="M12 11v6M12 7h.01"/>',
    }
    return f'<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{paths.get(name, paths["file"])}</svg>'


PROGRAM_GROUPS = {
    "bpa": {"label": "BPA Magnético", "icon": "file", "tone": "green", "packages": ("bpa",),
            "description": "Boletim de Produção Ambulatorial. Arquivo do aplicativo utilizado no registro da produção ambulatorial do SUS."},
    "apac": {"label": "APAC Magnético", "icon": "file", "tone": "orange", "packages": ("apac",),
             "description": "Aplicativo para registro das Autorizações de Procedimentos Ambulatoriais de Alta Complexidade."},
    "sia": {"label": "SIA", "icon": "chart", "tone": "purple", "packages": ("sia",),
            "description": "Sistema de Informações Ambulatoriais do SUS. Instalador para o processamento da produção ambulatorial."},
    "fpo": {"label": "FPO Magnético", "icon": "file", "tone": "red", "packages": ("fpo_installer", "fpo_update"),
            "description": "Aplicativo de programação físico-orçamentária. Escolha a instalação inicial ou a atualização para o sistema em uso.",
            "note": "Na primeira instalação, instale a base e depois aplique a atualização mais recente."},
    "sihd2": {"label": "SIHD2", "icon": "hospital", "tone": "blue", "packages": ("sihd2",),
              "description": "Sistema de Informações Hospitalares Descentralizado. Instalador disponível no catálogo do SIHD2."},
    "ciha02": {"label": "CIHA02", "icon": "grid", "tone": "amber", "packages": ("ciha02_installer", "ciha02"),
               "description": "Comunicação de Informação Hospitalar e Ambulatorial. Arquivos de instalação e atualização do módulo CIHA02.",
               "note": "Use o instalador inicial apenas em uma nova instalação. Ao atualizar, preserve o banco de dados existente."},
    "cnes": {"label": "CNES / SCNES", "icon": "hospital", "tone": "blue", "packages": ("cnes_complete", "cnes_app"),
             "description": "Cadastro Nacional de Estabelecimentos de Saúde. Aplicativo para cadastramento e manutenção das informações dos estabelecimentos.",
             "note": "Escolha instalação completa para começar ou atualização para o sistema já instalado. O Firebird é necessário para o funcionamento do SCNES."},
}
TABLE_GROUPS = {
    "bdsia": {"label": "SIA · Tabela mensal", "icon": "database", "tone": "blue",
              "description": "Tabelas do SIA organizadas por competência. Selecione o mês correspondente ao processamento."},
    "sigtap": {"label": "SIGTAP", "icon": "database", "tone": "purple",
               "description": "Tabela Unificada de Procedimentos, Medicamentos e OPM do SUS. Consulte a competência e a revisão que precisa."},
}


def choose_system(state_key, value):
    st.session_state[state_key] = value


def render_system_picker(scope, choices, snapshot_systems, default, state_key=None):
    state_key = state_key or f"{scope}_system"
    if st.session_state.get(state_key) not in choices:
        st.session_state[state_key] = default
    with st.container(key=f"focus_picker_{scope}"):
        st.markdown('<div class="ds-picker-heading"><h2>Sistemas disponíveis</h2>'
                    '<p>Selecione um sistema para ver os arquivos</p></div>', unsafe_allow_html=True)
        with st.container(key=f"mobile_picker_{scope}"):
            st.selectbox("Selecione um sistema", list(choices), key=state_key,
                         format_func=lambda key: choices[key]["label"])
        with st.container(key=f"desktop_picker_{scope}"):
            for key, group in choices.items():
                selected = st.session_state[state_key] == key
                package = group.get("packages", (key,))[-1]
                release = latest_release(package, snapshot_systems)
                subtitle = release_version(release)
                if scope == "tables" and release.get("competence"):
                    month = str(release["competence"])
                    subtitle = f"Competência {month[4:6]}/{month[:4]}"
                if scope == "manual":
                    count = sum(item["system"] == key or not key for item in load_manuals())
                    subtitle = f"{count} documentos"
                elif not key:
                    subtitle = f"{len(choices) - 1} sistemas"
                suffix = "_selected" if selected else ""
                with st.container(key=f"nav_item_{scope}_{key or 'all'}{suffix}"):
                    st.markdown(f'<span class="ds-nav-icon ds-tone-{group.get("tone", "blue")}">'
                                f'{ui_icon(group.get("icon", "file"))}</span>', unsafe_allow_html=True)
                    st.button(group["label"], key=f"choose_{scope}_{key or 'all'}", width="stretch",
                              on_click=choose_system, args=(state_key, key))
                    if subtitle:
                        st.caption(subtitle)
    return st.session_state[state_key]


def render_system_heading(group, eyebrow="SISTEMA SELECIONADO"):
    st.markdown(
        f'<div class="ds-detail-heading"><span class="ds-detail-icon ds-tone-{group.get("tone", "blue")}">'
        f'{ui_icon(group.get("icon", "file"))}</span><div><span class="ds-detail-eyebrow">{escape(eyebrow)}</span>'
        f'<h2>{escape(group["label"])}</h2></div></div>'
        f'<p class="ds-detail-description">{escape(group["description"])}</p>',
        unsafe_allow_html=True,
    )


@st.fragment
def render_programs(snapshot_systems):
    choices = {"": {"label": "Todos os programas e instaladores", "icon": "monitor", "tone": "blue"},
               **PROGRAM_GROUPS}
    navigation, details = st.columns([1, 2.8], gap="medium")
    with navigation:
        selected = render_system_picker("program", choices, snapshot_systems, "cnes")
    with details, st.container(key="focus_detail_programs"):
        for index, system_key in enumerate((selected,) if selected else PROGRAM_GROUPS):
            if index:
                st.divider()
            group = PROGRAM_GROUPS[system_key]
            render_system_heading(group, "SISTEMA SELECIONADO" if selected else "SISTEMA DISPONÍVEL")
            note = group.get("note", "Feche o aplicativo antes de instalar ou atualizar. Recomendamos fazer uma cópia de segurança da base de dados.")
            st.markdown(f'<div class="ds-install-note">{ui_icon("info")}<div><strong>Antes de instalar</strong>'
                        f'<p>{escape(note)}</p></div></div>', unsafe_allow_html=True)
            packages = group["packages"]
            for column, key in zip(st.columns(len(packages), gap="medium"), packages):
                with column:
                    render_single_version_card(key, snapshot_systems)


@st.fragment
def render_tables(snapshot_systems):
    choices = {"": {"label": "Todas as tabelas e bases", "icon": "database", "tone": "blue"},
               **TABLE_GROUPS}
    navigation, details = st.columns([1, 2.8], gap="medium")
    with navigation:
        selected = render_system_picker("tables", choices, snapshot_systems, "bdsia")
    with details, st.container(key="focus_detail_tables"):
        for index, system_key in enumerate((selected,) if selected else TABLE_GROUPS):
            if index:
                st.divider()
            render_system_heading(TABLE_GROUPS[system_key], "SISTEMA SELECIONADO" if selected else "SISTEMA DISPONÍVEL")
            render_competence_card(system_key, snapshot_systems)


@st.fragment
def render_manuals():
    choices = {"": {"label": "Todos os manuais", "icon": "book", "tone": "blue"}}
    for key, (label, _) in MANUAL_SYSTEMS.items():
        group = PROGRAM_GROUPS.get(key) or TABLE_GROUPS.get(key) or {}
        choices[key] = {"label": label, "icon": group.get("icon", "book"), "tone": group.get("tone", "blue")}
    navigation, details = st.columns([1, 2.8], gap="medium")
    with navigation:
        system = render_system_picker("manual", choices, {}, "", state_key="manual_system")
    with details, st.container(key="focus_detail_manuals"):
        render_system_heading({"label": "Manuais", "icon": "book",
                               "description": "Documentação e orientações para a rotina de trabalho. Encontre os arquivos por sistema ou assunto."})
        st.markdown('<div class="ds-library-label">BIBLIOTECA DE MANUAIS</div>'
                    '<p class="ds-manual-legend"><strong>Original / oficial:</strong> documento de referência. '
                    '<strong>Guia:</strong> orientações práticas, com o alcance indicado em cada cartão.</p>',
                    unsafe_allow_html=True)
        search, category_filter = st.columns([2, 1], gap="medium")
        with search:
            query = st.text_input("Buscar manual", placeholder="Ex.: instalação, BPA, equipes…", key="manual_search")
        with category_filter:
            category = st.selectbox("Assunto", ["", "Instalação", "Operação", "Orientações", "Layouts"],
                                    key="manual_category", format_func=lambda value: value or "Todos os assuntos")
        manuals = filter_manuals(query, system, category)
        st.caption(f"{len(manuals)} de {len(load_manuals())} documentos · {len(MANUAL_SYSTEMS)} sistemas")
        if not manuals:
            st.info("Nenhum manual encontrado. Experimente outra palavra ou amplie os filtros.", icon=":material/search:")
            return
        for system_key, (label, _) in MANUAL_SYSTEMS.items():
            group = [manual for manual in manuals if manual["system"] == system_key]
            if not group:
                continue
            st.markdown(f'<div class="ds-manual-group"><h3>{escape(label)}</h3>'
                        f'<span>{len(group)} documento{"s" if len(group) != 1 else ""}</span></div>',
                        unsafe_allow_html=True)
            ordered = sorted(group, key=lambda manual: {"original": 0, "guide": 1, "support": 2}.get(manual["role"], 3))
            for start in range(0, len(ordered), 2):
                for column, manual in zip(st.columns(2, gap="medium"), ordered[start:start + 2]):
                    with column:
                        render_manual_card(manual)
        st.caption("Os documentos têm cópia verificada no portal. Os conteúdos da Wiki Saúde são identificados com a data em que a cópia em PDF foi salva.")


def visible_updates(snapshot):
    return [event for event in recent_updates(merge_updates(snapshot.get("updates", []),
                    st.session_state.get("forced_live_updates", []))) if event.get("system_key") != "cnes_base"]


def update_items(updates):
    items = []
    for event in updates:
        source_note = " · catálogo comunitário" if event.get("catalog_source") == "community" else ""
        items.append(
            '<div class="ds-update-item">'
            f'<strong>{escape(str(event.get("system", "Sistema")))}</strong>'
            f'<span>{escape(str(event.get("name", "Nova versão")))}{source_note}</span>'
            f'<time title="Data da descoberta">{escape(update_day(event.get("found_at")))}</time></div>'
        )
    return "".join(items)


def render_masthead(snapshot):
    updated_at = (snapshot.get("last_check") or {}).get("completed_at") or snapshot.get("updated_at")
    checked = readable_date(updated_at).removesuffix(" (horário de Brasília)")
    updates = visible_updates(snapshot)
    news = update_items(updates[:1]) if updates else '<p class="ds-news-empty">Nenhuma nova versão identificada nos últimos 7 dias.</p>'
    more = f'<span class="ds-news-more">+ {len(updates) - 1} aviso(s) · veja os detalhes abaixo</span>' if len(updates) > 1 else ""
    st.markdown(
        '<header class="ds-masthead"><div class="ds-masthead-brand">'
        '<h1>Downloads Sistemas</h1><p>Instaladores, tabelas e manuais dos sistemas do SUS.</p></div>'
        f'<div class="ds-masthead-check">{ui_icon("clock")}<div><span>Última verificação</span>'
        f'<strong>{escape(checked)}</strong><small>Horário de Brasília · a cada 2 horas</small></div></div>'
        f'<div class="ds-masthead-news">{ui_icon("megaphone")}<div>'
        '<div class="ds-news-heading"><strong>Novidades dos sistemas</strong><span>Avisos por 7 dias</span></div>'
        f'{news}{more}</div></div></header>', unsafe_allow_html=True,
    )
    if updates:
        count = len(updates)
        with st.expander(f"Últimas atualizações · {count} aviso{'s' if count != 1 else ''} nos últimos 7 dias", expanded=False):
            st.caption("Cada aviso permanece disponível por 7 dias a partir da primeira identificação da versão.")
            st.markdown('<div class="ds-update-list">' + update_items(updates) + '</div>', unsafe_allow_html=True)


def render_force_check(snapshot):
    checked_at = st.session_state.get("forced_live_checked_at")
    if checked_at:
        st.caption(f"Última verificação manual, sem cache: {readable_date(checked_at)}")
    with st.container(key="focus_force_check"):
        if st.button("Verificar todos os sistemas", icon=":material/sync:", key="force_catalog_check",
                     type="primary", width="stretch", help="Consulta agora todos os catálogos. A atualização automática a cada duas horas continua ativa."):
            force_check_all_systems(snapshot.get("systems", {}))
            st.rerun()


@st.fragment(run_every="60s")
def refresh_catalog_when_changed(rendered_version, rendered_notice, rendered_updates):
    # Recarrega a página quando o catálogo, o aviso de consulta ou a janela de novidades muda.
    # A consulta às fontes continua sendo executada pela automação, não por visitante.
    current = load_snapshot()
    current_updates = tuple(event["id"] for event in visible_updates(current))
    if (catalog_revision(current) != rendered_version or verification_notice(current) != rendered_notice
            or current_updates != rendered_updates):
        st.rerun()


snapshot = load_snapshot()
forced_at = st.session_state.get("forced_live_checked_at")
automatic_check = snapshot.get("last_check") or {}
if forced_at and automatic_check.get("source") == "automatic" and str(automatic_check.get("completed_at", "")) > forced_at:
    for field in ["forced_live_catalogs", "forced_live_checked_at", "forced_live_updates"]:
        st.session_state.pop(field, None)
refresh_catalog_when_changed(catalog_revision(snapshot), verification_notice(snapshot),
                             tuple(event["id"] for event in visible_updates(snapshot)))
systems = snapshot.get("systems", {}) if isinstance(snapshot.get("systems"), dict) else {}
render_masthead(snapshot)
notice = verification_notice(snapshot)
if notice:
    st.warning(notice)

render_force_check(snapshot)
programs_tab, tables_tab, manuals_tab = st.tabs(["Programas e instaladores", "Tabelas e bases", "Manuais"])
with programs_tab:
    render_programs(systems)
with tables_tab:
    render_tables(systems)
with manuals_tab:
    render_manuals()

st.markdown('<footer class="ds-footer"><strong>Downloads Sistemas</strong>'
            '<span>Central de acesso aos arquivos dos sistemas de informação do SUS</span>'
            '<span>Consulta programada a cada 2 horas, incluindo 06:50 · Horário de Brasília</span></footer>',
            unsafe_allow_html=True)

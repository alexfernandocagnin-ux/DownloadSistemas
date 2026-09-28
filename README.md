# DownloadSistemas

Portal Streamlit que confere as versões oficiais do BPA Magnético, do SIA, da
tabela mensal BDSIA, do SIHD2, do CNES e do SIGTAP no site do Ministério
(`sia.datasus.gov.br`, `sihd.datasus.gov.br`, `cnes.datasus.gov.br`,
`sigtap.datasus.gov.br`) e oferece o download direto — mesmo quando esses
sites estão fora do ar, o que acontece com frequência.

## Como funciona

- **A cada visita**, o app tenta confirmar ao vivo a versão mais recente de
  cada sistema (consulta com cache de 15 minutos). Se a consulta falhar,
  mostra o último snapshot salvo em `data/catalog.json` e avisa que não deu
  para confirmar naquele momento.
- **O botão de download nunca depende do Ministério estar respondendo na
  hora do clique.** Sempre que o espelho já foi publicado (GitHub Releases,
  atualizado pelo workflow diário), o botão baixa de lá. Enquanto um arquivo
  ainda não tem espelho publicado, o app baixa ao vivo do DATASUS sob
  demanda (clique em "Preparar download") e guarda na sessão.
- Nada é executado: os `.exe` só são lidos como bytes, com validação de
  domínio/host e do cabeçalho `MZ` antes de aceitar qualquer arquivo (mesmo
  padrão de segurança usado no BPA Novo, em `catalogs/_common.py`).

## Sistemas cobertos

| Sistema | Fonte oficial | Natureza |
|---|---|---|
| BPA Magnético | `sia.datasus.gov.br/versao/listar_ftp_bpa.php` | instalador, versão única |
| SIA | `sia.datasus.gov.br/versao/listar_ftp_sia.php` | instalador, versão única |
| SIHD2 | `sihd.datasus.gov.br/versao/versao_sihd2.php` | instalador, versão única |
| CNES · SCNES (atualização) | API JSON por trás de `cnes.datasus.gov.br/pages/downloads/aplicativos.jsp` | instalador, versão única |
| BDSIA (tabela mensal do SIA) | mesma página do SIA | por competência (seletor de mês) |
| SIGTAP · Tabela Unificada | RSS de `sigtap.datasus.gov.br/tabela-unificada/competencias.rss` | por competência (seletor de mês) |
| CNES · Base de dados mensal | API JSON por trás de `cnes.datasus.gov.br/pages/downloads/arquivosBaseDados.jsp` | por competência (seletor de mês) |

**Fora do escopo por enquanto:** os arquivos `DSIHD017_<UF>_<competência>.ZIP`
do SIHD2 (dados mensais por estado, usados durante a importação de AIH) e as
variantes "SCNES Simplificado" do CNES — modalidades com mais arquivos por
competência/versão. Podem entrar depois como um seletor extra dentro do
cartão de cada sistema.

## Estrutura

- `catalogs/` — leitura e validação das páginas/FTP/API oficiais (sem
  executar nada); `_common.py` tem o parser HTML e as checagens de host/
  tamanho/assinatura (`MZ` ou `PK`) compartilhadas pelos módulos por sistema.
- `scripts/sync_catalog.py` — roda no cron do GitHub Actions: confere as
  sete fontes, baixa o que mudou para `dist/` e atualiza
  `data/catalog.json`. O workflow sobe cada arquivo de `dist/` como asset de
  uma GitHub Release (`bpa-latest`, `sia-latest`, `sihd2-latest`,
  `cnes-app-latest`, `bdsia-<competência>`, `sigtap-<competência>`,
  `cnes-base-<competência>`) e só comita o catálogo quando algo muda.
- `app.py` — a tela do portal.

## Executar localmente

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Para atualizar o catálogo manualmente (sem publicar Release, só para testar
os parsers):

```powershell
.\.venv\Scripts\python.exe scripts\sync_catalog.py
```

## Site acordado

O workflow `.github/workflows/keep-awake.yml` abre o app a cada 6 horas e
clica em *Yes, get this app back up!* quando o Streamlit Cloud o colocou para
dormir, igual ao BPA Novo. Configure a URL publicada em `DOWNLOAD_APP_URL`
(secret ou variável do repositório) depois do primeiro deploy.

## Testes

```powershell
.\.venv\Scripts\python.exe -m unittest test_catalogs.py -v
```

Os testes usam HTML/FTP simulados — não acessam a rede.

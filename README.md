# DownloadSistemas

Portal Streamlit que confere as versões oficiais do BPA Magnético, do SIA, da
tabela mensal BDSIA, do SIHD2, do CNES e do SIGTAP no site do Ministério
(`sia.datasus.gov.br`, `sihd.datasus.gov.br`, `cnes.datasus.gov.br`,
`sigtap.datasus.gov.br`) e oferece o download direto — mesmo quando esses
sites estão fora do ar, o que acontece com frequência.

## Como funciona

- O portal abre pelo catálogo salvo, sem esperar o DATASUS. A consulta oficial é opcional e tem cache de 15 minutos.
- A cada 6 horas, o GitHub Actions tenta obter as versões oficiais, publicar os arquivos e confirmar que cada asset existe e tem o tamanho esperado. Só depois atualiza o catálogo. Downloads ou uploads que falharem preservam a cópia anterior.
- Os instaladores e os seis meses recentes de cada tabela são espelhados. Competências já salvas permanecem disponíveis.
- O usuário prepara o arquivo e baixa dentro do portal. O servidor verifica se o espelho entrega o arquivo esperado e confere assinatura e tamanho, lendo apenas dois bytes. O arquivo é entregue diretamente pelo espelho, sem ocupar a memória do Streamlit. O SHA-256 é registrado na publicação. Se o espelho falhar, tenta a fonte oficial. Uma página de erro nunca é oferecida como instalador.
- As versões e revisões anteriores continuam acessíveis quando uma versão oficial nova ainda não foi espelhada.
- Nenhum instalador é executado. Arquivos ainda sem espelho dependem da fonte oficial. O GitHub e o Streamlit também podem sofrer indisponibilidades; o serviço não promete disponibilidade absoluta.

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
- `scripts/sync_catalog.py` — roda no cron do GitHub Actions com `--publish`: confere as
  sete fontes, baixa o que mudou para `dist/`, publica e verifica os assets antes de atualizar
  `data/catalog.json`. O script sobe cada arquivo de `dist/` como asset de
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
.\.venv\Scripts\python.exe -m unittest discover -v
```

Os testes usam HTML/FTP simulados — não acessam a rede.

## Publicação e recuperação

O workflow de sincronização executa automaticamente após mudanças nos scripts e a cada 6 horas. Também pode ser acionado manualmente na aba Actions. Precisa de permissão `contents: write`, já declarada no workflow. Os arquivos ficam em Releases públicas do repositório.

Para publicar manualmente, autentique o GitHub CLI (`gh auth login`), defina `GITHUB_REPOSITORY=alexfernandocagnin-ux/DownloadSistemas` e execute `python scripts/sync_catalog.py --publish`. Sem `--publish`, os arquivos são apenas preparados localmente e novos links de espelho não são inventados.

Links legados são novamente conferidos na sincronização. Assets ausentes são baixados e publicados de novo. `last_success_at` informa a última consulta bem-sucedida; `checked_at` registra a tentativa mais recente. Cada espelho novo registra tamanho, SHA-256 e data de verificação.

Os downloads CNES usam os diretórios oficiais `/cnes/Versoes-Fces-Nacional` e `/cnes` nos servidores `arpoador.datasus.gov.br` e `ftp.datasus.gov.br`, contornando o servlet de estatísticas quando indisponível. O catálogo também consulta esses diretórios se a API cair.

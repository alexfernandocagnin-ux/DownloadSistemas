# DownloadSistemas

Portal Streamlit que confere as versões oficiais do BPA Magnético, do SIA, da
FPO Magnética, da tabela mensal BDSIA, do SIHD2, do CNES e do SIGTAP no site
do Ministério
(`sia.datasus.gov.br`, `sihd.datasus.gov.br`, `cnes.datasus.gov.br`,
`sigtap.datasus.gov.br`) e oferece o download direto — mesmo quando esses
sites estão fora do ar, o que acontece com frequência.

## Como funciona

- O portal abre pelo catálogo salvo, sem esperar o DATASUS. **Verificar todos os sistemas** consulta, sob demanda e sem cache, os dez catálogos oficiais em paralelo; uma fonte indisponível não bloqueia as outras.
- A cada 6 horas, o GitHub Actions tenta obter as versões oficiais, publicar os arquivos e confirmar que cada asset existe e tem o tamanho esperado. Só depois atualiza o catálogo. Downloads ou uploads que falharem preservam a cópia anterior.
- Quando uma versão muda em relação a uma já conhecida, essa sincronização registra sistema, arquivo e data em um histórico persistente que aparece no quadro **Novidades dos sistemas** para todos os visitantes. A primeira coleta de um sistema serve como referência e não é anunciada como novidade.
- A tabela **Últimos lançamentos** mostra a versão mais recente de cada sistema. A data só aparece quando o catálogo oficial informa a publicação do arquivo; quando a fonte não oferece esse dado, a célula fica vazia.
- Os instaladores e os seis meses recentes de cada tabela são espelhados. Na primeira sincronização de uma tabela, a competência atual tem prioridade; o histórico entra nas próximas execuções. Competências já salvas permanecem disponíveis.
- O usuário prepara o arquivo e baixa dentro do portal. O servidor verifica se o espelho entrega o arquivo esperado e confere assinatura e tamanho, lendo apenas dois bytes. O arquivo é entregue diretamente pelo espelho, sem ocupar a memória do Streamlit. O SHA-256 é registrado na publicação. Se o espelho falhar, tenta a fonte oficial. Uma página de erro nunca é oferecida como instalador.
- As versões e revisões anteriores continuam acessíveis quando uma versão oficial nova ainda não foi espelhada.
- Nenhum instalador é executado. Arquivos ainda sem espelho dependem da fonte oficial. O GitHub e o Streamlit também podem sofrer indisponibilidades; o serviço não promete disponibilidade absoluta.

## Sistemas cobertos

| Sistema | Fonte oficial | Natureza |
|---|---|---|
| BPA Magnético | `sia.datasus.gov.br/versao/listar_ftp_bpa.php` | instalador, versão única |
| SIA | `sia.datasus.gov.br/versao/listar_ftp_sia.php` | instalador, versão única |
| FPO Magnético | `sia.datasus.gov.br/versao/listar_ftp_fpo.php` | instalador inicial e atualização mais recente |
| SIHD2 | `sihd.datasus.gov.br/versao/versao_sihd2.php` | instalador, versão única |
| CNES · SCNES (atualização) | API JSON por trás de `cnes.datasus.gov.br/pages/downloads/aplicativos.jsp` | instalador, versão única |
| BDSIA (tabela mensal do SIA) | mesma página do SIA | por competência (seletor de mês) |
| SIGTAP · Tabela Unificada | RSS de `sigtap.datasus.gov.br/tabela-unificada/competencias.rss` | por competência (seletor de mês) |
| CNES · Base de dados mensal | API JSON por trás de `cnes.datasus.gov.br/pages/downloads/arquivosBaseDados.jsp` | por competência (seletor de mês) |

Se a listagem HTTPS da FPO não responder, o sincronizador consulta o diretório
FTP oficial `/siasus/FPO` e continua validando os nomes e os arquivos antes de
publicá-los no espelho.

**Fora do escopo por enquanto:** os arquivos `DSIHD017_<UF>_<competência>.ZIP`
do SIHD2 (dados mensais por estado, usados durante a importação de AIH) e as
variantes "SCNES Simplificado" do CNES — modalidades com mais arquivos por
competência/versão. Podem entrar depois como um seletor extra dentro do
cartão de cada sistema.

## Estrutura

- `catalogs/` — leitura e validação das páginas/FTP/API oficiais (sem
  executar nada); `_common.py` tem o parser HTML e as checagens de host/
  tamanho/assinatura (`MZ` ou `PK`) compartilhadas pelos módulos por sistema.
- `scripts/sync_catalog.py` — roda no cron do GitHub Actions com `--publish`: confere os
  catálogos, baixa o que mudou para `dist/`, publica e verifica os assets antes de atualizar
  `data/catalog.json`. O script sobe cada arquivo de `dist/` como asset de
  uma GitHub Release (`bpa-latest`, `sia-latest`, `fpo-installer-latest`,
  `fpo-update-latest`, `sihd2-latest`, `cnes-app-latest`, `cnes-complete-latest`,
  `bdsia-<competência>`, `sigtap-<competência>`,
  `cnes-base-<competência>`) e só comita o catálogo quando algo muda.
- `app.py` - a tela do portal.
- `catalogs/updates.py` - deduplicação e retenção do histórico de novidades exibido no portal.

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

## Despertar periódico do portal

O workflow existente `.github/workflows/keep-awake.yml` visita o app com Chromium
sem tela às 00:23, 06:23, 12:23 e 18:23 UTC. Também pode ser executado por
**Actions → Acordar portal periodicamente → Run workflow**.
Configure `DOWNLOAD_APP_URL` em **Settings → Secrets and variables → Actions → Variables**.
Sem essa variável, usa `https://downloadsistemas.streamlit.app/`.

O navegador procura o botão *Yes, get this app back up!* na página e nos iframes
e clica quando necessário. Confirma o título real do portal, `Downloads Sistemas`,
antes de registrar sucesso. Exceções do Streamlit, falhas de navegação e tempo
esgotado produzem erro e execução vermelha no Actions. A navegação tem limite de
90 segundos; após ela, o portal tem até 240 segundos para carregar. A execução
completa tem limite de 10 minutos e não se sobrepõe a outra do mesmo workflow.

Isso não desativa a suspensão do Community Cloud: é uma tentativa periódica de
acordar o app. O agendamento do GitHub pode atrasar; indisponibilidade, mudança
na tela de suspensão ou no título do portal podem exigir manutenção. Em repositórios
públicos, o GitHub pode desativar agendamentos após 60 dias sem atividade.

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

Bases CNES atuais ultrapassam 700 MB. O espelho aceita pacotes CNES até 1 GB e entrega arquivos grandes diretamente pelo GitHub. Bases ainda sem espelho não são carregadas na memória do Streamlit; aguardam sincronização ou podem ser obtidas pelo portal oficial.

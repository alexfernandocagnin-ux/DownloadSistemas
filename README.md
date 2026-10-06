# DownloadSistemas

Portal Streamlit que confere as versões oficiais do BPA Magnético, do SIA, da
FPO Magnética, da tabela mensal BDSIA, do SIHD2, do CNES e do SIGTAP no site
do Ministério
(`sia.datasus.gov.br`, `sihd.datasus.gov.br`, `cnes.datasus.gov.br`,
`sigtap.datasus.gov.br`) e oferece o download direto — mesmo quando esses
sites estão fora do ar, o que acontece com frequência.

## Como funciona

- O portal abre pelo catálogo salvo e pelo histórico completo. A consulta de versões é automática, sem intervenção dos visitantes. O botão **Verificar todos os sistemas** permite antecipar uma consulta a qualquer momento. As descobertas são registradas no GitHub antes dos downloads grandes.
- A cada 2 horas, às 00:50, 02:50, 04:50, **06:50** e assim por diante no horário de Brasília, o GitHub Actions consulta as versões e tenta publicar os arquivos. O agendamento usa UTC e pode atrasar conforme a disponibilidade do GitHub. A descoberta é publicada em uma etapa própria, antes dos downloads grandes. A última versão encontrada é salva mesmo se o download falhar. O link do espelho só muda após a confirmação do asset; falhas preservam a cópia anterior.
- Quando uma versão muda em relação a uma já conhecida, essa sincronização registra sistema, arquivo e data em um histórico persistente que aparece no quadro **Novidades dos sistemas** para todos os visitantes durante sete dias após a descoberta. O histórico permanece salvo após esse prazo. A primeira coleta de um sistema serve como referência e não é anunciada como novidade.
- A tabela **Últimos lançamentos** mostra a versão mais recente de cada sistema e se existe uma cópia disponível. A data só aparece quando o catálogo oficial informa a publicação do arquivo; quando a fonte não oferece esse dado, a célula fica vazia. Na FPO, a atualização atual fica no cartão principal e o instalador base está no expansor de primeira instalação.
- Não há corte de seis meses: todas as competências encontradas ficam no seletor ao abrir o site, mesmo que sua cópia ainda não esteja no espelho. Arquivos pequenos podem ser preparados na fonte oficial. O espelho amplia o histórico a cada execução, priorizando os meses recentes e tentando até 16 novos pacotes por tabela dentro de um orçamento de oito minutos. Arquivos históricos com falha são tentados novamente após 24 horas; a competência mais recente é tentada em toda execução. Esse lote limita o trabalho da execução, não as competências disponíveis. Cópias já salvas permanecem disponíveis.
- Ao preparar um arquivo de até 50 MB, o servidor baixa a cópia completa e verifica assinatura, tamanho e SHA-256 registrado, antes de oferecer o download dentro do portal. Pacotes maiores têm assinatura e tamanho conferidos por uma leitura parcial e são entregues diretamente pelo espelho. Se o espelho falhar, tenta a fonte oficial. Uma página de erro nunca é oferecida como instalador.
- As versões e revisões anteriores continuam acessíveis quando uma versão oficial nova ainda não foi espelhada.
- Nenhum instalador é executado. Arquivos ainda sem espelho dependem da fonte oficial. O GitHub e o Streamlit também podem sofrer indisponibilidades; o serviço não promete disponibilidade absoluta.

## Sistemas cobertos

| Sistema | Fonte oficial | Natureza |
|---|---|---|
| BPA Magnético | `sia.datasus.gov.br/versao/listar_ftp_bpa.php` | instalador, versão única |
| APAC Magnético | `sia.datasus.gov.br/versao/listar_ftp_apac.php` | instalador, versão única |
| CIHA02 | `ciha.saude.gov.br/versao/versao_ciha2.php` | atualização e instalação inicial separadas |
| SIA | `sia.datasus.gov.br/versao/listar_ftp_sia.php` | instalador, versão única |
| FPO Magnético | `sia.datasus.gov.br/versao/listar_ftp_fpo.php` | instalador inicial e atualização mais recente |
| SIHD2 | `sihd.datasus.gov.br/versao/versao_sihd2.php` | instalador, versão única |
| CNES · SCNES (atualização) | API JSON por trás de `cnes.datasus.gov.br/pages/downloads/aplicativos.jsp` | instalador, versão única |
| BDSIA (tabela mensal do SIA) | mesma página do SIA | por competência (seletor de mês) |
| SIGTAP · Tabela Unificada | RSS de `sigtap.datasus.gov.br/tabela-unificada/competencias.rss` | por competência (seletor de mês) |
| CNES · SCNES completo | mesma API de aplicativos CNES | instalação completa, versão única |

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
  catálogos e salva a última versão encontrada em `data/catalog.json`. Baixa o que mudou
  para `dist/`, publica e verifica os assets antes de atualizar os links de download.
  O script sobe cada arquivo de `dist/` como asset de
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

Os testes usam HTML/FTP simulados - não acessam a rede.

Para conferir os downloads reais, incluindo o conteúdo completo dos pacotes grandes:

```powershell
.\.venv\Scripts\python.exe scripts\audit_downloads.py --full --output dist\download-audit.json
```

A auditoria não executa instaladores. Compara tamanho e SHA-256 dos espelhos e,
nos arquivos pequenos encontrados no catálogo atual, compara também com a origem.
O relatório identifica a fonte utilizada, inclusive o apoio comunitário do SIGTAP.
Sem `--full`, pacotes acima de 50 MB recebem apenas uma verificação parcial.
O comando retorna erro se houver arquivo inválido, catálogo inacessível ou uma
versão atual sem espelho.

## Publicação e recuperação

O workflow de sincronização executa automaticamente após mudanças nos scripts e a cada 2 horas, incluindo 06:50 no horário de Brasília. Também pode ser acionado manualmente na aba Actions. Precisa de permissão `contents: write`, já declarada no workflow. Os arquivos ficam em Releases públicas do repositório.

O menu do portal usa `toolbarMode = "minimal"`. Isso simplifica a interface, mas não substitui permissões: o painel **Manage app** pertence ao Streamlit Community Cloud. Somente contas com acesso de desenvolvedor podem reiniciar ou excluir o app; visitantes comuns não recebem essas permissões. Uma senha dentro do portal não controla esse painel externo.

Para publicar manualmente, autentique o GitHub CLI (`gh auth login`), defina `GITHUB_REPOSITORY=alexfernandocagnin-ux/DownloadSistemas` e execute `python scripts/sync_catalog.py --publish`. Sem `--publish`, os arquivos são apenas preparados localmente e novos links de espelho não são inventados.

Links legados são novamente conferidos na sincronização. Assets ausentes são baixados e publicados de novo. `catalog_checked_at` registra a consulta que identificou `latest`; `current` preserva o arquivo publicado e `pending_download` indica uma publicação pendente. `checked_at` registra a tentativa mais recente. Cada espelho novo registra tamanho, SHA-256 e data de verificação.

Os downloads CNES usam os diretórios oficiais `/cnes/Versoes-Fces-Nacional` e `/cnes` nos servidores `arpoador.datasus.gov.br` e `ftp.datasus.gov.br`, contornando o servlet de estatísticas quando indisponível. O catálogo também consulta esses diretórios se a API cair.

A base de dados mensal CNES foi retirada do portal e não é mais consultada ou baixada pela automação. Seu histórico já salvo é preservado no catálogo. Os instaladores SCNES completo e atualização continuam sendo consultados e espelhados normalmente.


## Revisão de confiabilidade — 01/10/2026

A publicação do catálogo usa `scripts/publish_catalog.py`: lê a revisão atual do GitHub, combina versões e cópias confirmadas e atualiza apenas `data/catalog.json`. Conflitos de gravação são repetidos com a nova revisão, sem rebase dos arquivos de código. Os downloads HTTP/FTP conferem o tamanho anunciado; ZIPs também precisam apresentar uma estrutura de arquivo válida. Fontes vazias tentam as alternativas oficiais disponíveis.

Detalhes da revisão, evidências e limites em `AUDITORIA-2026-10-01.md`.


## Atualização automática — revisão de 06/10/2026

A consulta e a preparação dos espelhos executam em jobs independentes, com filas separadas. Uma cópia lenta não bloqueia a próxima consulta programada. A consulta salva as versões e o resultado no GitHub antes de iniciar os espelhos; a preparação lê esse catálogo com `--publish --mirror-only`, sem alterar o horário da consulta nem refazer a descoberta.

`last_check.completed_at` registra quando a última consulta terminou, incluindo a consulta pelo botão. `last_check.succeeded`, `total` e `failed_systems` distinguem sucesso, resposta parcial e falha total. `updated_at` e `catalog_checked_at` só avançam após uma consulta bem-sucedida; a falha de um download não indica falha na consulta. Se todas as fontes falharem, a execução sinaliza erro e ainda publica o resultado e preserva os arquivos anteriores.

O portal consulta o catálogo público do GitHub com cache compartilhado de 60 segundos e preserva o arquivo local como alternativa. Páginas abertas conferem a revisão completa a cada minuto, incluindo novos espelhos que tenham o mesmo horário de descoberta. Isso evita depender de um reinício do Streamlit para receber dados publicados. Falhas na leitura remota mantêm o catálogo local; consultas locais pelo botão preservam versões mais recentes durante a combinação com o catálogo publicado. A persistência externa das consultas automáticas continua sendo responsabilidade do GitHub Actions; o botão grava o resultado no servidor Streamlit.

Downloads HTTP/FTP agora têm um limite total de cinco minutos por servidor, além do limite de espera da conexão. O agendamento permanece a cada duas horas, incluindo 06:50 em Brasília. Atrasos do agendador do GitHub continuam possíveis; o portal avisa quando a última verificação tem mais de três horas ou quando alguma fonte não respondeu.

Evidências e validação em `AUDITORIA-ATUALIZACAO-2026-10-06.md`.

# Revisão de confiabilidade — 01/10/2026

Revisados: aplicação Streamlit, módulos de catálogo, comparação e persistência de versões, downloads, espelhos, avisos de sete dias, sincronização, publicação, auditoria de arquivos, acordador, configurações e testes. Diretórios gerados, ambiente virtual e executáveis não fazem parte da revisão de código.

## Problemas confirmados e corrigidos

| Falha | Correção |
| --- | --- |
| Atualização do catálogo entrava em conflito com alterações no Git, interrompendo a sincronização. | Publicação isolada do JSON pela API do GitHub, combinando dados da revisão atual e repetindo conflitos de gravação. |
| Download encerrado antes do tamanho anunciado podia ser aceito. | Conferência de Content-Length no HTTP e SIZE no FTP quando fornecidos pelo servidor, além dos limites de tamanho. |
| ZIP com início PK, mas sem estrutura completa, podia ser aceito. | Validação do diretório do ZIP antes de liberar/publicar o pacote. |
| Uma primeira resposta FTP inválida impedia tentar outro servidor. | Resposta inválida agora permite tentar o próximo servidor oficial configurado. |
| Página/API vazia ou inacessível podia impedir consulta embora o FTP funcionasse. | Recuperação pelo FTP nos casos tratados de BPA, APAC, SIA/BDSIA, CNES e CIHA. |
| Competência do SIHD podia prevalecer sobre o número da versão. | Para instaladores, a comparação prioriza a versão; para tabelas mensais, a competência continua prioritária. |
| Uma versão cancelada do SIHD podia ser recuperada do catálogo anterior. | O catálogo transmite cancelamentos, e a combinação de dados exclui as versões retiradas. |
| Consulta antiga de uma sessão podia esconder uma versão mais nova salva por outra consulta. | Cartões e tabela combinam o resultado da sessão com as versões atualmente salvas. |
| Falha do espelho de pacote grande do CNES deixava o usuário sem alternativa. | Oferta de tentativa na fonte oficial, sem carregar o pacote grande no servidor Streamlit. |
| Feed SIGTAP gzip podia expandir muito além do limite de entrada. | Limite aplicado também ao conteúdo descompactado e recuperação de gzip interrompido. |
| Data global da rotina podia parecer uma consulta bem-sucedida após falhas. | Data global baseada nas consultas registradas, preservando a referência anterior quando não há nova confirmação. |

## Validação

- 85 testes passaram na suíte Python, incluindo os cenários de regressão desta revisão.
- Conferência real de assinatura e tamanho dos 13 arquivos atuais publicados: APAC, CIHA02 atualização/instalação, BPA, SIA, FPO instalador/atualização, SIHD2, CNES atualização/completo/base e BDSIA/SIGTAP. Todos responderam sem erro nesta conferência.
- Relatório local da conferência: `dist/audit-current-published.json`.
- Execução anterior da sincronização identificada com falha na etapa de publicação do catálogo; consulta de versões e testes haviam concluído. O novo publicador trata esse cenário.
- `git diff --check` sem erros.

## Limites da verificação

A conferência real acima leu assinatura e tamanho; não baixou novamente todo o histórico nem recalculou o SHA-256 de todos os arquivos grandes. ZIPs são verificados estruturalmente, sem descompactar todos os membros para testar CRC. Nenhum instalador foi executado.

DATASUS, GitHub e Streamlit continuam sendo dependências externas. Arquivos históricos sem espelho dependem da fonte oficial, e o agendamento do GitHub pode sofrer atrasos. Descobertas feitas pelo botão são salvas no servidor; a persistência externa continua a cargo da rotina automática. Uma recriação do servidor antes dessa rotina pode perder uma descoberta manual ainda não registrada no GitHub.

Uma revisão e testes não constituem garantia de ausência de falhas. Esta revisão registra os problemas reproduzidos, as correções e o alcance da validação.

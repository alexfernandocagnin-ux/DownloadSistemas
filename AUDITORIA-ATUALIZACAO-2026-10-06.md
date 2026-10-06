# Revisão da atualização automática — 06/10/2026

## Falhas verificadas

- As sete últimas sincronizações falharam por timeout na preparação dos espelhos, depois de 35 minutos. A descoberta e a publicação inicial do catálogo tinham concluído com sucesso. Exemplo: [execução 37494584321](https://github.com/alexfernandocagnin-ux/DownloadSistemas/actions/runs/37494584321).
- As bases mensais CNES, retiradas da interface, ainda eram consultadas e baixadas. Pacotes de aproximadamente 739 MB continuavam ocupando o sincronizador.
- Downloads tinham timeout de inatividade da conexão, mas uma transferência lenta contínua podia prolongar a execução indefinidamente.
- Arquivos históricos indisponíveis consumiam o mesmo lote em toda execução, atrasando o espelhamento de outras competências.
- A página só conferia `updated_at`; uma nova cópia publicada sem nova descoberta podia ficar invisível em uma página aberta.
- O portal dependia da cópia do catálogo no checkout do Streamlit para receber atualizações publicadas.
- A primeira sincronização sem nenhuma fonte disponível podia gravar o horário atual como se o catálogo tivesse sido confirmado.

## Correções

1. Jobs e filas separados para descobrir versões e preparar cópias. A preparação lê o catálogo publicado (`--mirror-only`) e preserva o horário e o resultado da consulta.
2. Bases mensais CNES desativadas na automação; histórico preservado. SCNES completo e atualização continuam ativos.
3. Prazo total de cinco minutos por transferência HTTP/FTP, além do timeout da conexão. O lote de espelhamento mensal deixa de iniciar arquivos após oito minutos ou 16 novas tentativas. Isso não restringe a idade dos arquivos oferecidos pelo portal.
4. Falhas históricas têm uma pausa de 24 horas por arquivo. A competência mais recente é tentada em todas as execuções. A tentativa é salva imediatamente, mesmo quando o download falha.
5. Resultado persistente da última consulta (`last_check`) com horário, total de fontes e fontes que falharam. O horário de confirmação de versões não avança por causa de uma falha ou de uma publicação de espelho.
6. Leitura do catálogo público do GitHub com cache compartilhado de um minuto e alternativa local. Combinação preserva versões mais recentes, revisões, cópias verificadas, cancelamentos e pausas de repetição.
7. Revisão completa do catálogo para atualizar páginas abertas, inclusive novos espelhos. Avisos de verificação parcial ou com atraso também acompanham o estado atual.
8. Botão de verificação preservado. Registra o horário da tentativa e os resultados no servidor Streamlit. Uma consulta automática posterior substitui o estado de consulta manual antigo da sessão.

## Validação

- Suíte existente: 95 testes aprovados.
- Regressões adicionais: falha total e parcial das fontes, primeira coleta sem resposta, preservação de datas no job de cópias, base CNES desativada, prazos HTTP/FTP, pausa de arquivos históricos, prioridade do mês atual, preservação do índice completo, gravação de tentativas, catálogo remoto indisponível/malformado, publicação sem reinício, combinações concorrentes e funcionamento do botão.
- A execução real após a publicação é conferida no GitHub Actions e no portal.

## Limites mantidos explícitos

O cron permanece a cada duas horas, incluindo 06:50 em Brasília. O [GitHub documenta possíveis atrasos ou descarte de agendamentos](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows). Não há promessa de execução no segundo exato. O portal avisa após três horas sem verificação.

Fontes oficiais, GitHub e Streamlit podem falhar. As cópias já confirmadas são preservadas e a consulta registra respostas parciais. O botão grava no servidor do Streamlit; a automação é responsável pela persistência externa no GitHub. Os avisos de novidades continuam disponíveis por sete dias.

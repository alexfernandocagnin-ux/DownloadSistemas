# Aparência anterior à modernização

Backup de app.py e .streamlit/config.toml criado em 06/10/2026, antes do novo design.

Para restaurar a aparência anterior, na raiz do projeto:

```powershell
Copy-Item -LiteralPath 'backups/interface-2026-10-06-modernizacao/app.py' -Destination 'app.py'
Copy-Item -LiteralPath 'backups/interface-2026-10-06-modernizacao/config.toml' -Destination '.streamlit/config.toml'
```

Os arquivos auxiliares do novo design podem permanecer; a versão anterior não os utiliza.
Revise e publique as alterações para restaurar também o site online.
A revisão de referência está marcada no Git como backup/interface-antes-redesign-2026-10-06.

# AutoTask — SQL Operations Portfolio

Versão demonstrativa de portfólio de uma aplicação web para execução **controlada e somente leitura** de consultas SQL em múltiplas instâncias PostgreSQL e Oracle.

> **Aviso:** este repositório é uma implementação demonstrativa/reconstruída para portfólio. Não contém código-fonte proprietário, credenciais, dados reais, endereços internos ou informações confidenciais de empregadores anteriores. Hosts, usuários, bancos e exemplos são fictícios.

## Funcionalidades

- Interface web com Flask
- Autenticação de usuário
- Suporte a PostgreSQL e Oracle
- Execução paralela em múltiplas instâncias
- Validação de SQL com foco em operações de leitura
- Bloqueio de comandos de escrita/DDL perigosos
- Consolidação de resultados e erros por instância
- Exportação dos resultados
- Histórico local de consultas no navegador
- Configuração externa de instâncias e credenciais

## Arquitetura

`Usuário → Flask → Validação SQL → Pool de execução → PostgreSQL/Oracle → Consolidação → Interface/Exportação`

## Tecnologias

Python, Flask, psycopg2, python-oracledb, Gunicorn e HTML/CSS/JavaScript.

## Executando localmente

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

Copie `.env.example` para `.env` e defina valores locais. Edite `config.json` e `lojas.json` apenas com ambientes nos quais você tenha autorização.

```bash
python app.py
```

## Segurança

- `.env`, ambientes virtuais, logs e caches não são versionados.
- Nunca publique senhas reais em `config.json` ou outros arquivos.
- O projeto foi desenhado para consultas de leitura, mas deve ser usado somente em bancos e infraestruturas autorizados.
- Para produção, recomenda-se um gerenciador de segredos e credenciais de banco com privilégio mínimo/read-only.

## Autor

Gabriel Munhoz — projeto demonstrativo de portfólio.

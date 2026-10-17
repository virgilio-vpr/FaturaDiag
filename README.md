# FaturaDiag

Plataforma de diagnóstico energético de faturas do Grupo A. A IA extrai dados dos documentos; o motor determinístico calcula; o profissional revisa e valida os resultados.

O MVP prioriza unidades A4 e AS e faturas de ENEL, EDP, CPFL e Elektro. Consulte [PROJECT_SPEC.md](PROJECT_SPEC.md) antes de implementar tarefas: ele define regras de domínio, arquitetura, convenções e critérios de aceite.

## Desenvolvimento

Requisitos iniciais: Python 3.12+, `uv`, GNU Make e Docker Compose.

```sh
cd backend
uv sync
cd ..
make check
make up
curl http://localhost:8000/health
```

Com os catálogos semeados e o CSV da ANEEL na raiz do projeto, importe as tarifas com:

```sh
make import-tariffs
```

O importador aceita também um caminho explícito e registra um relatório de importação:
`cd backend && uv run python -m app.scripts.import_tariffs /caminho/para/arquivo.csv`.

O tracker de implementação está na seção 16.0 da especificação. O ambiente Compose usa RustFS como storage compatível com S3; o frontend atual é temporário e será substituído pelo scaffold React/TypeScript na T-9.1.
# FaturaDiag
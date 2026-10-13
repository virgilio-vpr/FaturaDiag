# Changelog

## Unreleased

- Inicializada a estrutura do repositório e as ferramentas de qualidade da T-0.1.
- Adicionado ambiente Docker Compose de desenvolvimento com PostgreSQL, RustFS, backend e frontend provisório; healthchecks e smoke HTTP da pilha passaram.
- Adicionadas configuração FastAPI, readiness DB/storage, CORS, request ID e respostas de erro RFC 9457.
- Migrados os testes HTTP para HTTPX ASGITransport, removendo o uso deprecado do Starlette TestClient.
- Adicionado workflow de CI com PostgreSQL, migrações Alembic e gates de lint, tipos, dependências e testes do backend.

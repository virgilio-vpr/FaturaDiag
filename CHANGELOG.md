# Changelog

## Unreleased

- Inicializada a estrutura do repositório e as ferramentas de qualidade da T-0.1.
- Adicionado ambiente Docker Compose de desenvolvimento com PostgreSQL, RustFS, backend e frontend provisório; healthchecks e smoke HTTP da pilha passaram.
- Adicionadas configuração FastAPI, readiness DB/storage, CORS, request ID e respostas de erro RFC 9457.
- Migrados os testes HTTP para HTTPX ASGITransport, removendo o uso deprecado do Starlette TestClient.
- Adicionado workflow de CI com PostgreSQL, migrações Alembic e gates de lint, tipos, dependências e testes do backend.
- Corrigido o diretório de execução da migração Alembic no CI para carregar `backend/alembic.ini`.
- Implementada autenticação com Argon2, JWT de acesso e refresh rotativo, logout revogável, rate limit, bloqueio progressivo e validação de segredo em produção; adicionada migração e testes de integração.
- Adicionado RBAC via `requer_papel(...)` e `BaseRepository` com `organizacao_id` obrigatório, filtros tenant-scoped em leitura e validação de tenant na escrita.
- Adicionado `make seed` idempotente para organização demo e ADMIN; exige `SEED_ADMIN_PASSWORD` no ambiente e recusa reassociar usuários existentes entre tenants.
- Adicionados testes de isolamento por tenant nas rotas autenticadas existentes: perfil restrito à identidade do token, logout sem revogar sessão de outra organização e validação do vínculo usuário/sessão.
- Adicionados catálogos globais de distribuidoras prioritárias e feriados nacionais, com janelas de ponta pendentes de validação e seed idempotente; calendário via `holidays` (MIT).
- Adicionado serviço reutilizável de auditoria transacional com snapshots JSONB, validação de tenant/ator e redação de credenciais; migração converte a estrutura anterior de `audit_log`.
- Adicionado CRUD de clientes tenant-scoped com busca, cursor, soft delete, unicidade de CNPJ por organização e eventos de auditoria; criada a migração da tabela `cliente`.
- Adicionados cadastros tenant-scoped de unidades consumidoras e contratos de demanda, com validações de modalidade/subgrupo/AS, constraints de domínio no PostgreSQL e eventos de auditoria; criada a migração `unidade_consumidora`/`contrato_demanda`.
- Adicionados modelos e migração para tarifas versionadas, bandeiras tarifárias, parâmetros regulatórios e hints versionados por distribuidora.
- Adicionado importador idempotente do CSV de tarifas de aplicação da ANEEL para distribuidoras prioritárias, com filtros explícitos, relatório de conflitos e comando `make import-tariffs`.
- Adicionado resolvedor de tarifas por distribuidora, subgrupo, modalidade, posto, componente e data, respeitando vigência semiaberta e reportando ausência ou ambiguidade.
- Adicionado seed versionado dos parâmetros regulatórios, API administrativa restrita a ADMIN, carregador com vigência/cache e objeto de domínio imutável que expõe parâmetros pendentes de validação.
- Adicionada gestão administrativa de hints por distribuidora, com atualização auditada, versionamento por vigência, resolução histórica semiaberta e indicação de fallback quando não há hint específico.
- Adicionados tipos, enums, arredondamento `ROUND_HALF_UP` e `trace` imutável do motor de cálculo (T-4.1).
- Adicionado cálculo de demanda faturável e ultrapassagem (Verde e Azul) no motor, com casos dourados G-01, G-02a/b, G-13 e G-14 e `trace` (T-4.2).

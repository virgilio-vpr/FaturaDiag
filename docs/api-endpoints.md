# API FaturaDiag — guia de endpoints para testes

Base: `/api/v1`. Autenticação: `Authorization: Bearer <access_token>` (exceto `/auth/login` e `/auth/refresh`).
Erros: `application/problem+json` (RFC 9457). Valores monetários e decimais trafegam como **string** (`"12.34"`); float é rejeitado.

## Onde está a documentação interativa

- **Swagger UI:** `http://localhost:8000/docs` (com a API rodando; permite autenticar e disparar requisições).
- **ReDoc:** `http://localhost:8000/redoc`.
- **OpenAPI JSON (versionado):** [frontend/openapi.json](../frontend/openapi.json); regenerar com `make types`.
- Especificação funcional dos endpoints: `PROJECT_SPEC.md` §9.1.

Subir a API: `make up` (Docker) e `make migrate`, `make seed` (exige `SEED_ADMIN_PASSWORD`).

## Papéis

ADMIN ⊇ ANALISTA. CLIENTE só lê (faturas e diagnósticos/relatórios **PUBLICADOS** da própria organização). Todo acesso é isolado por organização (outra organização → 404).

## Endpoints

| Método | Rota | Papéis | Observações |
|---|---|---|---|
| POST | `/auth/login` | público | e-mail/senha → access + refresh token |
| POST | `/auth/refresh` | público | refresh rotativo |
| POST | `/auth/logout` | autenticado | revoga a sessão |
| GET | `/auth/me` | autenticado | perfil |
| GET/POST | `/clientes` | ADMIN, ANALISTA | listar/criar |
| GET/PATCH/DELETE | `/clientes/{cliente_id}` | ADMIN, ANALISTA | DELETE = soft delete |
| GET/POST | `/clientes/{cliente_id}/unidades` | ADMIN, ANALISTA | unidades consumidoras |
| GET/PATCH | `/unidades/{unidade_id}` | ADMIN, ANALISTA | mudar subgrupo/tipo_rede invalida diagnósticos |
| GET/POST | `/unidades/{unidade_id}/contratos` | ADMIN, ANALISTA | contratos de demanda; vigência sobreposta invalida diagnósticos |
| GET/PUT | `/admin/parametros` | ADMIN | parâmetros regulatórios versionados |
| GET/PUT | `/admin/hints` | ADMIN | hints de extração por distribuidora |
| POST | `/admin/hints/{distribuidora_id}/versionar` | ADMIN | nova versão de hint |
| POST | `/faturas` | ADMIN, ANALISTA | upload multipart (PDF/imagem); aceita `Idempotency-Key` |
| GET | `/faturas` | + CLIENTE | listagem |
| GET | `/faturas/{fatura_id}` | + CLIENTE | detalhe |
| GET | `/faturas/{fatura_id}/arquivo` | + CLIENTE | arquivo original |
| PUT | `/faturas/{fatura_id}/dados` | ADMIN, ANALISTA | revisão manual dos dados extraídos |
| POST | `/faturas/{fatura_id}/validar` | ADMIN, ANALISTA | → VALIDADA |
| POST | `/faturas/{fatura_id}/reextrair` | ADMIN, ANALISTA | nova extração |
| POST | `/unidades/{uc_id}/medicoes` | ADMIN, ANALISTA | upload CSV/XLSX de memória de massa |
| GET | `/unidades/{uc_id}/medicoes/resumo` | ADMIN, ANALISTA | resumo da medição |
| POST | `/diagnosticos` | ADMIN, ANALISTA | `Idempotency-Key`; só faturas VALIDADA/DIAGNOSTICADA; 422 com pendências se faltar dado; 409 fatura não validada |
| GET | `/diagnosticos/{id}` | + CLIENTE (publicados) | achados, simulações, fontes e pendências |
| PATCH | `/diagnosticos/{id}` | ADMIN, ANALISTA | `{"notas": "..."}` |
| POST | `/diagnosticos/{id}/revisar` | ADMIN, ANALISTA | → REVISADO; 409 se STALE |
| POST | `/diagnosticos/{id}/simulacoes-acl` | ADMIN, ANALISTA | persiste simulação ACL (um registro por cenário) |
| POST | `/simulacoes/demanda` | ADMIN, ANALISTA | simulação sem persistir |
| POST | `/simulacoes/acl` | ADMIN, ANALISTA | simulação sem persistir |
| POST | `/diagnosticos/{id}/relatorio` | ADMIN, ANALISTA | 202; gera nova versão do PDF; 409 se STALE |
| GET | `/relatorios/{id}/download` | + CLIENTE (publicados) | `application/pdf` |

## Fluxo de teste ponta a ponta

1. `POST /auth/login` → token.
2. `POST /clientes` → `POST /clientes/{id}/unidades` → `POST /unidades/{id}/contratos`.
3. Pré-requisitos globais: parâmetros (`PUT /admin/parametros`) e tarifas (`make import-tariffs`).
4. `POST /faturas` (≈12 meses para diagnóstico de histórico) → `PUT .../dados` se necessário → `POST .../validar`.
5. `POST /diagnosticos` (`{"uc_id","escopo":"HISTORICO","periodo_inicio","periodo_fim"}`) → `GET /diagnosticos/{id}`.
6. Opcional: `POST /diagnosticos/{id}/simulacoes-acl`, `PATCH` (notas), `POST .../revisar`.
7. `POST /diagnosticos/{id}/relatorio` → `GET /relatorios/{id}/download`.

Exemplo de corpo ACL (`/simulacoes/acl`):

```json
{
  "entrada": {"consumo_mwh_mes": "100", "te_cativa_rs_mwh": "300", "encargos_rs_mwh": "20", "custos_fixos_mes": "1000"},
  "cenarios": [{"nome": "conservador", "preco_rs_mwh": "280"}, {"nome": "base", "preco_rs_mwh": "230"}]
}
```

## Lacunas conhecidas (não bloqueiam os testes, mas importam)

- **Não há endpoint para publicar um diagnóstico** (status PUBLICADO) nem para criar usuários CLIENTE; hoje o CLIENTE nunca enxerga diagnósticos/relatórios pela API. Não consta em T-7.2/T-8.3; precisa de decisão (sugiro tarefa própria).
- Endpoints de organização (logo, cor, responsável técnico) ainda não existem (`modules/organizacoes` vazio); só via banco.
- Parâmetros regulatórios marcados VALIDAR (D-10) seguem pendentes: resultados são indicativos.

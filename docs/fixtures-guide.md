# Guia de fixtures de faturas

Fixtures de extração ficam em `backend/tests/fixtures/` e **nunca** contêm faturas reais.

## Estrutura

```text
backend/tests/fixtures/
├── faturas/<sigla>/<caso>.json   # texto da fatura (linhas) + valores esperados
└── llm/<sigla>__<caso>.json      # erros gravados do LLM por variante (com_hint / sem_hint)
```

- `<sigla>` em minúsculas, igual ao hint (`enel_sp`, `edp_sp`, `cpfl_paulista`, `elektro`, …).
- `linhas`: texto que vira um PDF nativo sintético durante a avaliação.
- `esperado`: valores corretos por campo de `FaturaExtraida` (alíquotas em %, como impresso;
  `null` quando o campo não existe). Os itens vão em `itens`.
- `llm/...`: ajustes aplicados sobre `esperado` para simular erros do LLM. `com_hint` e `sem_hint`
  permitem medir o ganho do hint específico. Vazio (`{}`) significa resposta perfeita.

## Anonimização (obrigatória antes de versionar)

| Dado | Substituir por |
|---|---|
| Razão social / nome | nome fictício (`EMPRESA FICTICIA ... LTDA`) |
| CNPJ / CPF | número fictício com dígitos válidos e prefixo `00.000.000/` |
| Código da UC, instalação, medidor | código fictício |
| Endereço, CEP, telefone, e-mail | removidos ou fictícios |
| Código de barras / linha digitável / chave de acesso | removidos |
| Valores e quantidades | podem ser reais; se a fatura identificar o cliente, alterar proporcionalmente |

Mantenha a **estrutura e a nomenclatura** da distribuidora (rótulos, blocos), pois são elas que o hint e
a checagem cruzada exercitam. Revise o JSON final procurando qualquer dado pessoal remanescente.

## Como adicionar um caso

1. Crie `faturas/<sigla>/caso_NN.json` com `descricao` contendo a palavra `SINTÉTICA` (ou
   `ANONIMIZADA` quando partir de fatura real) e os campos `linhas` e `esperado`.
2. Crie `llm/<sigla>__caso_NN.json` (opcional) com os erros esperados por variante.
3. Garanta que os totais dos itens somem `valor_total`, para não gerar alertas bloqueantes.
4. Rode `make eval-extraction`.

## Avaliação

- `make eval-extraction`: acurácia por campo, distribuidora e hint usado, custo e latência, usando
  respostas gravadas (sem rede). A meta do hint específico é **≥ 5 p.p.** sobre o genérico.
- `uv run python -m app.scripts.eval_extraction --live`: usa o provedor do `.env`; **gera custo**
  e deve ser executado manualmente, nunca em CI.
- `--exigir-meta` faz o comando falhar se o ganho ficar abaixo da meta.

> As fixtures atuais são **sintéticas**: validam o harness, mas **não medem acurácia real**.
> A medição real depende das amostras anonimizadas fornecidas pelo responsável (D-11).

# Hint: elektro

## Particularidades do layout
- Distribuidora: Elektro (UF SP e MG).
- Os itens de cobrança usam o "CCI" (Código de Classificação do Item). Extraia o CCI de cada item de cobrança e inclua-o ao final da `descricao`, no formato `[CCI: <código>]`, quando estiver impresso.
- O horário de ponta é variável. Extraia o horário informado no documento e registre em `observacoes_extrator`; não assuma um padrão.

## Nomenclatura específica
- "CCI" → código do item; use-o para ajudar a classificar `categoria`, sem substituir a leitura da descrição.
- "Demanda Contratada" / "Demanda Medida" → `demanda_contratada_*` / `demanda_medida_*`.

## Cuidados
- Se um item de cobrança não tiver CCI visível, transcreva a descrição normalmente e não invente o código.
- Não calcule nem corrija valores; transcreva como impresso.
- Hint baseado apenas na especificação; confirme com faturas reais anonimizadas.

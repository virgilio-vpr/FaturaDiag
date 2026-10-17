# Hint: enel_rj

## Particularidades do layout
- Distribuidora: Enel Distribuição Rio (UF RJ).
- Layout similar ao da Enel SP, com pequenas variações. Procure o bloco "GRANDEZAS MEDIDAS" ou equivalente para demandas, consumos e reativos.
- O horário de ponta desta distribuidora não está validado neste hint. Extraia o que o documento informar e registre em `observacoes_extrator`.
- O campo "AGRUPAMENTO" pode indicar várias UCs faturadas em conjunto; transcreva o texto em `observacoes_extrator`.

## Nomenclatura específica
- "GRANDEZAS MEDIDAS" (ou bloco equivalente) → `demanda_medida_*`, `consumo_*`, `reativo_*`.
- "Demanda Contratada" / "Demanda Medida" → `demanda_contratada_*` / `demanda_medida_*`.

## Cuidados
- Se o bloco de grandezas medidas não aparecer, localize os valores pelo significado, não pela posição.
- Não calcule nem corrija valores; transcreva como impresso.
- Hint baseado apenas na especificação; confirme com faturas reais anonimizadas.

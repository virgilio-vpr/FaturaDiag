# Hint: enel_sp

## Particularidades do layout
- Distribuidora: Enel Distribuição São Paulo (UF SP).
- A fatura traz um bloco intitulado "GRANDEZAS MEDIDAS", onde ficam as demandas e os consumos por posto horário. Procure ali as leituras de demanda medida, consumo e energia reativa.
- Horário de ponta informado pela distribuidora: 18h às 21h. Registre em `observacoes_extrator` se o documento indicar outro horário.
- Os percentuais de perdas de transformação, quando impressos, costumam ser 0% ou 2,5%. Transcreva o que estiver impresso; não infira.
- O campo "AGRUPAMENTO" pode indicar que várias UCs são faturadas em conjunto. Transcreva o texto em `observacoes_extrator`.

## Nomenclatura específica
- "GRANDEZAS MEDIDAS" → bloco de onde saem `demanda_medida_*`, `consumo_*` e `reativo_*`.
- "Demanda Contratada" / "Demanda Medida" → `demanda_contratada_*` / `demanda_medida_*`, separadas por posto Ponta e Fora Ponta (Azul) ou única (Verde).
- "Energia Reativa Excedente" / "Demanda Reativa Excedente" → categorias `ENERGIA_REATIVA_EXCEDENTE` / `DEMANDA_REATIVA_EXCEDENTE`.

## Cuidados
- Não confunda demanda medida com demanda contratada nem com demanda faturada.
- Não calcule nem corrija valores; transcreva como impresso.
- Este hint reflete apenas o que consta na especificação do projeto. Confirme com faturas reais anonimizadas antes de tratar como definitivo.

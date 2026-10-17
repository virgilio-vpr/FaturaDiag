# Hint: cpfl_paulista

## Particularidades do layout
- Distribuidora: CPFL Paulista (UF SP).
- A apresentação de tarifas e itens pode variar entre faturas. Algumas faturas seguem o modelo "Preço", com valores unitários que já embutem os tributos. Quando isso ocorrer, registre em `observacoes_extrator` que o modelo é "Preço".
- O horário de ponta não está validado neste hint. Extraia o que o documento informar.

## Nomenclatura específica
- "Demanda Contratada" / "Demanda Medida" → `demanda_contratada_*` / `demanda_medida_*`.
- Itens de energia com tarifa unitária → `tarifa_unitaria` exatamente como impresso, sem remover nem adicionar tributos.

## Cuidados
- No modelo "Preço", a tarifa unitária impressa inclui tributos. Transcreva sem ajustar; o ajuste é feito depois, fora do extrator.
- Não calcule nem corrija valores; transcreva como impresso.
- Hint baseado apenas na especificação; confirme com faturas reais anonimizadas.

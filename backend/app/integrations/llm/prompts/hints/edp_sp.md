# Hint: edp_sp

## Particularidades do layout
- Distribuidora: EDP São Paulo (UF SP).
- Os blocos de demanda e de consumo aparecem separados. Leia cada um no seu bloco e não misture as grandezas.
- Horário de ponta informado pela distribuidora: 17h30 às 20h30. Se o documento indicar horário diferente, registre em `observacoes_extrator`.

## Nomenclatura específica
- Bloco de demanda → `demanda_contratada_*` e `demanda_medida_*` por posto.
- Bloco de consumo → `consumo_ponta_kwh` e `consumo_fora_ponta_kwh`.
- Linhas de energia reativa excedente → categoria `ENERGIA_REATIVA_EXCEDENTE`; reativa de demanda → `DEMANDA_REATIVA_EXCEDENTE`.

## Cuidados
- Não confunda demanda (kW) com consumo (kWh).
- Não calcule nem corrija valores; transcreva como impresso.
- Hint baseado apenas na especificação; confirme com faturas reais anonimizadas.

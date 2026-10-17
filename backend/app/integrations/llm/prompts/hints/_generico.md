# Hint: _generico

## Particularidades do layout
- Distribuidora sem hint específico. O layout é desconhecido; a ANEEL padroniza o conteúdo da fatura, não o posicionamento.
- Localize cada campo pelo significado, não pela posição na página.
- O horário de ponta varia por distribuidora. Extraia o horário impresso, se houver, e registre em `observacoes_extrator`.

## Nomenclatura específica
- "Demanda Contratada", "Demanda Medida", "Demanda Registrada" → `demanda_contratada_*` / `demanda_medida_*`, por posto Ponta e Fora Ponta (Azul) ou única (Verde).
- "Consumo", "Energia Ativa" → `consumo_ponta_kwh` / `consumo_fora_ponta_kwh`.
- "Energia Reativa Excedente" / "Demanda Reativa Excedente" → categorias de reativo excedente.

## Cuidados
- Atenção às unidades (kW, kWh, kvarh) e converta quando necessário, registrando em `observacoes_extrator`.
- Não calcule nem corrija valores; transcreva como impresso.
- A acurácia sem hint específico tende a ser menor; confianças baixas devem ser preservadas, não infladas.

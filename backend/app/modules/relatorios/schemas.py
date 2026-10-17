from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class RelatorioResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    diagnostico_id: UUID
    versao: int
    template: str
    gerado_por: UUID | None
    gerado_em: datetime
    download_url: str

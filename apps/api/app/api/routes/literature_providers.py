"""Read-only adapter capabilities, protected by the installation owner session."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.deps import AuthContext, current_context
from app.core.config import get_settings
from app.services.literature_capabilities import (
    ConfigurationStatus,
    ImplementationStatus,
    ProviderKind,
    provider_directory,
)

router = APIRouter(prefix="/literature", tags=["literature"])


class LiteratureProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider_key: str
    label: str
    kind: ProviderKind
    implementation_status: ImplementationStatus
    configuration_status: ConfigurationStatus
    connectivity_status: Literal["not_tested"]
    capabilities: list[str]
    entrypoint: str | None
    description: str


class LiteratureProvidersOut(BaseModel):
    providers: list[LiteratureProviderOut]


@router.get("/providers", response_model=LiteratureProvidersOut)
def providers(_: AuthContext = Depends(current_context)) -> LiteratureProvidersOut:
    return LiteratureProvidersOut(providers=[
        LiteratureProviderOut.model_validate(item) for item in provider_directory(get_settings())
    ])

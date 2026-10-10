"""Owner-only deployment status. Secret values are never returned."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import AuthContext, csrf_context, current_context
from app.core.config import get_settings
from app.db import get_db
from app.domain.skill_discovery import (
    SkillDiscoveryCapabilityOut,
    SkillDiscoveryOut,
    SkillDiscoveryRequest,
)
from app.services import skill_discovery
from app.services.configuration import ConfigurationReport, configuration_report, database_check

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/configuration", response_model=ConfigurationReport)
def get_configuration(
    context: AuthContext = Depends(current_context),
    db: Session = Depends(get_db),
) -> ConfigurationReport:
    return configuration_report(get_settings(), database_check(db.connection()))


@router.get("/skills/capability", response_model=SkillDiscoveryCapabilityOut)
def get_skill_discovery_capability(
    context: AuthContext = Depends(current_context),
) -> SkillDiscoveryCapabilityOut:
    return skill_discovery.capability()


@router.post("/skills/discover", response_model=SkillDiscoveryOut)
async def discover_skills(
    request: SkillDiscoveryRequest, context: AuthContext = Depends(csrf_context)
) -> SkillDiscoveryOut:
    return await skill_discovery.discover(request)

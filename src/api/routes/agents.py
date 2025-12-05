"""Agent API Routes"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.agents.manager import AgentManager
from src.agents.models import AgentCapability, AgentStatus

router = APIRouter()


class CreateAgentRequest(BaseModel):
    """Request to create a new agent"""
    name: str = Field(..., min_length=2, max_length=100)
    email: str = Field(..., pattern=r"^[\w\.-]+@[\w\.-]+\.\w+$")
    capabilities: list[str] = Field(..., min_length=1)
    persona_description: Optional[str] = None
    hourly_rate: float = Field(default=25.0, ge=10, le=500)
    timezone: str = Field(default="UTC")


class UpdateAgentRequest(BaseModel):
    """Request to update an agent"""
    name: Optional[str] = None
    hourly_rate: Optional[float] = None
    status: Optional[str] = None
    status_reason: Optional[str] = None


class AgentResponse(BaseModel):
    """Agent response model"""
    id: str
    name: str
    email: str
    status: str
    capabilities: list[str]
    hourly_rate: float
    success_rate: float
    total_earnings: float
    jobs_completed: int


@router.post("/", response_model=AgentResponse)
async def create_agent(
    request: CreateAgentRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new agent"""
    manager = AgentManager(db)

    # Convert capability strings to enums
    try:
        capabilities = [AgentCapability(c) for c in request.capabilities]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Invalid capability: {e}")

    agent = await manager.create_agent(
        name=request.name,
        email=request.email,
        capabilities=capabilities,
        persona_description=request.persona_description,
        hourly_rate=request.hourly_rate,
        timezone=request.timezone,
    )

    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        email=agent.email,
        status=agent.status.value,
        capabilities=agent.capabilities,
        hourly_rate=float(agent.hourly_rate),
        success_rate=float(agent.success_rate),
        total_earnings=float(agent.total_earnings),
        jobs_completed=agent.jobs_completed,
    )


@router.get("/", response_model=list[AgentResponse])
async def list_agents(
    status: Optional[str] = None,
    capability: Optional[str] = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List all agents"""
    manager = AgentManager(db)

    agent_status = AgentStatus(status) if status else None
    agent_capability = AgentCapability(capability) if capability else None

    agents = await manager.get_all_agents(
        status=agent_status,
        capability=agent_capability,
        limit=limit,
        offset=offset,
    )

    return [
        AgentResponse(
            id=str(agent.id),
            name=agent.name,
            email=agent.email,
            status=agent.status.value,
            capabilities=agent.capabilities,
            hourly_rate=float(agent.hourly_rate),
            success_rate=float(agent.success_rate),
            total_earnings=float(agent.total_earnings),
            jobs_completed=agent.jobs_completed,
        )
        for agent in agents
    ]


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific agent"""
    manager = AgentManager(db)

    try:
        agent = await manager.get_agent(agent_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Agent not found")

    return AgentResponse(
        id=str(agent.id),
        name=agent.name,
        email=agent.email,
        status=agent.status.value,
        capabilities=agent.capabilities,
        hourly_rate=float(agent.hourly_rate),
        success_rate=float(agent.success_rate),
        total_earnings=float(agent.total_earnings),
        jobs_completed=agent.jobs_completed,
    )


@router.get("/{agent_id}/stats")
async def get_agent_stats(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed agent statistics"""
    manager = AgentManager(db)
    return await manager.get_agent_stats(agent_id)


@router.patch("/{agent_id}")
async def update_agent(
    agent_id: UUID,
    request: UpdateAgentRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update an agent"""
    manager = AgentManager(db)

    if request.status:
        agent = await manager.update_agent_status(
            agent_id,
            AgentStatus(request.status),
            request.status_reason,
        )
        return {"success": True, "agent_id": str(agent.id)}

    return {"success": True}


@router.get("/fleet/summary")
async def get_fleet_summary(
    db: AsyncSession = Depends(get_db),
):
    """Get summary of entire agent fleet"""
    manager = AgentManager(db)
    return await manager.get_fleet_summary()

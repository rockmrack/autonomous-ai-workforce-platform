"""
AI Workforce Platform - Command Line Interface
"""

import asyncio
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="workforce",
    help="AI Workforce Platform CLI",
    add_completion=False,
)
console = Console()


@app.command()
def start(
    host: str = typer.Option("0.0.0.0", help="Host to bind to"),
    port: int = typer.Option(8000, help="Port to bind to"),
    workers: int = typer.Option(4, help="Number of workers"),
    reload: bool = typer.Option(False, help="Enable auto-reload"),
):
    """Start the API server"""
    import uvicorn

    console.print(f"[green]Starting AI Workforce Platform on {host}:{port}[/green]")

    uvicorn.run(
        "src.api.main:app",
        host=host,
        port=port,
        workers=workers if not reload else 1,
        reload=reload,
    )


@app.command()
def init_db():
    """Initialize the database"""
    from src.core.database import init_db as _init_db

    async def run():
        console.print("[yellow]Initializing database...[/yellow]")
        await _init_db()
        console.print("[green]Database initialized successfully![/green]")

    asyncio.run(run())


@app.command()
def create_agent(
    name: str = typer.Option(..., prompt=True, help="Agent name"),
    email: str = typer.Option(..., prompt=True, help="Agent email"),
    capabilities: str = typer.Option(
        "content_writing",
        prompt=True,
        help="Comma-separated capabilities",
    ),
):
    """Create a new agent"""
    from decimal import Decimal
    from src.agents.manager import AgentManager
    from src.agents.models import AgentCapability
    from src.core.database import init_db as _init_db

    async def run():
        await _init_db()
        manager = AgentManager()

        caps = [AgentCapability(c.strip()) for c in capabilities.split(",")]

        agent = await manager.create_agent(
            name=name,
            email=email,
            capabilities=caps,
            hourly_rate=Decimal("25.00"),
        )

        console.print(f"[green]Agent created: {agent.id}[/green]")
        console.print(f"Name: {agent.name}")
        console.print(f"Email: {agent.email}")
        console.print(f"Capabilities: {agent.capabilities}")

    asyncio.run(run())


@app.command()
def list_agents():
    """List all agents"""
    from src.agents.manager import AgentManager
    from src.core.database import init_db as _init_db

    async def run():
        await _init_db()
        manager = AgentManager()
        agents = await manager.get_all_agents()

        table = Table(title="Agents")
        table.add_column("ID", style="dim")
        table.add_column("Name")
        table.add_column("Status")
        table.add_column("Jobs")
        table.add_column("Earnings")
        table.add_column("Success Rate")

        for agent in agents:
            table.add_row(
                str(agent.id)[:8],
                agent.name,
                agent.status.value,
                str(agent.jobs_completed),
                f"${agent.total_earnings:,.2f}",
                f"{agent.success_rate:.1%}",
            )

        console.print(table)

    asyncio.run(run())


@app.command()
def scan_jobs(
    platform: Optional[str] = typer.Option(None, help="Specific platform to scan"),
):
    """Scan for new jobs"""
    from src.discovery.scanner import JobScanner
    from src.core.database import init_db as _init_db

    async def run():
        await _init_db()
        scanner = JobScanner()

        console.print("[yellow]Scanning for jobs...[/yellow]")
        jobs = await scanner.scan_all_platforms()

        console.print(f"[green]Found {len(jobs)} new jobs[/green]")

        if jobs:
            table = Table(title="Discovered Jobs")
            table.add_column("Platform")
            table.add_column("Title", max_width=40)
            table.add_column("Budget")
            table.add_column("Score")

            for job in jobs[:20]:  # Show first 20
                table.add_row(
                    job.platform,
                    job.title[:40],
                    job.budget_display,
                    f"{job.score:.2f}" if job.score else "N/A",
                )

            console.print(table)

    asyncio.run(run())


@app.command()
def status():
    """Show system status"""
    from src.orchestration.scheduler import workforce_scheduler
    from src.core.database import db_manager
    from src.core.cache import cache_manager
    from src.core.database import init_db as _init_db

    async def run():
        await _init_db()
        await cache_manager.initialize()

        db_health = await db_manager.health_check()
        cache_health = await cache_manager.health_check()
        scheduler_status = await workforce_scheduler.get_status()

        console.print("\n[bold]System Status[/bold]\n")

        # Database
        db_status = "[green]✓ Healthy[/green]" if db_health.get("healthy") else "[red]✗ Unhealthy[/red]"
        console.print(f"Database: {db_status}")

        # Cache
        cache_status = "[green]✓ Healthy[/green]" if cache_health.get("healthy") else "[red]✗ Unhealthy[/red]"
        console.print(f"Cache: {cache_status}")

        # Scheduler
        sched_status = "[green]✓ Running[/green]" if scheduler_status.get("is_running") else "[yellow]○ Stopped[/yellow]"
        console.print(f"Scheduler: {sched_status}")

        # Queues
        console.print(f"Job Queue: {scheduler_status.get('job_queue_size', 0)} items")

        await cache_manager.close()

    asyncio.run(run())


@app.command()
def generate_proposal(
    job_id: str = typer.Argument(..., help="Job ID to generate proposal for"),
    agent_id: str = typer.Argument(..., help="Agent ID to generate proposal as"),
):
    """Generate a proposal for a job"""
    from uuid import UUID
    from sqlalchemy import select
    from src.bidding.proposal_generator import ProposalGenerator
    from src.discovery.models import DiscoveredJob
    from src.agents.models import Agent
    from src.core.database import db_manager, init_db as _init_db

    async def run():
        await _init_db()

        async with db_manager.session() as session:
            # Get job
            result = await session.execute(
                select(DiscoveredJob).where(DiscoveredJob.id == UUID(job_id))
            )
            job = result.scalar_one_or_none()

            if not job:
                console.print("[red]Job not found[/red]")
                return

            # Get agent
            result = await session.execute(
                select(Agent).where(Agent.id == UUID(agent_id))
            )
            agent = result.scalar_one_or_none()

            if not agent:
                console.print("[red]Agent not found[/red]")
                return

        generator = ProposalGenerator()
        proposal = await generator.generate_proposal(job, agent)

        console.print("\n[bold]Generated Proposal[/bold]\n")
        console.print(f"[cyan]Bid:[/cyan] ${proposal.bid_amount:.2f} ({proposal.bid_type})")
        console.print(f"[cyan]Duration:[/cyan] {proposal.estimated_duration}")
        console.print(f"[cyan]Variant:[/cyan] {proposal.variant_id}")
        console.print("\n[cyan]Cover Letter:[/cyan]")
        console.print(proposal.cover_letter)

    asyncio.run(run())


if __name__ == "__main__":
    app()

import os
import asyncio
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import startup
from ansible_runner import AnsibleRunner
from scheduler import Scheduler
from routes.auth_routes import router as auth_router
from routes.instance_routes import router as instance_router
from routes.service_routes import router as service_router
from routes.job_routes import router as job_router
from routes.user_routes import router as user_router
from routes.role_routes import router as role_router
from routes.audit_routes import router as audit_router
from routes.inventory_routes import router as inventory_router
from routes.cost_routes import router as cost_router
from routes.schedule_routes import router as schedule_router
from routes.health_routes import router as health_router
from routes.drift_routes import router as drift_router
from routes.notification_routes import router as notification_router
from routes.preference_routes import router as preference_router
from health_checker import HealthPoller, load_health_configs
from drift_checker import DriftPoller


limiter = Limiter(key_func=get_remote_address)
logger = logging.getLogger(__name__)

COST_REFRESH_INTERVAL = 6 * 60 * 60  # 6 hours in seconds


async def _periodic_cost_refresh(runner):
    """Refresh cost/plans cache every 6 hours."""
    while True:
        await asyncio.sleep(COST_REFRESH_INTERVAL)
        try:
            logger.info("Starting periodic cost/plans cache refresh")
            await runner.refresh_costs()
        except Exception as e:
            logger.error(f"Periodic cost refresh failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    type_configs = await startup.main()
    app.state.ansible_runner = AnsibleRunner()
    app.state.inventory_types = type_configs or []

    # Start background scheduler
    scheduler = Scheduler(app.state.ansible_runner)
    app.state.scheduler = scheduler
    scheduler.start()

    # Start health check poller
    load_health_configs()
    health_poller = HealthPoller()
    app.state.health_poller = health_poller
    health_poller.start()

    # Start drift detection poller
    drift_poller = DriftPoller()
    app.state.drift_poller = drift_poller
    drift_poller.start()

    # Seed plans cache if empty, and start periodic refresh
    from database import SessionLocal, AppMetadata
    session = SessionLocal()
    try:
        plans_cache = AppMetadata.get(session, "plans_cache")
    finally:
        session.close()
    if not plans_cache:
        logger.info("Plans cache empty — triggering initial cost refresh")
        await app.state.ansible_runner.refresh_costs()

    cost_refresh_task = asyncio.create_task(_periodic_cost_refresh(app.state.ansible_runner))

    yield

    # Stop periodic cost refresh
    cost_refresh_task.cancel()
    try:
        await cost_refresh_task
    except asyncio.CancelledError:
        pass

    # Stop drift poller on shutdown
    await drift_poller.stop()

    # Stop health poller on shutdown
    await health_poller.stop()

    # Stop scheduler on shutdown
    await scheduler.stop()


app = FastAPI(lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
if allowed_origins:
    origins = [o.strip() for o in allowed_origins.split(",") if o.strip()]
else:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(instance_router)
app.include_router(service_router)
app.include_router(job_router)
app.include_router(user_router)
app.include_router(role_router)
app.include_router(audit_router)
app.include_router(inventory_router)
app.include_router(cost_router)
app.include_router(schedule_router)
app.include_router(health_router)
app.include_router(drift_router)
app.include_router(notification_router)
app.include_router(preference_router)

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/{full_path:path}")
async def spa_catchall(full_path: str):
    """Serve index.html for client-side routing (React SPA)."""
    static_path = os.path.join("static", full_path)
    if os.path.isfile(static_path):
        return FileResponse(static_path)
    return FileResponse("static/index.html")

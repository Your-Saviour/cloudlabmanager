import os
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
from routes.auth_routes import router as auth_router
from routes.instance_routes import router as instance_router
from routes.service_routes import router as service_router
from routes.job_routes import router as job_router
from routes.user_routes import router as user_router
from routes.role_routes import router as role_router
from routes.audit_routes import router as audit_router
from routes.inventory_routes import router as inventory_router
from routes.cost_routes import router as cost_router


limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    type_configs = await startup.main()
    app.state.ansible_runner = AnsibleRunner()
    app.state.inventory_types = type_configs or []
    yield


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

from fastapi import FastAPI
from contextlib import asynccontextmanager
import startup

@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup.main()    # <-- startup
    yield
    # shutdown code here if you want

app = FastAPI(lifespan=lifespan)


@app.get("/")
async def root():
    return {"message": "Hello World"}


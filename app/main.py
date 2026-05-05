from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.database import engine
from .models import Base
from .routers import batches, invoices, parties, payments, products, templates, reports

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root():
    return {"message": "Welcome to ERB"}


@app.get("/health")
async def health_check():
    return {"status": "healthy"}


app.include_router(parties)
app.include_router(products)
app.include_router(batches)
app.include_router(invoices)
app.include_router(payments)
app.include_router(templates)
app.include_router(reports)

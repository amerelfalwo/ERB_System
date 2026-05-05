from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware

from .core.config import settings
from .core.database import engine
from .core.deps import get_current_user
from .models import Base
from .routers import auth, batches, invoices, parties, payments, products, templates, reports

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


app.include_router(auth)
app.include_router(parties, dependencies=[Depends(get_current_user)])
app.include_router(products, dependencies=[Depends(get_current_user)])
app.include_router(batches, dependencies=[Depends(get_current_user)])
app.include_router(invoices, dependencies=[Depends(get_current_user)])
app.include_router(payments, dependencies=[Depends(get_current_user)])
app.include_router(templates, dependencies=[Depends(get_current_user)])
app.include_router(reports, dependencies=[Depends(get_current_user)])

"""
main.py
───────
Smart Irrigation System – FastAPI application entry point.

FIX: added load_dotenv() so .env file is read before the Supabase
     client is instantiated at module import time.
"""

import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv          # FIX: import dotenv loader

load_dotenv()                           # FIX: load .env before any os.environ reads

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import sensor_routes, irrigation_routes, pot_routes, plant_routes, device_routes
from supabase_client import supabase


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify Supabase connectivity at startup."""
    try:
        supabase.table("plant_types").select("id").limit(1).execute()
        print("✅ Supabase connection verified.")
    except Exception as exc:
        print(f"❌ Supabase connection failed at startup: {exc}")
        raise RuntimeError("Cannot connect to Supabase – check SUPABASE_URL / SUPABASE_KEY") from exc
    yield


app = FastAPI(
    title="Smart Irrigation System",
    description="Backend for ESP32-based automated gardening system",
    version="2.0.0",
    lifespan=lifespan,
)

_raw_origins = os.environ.get("ALLOWED_ORIGINS", "*")
allowed_origins = [o.strip() for o in _raw_origins.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(device_routes.router,     prefix="/devices",    tags=["Devices"])
app.include_router(pot_routes.router,        prefix="/pots",       tags=["Pot Management"])
app.include_router(plant_routes.router,      prefix="/plants",     tags=["Plant Types"])
app.include_router(sensor_routes.router,     prefix="/sensor",     tags=["Sensor Data"])
app.include_router(irrigation_routes.router, prefix="/irrigation", tags=["Irrigation Control"])


@app.get("/", tags=["Meta"])
def root():
    return {"message": "Smart Irrigation Backend Running", "status": "healthy"}


@app.get("/health", tags=["Meta"])
def health_check():
    return {"status": "ok"}

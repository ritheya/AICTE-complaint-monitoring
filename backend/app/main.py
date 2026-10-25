"""
AICTE Complaint Monitor - FastAPI Application Entry Point
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.config import CORS_ORIGINS, ENVIRONMENT, JWT_SECRET_KEY
from backend.app.routers import (
    auth,
    complaints,
    intake,
    institutions,
    overlaps,
    alerts,
    scheduler,
    dashboard
)

app = FastAPI(
    title="AICTE Integrated Institution Complaint Monitoring and Coordination Portal",
    description="Multi-bureau grievance coordination, automated overlap detection, and institutional risk intelligence API.",
    version="1.0.0"
)


@app.on_event("startup")
def validate_production_configuration():
    """
    Startup Security Check:
    Refuses to start with ENVIRONMENT=production if JWT_SECRET equals a demo or default insecure secret.
    """
    env = os.getenv("ENVIRONMENT", "development").lower()
    jwt_secret = os.getenv("JWT_SECRET_KEY", "aicte-secret-key-super-secure-change-in-prod-2026")
    insecure_defaults = [
        "aicte-secret-key-super-secure-change-in-prod-2026",
        "secret",
        "changeme",
        "default",
        "demo"
    ]
    if env == "production" and (jwt_secret in insecure_defaults or len(jwt_secret) < 32):
        raise RuntimeError(
            "FATAL CONFIGURATION ERROR: Cannot start in ENVIRONMENT=production with default or insecure JWT_SECRET_KEY!"
        )

# Restrict CORS to configured frontend origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register route modules
app.include_router(auth.router)
app.include_router(complaints.router)
app.include_router(intake.router)
app.include_router(institutions.router)
app.include_router(overlaps.router)
app.include_router(alerts.router)
app.include_router(scheduler.router)
app.include_router(dashboard.router)


@app.get("/health", tags=["Health"])
def health_check():
    """Service health verification endpoint."""
    return {
        "status": "healthy",
        "service": "AICTE Complaint Coordination Engine",
        "version": "1.0.0"
    }

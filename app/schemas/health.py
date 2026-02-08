"""Pydantic response models for the health check endpoint."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response model for the /health endpoint."""

    status: str
    database: str

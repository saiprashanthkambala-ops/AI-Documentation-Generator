"""
Pydantic schemas for request/response validation.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ProjectUploadResponse(BaseModel):
    """Response after uploading a ZIP file."""
    id: int
    name: str
    upload_date: datetime
    file_count: int
    file_list: str
    status: str
    message: str


class ProjectSummary(BaseModel):
    """Project summary for history list."""
    id: int
    name: str
    upload_date: datetime
    file_count: int
    status: str
    has_documentation: bool

    class Config:
        from_attributes = True


class ProjectDetail(BaseModel):
    """Full project with generated documentation."""
    id: int
    name: str
    upload_date: datetime
    file_count: int
    file_list: str
    status: str
    generated_documentation: str

    class Config:
        from_attributes = True


class GenerateResponse(BaseModel):
    """Response after generating documentation."""
    id: int
    name: str
    status: str
    message: str
    generated_documentation: str
    word_count: int = 0
    section_count: int = 0


class HealthResponse(BaseModel):
    """Health check response."""
    status: str
    app_name: str
    version: str


class GeminiStatusResponse(BaseModel):
    """Gemini connection status."""
    connected: bool
    model: str
    message: str


class MessageResponse(BaseModel):
    """Simple message response."""
    message: str

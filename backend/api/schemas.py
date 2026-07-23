from pydantic import BaseModel, UUID4
from datetime import datetime
from typing import Optional

class DocumentResponse(BaseModel):
    id: UUID4
    source_type: str
    title: Optional[str]
    summary: Optional[str]
    category: Optional[str]
    processing_status: str
    created_at: datetime
    tags: list[str] = []
    projects: list[str] = []
    model_config = {"from_attributes": True}

class ProjectResponse(BaseModel):
    id: UUID4
    name: str
    description: Optional[str]
    status: str
    created_at: datetime
    document_count: int = 0
    model_config = {"from_attributes": True}

class IngestTextRequest(BaseModel):
    text: str

class IngestUrlRequest(BaseModel):
    url: str

class ProcessingResult(BaseModel):
    status: str  # completed | pending_confirmation | failed
    doc_id: Optional[str]
    message: str

class SearchResult(BaseModel):
    doc_id: str
    title: Optional[str]
    summary: Optional[str]
    score: float
    source_type: str
    created_at: datetime

class MindmapNode(BaseModel):
    id: str
    title: Optional[str]
    source_type: str
    category: Optional[str]

class MindmapEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    score: float

class MindmapResponse(BaseModel):
    center_node: MindmapNode
    nodes: list[MindmapNode]
    edges: list[MindmapEdge]

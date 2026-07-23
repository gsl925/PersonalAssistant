"""Qdrant vector store wrapper for the Personal AI Assistant knowledge layer.

Provides async helpers for collection management, document upsert,
semantic search, and point-level CRUD on top of the qdrant-client library.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from loguru import logger
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)


class KnowledgeQdrantClient:
    """Thin async-friendly wrapper around the synchronous QdrantClient.

    The underlying qdrant-client library exposes both sync and async surfaces;
    we use the sync client wrapped in executor calls so callers can ``await``
    every method without blocking the event loop.

    Parameters
    ----------
    host:
        Hostname or IP of the Qdrant service.
    port:
        gRPC/HTTP port of the Qdrant service (default 6333).
    """

    COLLECTION_NAME: str = "documents"
    VECTOR_SIZE: int = 1024  # bge-m3 output dim

    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._client: QdrantClient | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self) -> QdrantClient:
        """Return (lazily creating) the underlying QdrantClient."""
        if self._client is None:
            logger.debug(
                "Connecting to Qdrant at {}:{}", self._host, self._port
            )
            self._client = QdrantClient(host=self._host, port=self._port)
        return self._client

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def init_collection(self) -> None:
        """Create the document collection if it does not already exist.

        Uses cosine distance and the configured VECTOR_SIZE.  Idempotent —
        calling this multiple times is safe.
        """
        import asyncio

        loop = asyncio.get_running_loop()

        def _create() -> None:
            client = self._get_client()
            existing = {c.name for c in client.get_collections().collections}
            if self.COLLECTION_NAME in existing:
                logger.debug(
                    "Qdrant collection '{}' already exists — skipping creation.",
                    self.COLLECTION_NAME,
                )
                return
            client.create_collection(
                collection_name=self.COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=self.VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )
            logger.info(
                "Created Qdrant collection '{}' (size={}, distance=COSINE).",
                self.COLLECTION_NAME,
                self.VECTOR_SIZE,
            )

        try:
            await loop.run_in_executor(None, _create)
        except Exception as exc:
            logger.error(
                "Failed to initialise Qdrant collection '{}': {}",
                self.COLLECTION_NAME,
                exc,
            )
            raise

    async def upsert_document(
        self,
        doc_id: str,
        vector: list[float],
        payload: dict[str, Any],
    ) -> None:
        """Store or overwrite a document embedding with its metadata payload.

        Parameters
        ----------
        doc_id:
            UUID string used as the Qdrant point ID.
        vector:
            Dense embedding of length VECTOR_SIZE.
        payload:
            Arbitrary metadata stored alongside the vector.  Recommended keys:
            ``title``, ``summary``, ``category``, ``source_type``,
            ``created_at`` (ISO-8601 string).
        """
        import asyncio

        # Ensure created_at is always present as an ISO string.
        payload = dict(payload)
        if "created_at" not in payload or payload["created_at"] is None:
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
        elif isinstance(payload["created_at"], datetime):
            payload["created_at"] = payload["created_at"].isoformat()

        point = PointStruct(id=doc_id, vector=vector, payload=payload)

        loop = asyncio.get_running_loop()

        def _upsert() -> None:
            self._get_client().upsert(
                collection_name=self.COLLECTION_NAME,
                points=[point],
            )

        try:
            await loop.run_in_executor(None, _upsert)
            logger.debug("Upserted document '{}' into Qdrant.", doc_id)
        except Exception as exc:
            logger.error(
                "Failed to upsert document '{}' into Qdrant: {}", doc_id, exc
            )
            raise

    async def search_similar(
        self,
        query_vector: list[float],
        limit: int = 10,
        filter_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic nearest-neighbour search.

        Parameters
        ----------
        query_vector:
            Dense query embedding of length VECTOR_SIZE.
        limit:
            Maximum number of results to return.
        filter_params:
            Optional dict of ``{field: value}`` pairs used to build a Qdrant
            ``Filter`` with ``must`` conditions.  Each pair becomes a
            ``FieldCondition`` with ``MatchValue``.

        Returns
        -------
        list of ``{"id": str, "score": float, "payload": dict}``
        """
        import asyncio

        qdrant_filter: Filter | None = None
        if filter_params:
            must_conditions = [
                FieldCondition(key=k, match=MatchValue(value=v))
                for k, v in filter_params.items()
            ]
            qdrant_filter = Filter(must=must_conditions)

        loop = asyncio.get_running_loop()

        def _search() -> list[dict[str, Any]]:
            hits = self._get_client().search(
                collection_name=self.COLLECTION_NAME,
                query_vector=query_vector,
                limit=limit,
                query_filter=qdrant_filter,
                with_payload=True,
            )
            return [
                {
                    "id": str(hit.id),
                    "score": hit.score,
                    "payload": hit.payload or {},
                }
                for hit in hits
            ]

        try:
            results = await loop.run_in_executor(None, _search)
            logger.debug(
                "Qdrant search returned {} result(s) (limit={}).",
                len(results),
                limit,
            )
            return results
        except Exception as exc:
            logger.error("Qdrant search failed: {}", exc)
            raise

    async def delete_document(self, doc_id: str) -> None:
        """Remove a single point from the collection by its ID.

        Parameters
        ----------
        doc_id:
            UUID string of the point to delete.
        """
        import asyncio

        loop = asyncio.get_running_loop()

        def _delete() -> None:
            self._get_client().delete(
                collection_name=self.COLLECTION_NAME,
                points_selector=PointIdsList(points=[doc_id]),
            )

        try:
            await loop.run_in_executor(None, _delete)
            logger.debug("Deleted document '{}' from Qdrant.", doc_id)
        except Exception as exc:
            logger.error(
                "Failed to delete document '{}' from Qdrant: {}", doc_id, exc
            )
            raise

    async def get_document(self, doc_id: str) -> dict[str, Any] | None:
        """Retrieve a single point by its ID.

        Parameters
        ----------
        doc_id:
            UUID string of the point to fetch.

        Returns
        -------
        ``{"id": str, "payload": dict}`` if found, ``None`` if not found.
        """
        import asyncio

        loop = asyncio.get_running_loop()

        def _retrieve() -> list:
            return self._get_client().retrieve(
                collection_name=self.COLLECTION_NAME,
                ids=[doc_id],
                with_payload=True,
                with_vectors=False,
            )

        try:
            points = await loop.run_in_executor(None, _retrieve)
        except Exception as exc:
            logger.error(
                "Failed to retrieve document '{}' from Qdrant: {}", doc_id, exc
            )
            raise

        if not points:
            logger.debug("Document '{}' not found in Qdrant.", doc_id)
            return None

        point = points[0]
        return {
            "id": str(point.id),
            "payload": point.payload or {},
        }

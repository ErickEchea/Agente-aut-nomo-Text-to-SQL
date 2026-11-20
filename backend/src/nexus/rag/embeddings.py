"""Embedding profiles: each model's recommended query/document input format.

Formats come from the model authors: Qwen3-Embedding instructs queries only
(``Instruct: {task}\\nQuery:{query}``, documents raw); EmbeddingGemma uses
``task: search result | query: …`` / ``title: … | text: …``. Whether a template helps on *our* data
is measured by ``nexus-eval-retrieval`` (docs/retrieval-eval.md), not assumed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from nexus.llm import LLMProvider

RETRIEVAL_TASK = (
    "Given a business question in Spanish, retrieve the database tables, columns, business "
    "definitions and examples needed to answer it with SQL"
)


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    model: str
    query_template: str = "{text}"
    document_template: str = "{text}"
    label: str = ""

    @property
    def name(self) -> str:
        return self.label or self.model

    def raw(self) -> EmbeddingProfile:
        """Same model without input templates (for the evaluation ablation)."""
        return replace(
            self, query_template="{text}", document_template="{text}", label=f"{self.model} (raw)"
        )


KNOWN_PROFILES: dict[str, EmbeddingProfile] = {
    "qwen3-embedding:0.6b": EmbeddingProfile(
        "qwen3-embedding:0.6b", query_template=f"Instruct: {RETRIEVAL_TASK}\nQuery:{{text}}"
    ),
    "embeddinggemma-2:latest": EmbeddingProfile(
        "embeddinggemma-2:latest",
        query_template="task: search result | query: {text}",
        document_template="title: {title} | text: {text}",
    ),
}


def profile_for(model: str) -> EmbeddingProfile:
    return KNOWN_PROFILES.get(model, EmbeddingProfile(model))


class Embedder:
    """Applies a profile's templates and batches calls to the provider."""

    def __init__(self, llm: LLMProvider, profile: EmbeddingProfile, batch_size: int = 32) -> None:
        self._llm = llm
        self.profile = profile
        self._batch = batch_size

    async def embed_documents(self, items: Sequence[tuple[str, str]]) -> list[list[float]]:
        """``items`` are (title, text) pairs."""
        texts = [self.profile.document_template.format(title=t or "none", text=x) for t, x in items]
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            vectors.extend(
                await self._llm.embed(texts[i : i + self._batch], model=self.profile.model)
            )
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        (vector,) = await self._llm.embed(
            [self.profile.query_template.format(text=text)], model=self.profile.model
        )
        return vector

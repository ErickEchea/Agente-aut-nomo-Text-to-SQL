"""Schema RAG against real PostgreSQL + pgvector (deterministic test embeddings)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from nexus.agent.catalog import SchemaCatalog, introspect
from nexus.agent.glossary import Glossary, load_glossary
from nexus.config import DatabaseSettings
from nexus.db.engines import create_engine
from nexus.db.migrate import upgrade
from nexus.demo.loader import LoadResult
from nexus.rag.documents import ExampleRecord, collect_samples
from nexus.rag.embeddings import Embedder, EmbeddingProfile
from nexus.rag.indexer import ensure_index
from nexus.rag.retriever import HybridRetriever, RetrievedExample
from nexus.rag.store import PgDocumentStore
from tests.integration.conftest import REPO_ROOT
from tests.unit.agent.fakes import ScriptedLLM

# The module-scoped engines live on one event loop shared by every test in this module.
pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

KEY = "test-retail"


@dataclass
class Rig:
    store: PgDocumentStore
    embedder: Embedder
    catalog: SchemaCatalog
    glossary: Glossary
    samples: dict[tuple[str, str], list[str]]
    app_engine: AsyncEngine


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def rig(
    app_db: DatabaseSettings, reader_db: DatabaseSettings, seeded: LoadResult
) -> AsyncIterator[Rig]:
    # Alembic's env runs its own event loop: keep it off this one.
    await asyncio.to_thread(upgrade, app_db.sqlalchemy_url().render_as_string(hide_password=False))
    app_engine = create_engine(app_db, application_name="test-rag")
    demo_engine = create_engine(reader_db, application_name="test-rag-reader")
    catalog = await introspect(demo_engine)
    samples = await collect_samples(demo_engine, catalog, ["clientes.cedula", "clientes.email"])
    await demo_engine.dispose()
    rig = Rig(
        store=PgDocumentStore(async_sessionmaker(app_engine, expire_on_commit=False)),
        embedder=Embedder(ScriptedLLM({}), EmbeddingProfile("hash-embedding")),
        catalog=catalog,
        glossary=load_glossary(REPO_ROOT / "data" / "glossary.yaml"),
        samples=samples,
        app_engine=app_engine,
    )
    yield rig
    await app_engine.dispose()


def retriever(rig: Rig, **flags: bool) -> HybridRetriever:
    async def no_examples(_: object) -> list[RetrievedExample]:
        return []

    return HybridRetriever(
        store=rig.store, embedder=rig.embedder, catalog=rig.catalog, glossary=rig.glossary,
        connection_key=KEY, samples=rig.samples, load_examples=no_examples, **flags,  # type: ignore[arg-type]
    )  # fmt: skip


async def test_samples_skip_pii_and_high_cardinality(rig: Rig) -> None:
    assert ("ventas", "estado") in rig.samples
    assert set(rig.samples[("ventas", "estado")]) == {"completada", "anulada"}
    assert ("regiones", "nombre") in rig.samples
    assert not any(t == "clientes" and c in {"cedula", "email"} for t, c in rig.samples)
    assert ("productos", "nombre") not in rig.samples  # 404 distinct values


async def test_index_is_built_once_then_reused(rig: Rig) -> None:
    kwargs = {"store": rig.store, "embedder": rig.embedder, "catalog": rig.catalog, "glossary": rig.glossary,
                  "samples": rig.samples, "examples": [], "connection_key": KEY}  # fmt: skip
    first = await ensure_index(**kwargs)  # type: ignore[arg-type]
    again = await ensure_index(**kwargs)  # type: ignore[arg-type]
    assert first.rebuilt and not again.rebuilt
    assert first.documents == again.documents > 90
    with_example = await ensure_index(  # a new verified example changes the fingerprint
        **{**kwargs, "examples": [ExampleRecord("e1", "Ventas por canal", "SELECT 1", ("ventas",))]}  # type: ignore[arg-type]
    )
    assert with_example.rebuilt and with_example.documents == first.documents + 1


async def test_lexical_and_fuzzy_search(rig: Rig) -> None:
    model = rig.embedder.profile.model
    lexical = await rig.store.lexical(KEY, model, "devoluciones de productos", 5)
    assert lexical and any("devoluciones" in h.tables for h in lexical)
    fuzzy = await rig.store.fuzzy(KEY, model, "sucursl", 5)  # typo
    assert any(h.ref == "sucursales" for h in fuzzy)


async def test_retriever_selects_connected_tables_with_forced_glossary_tables(rig: Rig) -> None:
    context = await retriever(rig).retrieve("¿Qué sucursal generó mayores ingresos en la Costa?")
    assert {"sucursales", "ventas", "detalle_ventas", "devoluciones", "regiones"} <= set(
        context.tables
    )
    assert "regiones" in context.forced_tables  # "Costa" is a regiones.nombre value
    conditions = {j.condition() for j in context.joins}
    assert "ventas.sucursal_id = sucursales.sucursal_id" in conditions
    assert "sucursales.region_id = regiones.region_id" in conditions
    assert any(t.term == "ingresos" for t in context.terms)
    assert context.strategy == "hybrid"
    assert len(context.tables) < len(rig.catalog.tables)


async def test_empty_index_falls_back_to_full_schema(rig: Rig) -> None:
    empty = HybridRetriever(
        store=rig.store, embedder=rig.embedder, catalog=rig.catalog, glossary=rig.glossary,
        connection_key="never-indexed", samples={}, load_examples=lambda _: _none(),  # type: ignore[arg-type,return-value]
    )  # fmt: skip
    context = await empty.retrieve("¿Cuál es el clima?")
    assert set(context.tables) == set(rig.catalog.tables)
    assert context.strategy.startswith("full-schema")


async def _none() -> list[RetrievedExample]:
    return []

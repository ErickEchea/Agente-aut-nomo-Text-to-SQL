"""Pure parts of the retrieval layer: RRF, value linking, join paths, documents, charts."""

from __future__ import annotations

from nexus.agent.charts import build_spec, candidates_for, column_role
from nexus.agent.glossary import Glossary, GlossaryTerm, SqlRequirement
from nexus.rag.documents import ExampleRecord, build_documents, fingerprint, tables_in_sql
from nexus.rag.embeddings import EmbeddingProfile, profile_for
from nexus.rag.joins import connect
from nexus.rag.retriever import link_values, reciprocal_rank_fusion
from nexus.rag.store import Hit
from tests.unit.agent.fakes import catalog


def hit(ref: str, doc_type: str = "table") -> Hit:
    return Hit(doc_type, ref, (ref,), ref, 0.0)


def test_rrf_rewards_agreement_between_rankings() -> None:
    fused = reciprocal_rank_fusion([[hit("a"), hit("b"), hit("c")], [hit("b"), hit("c"), hit("a")]])
    assert [h.ref for h, _ in fused] == ["b", "a", "c"]
    assert fused[0][1] == 1 / 62 + 1 / 61


def test_value_linking_prefers_the_table_retrieval_ranks_higher() -> None:
    samples = {
        ("regiones", "nombre"): ["Sierra", "Costa"],
        ("clientes", "ciudad"): ["Quito", "Loja"],
        ("sucursales", "ciudad"): ["Quito", "Loja"],
        ("ventas", "metodo_pago"): ["billetera_movil", "efectivo"],
        ("ventas", "canal"): ["online", "tienda"],
    }
    scores = {"sucursales": 0.5, "clientes": 0.1}
    assert link_values("Ventas en la COSTA de Quito", samples, scores) == ["regiones", "sucursales"]
    assert link_values("pagos con billetera móvil", samples, scores) == ["ventas"]
    assert link_values("¿Cuánto se vendió en la Costa?", samples, scores) == ["regiones"]
    assert link_values("¿Cuál es el costo?", samples, scores) == []  # no partial-word matches


def test_connect_adds_bridge_tables_and_join_conditions() -> None:
    cat = catalog()
    tables, joins = connect(cat, ["ventas", "sucursales"])
    assert tables == ["ventas", "sucursales"]
    assert [j.condition() for j in joins] == ["ventas.sucursal_id = sucursales.sucursal_id"]
    lone, no_joins = connect(cat, ["regiones", "clientes"])  # not connected in the fake catalog
    assert set(lone) == {"regiones", "clientes"}
    assert no_joins == []
    assert connect(cat, ["no_existe"]) == ([], [])


def test_documents_cover_tables_columns_terms_and_examples() -> None:
    glossary = Glossary(
        "USD",
        (
            GlossaryTerm(
                "ingresos", ("ventas netas",), "Neto.", requires=SqlRequirement(tables=("ventas",))
            ),
        ),
        (GlossaryTerm("sucursal", ("tienda",), "Tabla", maps_to="sucursales"),),
    )
    docs = build_documents(
        catalog(),
        glossary,
        {("ventas", "estado"): ["completada", "anulada"]},
        [ExampleRecord("1", "Ventas por sucursal", "SELECT 1 FROM retail.ventas", ("ventas",))],
    )
    kinds = {d.doc_type for d in docs}
    assert kinds == {"table", "column", "glossary", "example"}
    estado = next(d for d in docs if d.ref == "ventas.estado")
    assert "Valores: completada, anulada" in estado.content
    assert next(d for d in docs if d.ref == "sucursal").tables == ("sucursales",)
    assert fingerprint(docs, "m1") != fingerprint(docs, "m2")


def test_tables_in_sql_ignores_ctes() -> None:
    sql = (
        "WITH t AS (SELECT * FROM retail.ventas) SELECT * FROM t JOIN retail.sucursales s USING (x)"
    )
    assert tables_in_sql(sql) == ("sucursales", "ventas")
    assert tables_in_sql("not sql at all (") == ()


def test_embedding_profiles() -> None:
    qwen = profile_for("qwen3-embedding:0.6b")
    assert qwen.query_template.startswith("Instruct: ")
    assert qwen.query_template.endswith("Query:{text}")
    assert qwen.raw().query_template == "{text}"
    assert profile_for("other-model") == EmbeddingProfile("other-model")


def test_chart_rules() -> None:
    assert column_role([1, 2.5, None]) == "numeric"
    assert column_role(["2026-07-01", "2026-08-01"]) == "temporal"
    assert column_role(["a", 1]) == "category"
    trend = [("2026-07-01", 10.0), ("2026-08-01", 12.0), ("2026-09-01", 9.0), ("2026-10-01", 15.0)]
    assert candidates_for("ventas por mes", ("mes", "total"), trend)[0] == ["line", "bar"]
    share = [("tienda", 80.0), ("online", 20.0)]
    assert candidates_for("participación por canal", ("canal", "ventas"), share)[0] == [
        "pie",
        "bar",
    ]
    assert candidates_for("x", ("a", "b"), [("Samborondón", 299672.19)])[0] == ["kpi"]
    assert candidates_for("x", ("a",), [])[0] == ["table"]
    assert candidates_for("x", ("a", "b"), [(1.0, 2.0), (2.0, 3.0)])[0] == ["scatter"]


def test_chart_specs_validate() -> None:
    rows = [("Agua", 4768), ("Pollo", 2707)]
    kinds, reason, picks = candidates_for("top", ("producto", "unidades"), rows)
    spec = build_spec(
        "bar",
        0,
        candidates=kinds,
        reason=reason,
        title="Top",
        columns=("producto", "unidades"),
        rows=rows,
        picks=picks,
    )
    option = spec.option
    assert option is not None and option.xAxis is not None
    assert option.xAxis.data == ["Agua", "Pollo"]
    assert option.series[0].data == [4768.0, 2707.0]
    pie = build_spec(
        "pie",
        0,
        candidates=kinds,
        reason=reason,
        title="Top",
        columns=("producto", "unidades"),
        rows=rows,
        picks=picks,
    )
    assert pie.option is not None and pie.option.series[0].type == "pie"
    dumped = spec.model_dump(mode="json", exclude_none=True)
    assert dumped["option"]["series"][0]["type"] == "bar"

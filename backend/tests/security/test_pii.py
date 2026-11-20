import pytest

from nexus.security.pii import PiiMasker, mask_value

MASKER = PiiMasker(["clientes.cedula", "clientes.email", "clientes.telefono"])


def test_mask_value_keeps_last_two_characters() -> None:
    assert mask_value("1710034065") == "••••••••65"
    assert mask_value("abc") == "•••"
    assert mask_value(None) is None


@pytest.mark.parametrize(
    ("sql", "columns", "expected"),
    [
        ("SELECT nombres, email FROM retail.clientes", ("nombres", "email"), {1}),
        ("SELECT nombres, email AS contacto FROM retail.clientes", ("nombres", "contacto"), {1}),
        ("SELECT lower(c.email) AS e, c.ciudad FROM retail.clientes c", ("e", "ciudad"), {0}),
        ("SELECT count(email) AS n FROM retail.clientes", ("n",), set()),
        (
            "SELECT ciudad, count(*) FROM retail.clientes GROUP BY ciudad",
            ("ciudad", "count"),
            set(),
        ),
        ("SELECT * FROM retail.clientes", ("cliente_id", "cedula", "nombres", "email"), {1, 3}),
        (
            "WITH t AS (SELECT telefono AS tel FROM retail.clientes) SELECT tel FROM t",
            ("tel",),
            {0},
        ),
        (
            "SELECT x.contacto FROM (SELECT email AS contacto FROM retail.clientes) x",
            ("contacto",),
            {0},
        ),
        (
            "WITH t AS (SELECT count(email) AS n FROM retail.clientes) SELECT n FROM t",
            ("n",),
            set(),
        ),
    ],
)
def test_sensitive_columns(sql: str, columns: tuple[str, ...], expected: set[int]) -> None:
    assert MASKER.sensitive_columns(sql, columns) == expected


def test_mask_rows_reports_masked_columns() -> None:
    rows, masked = MASKER.mask(
        "SELECT nombres, cedula FROM retail.clientes",
        ("nombres", "cedula"),
        [("Ana", "1710034065"), ("Luis", None)],
    )
    assert rows == [("Ana", "••••••••65"), ("Luis", None)]
    assert masked == ("cedula",)


def test_disabled_masker_is_a_no_op() -> None:
    rows = [("x@y.com",)]
    assert PiiMasker([]).mask("SELECT email FROM clientes", ("email",), rows) == (rows, ())

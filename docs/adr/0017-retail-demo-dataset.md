# ADR-0017 — Retail demo dataset (Ecuador, USD)

- Status: Accepted
- Date: 2026-11-20

## Context
The demo database is the main surface for the agent, the golden set and the optimizer. It must be realistic
enough that questions have non-trivial answers (seasonality, regional effects, returns, anomalies), deterministic
(fixed seed), and fast to regenerate. The product owner is based in Ecuador: currency is **USD** and the
calendar follows Ecuadorian commerce.

## Decision

### Shape
Schema `retail` in database `retail`, Spanish identifiers, `COMMENT ON` every table and column.

| Table | Rows (scale 1.0) | Notes |
|---|---|---|
| `regiones` | 4 | Sierra, Costa, Amazonía, Insular (Galápagos) |
| `sucursales` | 24 | 18 cities in 16 provinces; formats hipermercado / supermercado / express; one opens mid-period |
| `categorias` | 10 | Electrónica, Electrodomésticos, Hogar, Alimentos y Bebidas, Cuidado Personal, Ropa y Calzado, Útiles Escolares, Juguetes, Deportes, Ferretería |
| `productos` | 404 | type × brand × variant catalogue with realistic USD list prices and costs |
| `clientes` | ~25k | valid Ecuadorian cédula (mod-10 check digit), PII columns (cédula, email, teléfono) for masking |
| `empleados` | 349 | per-branch staff with hierarchy (`supervisor_id`) |
| `ventas` | ~196k | ticket header: timestamp, branch, customer (NULL = consumidor final), employee, channel, payment method, status, subtotal, discount, IVA 15 %, total |
| `detalle_ventas` | ≈499.5k | line items: quantity, unit price (pre-tax), line discount |
| `inventario` | ~230k | month-end stock snapshot per branch × product with `stock_minimo` |
| `devoluciones` | ~7.7k | whole-line returns with reason and refund amount |

### Business definitions (data/glossary.yaml)
- **ingresos (netos)** = `SUM(cantidad × precio_unitario − descuento)` over lines of `ventas.estado = 'completada'`
  that have **no** row in `devoluciones` (returns are always whole lines, making the rule unambiguous).
- Amounts exclude IVA unless the question says otherwise; `ventas.total` includes IVA.
- **último trimestre** = most recent closed calendar quarter relative to `as_of`.

### Calendar effects (Ecuador)
Weekly pattern (weekend peak); paydays (15th and month-end); **décimo tercer sueldo** (December) and
**décimo cuarto sueldo** (March in Costa/Galápagos, August in Sierra/Amazonía) — a regional effect; Navidad;
Black Friday (last Friday of November) with electronics promotions; Día de la Madre (2nd Sunday of May) and
Día del Padre (3rd Sunday of June); Carnaval; **back-to-school** for *Útiles Escolares* — April/May in the
Costa-Galápagos regime and late August/September in Sierra-Amazonía; national holidays.
Trend: ~7 % YoY overall (Costa faster, Insular flat); online share grows from ~5 % to ~12 %; mobile-wallet payments grow.
Annual list-price adjustment each January (~2.5 %); Galápagos prices +10 % (transport).

### Planted anomalies (documented here, *not* in schema comments, so the agent must find them in data)
1. Stock-out: a best-selling TV at one Quito branch has zero stock and zero sales for three weeks in Aug 2026.
2. Returns spike: one blender model has ~25 % returns ("defecto de fábrica") in Jun–Aug 2025.
3. Temporary closure: one Cuenca branch closed for renovation 10–23 Feb 2025.
4. New branch: Manta opens 1 Jul 2025 (no earlier sales — a trap for per-branch YoY growth).
5. Outlier: one corporate bulk order of laptops in March 2026.
6. ~1 % voided tickets (`estado = 'anulada'`) that must be excluded from revenue.
7. **Missing index** on `detalle_ventas(producto_id)` on purpose, for the Phase 5 optimizer demo.

### Generation
- `nexus.demo` package (backend), numpy `Generator(PCG64(seed))`, fully vectorized; loaded with `COPY`.
- `scale` parameter (default 1.0) for fast integration tests.
- Metadata (`retail_meta.dataset`: version, seed, scale, row counts, content checksum) makes the seed job
  idempotent; it is not readable by `nexus_reader`.

## Consequences
- Golden-set questions can probe regional seasonality, net-vs-gross revenue, voided tickets and the new-branch trap.
- Any change to the generator bumps `DATASET_VERSION` and requires regenerating the golden set's expected results.

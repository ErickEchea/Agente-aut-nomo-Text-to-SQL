-- Foreign keys and secondary indexes, applied after COPY (much faster than row-by-row checks).
-- NOTE: there is deliberately NO index on detalle_ventas(producto_id) — ADR-0017 anomaly #7,
-- used by the query-optimization feature (Phase 5) to demonstrate a missing-index finding.

SET search_path = retail;

ALTER TABLE sucursales ADD CONSTRAINT sucursales_region_fk FOREIGN KEY (region_id) REFERENCES regiones (region_id);
ALTER TABLE productos ADD CONSTRAINT productos_categoria_fk FOREIGN KEY (categoria_id) REFERENCES categorias (categoria_id);
ALTER TABLE empleados ADD CONSTRAINT empleados_sucursal_fk FOREIGN KEY (sucursal_id) REFERENCES sucursales (sucursal_id);
ALTER TABLE empleados ADD CONSTRAINT empleados_supervisor_fk FOREIGN KEY (supervisor_id) REFERENCES empleados (empleado_id);
ALTER TABLE ventas ADD CONSTRAINT ventas_sucursal_fk FOREIGN KEY (sucursal_id) REFERENCES sucursales (sucursal_id);
ALTER TABLE ventas ADD CONSTRAINT ventas_cliente_fk FOREIGN KEY (cliente_id) REFERENCES clientes (cliente_id);
ALTER TABLE ventas ADD CONSTRAINT ventas_empleado_fk FOREIGN KEY (empleado_id) REFERENCES empleados (empleado_id);
ALTER TABLE ventas ADD CONSTRAINT ventas_total_ck CHECK (total = subtotal - descuento_total + iva);
ALTER TABLE detalle_ventas ADD CONSTRAINT detalle_venta_fk FOREIGN KEY (venta_id) REFERENCES ventas (venta_id);
ALTER TABLE detalle_ventas ADD CONSTRAINT detalle_producto_fk FOREIGN KEY (producto_id) REFERENCES productos (producto_id);
ALTER TABLE inventario ADD CONSTRAINT inventario_sucursal_fk FOREIGN KEY (sucursal_id) REFERENCES sucursales (sucursal_id);
ALTER TABLE inventario ADD CONSTRAINT inventario_producto_fk FOREIGN KEY (producto_id) REFERENCES productos (producto_id);
ALTER TABLE devoluciones ADD CONSTRAINT devoluciones_detalle_fk FOREIGN KEY (detalle_id) REFERENCES detalle_ventas (detalle_id);
ALTER TABLE devoluciones ADD CONSTRAINT devoluciones_venta_fk FOREIGN KEY (venta_id) REFERENCES ventas (venta_id);

CREATE INDEX ventas_fecha_idx ON ventas (fecha_venta);
CREATE INDEX ventas_sucursal_idx ON ventas (sucursal_id);
CREATE INDEX ventas_cliente_idx ON ventas (cliente_id);
CREATE INDEX detalle_ventas_venta_idx ON detalle_ventas (venta_id);
CREATE INDEX productos_categoria_idx ON productos (categoria_id);
CREATE INDEX empleados_sucursal_idx ON empleados (sucursal_id);
CREATE INDEX devoluciones_venta_idx ON devoluciones (venta_id);
CREATE INDEX devoluciones_fecha_idx ON devoluciones (fecha_devolucion);
CREATE INDEX inventario_fecha_idx ON inventario (fecha_corte);

-- Belt and braces: default privileges already grant SELECT to the reader role.
GRANT SELECT ON ALL TABLES IN SCHEMA retail TO nexus_reader;

ANALYZE;

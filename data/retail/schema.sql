-- Retail demo schema (ADR-0017). Executed by the seed job as `retail_owner`.
-- Tables are created without foreign keys / secondary indexes; `constraints.sql` adds them after COPY.
-- Every table and column has a COMMENT: they are source material for the schema RAG.

SET search_path = retail;

DROP TABLE IF EXISTS devoluciones, inventario, detalle_ventas, ventas, empleados, clientes,
    productos, categorias, sucursales, regiones CASCADE;

CREATE TABLE regiones (
    region_id   integer PRIMARY KEY,
    nombre      text NOT NULL UNIQUE,
    descripcion text NOT NULL
);
COMMENT ON TABLE regiones IS 'Regiones geográficas del Ecuador donde opera la cadena (Sierra, Costa, Amazonía, Insular).';
COMMENT ON COLUMN regiones.region_id IS 'Identificador de la región.';
COMMENT ON COLUMN regiones.nombre IS 'Nombre de la región: Sierra, Costa, Amazonía o Insular (Galápagos).';
COMMENT ON COLUMN regiones.descripcion IS 'Provincias que agrupa la región y notas operativas.';

CREATE TABLE sucursales (
    sucursal_id      integer PRIMARY KEY,
    codigo           text NOT NULL UNIQUE,
    nombre           text NOT NULL,
    ciudad           text NOT NULL,
    provincia        text NOT NULL,
    region_id        integer NOT NULL,
    formato          text NOT NULL CHECK (formato IN ('hipermercado', 'supermercado', 'express')),
    metros_cuadrados integer NOT NULL CHECK (metros_cuadrados > 0),
    fecha_apertura   date NOT NULL
);
COMMENT ON TABLE sucursales IS 'Tiendas físicas (sucursales o locales) de la cadena. Cada venta pertenece a una sucursal, incluidas las ventas online que se despachan desde ella.';
COMMENT ON COLUMN sucursales.sucursal_id IS 'Identificador de la sucursal.';
COMMENT ON COLUMN sucursales.codigo IS 'Código corto de la sucursal, p. ej. QUI-01 (ciudad + número).';
COMMENT ON COLUMN sucursales.nombre IS 'Nombre comercial de la sucursal o tienda.';
COMMENT ON COLUMN sucursales.ciudad IS 'Ciudad donde está la sucursal.';
COMMENT ON COLUMN sucursales.provincia IS 'Provincia del Ecuador donde está la sucursal.';
COMMENT ON COLUMN sucursales.region_id IS 'Región de la sucursal (referencia a regiones).';
COMMENT ON COLUMN sucursales.formato IS 'Formato de tienda: hipermercado, supermercado o express.';
COMMENT ON COLUMN sucursales.metros_cuadrados IS 'Superficie de sala de ventas en metros cuadrados.';
COMMENT ON COLUMN sucursales.fecha_apertura IS 'Fecha de apertura de la sucursal; no hay ventas anteriores a esta fecha.';

CREATE TABLE categorias (
    categoria_id integer PRIMARY KEY,
    nombre       text NOT NULL UNIQUE,
    descripcion  text NOT NULL
);
COMMENT ON TABLE categorias IS 'Categorías (líneas o departamentos) del catálogo de productos.';
COMMENT ON COLUMN categorias.categoria_id IS 'Identificador de la categoría.';
COMMENT ON COLUMN categorias.nombre IS 'Nombre de la categoría, p. ej. Electrónica, Alimentos y Bebidas, Útiles Escolares.';
COMMENT ON COLUMN categorias.descripcion IS 'Qué tipo de productos incluye la categoría.';

CREATE TABLE productos (
    producto_id       integer PRIMARY KEY,
    sku               text NOT NULL UNIQUE,
    nombre            text NOT NULL,
    marca             text NOT NULL,
    categoria_id      integer NOT NULL,
    precio_lista      numeric(12, 2) NOT NULL CHECK (precio_lista > 0),
    costo_unitario    numeric(12, 2) NOT NULL CHECK (costo_unitario > 0),
    graba_iva         boolean NOT NULL,
    fecha_lanzamiento date
);
COMMENT ON TABLE productos IS 'Catálogo de productos (artículos) que vende la cadena.';
COMMENT ON COLUMN productos.producto_id IS 'Identificador del producto.';
COMMENT ON COLUMN productos.sku IS 'Código SKU: prefijo de categoría + secuencial, p. ej. ELE-0001.';
COMMENT ON COLUMN productos.nombre IS 'Nombre descriptivo del producto, incluye presentación o tamaño.';
COMMENT ON COLUMN productos.marca IS 'Marca del producto. Casa Bella, Granja Andina y Urbano son marcas propias.';
COMMENT ON COLUMN productos.categoria_id IS 'Categoría del producto (referencia a categorias).';
COMMENT ON COLUMN productos.precio_lista IS 'Precio de lista vigente en USD, sin IVA. El precio histórico cobrado está en detalle_ventas.precio_unitario.';
COMMENT ON COLUMN productos.costo_unitario IS 'Costo unitario de compra en USD, sin IVA. Sirve para calcular margen.';
COMMENT ON COLUMN productos.graba_iva IS 'true si el producto grava IVA (15 %); false para bienes de tarifa 0 % como alimentos básicos.';
COMMENT ON COLUMN productos.fecha_lanzamiento IS 'Fecha de lanzamiento si el producto se incorporó durante el periodo; NULL si existía antes.';

CREATE TABLE clientes (
    cliente_id       integer PRIMARY KEY,
    cedula           text NOT NULL UNIQUE,
    nombres          text NOT NULL,
    apellidos        text NOT NULL,
    email            text NOT NULL UNIQUE,
    telefono         text NOT NULL,
    fecha_nacimiento date NOT NULL,
    ciudad           text NOT NULL,
    provincia        text NOT NULL,
    segmento         text NOT NULL CHECK (segmento IN ('ocasional', 'frecuente', 'corporativo')),
    fecha_registro   date NOT NULL
);
COMMENT ON TABLE clientes IS 'Clientes registrados (programa de fidelización). Las ventas a consumidor final no tienen cliente.';
COMMENT ON COLUMN clientes.cliente_id IS 'Identificador del cliente.';
COMMENT ON COLUMN clientes.cedula IS 'Cédula de identidad ecuatoriana (10 dígitos). Dato personal sensible (PII).';
COMMENT ON COLUMN clientes.nombres IS 'Nombres del cliente. Dato personal (PII).';
COMMENT ON COLUMN clientes.apellidos IS 'Apellidos del cliente. Dato personal (PII).';
COMMENT ON COLUMN clientes.email IS 'Correo electrónico del cliente. Dato personal (PII).';
COMMENT ON COLUMN clientes.telefono IS 'Teléfono celular del cliente (formato 09XXXXXXXX). Dato personal (PII).';
COMMENT ON COLUMN clientes.fecha_nacimiento IS 'Fecha de nacimiento; permite calcular edad o rango etario.';
COMMENT ON COLUMN clientes.ciudad IS 'Ciudad de residencia del cliente.';
COMMENT ON COLUMN clientes.provincia IS 'Provincia de residencia del cliente.';
COMMENT ON COLUMN clientes.segmento IS 'Segmento comercial: ocasional, frecuente o corporativo (empresas).';
COMMENT ON COLUMN clientes.fecha_registro IS 'Fecha en que el cliente se registró en el programa.';

CREATE TABLE empleados (
    empleado_id     integer PRIMARY KEY,
    cedula          text NOT NULL UNIQUE,
    nombres         text NOT NULL,
    apellidos       text NOT NULL,
    email           text NOT NULL UNIQUE,
    cargo           text NOT NULL,
    sucursal_id     integer NOT NULL,
    supervisor_id   integer,
    fecha_ingreso   date NOT NULL,
    salario_mensual numeric(12, 2) NOT NULL CHECK (salario_mensual > 0)
);
COMMENT ON TABLE empleados IS 'Personal de la cadena con su sucursal, cargo y jefe directo.';
COMMENT ON COLUMN empleados.empleado_id IS 'Identificador del empleado.';
COMMENT ON COLUMN empleados.cedula IS 'Cédula del empleado. Dato personal sensible (PII).';
COMMENT ON COLUMN empleados.nombres IS 'Nombres del empleado.';
COMMENT ON COLUMN empleados.apellidos IS 'Apellidos del empleado.';
COMMENT ON COLUMN empleados.email IS 'Correo corporativo del empleado.';
COMMENT ON COLUMN empleados.cargo IS 'Cargo: gerente general, gerente regional, gerente de sucursal, supervisor, cajero, vendedor o bodeguero.';
COMMENT ON COLUMN empleados.sucursal_id IS 'Sucursal donde trabaja el empleado.';
COMMENT ON COLUMN empleados.supervisor_id IS 'Jefe directo (referencia a empleados); NULL solo para el gerente general.';
COMMENT ON COLUMN empleados.fecha_ingreso IS 'Fecha de ingreso a la empresa.';
COMMENT ON COLUMN empleados.salario_mensual IS 'Salario mensual en USD. Dato sensible.';

CREATE TABLE ventas (
    venta_id        integer PRIMARY KEY,
    fecha_venta     timestamp NOT NULL,
    sucursal_id     integer NOT NULL,
    cliente_id      integer,
    empleado_id     integer NOT NULL,
    canal           text NOT NULL CHECK (canal IN ('tienda', 'online')),
    metodo_pago     text NOT NULL CHECK (metodo_pago IN ('efectivo', 'tarjeta_debito', 'tarjeta_credito', 'transferencia', 'billetera_movil')),
    estado          text NOT NULL CHECK (estado IN ('completada', 'anulada')),
    subtotal        numeric(12, 2) NOT NULL,
    descuento_total numeric(12, 2) NOT NULL,
    iva             numeric(12, 2) NOT NULL,
    total           numeric(12, 2) NOT NULL
);
COMMENT ON TABLE ventas IS 'Cabecera de cada venta o ticket (factura). El detalle de productos está en detalle_ventas. Para ingresos usar detalle_ventas y excluir ventas anuladas y líneas devueltas.';
COMMENT ON COLUMN ventas.venta_id IS 'Identificador de la venta (número de ticket), cronológico.';
COMMENT ON COLUMN ventas.fecha_venta IS 'Fecha y hora local (America/Guayaquil) de la venta.';
COMMENT ON COLUMN ventas.sucursal_id IS 'Sucursal donde se realizó o desde donde se despachó la venta.';
COMMENT ON COLUMN ventas.cliente_id IS 'Cliente registrado; NULL cuando la venta es a consumidor final.';
COMMENT ON COLUMN ventas.empleado_id IS 'Cajero o vendedor que registró la venta.';
COMMENT ON COLUMN ventas.canal IS 'Canal de venta: tienda (presencial) u online.';
COMMENT ON COLUMN ventas.metodo_pago IS 'Forma de pago: efectivo, tarjeta_debito, tarjeta_credito, transferencia o billetera_movil.';
COMMENT ON COLUMN ventas.estado IS 'completada o anulada. Las ventas anuladas no cuentan como ingresos.';
COMMENT ON COLUMN ventas.subtotal IS 'Suma de cantidad × precio_unitario de las líneas, en USD, antes de descuentos e IVA.';
COMMENT ON COLUMN ventas.descuento_total IS 'Suma de descuentos de las líneas, en USD.';
COMMENT ON COLUMN ventas.iva IS 'IVA cobrado (15 % sobre la base gravada neta de descuentos), en USD.';
COMMENT ON COLUMN ventas.total IS 'Total facturado = subtotal − descuento_total + iva, en USD. Incluye IVA.';

CREATE TABLE detalle_ventas (
    detalle_id      integer PRIMARY KEY,
    venta_id        integer NOT NULL,
    producto_id     integer NOT NULL,
    cantidad        integer NOT NULL CHECK (cantidad > 0),
    precio_unitario numeric(12, 2) NOT NULL CHECK (precio_unitario > 0),
    descuento       numeric(12, 2) NOT NULL CHECK (descuento >= 0)
);
COMMENT ON TABLE detalle_ventas IS 'Líneas de cada venta: qué producto, cuántas unidades, a qué precio y con qué descuento. Base para unidades vendidas e ingresos por producto.';
COMMENT ON COLUMN detalle_ventas.detalle_id IS 'Identificador de la línea de venta.';
COMMENT ON COLUMN detalle_ventas.venta_id IS 'Venta (ticket) a la que pertenece la línea.';
COMMENT ON COLUMN detalle_ventas.producto_id IS 'Producto vendido.';
COMMENT ON COLUMN detalle_ventas.cantidad IS 'Unidades vendidas en la línea.';
COMMENT ON COLUMN detalle_ventas.precio_unitario IS 'Precio unitario cobrado en USD, sin IVA (puede diferir del precio de lista).';
COMMENT ON COLUMN detalle_ventas.descuento IS 'Descuento total aplicado a la línea en USD (no por unidad).';

CREATE TABLE inventario (
    sucursal_id  integer NOT NULL,
    producto_id  integer NOT NULL,
    fecha_corte  date NOT NULL,
    stock        integer NOT NULL CHECK (stock >= 0),
    stock_minimo integer NOT NULL CHECK (stock_minimo >= 0),
    PRIMARY KEY (sucursal_id, producto_id, fecha_corte)
);
COMMENT ON TABLE inventario IS 'Foto mensual del inventario: unidades en stock por sucursal y producto al cierre de cada mes.';
COMMENT ON COLUMN inventario.sucursal_id IS 'Sucursal del inventario.';
COMMENT ON COLUMN inventario.producto_id IS 'Producto inventariado.';
COMMENT ON COLUMN inventario.fecha_corte IS 'Último día del mes al que corresponde la foto de inventario.';
COMMENT ON COLUMN inventario.stock IS 'Unidades disponibles al cierre del mes. 0 indica quiebre de stock.';
COMMENT ON COLUMN inventario.stock_minimo IS 'Stock mínimo de seguridad; stock por debajo de este valor requiere reposición.';

CREATE TABLE devoluciones (
    devolucion_id     integer PRIMARY KEY,
    detalle_id        integer NOT NULL UNIQUE,
    venta_id          integer NOT NULL,
    fecha_devolucion  date NOT NULL,
    cantidad          integer NOT NULL CHECK (cantidad > 0),
    motivo            text NOT NULL,
    monto_reembolsado numeric(12, 2) NOT NULL CHECK (monto_reembolsado >= 0)
);
COMMENT ON TABLE devoluciones IS 'Devoluciones de productos. Siempre se devuelve la línea completa de detalle_ventas; las líneas devueltas no cuentan como ingresos.';
COMMENT ON COLUMN devoluciones.devolucion_id IS 'Identificador de la devolución.';
COMMENT ON COLUMN devoluciones.detalle_id IS 'Línea de venta devuelta (referencia a detalle_ventas, única).';
COMMENT ON COLUMN devoluciones.venta_id IS 'Venta original de la línea devuelta.';
COMMENT ON COLUMN devoluciones.fecha_devolucion IS 'Fecha en que se recibió la devolución (hasta 30 días después de la venta).';
COMMENT ON COLUMN devoluciones.cantidad IS 'Unidades devueltas (igual a la cantidad de la línea).';
COMMENT ON COLUMN devoluciones.motivo IS 'Motivo: defecto de fábrica, producto dañado, no cumple expectativas, talla o modelo incorrecto, error en el pedido.';
COMMENT ON COLUMN devoluciones.monto_reembolsado IS 'Monto reembolsado en USD, sin IVA (neto del descuento de la línea).';

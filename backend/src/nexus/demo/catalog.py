"""Static reference data for the demo: regions, branches, categories, product catalogue and names.

Prices are USD list prices as of 2026, before IVA. Brands are those commonly sold in Ecuadorian retail;
house brands ("Casa Bella", "Granja Andina", "Urbano") are fictional.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Final

from nexus.demo.calendar import COSTA, SIERRA

# -------------------------------------------------------------------------------------------------
# Geography
# -------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Region:
    id: int
    nombre: str
    descripcion: str
    regime: int  # school regime: SIERRA (Sierra-Amazonía) or COSTA (Costa-Galápagos)
    annual_growth: float


REGIONS: Final[tuple[Region, ...]] = (
    Region(
        1,
        "Sierra",
        "Región interandina: Pichincha, Azuay, Tungurahua, Loja, Imbabura, Chimborazo, Cotopaxi.",
        SIERRA,
        0.06,
    ),
    Region(
        2,
        "Costa",
        "Región litoral: Guayas, Manabí, El Oro, Esmeraldas, Santo Domingo, Los Ríos.",
        COSTA,
        0.09,
    ),
    Region(3, "Amazonía", "Región amazónica: Pastaza, Sucumbíos.", SIERRA, 0.07),
    Region(4, "Insular", "Región insular: Galápagos. Precios con recargo logístico.", COSTA, 0.0),
)

# Two-digit province codes used as the first digits of the Ecuadorian cédula.
PROVINCE_CODES: Final[dict[str, str]] = {
    "Azuay": "01",
    "Chimborazo": "06",
    "Cotopaxi": "05",
    "El Oro": "07",
    "Esmeraldas": "08",
    "Guayas": "09",
    "Imbabura": "10",
    "Loja": "11",
    "Los Ríos": "12",
    "Manabí": "13",
    "Pastaza": "16",
    "Pichincha": "17",
    "Tungurahua": "18",
    "Galápagos": "20",
    "Sucumbíos": "21",
    "Santo Domingo de los Tsáchilas": "23",
}

FORMAT_TRAFFIC: Final[dict[str, float]] = {
    "hipermercado": 1.9,
    "supermercado": 1.0,
    "express": 0.45,
}


@dataclass(frozen=True, slots=True)
class Branch:
    id: int
    codigo: str
    nombre: str
    ciudad: str
    provincia: str
    region_id: int
    formato: str
    metros_cuadrados: int
    fecha_apertura: date


BRANCHES: Final[tuple[Branch, ...]] = (
    Branch(
        1,
        "QUI-01",
        "Quito Norte - Carcelén",
        "Quito",
        "Pichincha",
        1,
        "hipermercado",
        6500,
        date(2012, 3, 15),
    ),
    Branch(
        2,
        "QUI-02",
        "Quito Iñaquito",
        "Quito",
        "Pichincha",
        1,
        "hipermercado",
        7200,
        date(2009, 8, 1),
    ),
    Branch(
        3,
        "QUI-03",
        "Quito Sur - Quitumbe",
        "Quito",
        "Pichincha",
        1,
        "supermercado",
        4200,
        date(2015, 5, 20),
    ),
    Branch(
        4, "QUI-04", "Cumbayá", "Quito", "Pichincha", 1, "supermercado", 3100, date(2018, 10, 10)
    ),
    Branch(
        5,
        "GYE-01",
        "Guayaquil Norte - Alborada",
        "Guayaquil",
        "Guayas",
        2,
        "hipermercado",
        7000,
        date(2008, 6, 2),
    ),
    Branch(
        6,
        "GYE-02",
        "Guayaquil Centro",
        "Guayaquil",
        "Guayas",
        2,
        "supermercado",
        3800,
        date(2011, 2, 14),
    ),
    Branch(
        7,
        "GYE-03",
        "Guayaquil Sur - Guasmo",
        "Guayaquil",
        "Guayas",
        2,
        "supermercado",
        3500,
        date(2016, 9, 1),
    ),
    Branch(
        8,
        "SAM-01",
        "Samborondón",
        "Samborondón",
        "Guayas",
        2,
        "hipermercado",
        5600,
        date(2014, 11, 20),
    ),
    Branch(
        9, "CUE-01", "Cuenca Centro", "Cuenca", "Azuay", 1, "supermercado", 4000, date(2010, 4, 12)
    ),
    Branch(
        10,
        "CUE-02",
        "Cuenca El Ejido",
        "Cuenca",
        "Azuay",
        1,
        "supermercado",
        3300,
        date(2017, 7, 3),
    ),
    Branch(
        11, "AMB-01", "Ambato", "Ambato", "Tungurahua", 1, "supermercado", 3000, date(2013, 10, 1)
    ),
    Branch(12, "LOJ-01", "Loja", "Loja", "Loja", 1, "supermercado", 2600, date(2016, 3, 8)),
    Branch(
        13, "IBA-01", "Ibarra", "Ibarra", "Imbabura", 1, "supermercado", 2500, date(2017, 5, 15)
    ),
    Branch(
        14, "RIO-01", "Riobamba", "Riobamba", "Chimborazo", 1, "express", 1500, date(2019, 2, 11)
    ),
    Branch(
        15, "LAT-01", "Latacunga", "Latacunga", "Cotopaxi", 1, "express", 1300, date(2020, 8, 17)
    ),
    Branch(16, "MAN-01", "Manta", "Manta", "Manabí", 2, "supermercado", 3400, date(2025, 7, 1)),
    Branch(
        17,
        "POR-01",
        "Portoviejo",
        "Portoviejo",
        "Manabí",
        2,
        "supermercado",
        2900,
        date(2015, 6, 22),
    ),
    Branch(
        18, "MAC-01", "Machala", "Machala", "El Oro", 2, "supermercado", 3000, date(2014, 1, 27)
    ),
    Branch(
        19, "ESM-01", "Esmeraldas", "Esmeraldas", "Esmeraldas", 2, "express", 1400, date(2021, 4, 5)
    ),
    Branch(
        20,
        "STD-01",
        "Santo Domingo",
        "Santo Domingo",
        "Santo Domingo de los Tsáchilas",
        2,
        "supermercado",
        2800,
        date(2016, 11, 14),
    ),
    Branch(21, "QUE-01", "Quevedo", "Quevedo", "Los Ríos", 2, "express", 1300, date(2022, 3, 21)),
    Branch(22, "PUY-01", "Puyo", "Puyo", "Pastaza", 3, "express", 1000, date(2022, 9, 5)),
    Branch(
        23, "LAG-01", "Nueva Loja", "Nueva Loja", "Sucumbíos", 3, "express", 1000, date(2023, 6, 12)
    ),
    Branch(
        24,
        "GAL-01",
        "Puerto Ayora",
        "Puerto Ayora",
        "Galápagos",
        4,
        "express",
        800,
        date(2020, 1, 20),
    ),
)

# Planted anomalies (ADR-0017). Referenced by code so tests can assert them.
STOCKOUT_BRANCH_CODE: Final = "QUI-02"
STOCKOUT_WINDOW: Final = (date(2026, 8, 10), date(2026, 8, 31))
CLOSURE_BRANCH_CODE: Final = "CUE-02"
CLOSURE_WINDOW: Final = (date(2025, 2, 10), date(2025, 2, 23))
RETURNS_SPIKE_WINDOW: Final = (date(2025, 6, 1), date(2025, 8, 31))
RETURNS_SPIKE_RATE: Final = 0.25
OUTLIER_ORDER_DATE: Final = date(2026, 3, 12)
OUTLIER_ORDER_BRANCH_CODE: Final = "GYE-01"
OUTLIER_ORDER_QUANTITY: Final = 120
INSULAR_PRICE_SURCHARGE: Final = 1.10
ANNUAL_PRICE_INCREASE: Final = 0.025
IVA_RATE: Final = 0.15
VOID_RATE: Final = 0.01

# -------------------------------------------------------------------------------------------------
# Categories and products
# -------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Category:
    id: int
    nombre: str
    prefijo: str
    descripcion: str
    share: float  # baseline share of ticket lines
    qty_extra_mean: float  # quantity = 1 + Poisson(qty_extra_mean)
    margin: float  # cost / price
    return_rate: float


CATEGORIES: Final[tuple[Category, ...]] = (
    Category(
        1,
        "Electrónica",
        "ELE",
        "Televisores, celulares, computadoras, audio y accesorios.",
        0.065,
        0.05,
        0.80,
        0.040,
    ),
    Category(
        2,
        "Electrodomésticos",
        "EDO",
        "Línea blanca y pequeños electrodomésticos de cocina y hogar.",
        0.055,
        0.03,
        0.76,
        0.035,
    ),
    Category(
        3,
        "Hogar",
        "HOG",
        "Textiles, menaje de cocina, organización y limpieza del hogar.",
        0.105,
        0.35,
        0.62,
        0.020,
    ),
    Category(
        4,
        "Alimentos y Bebidas",
        "ALI",
        "Abarrotes, lácteos, cárnicos, frutas, verduras y bebidas.",
        0.39,
        1.2,
        0.78,
        0.002,
    ),
    Category(
        5,
        "Cuidado Personal",
        "CPE",
        "Higiene, cuidado del cabello y de la piel, cosméticos y bebés.",
        0.14,
        0.6,
        0.66,
        0.004,
    ),
    Category(
        6,
        "Ropa y Calzado",
        "ROP",
        "Vestimenta y calzado para hombre, mujer y niños, uniformes escolares.",
        0.085,
        0.25,
        0.55,
        0.050,
    ),
    Category(
        7,
        "Útiles Escolares",
        "UTI",
        "Cuadernos, papelería, mochilas y material escolar.",
        0.04,
        1.4,
        0.60,
        0.010,
    ),
    Category(
        8,
        "Juguetes",
        "JUG",
        "Juguetes, juegos de mesa y artículos de Carnaval.",
        0.035,
        0.15,
        0.58,
        0.025,
    ),
    Category(
        9,
        "Deportes",
        "DEP",
        "Balones, camisetas de fútbol, fitness, ciclismo y camping.",
        0.045,
        0.10,
        0.63,
        0.020,
    ),
    Category(
        10,
        "Ferretería",
        "FER",
        "Herramientas, pintura, electricidad, cerrajería y construcción.",
        0.04,
        0.45,
        0.68,
        0.015,
    ),
)


@dataclass(frozen=True, slots=True)
class ProductSpec:
    nombre: str
    marca: str
    precio: float
    graba_iva: bool = True
    tags: frozenset[str] = field(default_factory=frozenset)
    lanzamiento: date | None = None


def _p(
    nombre: str, marca: str, precio: float, *tags: str, iva: bool = True, launch: date | None = None
) -> ProductSpec:
    return ProductSpec(nombre, marca, precio, iva, frozenset(tags), launch)


def _family(
    base: str,
    brands: tuple[str, ...],
    variants: tuple[tuple[str, float], ...],
    *tags: str,
    iva: bool = True,
) -> list[ProductSpec]:
    """Cartesian product brand × variant; brand-specific price noise is applied by the generator."""
    return [
        _p(f"{base} {variant} {brand}".replace("  ", " ").strip(), brand, price, *tags, iva=iva)
        for brand in brands
        for variant, price in variants
    ]


PRODUCTS: Final[dict[str, list[ProductSpec]]] = {
    "Electrónica": [
        *_family(
            "Smart TV LED",
            ("Samsung", "LG", "TCL", "Hisense"),
            (('32"', 249.0), ('43"', 349.0), ('50"', 449.0), ('55"', 549.0), ('65"', 799.0)),
            "tv",
        ),
        _p("Celular Galaxy A16 128 GB", "Samsung", 199.0),
        _p("Celular Galaxy A26 256 GB", "Samsung", 279.0),
        _p("Celular Galaxy A56 256 GB", "Samsung", 449.0),
        _p("Celular Galaxy A57 256 GB", "Samsung", 469.0, launch=date(2026, 3, 1)),
        _p("Celular Redmi 14C 128 GB", "Xiaomi", 149.0),
        _p("Celular Redmi Note 14 256 GB", "Xiaomi", 249.0),
        _p("Celular Redmi Note 15 256 GB", "Xiaomi", 269.0, launch=date(2025, 10, 1)),
        _p("Celular Moto G35 128 GB", "Motorola", 179.0),
        _p("Celular Moto G85 256 GB", "Motorola", 299.0),
        _p("Celular iPhone 16 128 GB", "Apple", 999.0),
        _p("Laptop 15 Core i5 16 GB", "HP", 699.0, "laptop"),
        _p("Laptop Pavilion 15 Core i7", "HP", 899.0, "laptop"),
        _p("Laptop IdeaPad Slim 3 Ryzen 5", "Lenovo", 649.0, "laptop"),
        _p("Laptop ThinkPad E14 Core i5", "Lenovo", 999.0, "laptop", "corporate_laptop"),
        _p("Laptop Vivobook 15 Core i3", "Asus", 599.0, "laptop"),
        _p("Laptop Inspiron 15 Core i5", "Dell", 749.0, "laptop"),
        _p("Audífonos Tune 520BT", "JBL", 59.0),
        _p("Audífonos WH-CH520", "Sony", 69.0),
        _p("Audífonos Redmi Buds 6", "Xiaomi", 29.0),
        _p("Audífonos Galaxy Buds FE", "Samsung", 89.0),
        _p("Parlante Bluetooth Flip 6", "JBL", 129.0),
        _p("Parlante Bluetooth Go 4", "JBL", 49.0),
        _p("Parlante Bluetooth ULT Field 1", "Sony", 119.0),
        _p("Tablet Galaxy Tab A9", "Samsung", 179.0),
        _p("Tablet Tab M11", "Lenovo", 199.0),
        _p("Smartwatch Redmi Watch 5", "Xiaomi", 79.0),
        _p("Smartwatch Galaxy Watch FE", "Samsung", 199.0),
        _p("Consola PlayStation 5 Slim", "Sony", 549.0),
        _p("Consola Nintendo Switch 2", "Nintendo", 499.0, launch=date(2025, 6, 1)),
        _p("Cargador USB-C 20 W", "Samsung", 19.0),
        _p("Mouse inalámbrico M170", "Logitech", 15.0),
        _p("Teclado K120", "Logitech", 14.0),
        _p("Memoria USB 64 GB", "Kingston", 9.0),
        _p("Cable HDMI 2 m", "Xtech", 8.0),
    ],
    "Electrodomésticos": [
        _p("Refrigeradora 11 pies", "Indurama", 649.0),
        _p("Refrigeradora 14 pies", "Indurama", 849.0),
        _p("Refrigeradora 12 pies", "Mabe", 699.0),
        _p("Refrigeradora Inverter 14 pies", "Samsung", 1099.0),
        _p("Refrigeradora 17 pies", "LG", 1299.0),
        _p("Cocina 4 quemadores", "Indurama", 329.0),
        _p("Cocina 6 quemadores", "Indurama", 459.0),
        _p('Cocina 30"', "Mabe", 499.0),
        _p("Cocina de inducción 4 zonas", "Indurama", 599.0),
        _p("Lavadora 17 kg", "LG", 549.0),
        _p("Lavadora 19 kg", "Samsung", 649.0),
        _p("Lavadora 16 kg", "Mabe", 479.0),
        _p("Lavadora 18 kg", "Whirlpool", 599.0),
        _p("Secadora 18 kg", "LG", 699.0),
        _p("Secadora 18 kg", "Whirlpool", 649.0),
        _p("Microondas 0.7 pies", "Samsung", 99.0),
        _p("Microondas 1.1 pies", "LG", 139.0),
        _p("Microondas 1.2 pies", "Panasonic", 159.0),
        _p("Licuadora Clásica 3 velocidades", "Oster", 49.0),
        _p("Licuadora Xpert 10 velocidades", "Oster", 89.0, "defective_batch"),
        _p("Licuadora 10 velocidades", "Black+Decker", 39.0),
        _p("Licuadora Professional", "Ninja", 129.0),
        _p("Arrocera 1.8 L", "Umco", 29.0),
        _p("Arrocera 10 tazas", "Oster", 39.0),
        _p("Freidora de aire 4 L", "Oster", 89.0),
        _p("Freidora de aire AF101", "Ninja", 129.0),
        _p("Freidora de aire 3.5 L", "Imaco", 59.0),
        _p("Cafetera 12 tazas", "Oster", 39.0),
        _p("Cafetera Essenza Mini", "Nespresso", 149.0),
        _p("Plancha a vapor", "Black+Decker", 25.0),
        _p("Plancha a vapor", "Oster", 29.0),
        _p("Aspiradora 1600 W", "Electrolux", 129.0),
        _p("Aspiradora de mano", "Black+Decker", 89.0),
        _p('Ventilador de mesa 16"', "Imaco", 35.0, "cooling"),
        _p("Ventilador de pedestal", "Taurus", 45.0, "cooling"),
        _p("Aire acondicionado split 12000 BTU", "LG", 499.0, "cooling"),
        _p("Aire acondicionado split 12000 BTU", "Midea", 449.0, "cooling"),
        _p("Extractor de jugos", "Oster", 59.0),
        _p("Batidora de mano", "Oster", 49.0),
        _p("Batidora de pedestal Artisan", "KitchenAid", 399.0),
        _p("Sanduchera", "Oster", 29.0),
    ],
    "Hogar": [
        *_family(
            "Juego de sábanas",
            ("Casa Bella",),
            (("1.5 plazas", 24.0), ("2 plazas", 29.0), ("King", 39.0)),
        ),
        *_family("Edredón", ("Casa Bella",), (("2 plazas", 49.0), ("King", 69.0)), "warm"),
        _p("Almohada estándar", "Casa Bella", 12.0),
        _p("Almohada viscoelástica", "Casa Bella", 29.0),
        _p("Toalla de baño", "Casa Bella", 9.99),
        _p("Juego de toallas 3 piezas", "Casa Bella", 24.0),
        _p("Juego de ollas 7 piezas", "Umco", 79.0),
        _p("Juego de ollas 7 piezas", "Tramontina", 99.0),
        _p("Sartén antiadherente 24 cm", "Tramontina", 19.0),
        _p("Sartén antiadherente 28 cm", "Tramontina", 25.0),
        _p("Vajilla 16 piezas", "Casa Bella", 39.0),
        _p("Vajilla 20 piezas", "Corelle", 89.0),
        _p("Juego de vasos 6 unidades", "Cristar", 12.0),
        _p("Juego de cubiertos 24 piezas", "Tramontina", 29.0),
        _p("Caja organizadora 30 L", "Pika", 12.0),
        _p("Caja organizadora 60 L", "Pika", 18.0),
        _p("Cortina blackout", "Casa Bella", 29.0),
        _p("Lámpara de mesa", "Casa Bella", 25.0),
        _p("Tacho de basura 20 L", "Pika", 14.0),
        _p("Escoba", "Pika", 4.99),
        _p("Trapeador", "Pika", 6.99),
        _p("Balde 12 L", "Pika", 3.99),
        _p("Detergente en polvo 2 kg", "Ariel", 8.99),
        _p("Detergente en polvo 1.5 kg", "Fab", 5.49),
        _p("Cloro 1 L", "Clorox", 1.89),
        _p("Suavizante 1 L", "Downy", 4.49),
        _p("Lavavajillas en crema 500 g", "Axion", 2.29),
        _p("Desinfectante multiusos 1 L", "Fabuloso", 2.49),
        _p("Papel higiénico 12 rollos", "Familia", 6.99, "staple"),
        _p("Servilletas 100 unidades", "Familia", 1.29),
        _p("Toallas de cocina 3 rollos", "Scott", 3.49),
        _p("Fundas de basura 10 unidades", "Pika", 1.99),
        _p("Ambientador en aerosol", "Glade", 3.29),
        _p("Insecticida en aerosol", "Raid", 4.99, "cooling"),
    ],
    "Alimentos y Bebidas": [
        *_family(
            "Arroz",
            ("Gustadina", "Real", "Conejo"),
            (("2 kg", 2.29), ("5 kg", 5.39)),
            "staple",
            iva=False,
        ),
        *_family(
            "Aceite vegetal",
            ("La Favorita", "Alesol", "Girasol"),
            (("1 L", 2.99), ("2 L", 5.69)),
            "staple",
            iva=False,
        ),
        *_family(
            "Azúcar blanca 2 kg", ("Valdez", "San Carlos"), (("", 2.19),), "staple", iva=False
        ),
        *_family(
            "Leche entera 1 L",
            ("Vita", "Toni", "Nutri", "Parmalat"),
            (("", 1.05),),
            "staple",
            iva=False,
        ),
        *_family("Yogur 1 L", ("Toni", "Alpina", "Chivería"), (("", 2.39),), iva=False),
        *_family("Queso fresco 500 g", ("Kiosko", "Floralp", "González"), (("", 3.99),), iva=False),
        *_family("Pan de molde", ("Supan", "Bimbo"), (("", 1.99),), "staple", iva=False),
        _p("Huevos 30 unidades", "Indaves", 4.99, "staple", iva=False),
        *_family(
            "Atún en aceite 180 g", ("Real", "Van Camp's", "Isabel"), (("", 1.59),), iva=False
        ),
        _p("Sardinas en salsa de tomate", "Real", 1.09, iva=False),
        *_family(
            "Fideo tallarín 400 g", ("Don Vittorio", "Oriental", "Sumesa"), (("", 0.99),), iva=False
        ),
        _p("Avena 400 g", "Quaker", 1.79, iva=False),
        _p("Café soluble 170 g", "Nescafé", 6.49),
        _p("Café soluble 200 g", "Sí Café", 4.99),
        _p("Café molido 340 g", "Juan Valdez", 8.49),
        *_family("Galletas", ("Amor", "Oreo", "Ricas", "Club Social"), (("paquete", 1.29),)),
        _p("Chocolate 72 % cacao 50 g", "Pacari", 3.49),
        _p("Chocolate Manicho", "Nestlé", 0.50),
        _p("Chocolate Galak", "Nestlé", 0.45),
        *_family("Snack", ("Doritos", "K-chitos", "Inalecsa", "Ruffles"), (("familiar", 1.25),)),
        *_family(
            "Gaseosa",
            ("Coca-Cola", "Pepsi", "Fanta", "Sprite", "Tropical", "Fioravanti"),
            (("3 L", 2.19),),
        ),
        _p("Gaseosa 500 ml", "Coca-Cola", 0.75),
        _p("Agua mineral 1.5 L", "Güitig", 0.99, "staple"),
        _p("Agua sin gas 1 L", "Tesalia", 0.75),
        _p("Agua sin gas 600 ml", "Dasani", 0.55),
        *_family("Jugo 1 L", ("Natura", "Del Valle", "Pulp"), (("", 1.79),)),
        _p("Cerveza Pilsener 6 pack", "Pilsener", 6.99),
        _p("Cerveza Club 6 pack", "Club", 7.99),
        _p("Cerveza Corona 6 pack", "Corona", 9.99),
        _p("Cerveza Budweiser 6 pack", "Budweiser", 7.49),
        *_family("Salchicha 500 g", ("Plumrose", "Don Diego", "Juris"), (("", 3.49),), iva=False),
        *_family(
            "Pollo entero por kg", ("Mr. Pollo", "Pronaca"), (("", 3.49),), "staple", iva=False
        ),
        _p("Carne molida de res 1 kg", "Granja Andina", 6.99, iva=False),
        _p("Banano por kg", "Granja Andina", 0.89, "staple", iva=False),
        _p("Papa chola 2 kg", "Granja Andina", 1.79, "staple", iva=False),
        _p("Tomate riñón por kg", "Granja Andina", 1.29, iva=False),
        _p("Cebolla colorada por kg", "Granja Andina", 1.19, iva=False),
        _p("Aguacate unidad", "Granja Andina", 0.69, iva=False),
        _p("Limón malla 1 kg", "Granja Andina", 1.49, iva=False),
        _p("Mermelada de frutilla 300 g", "Snob", 2.49),
        _p("Mayonesa 400 g", "Maggi", 2.79),
        _p("Salsa de tomate 400 g", "Los Andes", 1.89),
        _p("Sal yodada 1 kg", "Cris-Sal", 0.59, iva=False),
        _p("Harina de trigo 1 kg", "Ya", 1.29, iva=False),
        _p("Lenteja 500 g", "Granja Andina", 1.15, iva=False),
        _p("Fréjol rojo 500 g", "Granja Andina", 1.35, iva=False),
        _p("Mantequilla 250 g", "Kiosko", 2.69, iva=False),
        _p("Helado 1 L", "Pingüino", 4.49),
        _p("Hamburguesas 4 unidades", "Plumrose", 4.29, iva=False),
    ],
    "Cuidado Personal": [
        *_family(
            "Shampoo 400 ml",
            ("Head & Shoulders", "Pantene", "Sedal", "Herbal Essences"),
            (("", 6.49),),
        ),
        *_family("Acondicionador 400 ml", ("Pantene", "Sedal"), (("", 4.99),)),
        *_family("Jabón de tocador pack 3", ("Protex", "Dove", "Palmolive", "Lux"), (("", 2.99),)),
        *_family(
            "Pasta dental 100 ml",
            ("Colgate", "Colgate Total", "Sensodyne", "Oral-B"),
            (("", 3.49),),
        ),
        *_family("Cepillo dental", ("Colgate", "Oral-B"), (("", 2.49),)),
        *_family(
            "Desodorante", ("Rexona", "Axe", "Dove", "Nivea", "Lady Speed Stick"), (("", 4.29),)
        ),
        *_family("Crema corporal 400 ml", ("Nivea", "Johnson's", "Dove"), (("", 6.99),)),
        _p("Protector solar FPS 50", "Nivea", 14.99, "sun"),
        _p("Protector solar FPS 50", "Banana Boat", 16.99, "sun"),
        _p("Protector solar Anthelios FPS 50", "La Roche-Posay", 21.99, "sun"),
        _p("Perfume 212 VIP 80 ml", "Carolina Herrera", 89.0),
        _p("Perfume Boss Bottled 100 ml", "Hugo Boss", 79.0),
        _p("Perfume Ccori 50 ml", "Yanbal", 49.0),
        _p("Base de maquillaje Fit Me", "Maybelline", 12.99),
        _p("Labial Color Riche", "L'Oréal", 9.99),
        _p("Máscara de pestañas Lash Sensational", "Maybelline", 10.99),
        *_family(
            "Pañales etapa 3 x40", ("Pampers", "Huggies", "Panolini"), (("", 15.99),), iva=False
        ),
        *_family("Toallas sanitarias x10", ("Kotex", "Nosotras", "Always"), (("", 2.49),)),
        _p("Máquina de afeitar Mach3", "Gillette", 9.99),
        _p("Máquina de afeitar Hydro 5", "Schick", 8.99),
        _p("Secador de cabello 1875 W", "Remington", 29.99),
        _p("Secador de cabello 1875 W", "Conair", 34.99),
        _p("Plancha de cabello", "Remington", 39.99),
        _p("Alcohol antiséptico 1 L", "Weir", 3.49),
        _p("Enjuague bucal 500 ml", "Listerine", 5.99),
    ],
    "Ropa y Calzado": [
        _p("Camiseta básica hombre", "Urbano", 9.99),
        _p("Camiseta básica mujer", "Urbano", 9.99),
        _p("Jean 501 hombre", "Levi's", 59.99),
        _p("Jean 721 mujer", "Levi's", 54.99),
        _p("Jean clásico", "Pinto", 29.99),
        _p("Camisa formal hombre", "Pinto", 24.99),
        _p("Blusa mujer", "Urbano", 19.99),
        _p("Chompa impermeable", "Urbano", 39.99, "warm"),
        _p("Chompa polar", "Urbano", 24.99, "warm"),
        _p("Zapatos deportivos Revolution 7", "Nike", 69.99),
        _p("Zapatos deportivos Runfalcon", "Adidas", 59.99),
        _p("Zapatos deportivos Smash", "Puma", 54.99),
        _p("Zapatos deportivos Go Walk", "Skechers", 64.99),
        _p("Zapatos formales hombre", "Bunky", 49.99),
        _p("Zapatos formales mujer", "Bunky", 44.99),
        _p("Sandalias", "Havaianas", 19.99, "sun"),
        _p("Sandalias Classic Clog", "Crocs", 44.99, "sun"),
        _p("Botas de caucho", "Venus", 12.99),
        _p("Medias pack 3", "Urbano", 5.99),
        _p("Ropa interior hombre pack 3", "Urbano", 9.99),
        _p("Ropa interior mujer pack 3", "Urbano", 9.99),
        _p("Camisa escolar blanca", "Pinto", 9.99, "school_uniform"),
        _p("Pantalón escolar", "Pinto", 14.99, "school_uniform"),
        _p("Zapatos escolares", "Bunky", 29.99, "school_uniform"),
        _p("Pijama", "Urbano", 19.99, "warm"),
        _p("Vestido casual", "Urbano", 29.99),
        _p("Gorra", "Nike", 19.99, "sun"),
        _p("Bufanda", "Urbano", 9.99, "warm"),
        _p("Body bebé pack 3", "Urbano", 12.99),
        _p("Licra deportiva mujer", "Adidas", 29.99),
        _p("Short deportivo", "Nike", 19.99, "sun"),
        _p("Calentador deportivo", "Marathon", 39.99, "warm"),
    ],
    "Útiles Escolares": [
        *_family("Cuaderno universitario 100 hojas", ("Norma", "Estilo", "Scribe"), (("", 1.99),)),
        *_family("Cuaderno pequeño 60 hojas", ("Norma", "Estilo"), (("", 1.25),)),
        _p("Lápices HB caja 12", "Faber-Castell", 3.49),
        _p("Lápices HB caja 12", "Staedtler", 3.29),
        _p("Esferos caja 10", "BIC", 3.99),
        _p("Pinturas 12 colores", "Faber-Castell", 3.99),
        _p("Pinturas 24 colores", "Faber-Castell", 6.99),
        _p("Marcadores 12 unidades", "Pelikan", 4.49),
        _p("Borrador", "Pelikan", 0.35),
        _p("Sacapuntas", "Maped", 0.79),
        _p("Regla 30 cm", "Maped", 0.79),
        _p("Tijeras escolares", "Maped", 1.99),
        _p("Goma en barra", "Pelikan", 0.99),
        _p("Mochila escolar", "Totto", 39.99),
        _p("Mochila escolar", "Xtrem", 49.99),
        _p("Mochila escolar", "Chenson", 24.99),
        _p("Lonchera térmica", "Totto", 12.99),
        _p("Calculadora científica fx-82", "Casio", 19.99),
        _p("Resma papel bond A4", "Copy Laser", 4.99),
        _p("Carpeta archivadora", "Estilo", 2.49),
        _p("Cartulina pliego", "Estilo", 0.40),
        _p("Diccionario escolar", "Larousse", 14.99),
        _p("Juego geométrico", "Maped", 2.49),
        _p("Plastilina 12 barras", "Pelikan", 1.49),
        _p("Cinta adhesiva", "3M", 0.89),
        _p("Corrector líquido", "BIC", 1.19),
    ],
    "Juguetes": [
        _p("LEGO Classic caja mediana", "LEGO", 49.99),
        _p("LEGO City estación de policía", "LEGO", 69.99),
        _p("Muñeca Fashionista", "Barbie", 24.99),
        _p("Autos pack 5", "Hot Wheels", 7.99),
        _p("Muñeca Baby Alive", "Hasbro", 39.99),
        _p("Carro a control remoto", "Xtech Toys", 29.99),
        _p("Rompecabezas 1000 piezas", "Ravensburger", 19.99),
        _p("Juego de mesa Monopoly", "Hasbro", 34.99),
        _p("Juego de cartas UNO", "Mattel", 7.99),
        _p("Jenga", "Hasbro", 14.99),
        _p("Peluche oso 30 cm", "Casa Bella", 14.99),
        _p("Lanzador Nerf Elite", "Hasbro", 29.99),
        _p("Play-Doh pack 4", "Hasbro", 9.99),
        _p("Bicicleta infantil aro 16", "Monark", 129.99),
        _p("Scooter infantil", "Xtech Toys", 59.99),
        _p("Figura de acción Spider-Man", "Hasbro", 19.99),
        _p("Set de cocina de juguete", "Xtech Toys", 24.99),
        _p("Dron infantil", "Xtech Toys", 49.99),
        _p("Pistola de agua", "Xtech Toys", 9.99, "carnaval"),
        _p("Espuma de carnaval 400 ml", "Fiesta", 1.99, "carnaval"),
        _p("Globos de agua x100", "Fiesta", 2.49, "carnaval"),
        _p("Pelota de playa", "Xtech Toys", 4.99, "sun"),
    ],
    "Deportes": [
        _p("Balón de fútbol Tiro League", "Adidas", 29.99),
        _p("Balón de fútbol Strike", "Nike", 24.99),
        _p("Balón de vóley", "Molten", 34.99),
        _p("Balón de básquet", "Spalding", 29.99),
        _p("Camiseta Selección Ecuador 2026", "Marathon", 89.99, "worldcup"),
        _p("Camiseta Barcelona SC", "Marathon", 69.99, "club_costa"),
        _p("Camiseta Emelec", "Adidas", 69.99, "club_costa"),
        _p("Camiseta Liga de Quito", "Puma", 69.99, "club_sierra"),
        _p("Bicicleta montañera aro 29", "Monark", 349.99),
        _p("Bicicleta urbana", "Monark", 249.99),
        _p("Mancuernas 5 kg par", "Marathon", 29.99, "fitness"),
        _p("Colchoneta de yoga", "Marathon", 19.99, "fitness"),
        _p("Banda elástica de resistencia", "Marathon", 9.99, "fitness"),
        _p("Cuerda para saltar", "Marathon", 5.99, "fitness"),
        _p("Carpa 4 personas", "Coleman", 89.99),
        _p("Sleeping bag", "Coleman", 39.99, "warm"),
        _p("Termo deportivo 1 L", "Marathon", 14.99),
        _p("Guantes de gimnasio", "Marathon", 12.99, "fitness"),
        _p("Caminadora eléctrica", "Athletic", 599.99, "fitness"),
        _p("Bicicleta estática", "Athletic", 299.99, "fitness"),
        _p("Raqueta de tenis de mesa", "Butterfly", 14.99),
        _p("Pelotas de tenis x3", "Wilson", 6.99),
        _p("Patines en línea", "Marathon", 79.99),
        _p("Casco de ciclismo", "Giro", 34.99),
        _p("Proteína whey 2 lb", "Optimum Nutrition", 39.99, "fitness"),
    ],
    "Ferretería": [
        _p("Taladro percutor 650 W", "Bosch", 89.99),
        _p("Taladro percutor 550 W", "Black+Decker", 59.99),
        _p("Taladro inalámbrico 20 V", "DeWalt", 129.99),
        _p("Juego de destornilladores 6 piezas", "Stanley", 14.99),
        _p("Martillo de uña 16 oz", "Stanley", 12.99),
        _p("Alicate universal", "Stanley", 9.99),
        _p('Llave inglesa 10"', "Truper", 11.99),
        _p("Flexómetro 5 m", "Stanley", 6.99),
        _p("Caja de herramientas", "Truper", 24.99),
        _p("Pintura látex galón blanco", "Pintuco", 18.99),
        _p("Pintura látex galón blanco", "Cóndor", 16.99),
        _p("Pintura esmalte galón", "Unidas", 22.99),
        _p('Brocha 3"', "Truper", 2.99),
        _p("Rodillo de pintura", "Truper", 4.99),
        _p("Foco LED 9 W", "Philips", 2.49),
        _p("Foco LED 9 W", "Sylvania", 1.99),
        _p("Extensión eléctrica 5 m", "Xtech", 7.99),
        _p("Regleta 6 tomas", "Xtech", 9.99),
        _p("Candado 40 mm", "Yale", 9.99),
        _p("Cerradura de pomo", "Kwikset", 34.99),
        _p("Manguera 15 m", "Truper", 19.99),
        _p("Pala cuadrada", "Truper", 14.99),
        _p("Carretilla", "Truper", 69.99),
        _p("Silicona transparente", "Sika", 3.99),
        _p("Cinta aislante", "3M", 0.99),
        _p("Pegamento instantáneo", "Super Bonder", 1.99),
        _p('Clavos 2" 1 lb', "Ideal", 1.49),
        _p("Tornillos surtidos caja", "Ideal", 2.99),
        _p("Escalera de aluminio 5 pasos", "Truper", 79.99),
        _p("Cemento 50 kg", "Holcim", 8.49),
    ],
}

# -------------------------------------------------------------------------------------------------
# People
# -------------------------------------------------------------------------------------------------

FIRST_NAMES_F: Final = (
    "María",
    "María José",
    "Ana",
    "Gabriela",
    "Daniela",
    "Andrea",
    "Paola",
    "Verónica",
    "Carolina",
    "Fernanda",
    "Valeria",
    "Camila",
    "Sofía",
    "Isabella",
    "Lucía",
    "Diana",
    "Karla",
    "Mónica",
    "Patricia",
    "Rosa",
    "Carmen",
    "Jessica",
    "Estefanía",
    "Doménica",
    "Emilia",
    "Martina",
    "Victoria",
    "Elizabeth",
    "Johanna",
    "Nathaly",
    "Mishell",
    "Belén",
    "Cristina",
    "Silvia",
    "Gloria",
    "Lorena",
    "Tatiana",
    "Pamela",
    "Alejandra",
    "Mayra",
)
FIRST_NAMES_M: Final = (
    "José",
    "Juan",
    "Luis",
    "Carlos",
    "Jorge",
    "Andrés",
    "Diego",
    "Fernando",
    "Javier",
    "Miguel",
    "Francisco",
    "Pablo",
    "Santiago",
    "Sebastián",
    "Mateo",
    "Daniel",
    "David",
    "Alejandro",
    "Ricardo",
    "Roberto",
    "Marco",
    "Mauricio",
    "Patricio",
    "Fabián",
    "Galo",
    "Wilson",
    "Édison",
    "Byron",
    "Kevin",
    "Bryan",
    "Christian",
    "Esteban",
    "Gustavo",
    "Hugo",
    "Iván",
    "Jaime",
    "Julio",
    "Kléber",
    "Leonardo",
    "Xavier",
)
SURNAMES: Final = (
    "Zambrano",
    "Vera",
    "Cedeño",
    "Mendoza",
    "Bravo",
    "Moreira",
    "Macías",
    "Intriago",
    "Loor",
    "Alcívar",
    "Pérez",
    "García",
    "Rodríguez",
    "Sánchez",
    "Torres",
    "Romero",
    "Morales",
    "Castillo",
    "Chávez",
    "Guerrero",
    "Andrade",
    "Salazar",
    "Vásquez",
    "Ortiz",
    "Rivera",
    "Herrera",
    "Paredes",
    "Suárez",
    "Villacís",
    "Jaramillo",
    "Espinoza",
    "Ramírez",
    "Flores",
    "Muñoz",
    "Rojas",
    "Cevallos",
    "Aguirre",
    "Proaño",
    "Benítez",
    "Valencia",
    "Quishpe",
    "Guamán",
    "Chicaiza",
    "Pilco",
    "Tituaña",
    "Yánez",
    "Calderón",
    "León",
    "Montalvo",
    "Carrera",
    "Navarrete",
    "Ponce",
    "Jiménez",
    "Gómez",
    "Molina",
    "Ruiz",
    "Reyes",
    "Cruz",
    "Medina",
    "Vargas",
    "Castro",
    "Ortega",
    "Delgado",
    "Cabrera",
    "Arias",
    "Mora",
    "Ochoa",
    "Peña",
    "Velasco",
    "Garcés",
    "Erazo",
    "Borja",
    "Cordero",
    "Vintimilla",
    "Coronel",
    "Granda",
    "Ordóñez",
    "Ludeña",
    "Tapia",
    "Naranjo",
    "Barrera",
)
EMAIL_DOMAINS: Final = ("gmail.com", "hotmail.com", "outlook.com", "yahoo.com")
CORPORATE_EMAIL_DOMAIN: Final = "nexusretail.ec"

PAYMENT_METHODS: Final = (
    "efectivo",
    "tarjeta_debito",
    "tarjeta_credito",
    "transferencia",
    "billetera_movil",
)
# Shares at the start and at the end of the period (linearly interpolated).
PAYMENT_SHARES_START: Final = (0.42, 0.24, 0.22, 0.08, 0.04)
PAYMENT_SHARES_END: Final = (0.32, 0.25, 0.23, 0.08, 0.12)

RETURN_REASONS: Final = (
    "defecto de fábrica",
    "producto dañado",
    "no cumple expectativas",
    "talla o modelo incorrecto",
    "error en el pedido",
)

SEGMENTS: Final = ("ocasional", "frecuente", "corporativo")
SEGMENT_SHARES: Final = (0.70, 0.25, 0.05)
SEGMENT_PURCHASE_WEIGHT: Final = (1.0, 4.0, 2.0)

STAFF_PLAN: Final[dict[str, dict[str, int]]] = {
    "hipermercado": {
        "gerente de sucursal": 1,
        "supervisor": 2,
        "cajero": 12,
        "vendedor": 6,
        "bodeguero": 4,
    },
    "supermercado": {
        "gerente de sucursal": 1,
        "supervisor": 2,
        "cajero": 7,
        "vendedor": 3,
        "bodeguero": 2,
    },
    "express": {
        "gerente de sucursal": 1,
        "supervisor": 1,
        "cajero": 3,
        "vendedor": 1,
        "bodeguero": 1,
    },
}
SALARY_RANGES: Final[dict[str, tuple[int, int]]] = {
    "gerente general": (5200, 6000),
    "gerente regional": (3200, 3800),
    "gerente de sucursal": (1800, 2600),
    "supervisor": (900, 1250),
    "cajero": (482, 560),
    "vendedor": (520, 680),
    "bodeguero": (482, 580),
}
SELLING_ROLES: Final = ("cajero", "vendedor")

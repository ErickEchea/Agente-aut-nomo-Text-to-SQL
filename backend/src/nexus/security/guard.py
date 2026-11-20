"""Deterministic pre-LLM guard for questions (ADR-0005, prompt-injection posture).

Runs before any model call. It refuses requests to modify data and well-known injection phrasings,
so those never depend on the model "behaving". Analytical questions *about* changes ("¿cuántos
productos se devolvieron?") are not affected: only imperative/command forms and SQL commands match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class GuardCategory(StrEnum):
    DATA_MODIFICATION = "data_modification"
    PROMPT_INJECTION = "prompt_injection"
    PRIVILEGE_REQUEST = "privilege_request"


@dataclass(frozen=True, slots=True)
class GuardVerdict:
    allowed: bool
    category: GuardCategory | None = None
    matched: str = ""

    @property
    def reason(self) -> str:
        match self.category:
            case GuardCategory.DATA_MODIFICATION:
                return (
                    "NEXUS solo consulta datos: no puede borrar, crear ni modificar información. "
                    "Puedes preguntar por los datos, por ejemplo «¿cuántas devoluciones hubo este mes?»."
                )
            case GuardCategory.PROMPT_INJECTION:
                return (
                    "La pregunta intenta cambiar las reglas del asistente. Formula una pregunta de negocio "
                    "sobre ventas, productos, sucursales, clientes o inventario."
                )
            case GuardCategory.PRIVILEGE_REQUEST:
                return "NEXUS no gestiona permisos ni accesos. Contacta a un administrador."
            case None:
                return ""


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return " ".join("".join(c for c in decomposed if not unicodedata.combining(c)).split())


_IMPERATIVE_ES = (
    r"borra|borren|elimina|eliminen|suprime|actualiza|actualicen|modifica|modifiquen|inserta|inserten|"
    r"agrega|agreguen|anade|crea|creen|vacia|vacien|trunca|cambia|cambien|reemplaza|sobrescribe|"
    r"resetea|restablece|desactiva|bloquea|ejecuta|corre"
)
_INFINITIVE_ES = (
    r"borrar|eliminar|suprimir|actualizar|modificar|insertar|agregar|anadir|crear|vaciar|truncar|"
    r"cambiar|reemplazar|sobrescribir|ejecutar"
)
_DATA_OBJECTS = (
    r"tabla|tablas|base|datos|registro|registros|fila|filas|columna|columnas|cliente|clientes|producto|"
    r"productos|venta|ventas|sucursal|sucursales|precio|precios|inventario|devoluciones|empleado|"
    r"empleados|usuario|usuarios|esquema|indice"
)

PATTERNS: tuple[tuple[GuardCategory, re.Pattern[str]], ...] = (
    (
        GuardCategory.PROMPT_INJECTION,
        re.compile(
            r"\b(ignora|ignorar|olvida|olvidar|omite|desobedece)\b.{0,40}\b(instrucciones|reglas|indicaciones|"
            r"restricciones|prompt)\b|\bignore\b.{0,40}\b(instructions|rules|prompt)\b|"
            r"\b(prompt|mensaje|instrucciones)\s+(de|del)\s+sistema\b|\bsystem\s+prompt\b|"
            r"\b(ahora\s+eres|eres\s+ahora|actua\s+como|act\s+as|you\s+are\s+now|jailbreak|modo\s+desarrollador)\b"
        ),
    ),
    (
        GuardCategory.DATA_MODIFICATION,
        re.compile(
            r"\b(drop|truncate|alter|grant|revoke|vacuum|copy)\s+\w+|\bdelete\s+from\b|\binsert\s+into\b|"
            r"\bupdate\s+\w+\s+set\b|\bcreate\s+(table|function|role|user|index|schema|view)\b|"
            r"\bpg_sleep\b|\bset_config\b"
        ),
    ),
    (
        GuardCategory.DATA_MODIFICATION,
        re.compile(
            rf"(^|[¿?!.,;:]\s*|\b(?:por\s+favor|puedes|podrias|quiero|necesito|debes)\s+)"
            rf"(?:{_IMPERATIVE_ES}|{_INFINITIVE_ES})\b(?=.{{0,60}}\b(?:{_DATA_OBJECTS})\b)"
        ),
    ),
    (
        GuardCategory.DATA_MODIFICATION,
        re.compile(r"^(?:delete|drop|update|insert|truncate|remove|erase)\b"),
    ),
    (
        GuardCategory.PRIVILEGE_REQUEST,
        re.compile(
            r"\b(dame|darme|otorga|concede|asigna)\b.{0,30}\b(permisos?|privilegios?|acceso\s+de\s+escritura|"
            r"rol\s+de\s+administrador|superusuario)\b"
        ),
    ),
)


def check_question(question: str) -> GuardVerdict:
    text = _normalize(question)
    for category, pattern in PATTERNS:
        match = pattern.search(text)
        if match:
            return GuardVerdict(allowed=False, category=category, matched=match.group(0).strip())
    return GuardVerdict(allowed=True)

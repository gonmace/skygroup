"""Estado visual de un registro: rojo (vacío), amarillo (con datos) o verde (concluido).

Qué cuenta como «con datos» lo aportan otras apps (fotos, pasos, mapas), que registran aquí su fuente con
`registrar_fuente(func)`. `func(modelo)` devuelve una expresión `Exists(...)` correlacionada con `OuterRef('pk')`.
Así `reg_base` no depende de ellas y el estado se completa a medida que se instalan.
"""
from django.db.models import BooleanField, Case, ExpressionWrapper, IntegerField, Q, Value, When

_FUENTES = []

AMARILLO, VERDE, ROJO = 1, 2, 3   # orden_estado: en proceso, concluido, vacío


def registrar_fuente(func):
    _FUENTES.append(func)
    return func


class EstadoQuerySet:
    """Mixin para el QuerySet de un registro concluible."""

    def with_estado(self):
        """Anota `has_widgets` (el registro tiene datos) y `orden_estado` (1 en proceso, 2 concluido, 3 vacío)."""
        if _FUENTES:
            tiene = _FUENTES[0](self.model)
            for f in _FUENTES[1:]:
                tiene = tiene | f(self.model)
        else:
            tiene = ExpressionWrapper(Value(False), output_field=BooleanField())
        return self.annotate(has_widgets=tiene).annotate(orden_estado=Case(
            When(concluido=False, has_widgets=True, then=Value(AMARILLO)),
            When(concluido=True, then=Value(VERDE)),
            default=Value(ROJO), output_field=IntegerField(),
        ))


def color_estado(registro):
    """'verde' | 'amarillo' | 'rojo' (requiere haber anotado con `with_estado`)."""
    if registro.concluido:
        return 'verde'
    return 'amarillo' if getattr(registro, 'has_widgets', False) else 'rojo'

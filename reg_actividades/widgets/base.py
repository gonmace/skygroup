"""Contrato de un widget de paso.

Un widget lee sus campos del POST (`<slug>__<campo>`), los valida y los guarda como `{…}` bajo su slug en
`DatoPaso.datos`. `nivel` resume su estado: 0 sin configurar · 1 vacío · 2 parcial · 3 completo."""
from dataclasses import dataclass, field


@dataclass
class Contexto:
    """Lo que un widget puede necesitar saber de dónde está: el registro, el paso y quién lo mira."""
    registro: object
    paso: object
    clave: str                    # clave corta del tipo de registro (txtss, construccion…)
    user: object = None
    puede_escribir: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def etapa(self):
        return self.paso.nombre


class WidgetBase:
    slug = ''
    nombre = ''
    plantilla = ''
    guarda_datos = True   # False: sus datos viven en otro modelo (fotos)
    icono = ''            # icono del botón del paso (components/icon.html); vacío = el de `servicios.ICONOS` o «clipboard»

    def nombre_campo(self, campo):
        return f'{self.slug}__{campo}'

    def validar_config(self, config):
        return []

    def leer(self, post, files, config, ctx=None):
        """(datos, errores) a partir del POST del paso. `ctx` (puede faltar) trae quién guarda y, en
        `ctx.extra['previos']`, lo que ya estaba guardado de este widget."""
        return {}, []

    def persistir(self, datos, config, ctx):
        """Gancho para widgets cuyos datos también viven en otros modelos (hallazgos…). `guardar_paso` lo llama
        DENTRO de la misma transacción, solo si todos los widgets del paso validaron. Por defecto no hace nada."""

    def nivel(self, datos, config, ctx):
        return 0 if not datos else 3

    def contexto(self, datos, config, ctx):
        """Variables extra para la plantilla del widget."""
        return {}

    def vacio(self, datos):
        """True si no hay ningún valor capturado (para la marca `tiene_datos`)."""
        return not any(_lleno(v) for v in (datos or {}).values())


def _lleno(valor):
    if isinstance(valor, bool):
        return True            # un toggle guardado (aunque sea «No») es una respuesta
    if isinstance(valor, (list, tuple, dict)):
        return bool(valor)
    return valor not in (None, '')


def texto_numero(valor):
    """Número como texto con punto decimal (nunca localizado) para `<input>`; '' si no hay valor."""
    if valor is None or valor == '':
        return ''
    try:
        f = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    return str(int(f)) if f.is_integer() else repr(f)

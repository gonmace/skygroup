"""Datos estructurales de un poste (TX/TSS). Mismas claves que `poste_form_widget` del original
(reg.tekon-rl.cl), para que `DatoPaso.datos` migrado se lea sin transformar."""
from . import registrar
from .base import WidgetBase

OBLIGATORIOS = (
    ('tipo_estructura', 'Tipo de estructura'),
    ('altura', 'Altura'),
    ('tension', 'Tensión'),
)
TEXTOS = ('tipo_estructura', 'altura', 'tension', 'placa_poste', 'obstaculos', 'empresa_energia', 'comentario')
TOGGLES = (
    ('luminaria', 'Luminaria'),
    ('red_protegida', 'Red protegida'),
    ('acceso_camion_grua', 'Acceso camión grúa'),
    ('vegetacion', 'Vegetación'),
    ('antena_microondas', 'Antena microondas'),
)
LIMITE_TEXTO = 500
LIMITE_COMENTARIO = 2000


@registrar
class PosteFormWidget(WidgetBase):
    slug = 'poste_form_widget'
    nombre = 'Datos del poste'
    plantilla = 'reg_actividades/widgets/poste.html'

    def leer(self, post, files, config, ctx=None):
        datos, errores = {}, []
        for campo in TEXTOS:
            limite = LIMITE_COMENTARIO if campo == 'comentario' else LIMITE_TEXTO
            datos[campo] = (post.get(self.nombre_campo(campo)) or '').strip()[:limite]
        for campo, _label in TOGGLES:
            datos[campo] = self.nombre_campo(campo) in post
        for campo, label in OBLIGATORIOS:
            if not datos[campo]:
                errores.append(f'{label}: es obligatorio.')
        return datos, errores

    def nivel(self, datos, config, ctx):
        datos = datos or {}
        llenos = sum(1 for c in TEXTOS if str(datos.get(c, '')).strip())
        return 1 if llenos == 0 else (3 if llenos == len(TEXTOS) else 2)

    def contexto(self, datos, config, ctx):
        guardado = bool(datos)
        datos = datos or {}

        def valor(campo):   # sin datos guardados se ofrece el valor por defecto de la configuración
            return datos.get(campo) or ('' if guardado else config.get(f'default_{campo}', ''))

        acceso_grua = datos.get('acceso_camion_grua') if guardado else bool(config.get('default_acceso_camion_grua'))
        return {
            'etiqueta': config.get('label', self.nombre),
            'textos': {c: {'campo': self.nombre_campo(c), 'valor': valor(c)} for c in TEXTOS},
            'toggles': [{'campo': self.nombre_campo(c), 'label': label,
                         'marcado': bool(acceso_grua if c == 'acceso_camion_grua' else datos.get(c))}
                        for c, label in TOGGLES],
        }

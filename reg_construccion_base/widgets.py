"""Widgets de los pasos de «Construcción (base)»: hallazgos de la visita y seguimiento de los anteriores."""
from reg_actividades.widgets import registrar
from reg_actividades.widgets.base import WidgetBase

from . import servicios
from .models import Hallazgo, SeguimientoHallazgo

Resultado = SeguimientoHallazgo.Resultado


@registrar
class HallazgosWidget(WidgetBase):
    """Hallazgos levantados en ESTA visita. Cada uno es una entidad aparte (con fotos, severidad y plazo) que se
    crea desde su propia pantalla; aquí se listan y se puede declarar «sin hallazgos»."""
    slug = 'hallazgos_widget'
    nombre = 'Hallazgos'
    plantilla = 'reg_construccion_base/widgets/hallazgos.html'
    icono = 'eye'
    CAMPO = 'sin_hallazgos'

    def leer(self, post, files, config, ctx=None):
        # Solo se guarda cuando está marcado: un `False` guardado contaría como dato (ver `_lleno`) y pintaría la visita.
        return ({self.CAMPO: True} if self.nombre_campo(self.CAMPO) in post else {}), []

    def _hallazgos(self, ctx):
        return ctx.registro.hallazgos.filter(is_deleted=False).order_by('numero') if getattr(ctx.registro, 'pk', None) else []

    def nivel(self, datos, config, ctx):
        if (datos or {}).get(self.CAMPO):
            return 3
        return 3 if ctx is not None and self._hallazgos(ctx).exists() else 1

    def html_pdf(self, pw, datos, ctx, archivo):
        from html import escape
        hallazgos = list(self._hallazgos(ctx))
        etiqueta = escape(pw.config.get('label') or self.nombre)
        if not hallazgos:
            return f'<h3>{etiqueta}</h3><p>Sin hallazgos en esta visita.</p>' if (datos or {}).get(self.CAMPO) else ''
        filas = ''.join(
            f'<tr><td>{h.codigo}</td><td>{h.get_tipo_display()}</td>'
            f'<td>{h.get_severidad_display()}</td><td>{escape(h.descripcion)}</td><td>{escape(h.responsable)}</td>'
            f'<td>{h.plazo.strftime("%d/%m/%Y") if h.plazo else ""}</td></tr>'
            for h in hallazgos)
        return (f'<h3>{etiqueta}</h3><table width="100%"><tr><th>Cód.</th><th>Tipo</th><th>Severidad</th>'
                f'<th>Descripción</th><th>Responsable</th><th>Plazo</th></tr>{filas}</table>')

    def contexto(self, datos, config, ctx):
        hallazgos = list(self._hallazgos(ctx))
        return {'campo': self.nombre_campo(self.CAMPO), 'sin_hallazgos': bool((datos or {}).get(self.CAMPO)),
                'hallazgos': hallazgos, 'total': len(hallazgos), 'etiqueta': config.get('label', self.nombre)}


@registrar
class SeguimientoWidget(WidgetBase):
    """Verificación de los hallazgos abiertos de visitas anteriores. Es el único camino para cerrarlos. Si no hay
    hallazgos pendientes el widget queda completo solo."""
    slug = 'seguimiento_widget'
    nombre = 'Verificación de observaciones previas'
    plantilla = 'reg_construccion_base/widgets/seguimiento.html'
    icono = 'check-square'

    def _campo(self, que, pk):
        return self.nombre_campo(f'{que}_{pk}')

    def leer(self, post, files, config, ctx=None):
        items, errores = [], []
        validos = {r.value for r in Resultado}
        for h in servicios.pendientes_de_seguimiento(ctx.registro):
            estado = (post.get(self._campo('estado', h.pk)) or '').strip()
            comentario = (post.get(self._campo('comentario', h.pk)) or '').strip()[:1000]
            if not estado:
                continue   # sin verificar todavía
            if estado not in validos:
                errores.append(f'{h.codigo}: resultado inválido.')
                continue
            items.append({'hallazgo': h.pk, 'estado': estado, 'comentario': comentario})
        return {'items': items}, errores

    def persistir(self, datos, config, ctx):
        visita = ctx.registro
        pendientes = {h.pk: h for h in servicios.pendientes_de_seguimiento(visita)}
        elegidos = []
        for it in datos.get('items', []):
            h = pendientes.get(it['hallazgo'])
            if h is None:
                continue
            servicios.registrar_seguimiento(visita, h, it['estado'], it['comentario'])
            elegidos.append(h.pk)
        servicios.quitar_seguimientos_salvo(visita, elegidos)

    def nivel(self, datos, config, ctx):
        pendientes = list(servicios.pendientes_de_seguimiento(ctx.registro).values_list('pk', flat=True))
        if not pendientes:
            return 3
        hechos = {i['hallazgo'] for i in (datos or {}).get('items', [])}
        n = len(hechos & set(pendientes))
        return 1 if n == 0 else (3 if n == len(pendientes) else 2)

    def vacio(self, datos):
        return not (datos or {}).get('items')

    def html_pdf(self, pw, datos, ctx, archivo):
        from html import escape
        seguimientos = list(ctx.registro.seguimientos.select_related('hallazgo').order_by('hallazgo__numero'))
        if not seguimientos:
            return ''
        filas = ''.join(f'<tr><td>{s.hallazgo.codigo}</td><td>{escape(s.hallazgo.descripcion)}</td>'
                        f'<td>{s.get_estado_display()}</td><td>{escape(s.comentario)}</td></tr>' for s in seguimientos)
        return (f'<h3>{escape(pw.config.get("label") or self.nombre)}</h3><table width="100%"><tr><th>Cód.</th>'
                f'<th>Observación</th><th>Resultado</th><th>Comentario</th></tr>{filas}</table>')

    def contexto(self, datos, config, ctx):
        previos = {i['hallazgo']: i for i in (datos or {}).get('items', [])}
        filas = []
        for h in servicios.pendientes_de_seguimiento(ctx.registro):
            it = previos.get(h.pk, {})
            filas.append({'h': h, 'estado': it.get('estado', ''), 'comentario': it.get('comentario', ''),
                          'campo_estado': self._campo('estado', h.pk), 'campo_comentario': self._campo('comentario', h.pk),
                          'etapa': f'seguimiento-{h.pk}'})
        return {'filas': filas, 'resultados': Resultado.choices, 'etiqueta': config.get('label', self.nombre)}

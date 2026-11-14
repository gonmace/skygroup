from reg_base.geo import distancia_m, formatear_distancia

from . import registrar
from .base import WidgetBase, texto_numero


def _coordenada(valor, minimo, maximo):
    valor = str(valor or '').strip().replace(',', '.')
    if not valor:
        return None, None
    try:
        v = float(valor)
    except ValueError:
        return None, 'valor inválido'
    if not (minimo <= v <= maximo):
        return None, f'fuera de rango ({minimo} a {maximo})'
    return v, None


@registrar
class UbicacionWidget(WidgetBase):
    slug = 'ubicacion_widget'
    nombre = 'Ubicación GPS'
    plantilla = 'reg_actividades/widgets/ubicacion.html'

    def leer(self, post, files, config, ctx=None):
        errores = []
        lat, e1 = _coordenada(post.get(self.nombre_campo('lat')), -90, 90)
        lon, e2 = _coordenada(post.get(self.nombre_campo('lon')), -180, 180)
        if e1:
            errores.append(f'Latitud: {e1}.')
        if e2:
            errores.append(f'Longitud: {e2}.')
        if not errores and (lat is None) != (lon is None):
            errores.append('Indica latitud y longitud juntas.')
        if errores:   # se devuelve lo escrito para volver a mostrarlo junto al error
            return {'lat': post.get(self.nombre_campo('lat'), ''), 'lon': post.get(self.nombre_campo('lon'), '')}, errores
        datos = {}
        if lat is not None:
            datos = {'lat': lat, 'lon': lon}
            precision, _e = _coordenada(post.get(self.nombre_campo('accuracy')), 0, 100000)
            if precision is not None:
                datos['accuracy'] = precision
        return datos, []

    def nivel(self, datos, config, ctx):
        datos = datos or {}
        return 3 if datos.get('lat') is not None and datos.get('lon') is not None else 1

    def contexto(self, datos, config, ctx):
        datos = datos or {}
        proyecto = getattr(ctx.registro, 'proyecto', None)
        distancia = None
        plat, plon = proyecto.coordenada_principal if proyecto else (None, None)
        if datos.get('lat') is not None and plat is not None:
            distancia = distancia_m(plat, plon, datos['lat'], datos['lon'])
        # Calidad de la precisión del GPS y tolerancia del desfase (mismos umbrales que el informe: 150 / 200 m).
        acc = datos.get('accuracy')
        precision_texto, precision_clase = '', ''
        if acc is not None:
            precision_texto, precision_clase = (
                ('Precisión buena', 'badge-success') if acc <= 20 else
                ('Precisión media', 'badge-warning') if acc <= 50 else ('Precisión baja', 'badge-ghost'))
            precision_texto += f' (±{acc:.0f} m)'
        tolerancia_texto, tolerancia_clase = '', 'badge-ghost'
        if distancia is not None:
            tolerancia_texto, tolerancia_clase = (
                ('dentro de tolerancia', 'badge-success') if distancia <= 150 else
                ('revisar', 'badge-warning') if distancia <= 200 else ('fuera de tolerancia', 'badge-warning'))
        return {
            'ejes_dms': (('lat', 'Latitud', (('S', 'Sur'), ('N', 'Norte'))),
                         ('lon', 'Longitud', (('W', 'Oeste'), ('E', 'Este')))),
            'precision_texto': precision_texto, 'precision_clase': precision_clase,
            'tolerancia_texto': tolerancia_texto, 'tolerancia_clase': tolerancia_clase,
            'campo_lat': self.nombre_campo('lat'), 'campo_lon': self.nombre_campo('lon'),
            'campo_acc': self.nombre_campo('accuracy'),
            'lat': texto_numero(datos.get('lat')), 'lon': texto_numero(datos.get('lon')),
            'accuracy': texto_numero(datos.get('accuracy')),
            'etiqueta': config.get('label', self.nombre),
            'distancia': formatear_distancia(distancia) if distancia is not None else None,
            'referencia': ctx.registro.proyecto.nombre if proyecto else '',
            'mapa_url': f'https://maps.google.com/?q={datos["lat"]},{datos["lon"]}' if datos.get('lat') is not None else None,
        }

"""Widgets de fotos: los archivos viven en `reg_fotos` (por etapa); aquí solo se calcula el estado y se enlaza a la galería."""
from django.contrib.contenttypes.models import ContentType

from . import registrar
from .base import WidgetBase


def _entero(config, *claves, defecto):
    for c in claves:
        if c in config:
            return config[c]
    return defecto


class _FotosBase(WidgetBase):
    guarda_datos = False
    insignia_texto = ''   # texto fijo en la esquina del botón (en vez del contador); la config `insignia` lo reemplaza
    plantilla = 'reg_actividades/widgets/camera.html'

    def validar_config(self, config):
        errores = []
        for clave in ('min_photos', 'foto_min'):
            if clave in config and not (isinstance(config[clave], int) and config[clave] >= 0):
                errores.append(f'{clave} debe ser un entero mayor o igual a 0.')
        if 'opcional' in config and not isinstance(config['opcional'], bool):
            errores.append('opcional debe ser verdadero o falso.')
        if 'etapa' in config and not (isinstance(config['etapa'], str) and config['etapa'].strip()):
            errores.append('etapa debe ser un texto no vacío.')
        if 'exigir_metadatos' in config and not isinstance(config['exigir_metadatos'], bool):
            errores.append('exigir_metadatos debe ser verdadero o falso.')
        if 'insignia' in config and not (isinstance(config['insignia'], str) and len(config['insignia']) <= 30):
            errores.append('insignia debe ser un texto de hasta 30 caracteres.')
        return errores

    def etapa(self, config, ctx):
        return config.get('etapa') or ctx.etapa

    def _fotos(self, config, ctx):
        from reg_fotos.models import Foto
        ct = ContentType.objects.get_for_model(type(ctx.registro))
        return Foto.objects.filter(content_type=ct, object_id=ctx.registro.pk, etapa=self.etapa(config, ctx))

    def minimo(self, config):
        return _entero(config, 'foto_min', 'min_photos', defecto=1)

    def nivel(self, datos, config, ctx):
        n = self._fotos(config, ctx).count()
        return 1 if n == 0 else (2 if n < self.minimo(config) else 3)

    def contexto(self, datos, config, ctx):
        fotos = list(self._fotos(config, ctx))
        return {'fotos': fotos[:12], 'total': len(fotos), 'minimo': self.minimo(config),
                'etapa': self.etapa(config, ctx), 'etiqueta': config.get('label', self.nombre),
                'exigir_metadatos': bool(config.get('exigir_metadatos'))}


@registrar
class CameraWidget(_FotosBase):
    slug = 'camera_widget'
    nombre = 'Fotos'


@registrar
class CameraLibroWidget(_FotosBase):
    """Segunda cámara de un paso: sus fotos van a una etapa propia (config `etapa`, por defecto «obra_libro»)."""
    slug = 'camera_libro_widget'
    nombre = 'Libro de obras'
    insignia_texto = 'Libro de Obras'   # el ícono solo no basta para reconocerlo: el botón lleva su nombre en la esquina

    def etapa(self, config, ctx):
        return config.get('etapa') or 'obra_libro'


@registrar
class ImgsDescWidget(_FotosBase):
    """Una foto por cada descripción pedida (config `descripciones`, separadas por coma)."""
    slug = 'imgs_desc_widget'
    nombre = 'Fotos con descripción'
    plantilla = 'reg_actividades/widgets/imgs_desc.html'

    @staticmethod
    def descripciones(config):
        crudo = config.get('descripciones', '')
        if isinstance(crudo, str):
            crudo = crudo.split(',')
        return [str(d).strip() for d in crudo if str(d).strip()]

    def validar_config(self, config):
        errores = super().validar_config(config)
        if not self.descripciones(config):
            errores.append("Indica «descripciones» con al menos un valor (separados por coma).")
        return errores

    def nivel(self, datos, config, ctx):
        pedidas = self.descripciones(config)
        presentes = {f.descripcion for f in self._fotos(config, ctx)}
        llenas = sum(1 for d in pedidas if d in presentes)
        return 1 if llenas == 0 else (3 if llenas == len(pedidas) else 2)

    def contexto(self, datos, config, ctx):
        por_desc, fotos = {}, list(self._fotos(config, ctx))
        for f in fotos:
            por_desc.setdefault(f.descripcion, f)
        espacios = [{'descripcion': d, 'foto': por_desc.get(d)} for d in self.descripciones(config)]
        en_espacio = {e['foto'].pk for e in espacios if e['foto']}
        extras = [f for f in fotos if f.pk not in en_espacio]   # descripción no pedida o repetida: no se pierden de vista
        # Contador (p. ej. 8/5): todas las fotos tomadas, con o sin descripción, frente a las descripciones pedidas.
        return {'etiqueta': config.get('label', self.nombre), 'etapa': self.etapa(config, ctx),
                'total': len(fotos), 'minimo': len(espacios),
                'espacios': espacios, 'extras': extras}

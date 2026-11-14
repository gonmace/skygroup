"""Genera las imágenes de Google Maps (mandato y desfase) de los TX/TSS que aún no las tienen o cuyas coordenadas cambiaron.

    manage.py generar_mapas_txtss --empresa pti --dry-run     # cuántos registros lo necesitan
    manage.py generar_mapas_txtss --empresa pti --limite 50   # genera (cada imagen es una consulta a Google)
"""
from django.core.management.base import BaseCommand, CommandError

from reg_actividades import mapas
from reg_txtss.models import RegTxtss


class Command(BaseCommand):
    help = 'Genera los mapas de Google de los TX/TSS que les falten.'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', help='Slug de la empresa (por defecto, todas).')
        parser.add_argument('--limite', type=int, default=0, help='Máximo de registros a procesar (0 = todos).')
        parser.add_argument('--dry-run', action='store_true', help='Solo cuenta los registros pendientes; no llama a Google.')

    def handle(self, *args, empresa=None, limite=0, dry_run=False, **opciones):
        if not mapas.hay_clave():
            raise CommandError('No hay clave de Google Maps: cárgala en Plataforma → Credenciales.')
        qs = RegTxtss.objects.filter(is_deleted=False).select_related('proyecto', 'empresa').order_by('pk')
        if empresa:
            qs = qs.filter(empresa__slug=empresa)
        procesados = generados = pendientes = 0
        for r in qs.iterator():
            if limite and procesados >= limite:
                break
            if dry_run:
                if self._pendiente(r):
                    pendientes += 1
                continue
            n = mapas.generar_automaticas(r, 'txtss')
            if n:
                procesados += 1
                generados += n
        if dry_run:
            self.stdout.write(f'{pendientes} registro(s) con mapas pendientes.')
        else:
            self.stdout.write(self.style.SUCCESS(f'{generados} imagen(es) generada(s) en {procesados} registro(s).'))

    @staticmethod
    def _pendiente(registro):
        from reg_actividades.servicios import asignados_de
        for a in asignados_de(registro, 'txtss'):
            for pw in a.paso.widgets.all():
                if pw.widget_slug not in ('mapa_1p', 'mapa_2_puntos'):
                    continue
                esperados = 2 if pw.widget_slug == 'mapa_2_puntos' else 1
                puntos = mapas.puntos_de_widget(pw.widget_slug, pw.config, registro, a.paso)
                existente = mapas.imagen_de(registro, a.paso.nombre)
                if len(puntos) >= esperados and (existente is None or not mapas.misma_geometria(existente.coordenadas, puntos)):
                    return True
        return False

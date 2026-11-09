"""Asigna `Jornada.proyecto` a las jornadas sin proyecto, deduciéndolo de lo que mencionan sus reportes.

    python manage.py asignar_proyecto_a_jornadas emb             # solo muestra qué haría
    python manage.py asignar_proyecto_a_jornadas emb --aplicar   # guarda

Skylog no guardaba un proyecto por jornada. Es una INFERENCIA: a cada jornada sin proyecto se le da el proyecto
que más actividades REALIZADAS de su reporte mencionan (por etiqueta, con las variantes fusionadas en su canónica
y solo etiquetas ya vinculadas a un `Proyecto`). A igualdad gana el proyecto más mencionado en toda la empresa y
luego el nombre. No toca jornadas que ya tienen proyecto; idempotente.
"""
from collections import Counter, defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from empresas.models import Empresa
from jor_actividades.models import Etiqueta, ItemActividad
from jor_diario.models import Jornada


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--aplicar', action='store_true', help='guarda los cambios (sin esto solo se muestran)')

    def handle(self, *args, slug, aplicar, **opts):
        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{slug}».')
        try:
            with transaction.atomic():
                self.ejecutar(empresa)
                if not aplicar:
                    raise _Deshacer
        except _Deshacer:
            self.stdout.write(self.style.WARNING('\nSimulación: no se guardó nada. Usa --aplicar para guardar.'))

    def ejecutar(self, empresa):
        etiquetas = {e.pk: e for e in Etiqueta.objects.filter(empresa=empresa, tipo=Etiqueta.Tipo.PROYECTO)}
        proyecto_de = {pk: (etiquetas[e.canonica_id] if e.canonica_id in etiquetas else e).proyecto_id
                       for pk, e in etiquetas.items()}
        Through = ItemActividad.etiquetas.through
        pares = set()                  # (actividad, proyecto): una actividad cuenta una vez por proyecto
        jornada_de = {}
        for item, etq, jor in Through.objects.filter(
                itemactividad__empresa=empresa, itemactividad__tipo=ItemActividad.Tipo.HECHO,
                etiqueta__tipo=Etiqueta.Tipo.PROYECTO, etiqueta__ignorada=False,
        ).values_list('itemactividad_id', 'etiqueta_id', 'itemactividad__reporte__jornada_id'):
            if proyecto_de.get(etq):
                pares.add((item, proyecto_de[etq]))
                jornada_de[item] = jor
        global_ = Counter(p for _, p in pares)
        por_jornada = defaultdict(Counter)
        for item, p in pares:
            por_jornada[jornada_de[item]][p] += 1

        sin_proyecto = set(Jornada.objects.filter(empresa=empresa, proyecto__isnull=True).values_list('pk', flat=True))
        asignadas = Counter()
        for jor, ctr in por_jornada.items():
            if jor not in sin_proyecto:
                continue
            mejor = min(ctr, key=lambda p: (-ctr[p], -global_[p], p))
            Jornada.objects.filter(pk=jor).update(proyecto_id=mejor)
            asignadas[mejor] += 1

        from proyectos.models import Proyecto
        nombres = dict(Proyecto.objects.filter(pk__in=list(asignadas)).values_list('pk', 'nombre'))
        self.stdout.write(f'Jornadas sin proyecto: {len(sin_proyecto)}. Se asignan: {sum(asignadas.values())}; '
                          f'quedan sin proyecto: {len(sin_proyecto) - sum(asignadas.values())} (sus reportes no mencionan ninguno).')
        for p, n in asignadas.most_common():
            self.stdout.write(f'  {n:>4}  {nombres.get(p, p)}')


class _Deshacer(Exception):
    pass

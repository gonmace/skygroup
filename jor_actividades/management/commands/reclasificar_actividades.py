from django.core.management.base import BaseCommand, CommandError

from empresas.models import Empresa
from jor_actividades.servicios import sincronizar_items
from jor_diario.models import ReporteDiario


class Command(BaseCommand):
    help = 'Vuelve a clasificar los reportes de una empresa (respeta lo asignado a mano).'

    def add_arguments(self, parser):
        parser.add_argument('--empresa', required=True, help='slug de la empresa')

    def handle(self, *args, empresa, **opts):
        try:
            e = Empresa.objects.get(slug=empresa)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{empresa}».')
        n = 0
        for r in ReporteDiario.objects.filter(jornada__empresa=e).select_related('jornada__empresa'):
            sincronizar_items(r)
            n += 1
        self.stdout.write(f'Reportes reclasificados: {n}')

from django.core.management.base import BaseCommand, CommandError

from empresas.models import Empresa
from reg_actividades.servicios import sembrar_ejemplo


class Command(BaseCommand):
    help = 'Crea pasos y plantillas de ejemplo (TX/TSS y Construcción) para una empresa. Es idempotente.'

    def add_arguments(self, parser):
        parser.add_argument('slug', help='Identificador (slug) de la empresa.')

    def handle(self, *args, slug, **opts):
        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{slug}».')
        pasos, plantillas = sembrar_ejemplo(empresa)
        self.stdout.write(self.style.SUCCESS(f'{empresa}: {pasos} paso(s) y {plantillas} plantilla(s) nuevos.'))

from django.core.management.base import BaseCommand

from jor_diario.servicios import cerrar_vencidas


class Command(BaseCommand):
    help = 'Cierra las jornadas que quedaron abiertas de días anteriores (programar cada noche con cron o n8n).'

    def handle(self, *args, **opts):
        self.stdout.write(f'Jornadas cerradas: {cerrar_vencidas()}')

"""Lee de la API de n8n los tokens de las llamadas a la IA aún sin medir y calcula su costo (`LlamadaIA`)."""
from django.core.management.base import BaseCommand

from apu_generador import ia
from apu_generador.models import LlamadaIA


class Command(BaseCommand):
    help = 'Sincroniza los tokens y el costo de las llamadas a la IA de APU con la API de n8n (N8N_API_URL / N8N_API_KEY).'

    def add_arguments(self, parser):
        parser.add_argument('--limite', type=int, default=500, help='Máximo de llamadas a sincronizar (por defecto 500).')

    def handle(self, *args, **opciones):
        pendientes = list(LlamadaIA.objects.filter(uso__isnull=True).exclude(ejecucion_id='').order_by('-fecha')[:opciones['limite']])
        hechas = ia.sincronizar_uso(pendientes)
        self.stdout.write(f'{hechas} de {len(pendientes)} llamada(s) sincronizadas.')

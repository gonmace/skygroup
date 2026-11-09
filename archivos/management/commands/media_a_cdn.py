import re

from django.core.management.base import BaseCommand, CommandError

from archivos.services import MigracionError, migrar_a_cdn


def _dias(valor):
    m = re.fullmatch(r'(\d+)\s*d?', valor.strip())
    if not m:
        raise CommandError('--antiguedad espera días, ej. 7d o 7')
    return int(m.group(1))


class Command(BaseCommand):
    help = 'Sube los archivos de media que siguen en disco al bucket S3/CDN configurado.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Solo lista; no sube ni borra.')
        parser.add_argument('--prefijo', default='', help='Solo rutas que empiecen así, ej. photos/')
        parser.add_argument('--borrar-local', action='store_true',
                            help='Borra del disco cada archivo verificado en el bucket.')
        parser.add_argument('--antiguedad', default='0', help='Solo archivos de más de N días (ej. 7d).')

    def handle(self, *args, **opts):
        try:
            tarea = migrar_a_cdn(
                dry_run=opts['dry_run'], prefijo=opts['prefijo'], borrar_local=opts['borrar_local'],
                antiguedad_dias=_dias(opts['antiguedad']), log=self.stdout.write,
            )
        except MigracionError as exc:
            raise CommandError(str(exc))
        self.stdout.write(self.style.SUCCESS(
            f'{tarea.get_estado_display()}: {tarea.archivos_subidos} subidos '
            f'({tarea.bytes_subidos} B), {tarea.archivos_omitidos} ya estaban, '
            f'{tarea.archivos_borrados} borrados de disco, de {tarea.archivos_total}.'
        ))
        if tarea.errores:
            self.stderr.write(tarea.errores)
            raise CommandError('Hubo errores; reintenta: el comando es reanudable.')

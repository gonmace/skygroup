from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from empresas.models import Empresa
from reg_base.importar import Importador


class Command(BaseCommand):
    help = ('Importa los datos de reg.tekon-rl.cl (JSONL de scripts/traer_legacy_reg.sh + media) a una empresa. '
            'Es idempotente: se puede repetir sin duplicar.')

    def add_arguments(self, parser):
        parser.add_argument('slug', help='Identificador (slug) de la empresa destino.')
        parser.add_argument('--dir', default='backups/legacy/reg', help='Carpeta con los .jsonl.')
        parser.add_argument('--media', default='backups/legacy/reg_media', help='Carpeta con photos/ y google_maps/.')
        parser.add_argument('--sin-archivos', action='store_true', help='No importar fotos ni imágenes de mapa.')
        parser.add_argument('--limpiar', action='store_true', help='Antes, borrar los datos de ejemplo de la empresa.')
        parser.add_argument('--dry-run', action='store_true', help='Ejecuta todo y revierte al final (muestra los conteos). No copia fotos ni mapas.')

    def handle(self, *args, slug, dir, media, sin_archivos, limpiar, dry_run, **opts):
        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{slug}».')
        imp = Importador(empresa, dir, media=media, con_archivos=not (sin_archivos or dry_run), salida=self.stdout.write)
        if not imp.tabla('core_site'):
            raise CommandError(f'No hay datos en {dir} (¿corriste scripts/traer_legacy_reg.sh?).')
        try:
            with transaction.atomic():
                n, omitidos, avisos = imp.ejecutar(limpiar=limpiar)
                if dry_run:
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f'Importación cancelada (nada se guardó): {exc!r}')
        self.stdout.write(self.style.SUCCESS(('[dry-run, revertido] ' if dry_run else '') + 'Creados:'))
        for k, v in sorted(n.items()):
            self.stdout.write(f'  {k}: {v}')
        for k, v in sorted(omitidos.items()):
            self.stdout.write(self.style.WARNING(f'  omitidos · {k}: {v}'))
        for a in avisos:
            self.stdout.write(self.style.WARNING(f'  ! {a}'))

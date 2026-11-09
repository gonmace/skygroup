import os

from django.conf import settings
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from archivos.models import get_media_config
from archivos.storage import ConfigurableMediaStorage


class Command(BaseCommand):
    help = ('Copia los archivos públicos de MEDIA_ROOT (disco local) al almacenamiento configurado en el admin. '
            'No borra nada y omite media/privado/ (para eso: media_a_cdn).')

    def handle(self, *args, **options):
        if get_media_config()['mode'] != 's3':
            raise CommandError('El almacenamiento configurado es local: no hay nada que sincronizar.')
        storage = ConfigurableMediaStorage()._backend()
        copied = skipped = 0
        for root, _dirs, files in os.walk(settings.MEDIA_ROOT):
            for filename in files:
                path = os.path.join(root, filename)
                name = os.path.relpath(path, settings.MEDIA_ROOT).replace(os.sep, '/')
                if name.startswith('privado/'):
                    continue  # los privados van al bucket privado: usar media_a_cdn
                if storage.exists(name):
                    skipped += 1
                    continue
                with open(path, 'rb') as fh:
                    storage.save(name, File(fh))
                copied += 1
                self.stdout.write(f'  ↑ {name}')
        self.stdout.write(self.style.SUCCESS(f'Copiados: {copied} · ya existían: {skipped}'))

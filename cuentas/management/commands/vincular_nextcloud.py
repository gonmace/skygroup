"""Vincula a las personas que YA son miembros de una empresa con su usuario de Nextcloud (no crea cuentas).

    python manage.py vincular_nextcloud <slug-empresa>                     # simulación: muestra qué haría
    python manage.py vincular_nextcloud <slug-empresa> --aplicar
    python manage.py vincular_nextcloud <slug-empresa> --archivo uids.csv --aplicar   # «uid,correo» por línea

Sin archivo se asume que el usuario de Nextcloud es el correo de la cuenta (como en skylog: `gmartinez@redlinegs.com`).
Solo vincula miembros activos de esa empresa y de ninguna otra (una cuenta compartida la vincula la propia persona);
omite cuentas con privilegios (staff/superusuario) y nunca pisa un vínculo existente ni repite un uid ya tomado por otra persona."""
import csv

from django.core.management.base import BaseCommand, CommandError

from cuentas.models import Membresia, NextcloudVinculo
from cuentas.nextcloud import _solo_de
from empresas.models import Empresa


class Command(BaseCommand):
    help = 'Vincula miembros existentes de una empresa con su usuario de Nextcloud (no crea cuentas).'

    def add_arguments(self, parser):
        parser.add_argument('slug', help='Slug de la empresa.')
        parser.add_argument('--archivo', help='CSV «uid,correo» (si falta, uid = correo de la cuenta).')
        parser.add_argument('--aplicar', action='store_true', help='Guardar los vínculos (por defecto solo simula).')

    def handle(self, *args, slug, archivo, aplicar, **opts):
        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{slug}».')
        por_correo = {}
        if archivo:
            with open(archivo, newline='', encoding='utf-8') as f:
                for fila in csv.reader(f):
                    if fila and fila[0].strip():
                        uid = fila[0].strip()
                        por_correo[(fila[1] if len(fila) > 1 else uid).strip().lower()] = uid
        miembros = (Membresia.objects.filter(empresa=empresa, activa=True, user__is_active=True, user__is_deleted=False)
                    .select_related('user'))
        nuevos = omitidos = 0
        for m in miembros:
            u = m.user
            uid = por_correo.get(u.email.lower()) if archivo else u.email.lower()
            if not uid:
                continue
            motivo = ''
            if NextcloudVinculo.objects.filter(empresa=empresa, user=u).exists():
                motivo = 'ya vinculado'
            elif u.is_superuser or u.is_staff:
                motivo = 'cuenta con privilegios'
            elif not _solo_de(u, empresa):
                motivo = 'tiene acceso a otras empresas: debe vincularla ella misma'
            elif NextcloudVinculo.objects.filter(empresa=empresa, uid=uid).exists():
                motivo = 'uid ya usado por otra cuenta'
            if motivo:
                omitidos += 1
                self.stdout.write(f'  omito {u.email} ({motivo})')
                continue
            if aplicar:
                NextcloudVinculo.objects.create(empresa=empresa, user=u, uid=uid)
            nuevos += 1
            self.stdout.write(f'  {"vinculo" if aplicar else "vincularía"} {u.email} → {uid}')
        self.stdout.write(self.style.SUCCESS(
            f'{empresa}: {nuevos} vínculo(s) {"creados" if aplicar else "por crear (simulación; usa --aplicar)"}, {omitidos} omitido(s).'))

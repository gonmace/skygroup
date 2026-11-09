"""Vacía los datos OPERATIVOS de una empresa para poder reimportarlos limpios desde producción.

    python manage.py vaciar_datos pti --dry-run    # muestra qué borraría y revierte
    python manage.py vaciar_datos pti              # borra

Borra: tickets, registros (TX/TSS, Construcción, Construcción base + hallazgos), fotos, datos de pasos,
imágenes de mapa, jornadas (con reportes y actividades), ausencias, notas de calendario, mensajes y chats
directos, notificaciones, proyectos sin etiquetas de Jornadas y contratistas sin personas.

Conserva: usuarios, membresías, cargos, perfiles, configuración de la empresa, pasos/plantillas de Registros,
categorías y etiquetas de Jornadas (con sus fusiones y vínculos a proyecto) y el canal General del chat.
Todo dentro de una transacción: si algo falla no se borra nada. Usa `.delete()` para que corran las
cascadas y las señales que borran los archivos de fotos/adjuntos.
"""
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import ProtectedError

from empresas.models import Empresa


class Command(BaseCommand):
    help = __doc__

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--dry-run', action='store_true', help='Ejecuta todo y revierte al final.')

    def handle(self, *args, slug, dry_run, **opts):
        try:
            empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{slug}».')
        n = Counter()
        try:
            with transaction.atomic():
                self.borrar(empresa, n)
                if dry_run:
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f'Cancelado (nada se borró): {exc!r}')
        self.stdout.write(self.style.SUCCESS(('[dry-run, revertido] ' if dry_run else '') + 'Borrados:'))
        for k, v in sorted(n.items()):
            self.stdout.write(f'  {k}: {v}')

    def _qs(self, n, nombre, qs):
        n[nombre] += qs.count()
        qs.delete()

    def _uno_a_uno(self, n, nombre, qs):
        """Instancia por instancia, para arrastrar GenericRelations (fotos, datos de pasos)."""
        for obj in qs:
            obj.delete()
            n[nombre] += 1

    def borrar(self, e, n):
        from empresas.models import Contratista
        from jor_actividades.models import ItemActividad
        from jor_diario.models import Ausencia, Jornada, NotaCalendario
        from mje_mensajes.models import Conversacion, Mensaje
        from notificaciones.models import Notificacion
        from proyectos.models import Proyecto
        from reg_actividades.models import DatoPaso, ImagenMapa
        from reg_construccion.models import RegConstruccion
        from reg_construccion_base.models import Hallazgo, RegConstruccionBase
        from reg_fotos.models import Foto
        from reg_txtss.models import RegTxtss
        from tar_tickets.models import Ticket

        self._qs(n, 'tickets', Ticket.objects.filter(empresa=e))
        for nombre, modelo in (('reg TX/TSS', RegTxtss), ('reg Construcción', RegConstruccion)):
            self._uno_a_uno(n, nombre, modelo.objects.filter(empresa=e))
        self._qs(n, 'hallazgos', Hallazgo.objects.filter(empresa=e))
        self._uno_a_uno(n, 'reg Construcción base', RegConstruccionBase.objects.filter(empresa=e))
        self._uno_a_uno(n, 'fotos sueltas', Foto.objects.filter(empresa=e))
        self._qs(n, 'datos de pasos', DatoPaso.objects.filter(empresa=e))
        self._uno_a_uno(n, 'imágenes de mapa', ImagenMapa.objects.filter(empresa=e))

        self._qs(n, 'actividades', ItemActividad.objects.filter(empresa=e))
        self._qs(n, 'jornadas', Jornada.objects.filter(empresa=e))
        self._qs(n, 'ausencias', Ausencia.objects.filter(empresa=e))
        self._qs(n, 'notas de calendario', NotaCalendario.objects.filter(empresa=e))

        self._qs(n, 'mensajes', Mensaje.objects.filter(conversacion__empresa=e))
        self._qs(n, 'chats directos', Conversacion.objects.filter(empresa=e, tipo='directo'))
        self._qs(n, 'notificaciones', Notificacion.objects.filter(empresa=e))

        # El Proyecto es común a los 3 módulos: se conservan los que ya representan una etiqueta de Jornadas.
        self._qs(n, 'proyectos', Proyecto.objects.filter(empresa=e, etiquetas__isnull=True))
        for c in Contratista.objects.filter(empresa=e, membresias__isnull=True):
            try:
                with transaction.atomic():
                    c.delete()
                n['contratistas'] += 1
            except ProtectedError:
                pass

"""Importa a una empresa los datos de Jornadas de skylog (dump `backups/legacy/skylog.sql.gz`).

    python manage.py importar_jor emb [--dump RUTA] [--dry-run]

Idempotente: lo que ya trae `legacy_source='skylog'` + `legacy_id` se reutiliza. Lee el dump de texto
(bloques COPY de pg_dump), sin necesitar PostgreSQL. No importa capturas de pantalla ni datos del agente
(esas apps ya no existen en skygroup).
"""
import gzip
from collections import Counter
from datetime import datetime
from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date, parse_datetime

from cuentas.models import Membresia, RolEmpresa, User
from cuentas.roles import RolBase
from empresas.models import Empresa
from jor_actividades.models import CategoriaActividad, Etiqueta, ItemActividad
from jor_actividades.texto import normalizar
from jor_diario.models import Ausencia, Jornada, NotaCalendario, ReporteDiario
from jor_empleados.models import Perfil

FUENTE = 'skylog'
ESTADO = {'completed': 'completada', 'in_progress': 'en_curso', 'incomplete': 'incompleta'}
AUSENCIA = {'vacation': 'vacacion', 'vacacion': 'vacacion', 'sick': 'licencia', 'licencia': 'licencia',
            'permiso': 'permiso', 'permission': 'permiso'}
ETIQUETA = {'project': 'proyecto', 'location': 'ubicacion', 'deliverable': 'entregable'}
TIPO_ITEM = {'done': 'hecho', 'planned': 'planificado'}
FUENTE_ITEM = {'keyword': 'palabras', 'llm': 'llm', 'manual': 'manual'}


def _celda(v):
    if v == '\\N':
        return None
    if '\\' not in v:
        return v
    mapa = {'t': '\t', 'n': '\n', 'r': '\r', '\\': '\\', 'b': '\b', 'f': '\f', 'v': '\v'}
    out, i = [], 0
    while i < len(v):
        if v[i] == '\\' and i + 1 < len(v):
            out.append(mapa.get(v[i + 1], v[i + 1]))
            i += 2
        else:
            out.append(v[i])
            i += 1
    return ''.join(out)


def leer_dump(ruta):
    """{tabla: [dict, …]} a partir de los bloques COPY de un pg_dump en texto."""
    tablas, actual, cols = {}, None, None
    with gzip.open(ruta, 'rt', encoding='utf-8') as f:
        for linea in f:
            linea = linea.rstrip('\n')
            if actual is None:
                if linea.startswith('COPY public.'):
                    cabecera = linea[len('COPY public.'):]
                    actual = cabecera.split(' ', 1)[0]
                    cols = [c.strip().strip('"') for c in cabecera.split('(', 1)[1].split(')', 1)[0].split(',')]
                    tablas[actual] = []
            elif linea == '\\.':
                actual = None
            else:
                tablas[actual].append(dict(zip(cols, (_celda(v) for v in linea.split('\t')))))
    return tablas


def _dt(v):
    return parse_datetime(v) if v else None


def _dec(v):
    return Decimal(v) if v not in (None, '') else None


class Command(BaseCommand):
    help = 'Importa las jornadas, reportes, ausencias, mensajes y actividades de skylog a una empresa.'

    def add_arguments(self, parser):
        parser.add_argument('slug')
        parser.add_argument('--dump', default='backups/legacy/skylog.sql.gz')
        parser.add_argument('--desde', help='AAAA-MM-DD: solo crea jornadas, ausencias, notas y mensajes de esa fecha en adelante.')
        parser.add_argument('--dry-run', action='store_true', help='Ejecuta todo y revierte al final.')

    def handle(self, *args, slug, dump, dry_run, desde=None, **opts):
        self.desde = parse_date(desde) if desde else None
        if desde and self.desde is None:
            raise CommandError('--desde debe ser AAAA-MM-DD.')
        try:
            self.empresa = Empresa.objects.get(slug=slug)
        except Empresa.DoesNotExist:
            raise CommandError(f'No existe la empresa «{slug}».')
        try:
            self.t = leer_dump(dump)
        except OSError as exc:
            raise CommandError(f'No se pudo leer {dump}: {exc}')
        self.n, self.avisos = Counter(), []
        try:
            with transaction.atomic():
                self.personas()
                self.categorias_y_etiquetas()
                self.jornadas()
                self.ausencias_y_notas()
                self.mensajes()
                if dry_run:
                    transaction.set_rollback(True)
        except Exception as exc:
            raise CommandError(f'Importación cancelada (nada se guardó): {exc!r}')
        self.stdout.write(self.style.SUCCESS(('[dry-run, revertido] ' if dry_run else '') + 'Creados:'))
        for k, v in sorted(self.n.items()):
            self.stdout.write(f'  {k}: {v}')
        for a in self.avisos:
            self.stdout.write(self.style.WARNING(f'  ! {a}'))

    # ── personas ─────────────────────────────────────────────────────────────
    def _rol(self, base):
        return RolEmpresa.objects.filter(empresa=self.empresa, rol_base=base, activo=True).order_by('orden', 'pk').first()

    def _usuario(self, fila):
        email = (fila.get('email') or '').strip().lower() or f"{fila['username']}@skylog.legacy".lower()
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            user = User(email=email, first_name=fila.get('first_name') or '', last_name=fila.get('last_name') or '',
                        is_active=fila.get('is_active') == 't', legacy_source=FUENTE, legacy_id=int(fila['id']))
            user.password = fila.get('password') or ''
            if not user.password:
                user.set_unusable_password()
            if fila.get('is_superuser') == 't':   # el superusuario de skylog sigue siéndolo
                user.is_superuser = user.is_staff = True
            user.save()
            self.n['usuarios'] += 1
        return user

    def _membresia(self, user, base):
        m, creada = Membresia.objects.get_or_create(
            user=user, empresa=self.empresa, defaults={'rol': self._rol(base), 'activa': user.is_active})
        self.n['membresías'] += creada
        return m

    def personas(self):
        usuarios = {u['id']: u for u in self.t['auth_user']}
        self.perfil = {}   # employee legacy id → Perfil
        for e in self.t['employees_employee']:
            u = usuarios[e['user_id']]
            nombre = (e['full_name'] or '').strip()
            if nombre and not (u.get('first_name') or u.get('last_name')):
                u['first_name'], _, u['last_name'] = nombre.partition(' ')
            user = self._usuario(u)
            cargo = e['cargo'] or ''
            base = RolBase.MIEMBRO   # todos los empleados entran como Ejecutor; el cargo (PM, Supervisor…) queda en el Perfil
            m = self._membresia(user, base)
            # El reporte diario es obligatorio por defecto para todos (el tipo «mobile_type» de skylog ya no decide);
            # un coordinador lo apaga a mano en Equipo para quien no reporta (p. ej. bodega).
            perfil, creado = Perfil.objects.get_or_create(membresia=m, defaults=dict(
                cargo=cargo, hora_entrada=e['hora_entrada'], exige_reporte=True,
                haber_basico=_dec(e['haber_basico']) or 0, ciudad_catering=e['ciudad'] or 'NONE',
                numero_item=int(e['item_number']) if e['item_number'] else None,
                activo=e['skylog_access'] == 't' if e.get('skylog_access') else True,
                legacy_source=FUENTE, legacy_id=int(e['id'])))
            self.n['perfiles'] += creado
            self.perfil[e['id']] = perfil
            self.user_de_legacy = getattr(self, 'user_de_legacy', {})
            self.user_de_legacy[e['user_id']] = user
        for u in usuarios.values():   # usuarios sin empleado (p. ej. administradores) para atribuir mensajes y notas
            if u['id'] not in self.user_de_legacy and u.get('email'):
                self.user_de_legacy[u['id']] = User.objects.filter(email__iexact=u['email']).first()

    # ── actividades ──────────────────────────────────────────────────────────
    def categorias_y_etiquetas(self):
        for c in self.t['workdays_activitycategory']:
            _, creada = CategoriaActividad.objects.get_or_create(
                empresa=self.empresa, codigo=c['code'],
                defaults=dict(etiqueta=c['label'], color=c['color'], orden=int(c['order']),
                              activa=c['is_active'] == 't', protegida=c['is_protected'] == 't'))
            self.n['categorías'] += creada
        self.etq = {}
        filas = self.t['workdays_activitytag']
        for f in filas:
            tipo = ETIQUETA.get(f['kind'])
            if not tipo:
                continue
            e, creada = Etiqueta.objects.get_or_create(
                empresa=self.empresa, tipo=tipo, clave=f['key'],
                defaults=dict(nombre=f['name'], codigo=f['code'] or '', color=f['color'] or '', ignorada=f['ignored'] == 't'))
            self.n['etiquetas'] += creada
            self.etq[f['id']] = e
        for f in filas:   # fusiones (canónica) en una segunda pasada
            e = self.etq.get(f['id'])
            c = self.etq.get(f['canonical_id']) if f['canonical_id'] else None
            if e and c and e.canonica_id != c.pk and e.pk != c.pk:
                e.canonica = c
                e.save(update_fields=['canonica'])

    # ── jornadas, reportes, actividades ──────────────────────────────────────
    def jornadas(self):
        existentes = {j.legacy_id: j for j in Jornada.objects.filter(empresa=self.empresa, legacy_source=FUENTE)}
        jor = {}
        for w in self.t['workdays_workday']:
            perfil = self.perfil.get(w['employee_id'])
            if perfil is None:
                continue
            j = existentes.get(int(w['id']))
            if j is not None and j.estado == 'en_curso' and w['status'] != 'in_progress':
                # La jornada seguía abierta en una importación anterior y ya se cerró en skylog: se pone al día
                # (además libera la restricción de una sola jornada en curso por persona).
                j.fin, j.duracion_min = _dt(w['end_time']), int(w['duration_minutes']) if w['duration_minutes'] else None
                j.estado, j.cierre_auto = ESTADO.get(w['status'], 'incompleta'), w['auto_closed'] == 't'
                j.lat_fin, j.lon_fin = _dec(w['end_latitude']), _dec(w['end_longitude'])
                j.save(update_fields=['fin', 'duracion_min', 'estado', 'cierre_auto', 'lat_fin', 'lon_fin'])
                self.n['jornadas actualizadas'] += 1
            if j is None and self.desde and (_dt(w['start_time']) or datetime.min.replace(tzinfo=None)).date() < self.desde:
                continue
            if j is None:
                j = Jornada.objects.create(
                    empresa=self.empresa, perfil=perfil, inicio=_dt(w['start_time']), fin=_dt(w['end_time']),
                    duracion_min=int(w['duration_minutes']) if w['duration_minutes'] else None,
                    estado=ESTADO.get(w['status'], 'incompleta'), cierre_auto=w['auto_closed'] == 't',
                    lat_inicio=_dec(w['start_latitude']), lon_inicio=_dec(w['start_longitude']),
                    lat_fin=_dec(w['end_latitude']), lon_fin=_dec(w['end_longitude']),
                    legacy_source=FUENTE, legacy_id=int(w['id']))
                self.n['jornadas'] += 1
            jor[w['id']] = j
        reportes = {}
        for r in self.t['workdays_dailyreport']:
            j = jor.get(r['workday_id'])
            if j is None:
                continue
            rep, creado = ReporteDiario.objects.get_or_create(
                jornada=j, defaults=dict(realizado=r['activities_done'], planificado=r['activities_planned']))
            if creado:
                ReporteDiario.objects.filter(pk=rep.pk).update(enviado=_dt(r['submitted_at']))   # auto_now_add
                self.n['reportes'] += 1
            reportes[r['id']] = rep
        con_items = set(ItemActividad.objects.filter(empresa=self.empresa).values_list('reporte_id', flat=True))
        tags = {}
        for t in self.t['workdays_activityitem_tags']:
            tags.setdefault(t['activityitem_id'], []).append(t['activitytag_id'])
        nuevos = []
        for it in self.t['workdays_activityitem']:
            rep = reportes.get(it['report_id'])
            if rep is None or rep.pk in con_items:
                continue
            nuevos.append((it, ItemActividad(
                empresa=self.empresa, reporte=rep, tipo=TIPO_ITEM.get(it['kind'], 'hecho'), posicion=int(it['position']),
                texto=it['text'], categoria=it['category'] or 'otros', fuente=FUENTE_ITEM.get(it['source'], 'palabras'),
                palabra=it['matched_keyword'] or '', manual=it['manual_override'] == 't')))
        ItemActividad.objects.bulk_create([o for _, o in nuevos], batch_size=500)
        self.n['actividades'] += len(nuevos)
        if nuevos and nuevos[0][1].pk is None:   # backend sin RETURNING: recuperar las filas para enlazar etiquetas
            self.avisos.append('El backend no devolvió las claves de las actividades: etiquetas no enlazadas.')
            return
        Through = ItemActividad.etiquetas.through
        enlaces = [Through(itemactividad_id=o.pk, etiqueta_id=self.etq[tg].pk)
                   for it, o in nuevos for tg in tags.get(it['id'], []) if tg in self.etq]
        Through.objects.bulk_create(enlaces, batch_size=1000, ignore_conflicts=True)
        self.n['etiquetas enlazadas'] += len(enlaces)

    # ── ausencias, notas, mensajes ───────────────────────────────────────────
    def ausencias_y_notas(self):
        for a in self.t['workdays_employeeleave']:
            perfil = self.perfil.get(a['employee_id'])
            if perfil is None or (self.desde and a['end_date'] < self.desde.isoformat()):
                continue
            _, creada = Ausencia.objects.get_or_create(
                empresa=self.empresa, perfil=perfil, desde=a['start_date'], hasta=a['end_date'],
                defaults=dict(tipo=AUSENCIA.get(a['leave_type'], 'otro'), nota=(a['note'] or '')[:200],
                              estado='aprobada', creada_por=self.user_de_legacy.get(a['created_by_id'])))
            self.n['ausencias'] += creada
        for c in self.t['workdays_calendarnote']:
            if self.desde and c['date'] < self.desde.isoformat():
                continue
            tipo = c['note_type'] if c['note_type'] in ('feriado', 'evento', 'otro') else 'otro'
            _, creada = NotaCalendario.objects.get_or_create(
                empresa=self.empresa, fecha=c['date'], texto=c['text'][:200],
                defaults=dict(tipo=tipo, creada_por=self.user_de_legacy.get(c['created_by_id'])))
            self.n['notas de calendario'] += creada

    def mensajes(self):
        """Los avisos de skylog pasan a mensajes directos remitente → destinatario (los sin remitente no
        tienen conversación: ya no existe el aviso de skyBot en el chat)."""
        from mje_mensajes import servicios as chat
        from mje_mensajes.models import Conversacion, Mensaje
        hechos = set(Mensaje.objects.filter(conversacion__empresa=self.empresa, legacy_source=FUENTE)
                     .values_list('legacy_id', flat=True))
        for m in self.t['workdays_executivemessage']:
            perfil = self.perfil.get(m['recipient_id'])
            autor = self.user_de_legacy_empleado(m['sender_id'])
            if self.desde and (_dt(m['sent_at']) is None or _dt(m['sent_at']).date() < self.desde):
                continue
            if perfil is None or autor is None or autor.pk == perfil.membresia.user_id or int(m['id']) in hechos:
                continue
            conv = chat.directo(self.empresa, autor, perfil.membresia.user)
            obj = Mensaje.objects.create(conversacion=conv, autor=autor, texto=m['body'][:chat.MAX_TEXTO],
                                         legacy_source=FUENTE, legacy_id=int(m['id']))
            enviado = _dt(m['sent_at'])
            Mensaje.objects.filter(pk=obj.pk).update(creado=enviado)   # auto_now_add
            Conversacion.objects.filter(pk=conv.pk).update(ultimo_mensaje_en=enviado)
            self.n['mensajes'] += 1

    def user_de_legacy_empleado(self, employee_id):
        """El remitente de skylog es un Employee; su usuario es el de su perfil."""
        if not employee_id:
            return None
        p = self.perfil.get(employee_id)
        return p.membresia.user if p else None

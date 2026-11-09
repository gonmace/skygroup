"""Llena TODOS los modelos propios con datos falsos (solo desarrollo).

    python manage.py seed_junk [--count 15] [--seed N] [--force] [--media-root DIR]

- Se niega a correr con DEBUG=False salvo --force.
- Solo stdlib + Pillow (ya instalado por los ImageField). Sin dependencias nuevas.
- Idempotente: empresas `junk-emp-N`, usuarios `junk_NN@example.com`; cada sección «completa» hasta
  `--count` filas de lo ya sembrado, así que correrlo dos veces no duplica.
- Los archivos (PNG/JPG diminutos) se escriben solo bajo MEDIA_ROOT (o --media-root).
- Se silencian los avisos en vivo (Channels/Redis) de tar_tickets durante el seed.
"""
import hashlib
import io
import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.test.utils import override_settings
from django.utils import timezone

PASSWORD = 'junk-pass-1234'
NOMBRES = ['Ana', 'Luis', 'María', 'Carlos', 'Lucía', 'Jorge', 'Elena', 'Pedro', 'Sofía', 'Diego',
           'Valeria', 'Andrés', 'Camila', 'Mateo', 'Paula', 'Hugo', 'Rosa', 'Iván', 'Nora', 'Raúl']
APELLIDOS = ['Rojas', 'Mamani', 'Quispe', 'Flores', 'Vargas', 'Choque', 'Gutiérrez', 'Torrez', 'Salvatierra',
             'Cruz', 'Soliz', 'Arce', 'Montaño', 'Peña', 'Ibáñez']
EMPRESAS = ['Andes Telecom', 'Altiplano Redes', 'Condor Torres', 'Valle Fibra', 'Sol Naciente Ingeniería',
            'Pampa Energía', 'Illimani Obras', 'Titicaca Servicios']
FRASES = ['Revisión de anclajes', 'Montaje de antena sectorial', 'Cambio de feeder', 'Inspección de puesta a tierra',
          'Medición de enlace', 'Reunión con el contratista', 'Informe de avance semanal', 'Pruebas de aceptación',
          'Limpieza de sitio', 'Replanteo topográfico', 'Instalación de gabinete', 'Corrección de observaciones']


def _imagen(formato='PNG', color=(30, 120, 200)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (16, 16), color).save(buf, formato)
    return buf.getvalue()


class Command(BaseCommand):
    help = 'Llena todos los modelos propios con datos falsos (solo dev; usuarios junk_*).'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=15, help='Filas objetivo por modelo (default 15).')
        parser.add_argument('--seed', type=int, default=None, help='Semilla del generador aleatorio.')
        parser.add_argument('--force', action='store_true', help='Permitir con DEBUG=False.')
        parser.add_argument('--media-root', default=None, help='Directorio para los archivos (default MEDIA_ROOT).')

    # ── Utilidades ────────────────────────────────────────────────────────────
    def faltan(self, qs, n=None):
        return max(0, (n or self.count) - qs.count())

    def tick(self, modelo, n=1):
        self.creados[modelo._meta.label] = self.creados.get(modelo._meta.label, 0) + n

    def get_or_create(self, modelo, defaults=None, **lookup):
        obj, creado = modelo.objects.get_or_create(defaults=defaults or {}, **lookup)
        if creado:
            self.tick(modelo)
        return obj

    def create(self, modelo, **campos):
        obj = modelo.objects.create(**campos)
        self.tick(modelo)
        return obj

    def dt(self, dias_atras=0, hora=8, minuto=0):
        d = timezone.localdate() - timedelta(days=dias_atras)
        return timezone.make_aware(datetime.combine(d, time(hora, minuto)))

    # ── Entrada ───────────────────────────────────────────────────────────────
    def handle(self, *args, count, seed, force, media_root, **opts):
        if not settings.DEBUG and not force:
            raise CommandError('DEBUG=False: seed_junk solo corre en desarrollo (usa --force bajo tu riesgo).')
        if count < 1:
            raise CommandError('--count debe ser >= 1.')
        from archivos.models import get_media_config
        raiz = media_root or settings.MEDIA_ROOT
        self.count = count
        self.rng = random.Random(seed)
        self.creados = {}
        self.stdout.write(f'BD: {settings.DATABASES["default"]["NAME"]}  |  media: {raiz}')
        with override_settings(MEDIA_ROOT=str(raiz)):
            if get_media_config()['mode'] != 'local':
                raise CommandError('La configuración de media usa S3: se aborta para no subir archivos falsos.')
            from tar_tickets import realtime
            with mock.patch.object(realtime, 'tablero_cambio'), mock.patch.object(realtime, 'comentario_nuevo'), \
                    transaction.atomic():
                self.sembrar()
        self.resumen()

    def sembrar(self):
        self.base()
        self.cuentas()
        self.registros()
        self.tareas()
        self.jornadas()

    # ── Base: empresas, usuarios, membresías, proyectos ──────────────────────
    def base(self):
        from archivos.models import MediaStorageConfig, TareaMigracionMedia
        from cuentas.models import Membresia, RolEmpresa, User
        from cuentas.roles import RolBase
        from cuentas.services import sembrar_roles
        from django.contrib.auth.hashers import make_password
        from empresas.models import Contratista, Empresa
        from proyectos.models import Proyecto, ProyectoUbicacion, TipoProyecto

        rng, n = self.rng, self.count
        self.E = 2  # solo EMBOL y PTI
        per = self.per = -(-n // self.E)

        # Empresas (+ roles base sembrados, + logo/favicon falsos)
        self.empresas = []
        for k, (slug, nombre) in enumerate((('emb', 'EMBOL'), ('pti', 'PTI')), start=1):
            e, creada = Empresa.objects.get_or_create(slug=slug, defaults=dict(
                nombre=nombre, razon_social=f'{nombre} S.R.L.', rut=f'{rng.randint(10**9, 10**10 - 1)}',
                contacto_email=f'contacto{k}@example.com', contacto_telefono=f'+591 7{rng.randint(1000000, 9999999)}',
                termino_proyecto_singular='Sitio', termino_proyecto_plural='Sitios', nombre_marca=nombre,
                color_primario='#%06X' % rng.randint(0, 0xFFFFFF), color_acento='#%06X' % rng.randint(0, 0xFFFFFF),
                email_remitente_nombre=nombre, email_remitente=f'no-reply{k}@example.com'))
            if e.nombre != nombre:
                e.nombre = nombre
                e.save(update_fields=['nombre'])
            sembrar_roles(e)
            for nom, base in (('ITO', RolBase.MIEMBRO), ('Revisor técnico', RolBase.ESPECIALISTA)):
                self.get_or_create(RolEmpresa, empresa=e, nombre=nom, defaults=dict(
                    rol_base=base.value, orden=10, descripcion=f'Rol «{nom}» de prueba'))
            if not e.logo_claro:
                e.logo_claro.save('logo.png', ContentFile(_imagen('PNG')), save=False)
                e.favicon.save('favicon.png', ContentFile(_imagen('PNG', (200, 60, 60))), save=False)
                e.save()
            self.empresas.append(e)

        # Usuarios junk_NN
        hash_ = make_password(PASSWORD)
        self.users = []
        for j in range(n):
            u = User.objects.filter(email=f'junk_{j:02d}@example.com').first()
            if u is None:
                u = self.create(User, email=f'junk_{j:02d}@example.com', password=hash_,
                                first_name=NOMBRES[j % len(NOMBRES)], last_name=APELLIDOS[j % len(APELLIDOS)],
                                telefono=f'+591 6{rng.randint(1000000, 9999999)}', is_active=True)
            self.users.append(u)

        # Membresías: primaria por usuario + garantía de los 4 roles base en cada empresa
        bases = [RolBase.COORDINADOR, RolBase.MIEMBRO, RolBase.ESPECIALISTA, RolBase.OBSERVADOR]
        rol_de = lambda e, base: e.roles.filter(rol_base=base.value).order_by('orden', 'id').first()  # noqa: E731
        for j, u in enumerate(self.users):
            e = self.empresas[j % self.E]
            self.get_or_create(Membresia, user=u, empresa=e, defaults={'rol': rol_de(e, bases[j % 4])})
        for ke, e in enumerate(self.empresas):
            for kb, base in enumerate(bases):
                if not e.membresias.filter(rol__rol_base=base.value, user__in=self.users).exists():
                    for off in range(n):
                        u = self.users[(ke * 4 + kb + off) % n]
                        if not Membresia.objects.filter(user=u, empresa=e).exists():
                            self.get_or_create(Membresia, user=u, empresa=e, defaults={'rol': rol_de(e, base)})
                            break

        # Contratistas
        self.contratistas = {e.pk: [] for e in self.empresas}
        for ke, e in enumerate(self.empresas, 1):
            for c in range(1, per + 1):
                self.contratistas[e.pk].append(self.get_or_create(
                    Contratista, empresa=e, codigo=f'JC{ke}{c}',
                    defaults={'nombre': f'Contratista {rng.choice(APELLIDOS)} {ke}-{c}'}))
        for m in Membresia.objects.filter(empresa__in=self.empresas, rol__rol_base=RolBase.MIEMBRO, contratista=None)[::2]:
            m.contratista = rng.choice(self.contratistas[m.empresa_id])
            m.save(update_fields=['contratista'])

        # Tipos de proyecto, config de Registros, proyectos y ubicaciones
        self.tipos, self.proyectos = {}, {}
        for e in self.empresas:
            nombres = ['Poste', 'Torre', 'Rooftop', 'Shelter', 'Monopolo']
            self.tipos[e.pk] = [self.get_or_create(TipoProyecto, empresa=e, nombre=nombres[i % 5] + ('' if i < 5 else f' {i}'),
                                                   defaults={'orden': i}) for i in range(max(3, per))]
        for ke, e in enumerate(self.empresas, 1):
            self.proyectos[e.pk] = []
            miembros = list(Membresia.objects.filter(empresa=e))
            for p in range(per):
                tipo = self.tipos[e.pk][p % 3]
                lat, lon = -16.5 + rng.uniform(-2, 2), -68.1 + rng.uniform(-2, 2)
                proy, creado = Proyecto.objects.get_or_create(empresa=e, codigo=f'JNK{ke}-{p + 1:02d}', is_deleted=False, defaults=dict(
                    nombre=f'Sitio {rng.choice(APELLIDOS)} {ke}-{p + 1}',
                    codigo_operador=f'OP-{rng.randint(100, 999)}', tipo=tipo,
                    estado=rng.choice(Proyecto.Estado.values), region='La Paz', comuna=rng.choice(APELLIDOS), ciudad='El Alto',
                    descripcion='Proyecto generado por seed_junk.'))
                if creado:
                    self.tick(Proyecto)
                    proy.equipo.set(rng.sample(miembros, min(len(miembros), 3)))
                self.proyectos[e.pk].append(proy)
                for etiqueta in (['Construcción', 'Ingeniería'] if tipo is self.tipos[e.pk][1] else ['Mandato'])[:2]:
                    self.get_or_create(ProyectoUbicacion, proyecto=proy, etiqueta=etiqueta, defaults=dict(
                        lat=Decimal(f'{lat + rng.uniform(-.01, .01):.6f}'), lon=Decimal(f'{lon + rng.uniform(-.01, .01):.6f}')))

        # Media: singleton local (no se toca si ya existe) y tareas de migración falsas
        if not MediaStorageConfig.objects.exists():
            MediaStorageConfig().save()
            self.tick(MediaStorageConfig)
        qs = TareaMigracionMedia.objects.filter(prefijo__startswith='junk/')
        for i in range(self.faltan(qs)):
            total = rng.randint(5, 500)
            estado = rng.choice(TareaMigracionMedia.Estado.values)
            subidos = total if estado == 'OK' else rng.randint(0, total)
            tb = rng.randint(10**5, 10**9)
            self.create(TareaMigracionMedia, estado=estado, usuario=rng.choice(self.users), dry_run=rng.random() < .3,
                        prefijo=f'junk/{i}', borrar_local=rng.random() < .2, antiguedad_dias=rng.randint(0, 90),
                        archivos_total=total, archivos_subidos=subidos, archivos_omitidos=total - subidos,
                        archivos_borrados=0, bytes_total=tb, bytes_subidos=tb * subidos // max(total, 1),
                        terminada=timezone.now() if estado != 'EN_CURSO' else None,
                        errores='' if estado in ('OK', 'EN_CURSO') else 'Error simulado: timeout')

    def miembros(self, empresa, excluir_observador=True):
        from cuentas.models import Membresia
        qs = Membresia.objects.filter(empresa=empresa, activa=True, user__in=self.users).select_related('user', 'rol')
        return list(qs.exclude(rol__rol_base='OBSERVADOR') if excluir_observador else qs)

    # ── Cuentas: permisos y accesos ──────────────────────────────────────────
    def cuentas(self):
        from cuentas import capacidades
        from cuentas.models import AccesoModulo, Membresia, RolEmpresa, RolPermiso, UsuarioPermiso
        from empresas.models import Modulo

        rng = self.rng
        claves = sorted(capacidades.claves()) or ['proyectos.view', 'proyectos.manage']
        roles = list(RolEmpresa.objects.filter(empresa__in=self.empresas).order_by('empresa_id', 'id'))
        mems = list(Membresia.objects.filter(empresa__in=self.empresas).order_by('id'))

        def completar(modelo, qs, padres, campo):
            for i in range(self.faltan(qs)):
                for off in range(len(padres) * len(claves)):
                    padre, clave = padres[(i + off) % len(padres)], claves[(i * 7 + off) % len(claves)]
                    _, creado = modelo.objects.get_or_create(**{campo: padre, 'capacidad': clave},
                                                             defaults={'habilitado': rng.random() < .6})
                    if creado:
                        self.tick(modelo)
                        break

        completar(RolPermiso, RolPermiso.objects.filter(rol_empresa__in=roles), roles, 'rol_empresa')
        completar(UsuarioPermiso, UsuarioPermiso.objects.filter(membresia__in=mems), mems, 'membresia')

        qs = AccesoModulo.objects.filter(membresia__in=mems)
        modulos = Modulo.values
        for i in range(self.faltan(qs)):
            for off in range(len(mems) * len(modulos)):
                m, mod = mems[(i + off) % len(mems)], modulos[((i + off) // len(mems) + i) % len(modulos)]
                if not AccesoModulo.objects.filter(membresia=m, modulo=mod).exists():
                    otros = [r for r in roles if r.empresa_id == m.empresa_id]
                    self.create(AccesoModulo, membresia=m, modulo=mod, habilitado=rng.random() < .8,
                                rol_override=rng.choice(otros) if rng.random() < .4 else None)
                    break

    # ── Registros ────────────────────────────────────────────────────────────
    def registros(self):
        from django.contrib.contenttypes.models import ContentType
        from reg_actividades.models import DatoPaso, Paso, PasoAsignado, PasoWidget, Plantilla
        from reg_actividades.servicios import sembrar_ejemplo
        from reg_construccion.models import RegConstruccion
        from reg_fotos.models import Foto
        from reg_txtss.models import RegTxtss

        rng, n, hoy = self.rng, self.count, timezone.localdate()
        antes = {m: m.objects.count() for m in (Paso, Plantilla, PasoAsignado, PasoWidget)}
        from reg_base import tipos
        for e in self.empresas:
            sembrar_ejemplo(e)
            for clave in ('txtss', 'construccion', 'construccion-base'):   # los datos de prueba necesitan el tipo activo
                tipos.habilitar(e, clave)
        for m, c in antes.items():
            self.tick(m, m.objects.count() - c)
        # Pasos/plantillas extra para llegar a --count (filas con tipo de proyecto, activas y únicas)
        extra = Plantilla.objects.filter(empresa__in=self.empresas)
        deficit = self.faltan(extra)
        for e in self.empresas:
            for tipo in self.tipos[e.pk][:2]:
                if deficit <= 0:
                    break
                for clave in ('txtss', 'construccion'):
                    if deficit <= 0:
                        break
                    if not Plantilla.objects.filter(empresa=e, tipo_registro=clave, tipo_proyecto=tipo).exists():
                        pl = self.create(Plantilla, empresa=e, nombre=f'{clave} · {tipo.nombre}', tipo_registro=clave,
                                         tipo_proyecto=tipo, descripcion='Plantilla específica de prueba')
                        self.create(PasoAsignado, plantilla=pl, paso=Paso.objects.get(empresa=e, nombre='sitio'), orden=1)
                        deficit -= 1
        # Más pasos (slug único por empresa) hasta --count
        for i in range(self.faltan(Paso.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            p = self.create(Paso, empresa=e, nombre=f'junk-paso-{i}', titulo=f'Paso de prueba {i}', descripcion='Paso falso')
            self.create(PasoWidget, paso=p, widget_slug='comentario_widget', orden=1, config={'label': 'Notas'})
            self.create(PasoWidget, paso=p, widget_slug='lista_widget', orden=2, config={'numerada': True})
        for i in range(self.faltan(PasoWidget.objects.filter(paso__empresa__in=self.empresas))):
            p = rng.choice(list(Paso.objects.filter(empresa__in=self.empresas)))
            libres = [s for s in ('distancia_widget', 'ubicacion_widget', 'imgs_desc_widget', 'lista_widget') if not p.widgets.filter(widget_slug=s).exists()]
            if libres:
                self.create(PasoWidget, paso=p, widget_slug=libres[0], orden=9, config={})
        for i in range(self.faltan(PasoAsignado.objects.filter(plantilla__empresa__in=self.empresas))):
            pl = rng.choice(list(Plantilla.objects.filter(empresa__in=self.empresas)))
            libres = Paso.objects.filter(empresa=pl.empresa).exclude(asignaciones__plantilla=pl)
            if libres.exists():
                self.create(PasoAsignado, plantilla=pl, paso=libres.first(), orden=9)

        def usuario_de(e):
            return rng.choice(self.miembros(e)).user

        # TX/TSS (proyectos tipo Poste) y Construcción (tipo Torre, visitas en fechas distintas)
        for i in range(self.faltan(RegTxtss.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            proy = self.proyectos[e.pk][0]
            fecha = hoy - timedelta(days=i // self.E * 3 + i % 3)
            u = usuario_de(e)
            while RegTxtss.objects.filter(proyecto=proy, user=u, fecha=fecha, alternativa='A', is_deleted=False).exists():
                fecha -= timedelta(days=1)
            self.create(RegTxtss, empresa=e, proyecto=proy, user=u, fecha=fecha, alternativa=rng.choice('ABC'),
                        concluido=rng.random() < .4)
        for i in range(self.faltan(RegConstruccion.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            proy = self.proyectos[e.pk][1]
            fecha = hoy - timedelta(days=7 * (i // self.E) + 1)
            while RegConstruccion.objects.filter(proyecto=proy, fecha=fecha, is_deleted=False).exists():
                fecha -= timedelta(days=1)
            self.create(RegConstruccion, empresa=e, proyecto=proy, user=usuario_de(e), fecha=fecha,
                        contratista=rng.choice(self.contratistas[e.pk]), nombre_obra=f'Obra {proy.nombre}',
                        revision=rng.randint(0, 3),
                        concluido=rng.random() < .2, avance_pct=Decimal(rng.randint(0, 100)))

        # Construcción (base): visitas con hallazgos de distinta severidad (algunos vencidos o cerrados)
        from reg_construccion_base.models import Hallazgo, RegConstruccionBase
        for i in range(self.faltan(RegConstruccionBase.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            proy = self.proyectos[e.pk][-1]
            fecha = hoy - timedelta(days=7 * (i // self.E) + 2)
            while RegConstruccionBase.objects.filter(proyecto=proy, fecha=fecha, is_deleted=False).exists():
                fecha -= timedelta(days=1)
            emitida = rng.random() < .5
            v = self.create(RegConstruccionBase, empresa=e, proyecto=proy, user=usuario_de(e), fecha=fecha,
                            contratista=rng.choice(self.contratistas[e.pk]), concluido=emitida,
                            emitido_en=timezone.now() if emitida else None)
            if rng.random() < .7:
                estado = rng.choice(['abierto', 'abierto', 'en_proceso', 'cerrado'])
                self.create(Hallazgo, empresa=e, proyecto=proy, visita=v, descripcion=rng.choice(FRASES),
                            tipo=rng.choice(Hallazgo.Tipo.values), severidad=rng.choice(Hallazgo.Severidad.values),
                            plazo=hoy + timedelta(days=rng.randint(-10, 20)), estado=estado,
                            cerrado_fecha=hoy if estado == 'cerrado' else None, creado_por=v.user)

        # Datos de pasos (genéricos, por registro) y fotos (archivos falsos en storage privado)
        ct_tx, ct_co = ContentType.objects.get_for_model(RegTxtss), ContentType.objects.get_for_model(RegConstruccion)
        registros = list(RegTxtss.objects.filter(empresa__in=self.empresas)) + list(RegConstruccion.objects.filter(empresa__in=self.empresas))
        rng.shuffle(registros)
        faltan_datos = self.faltan(DatoPaso.objects.filter(empresa__in=self.empresas))
        for r in registros:
            if faltan_datos <= 0:
                break
            ct = ct_tx if isinstance(r, RegTxtss) else ct_co
            paso = 'sitio' if ct is ct_tx else 'obra_electrico'      # evita 'obra_avance' (recalcula acumulados)
            if not DatoPaso.objects.filter(content_type=ct, object_id=r.pk, paso_nombre=paso).exists():
                self.create(DatoPaso, empresa=r.empresa, content_type=ct, object_id=r.pk, paso_nombre=paso, tiene_datos=True,
                            datos={'comentario_widget': {'comentario': rng.choice(FRASES)}})
                faltan_datos -= 1
        faltan_fotos = self.faltan(Foto.objects.filter(empresa__in=self.empresas))
        for i in range(faltan_fotos):
            r = registros[i % len(registros)]
            ct = ct_tx if isinstance(r, RegTxtss) else ct_co
            png = _imagen('PNG', (rng.randint(0, 255), rng.randint(0, 255), rng.randint(0, 255)))
            f = Foto(empresa=r.empresa, content_type=ct, object_id=r.pk, etapa='sitio' if ct is ct_tx else 'obra_electrico',
                     descripcion=rng.choice(FRASES)[:128], orden=i, tamano=len(png), subida_por=r.user,
                     exif_lat=-16.5 + rng.uniform(-1, 1), exif_lon=-68.1 + rng.uniform(-1, 1),
                     exif_fecha=timezone.now() - timedelta(days=rng.randint(0, 30)))
            f.imagen.save(f'junk-{i}.png', ContentFile(png), save=False)
            if i % 2 == 0:
                f.miniatura.save(f'junk-{i}.png', ContentFile(png), save=False)
            f.save()
            self.tick(Foto)

    # ── Tareas ───────────────────────────────────────────────────────────────
    def tareas(self):
        from notificaciones.models import Notificacion
        from tar_adjuntos.models import Adjunto
        from tar_tickets.models import Asignacion, Comentario, ConfigTareas, Etiqueta, Evento, Ticket

        rng, hoy = self.rng, timezone.localdate()
        for e in self.empresas:
            _, creado = ConfigTareas.objects.get_or_create(empresa=e, defaults={'prefijo': ConfigTareas.prefijo_por_defecto(e)})
            if creado:
                self.tick(ConfigTareas)
        nombres = ['Instalación', 'Mantenimiento', 'Inspección', 'Soporte', 'Administrativo', 'Reunión']
        self.etiquetas = {e.pk: [] for e in self.empresas}
        for e in self.empresas:
            for i in range(max(3, self.per)):
                self.etiquetas[e.pk].append(self.get_or_create(
                    Etiqueta, empresa=e, nombre=nombres[i % 6] + ('' if i < 6 else f' {i}'),
                    defaults={'color': Etiqueta.Color.values[i % len(Etiqueta.Color.values)]}))

        for i in range(self.faltan(Ticket.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            ms = self.miembros(e)
            estado = rng.choice(Ticket.Estado.values)
            padre = Ticket.objects.filter(empresa=e).order_by('-id').first() if i % 5 == 4 else None
            t = Ticket.objects.create(
                empresa=e, titulo=f'{rng.choice(FRASES)} #{i}', solicitante=f'{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}',
                descripcion='Ticket generado por seed_junk.', padre=padre, estado=estado,
                prioridad=rng.choice(Ticket.Prioridad.values), tiene_subproductos=rng.random() < .4,
                creador=rng.choice(ms).user, proyecto=rng.choice(self.proyectos[e.pk]),
                vence=hoy + timedelta(days=rng.randint(-5, 30)), posicion=i,
                cerrado_en=timezone.now() if estado == 'DONE' else None,
                archivado_en=timezone.now() if estado == 'DONE' and rng.random() < .3 else None,
                es_parte_dividida=bool(padre) and rng.random() < .4)
            t.etiquetas.set(rng.sample(self.etiquetas[e.pk], 2))
            self.tick(Ticket)

        tickets = list(Ticket.objects.filter(empresa__in=self.empresas).order_by('id'))
        for t in tickets:
            if t.asignaciones.exists():
                continue
            ms = self.miembros(t.empresa)
            for user, tipo in zip(rng.sample([m.user for m in ms], min(2, len(ms))), ('EJECUTOR', 'EXPERTO')):
                est = t.estado if tipo == 'EJECUTOR' else 'TODO'
                self.create(Asignacion, ticket=t, user=user, tipo=tipo, estado=est, posicion=0,
                            iniciado_en=timezone.now() - timedelta(days=2) if est in ('IN_PROGRESS', 'DONE') else None,
                            cerrado_en=t.cerrado_en if est == 'DONE' else None,
                            aprobado_en=t.cerrado_en if est == 'DONE' else None,
                            conclusion='Concluido (falso).' if est == 'DONE' else '',
                            tiempo_por_hacer=timedelta(hours=rng.randint(0, 12)), tiempo_en_progreso=timedelta(hours=rng.randint(0, 30)))
        asigs = list(Asignacion.objects.filter(ticket__in=tickets))
        for i in range(self.faltan(Comentario.objects.filter(ticket__in=tickets))):
            t = tickets[i % len(tickets)]
            self.create(Comentario, ticket=t, autor=rng.choice(self.miembros(t.empresa)).user, texto=rng.choice(FRASES) + '.')
        comentarios = list(Comentario.objects.filter(ticket__in=tickets))
        tipos_ev = ['created', 'status', 'assignee', 'priority', 'due', 'conclude', 'approve', 'reject', 'archived', 'split']
        for i in range(self.faltan(Evento.objects.filter(ticket__in=tickets))):
            t = tickets[i % len(tickets)]
            a = rng.choice([x for x in asigs if x.ticket_id == t.pk] or [None])
            self.create(Evento, ticket=t, asignacion=a, actor=rng.choice(self.miembros(t.empresa)).user,
                        tipo=tipos_ev[i % len(tipos_ev)], detalle=f'Evento de prueba {i}')
        previo = None
        for i in range(self.faltan(Adjunto.objects.filter(empresa__in=self.empresas))):
            t = previo.ticket if (previo and i % 5 == 4) else tickets[i % len(tickets)]
            png = _imagen('PNG', (rng.randint(0, 255), 80, 120))
            com = next((c for c in comentarios if c.ticket_id == t.pk), None) if i % 2 == 0 else None
            a = Adjunto(empresa=t.empresa, ticket=t, comentario=com, nombre=f'junk-{i}.png', mime_type='image/png',
                        tamano=len(png), sha256=hashlib.sha256(png).hexdigest(), subido_por=t.creador,
                        version_de=previo if (previo and i % 5 == 4) else None,
                        version_numero=2 if (previo and i % 5 == 4) else 1)
            a.archivo.save(f'junk-{i}.png', ContentFile(png), save=False)
            a.save()
            self.tick(Adjunto)
            previo = a

        for i in range(self.faltan(Notificacion.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            ms = self.miembros(e, excluir_observador=False)
            self.create(Notificacion, destinatario=rng.choice(ms).user, empresa=e, actor=rng.choice(ms).user if i % 4 else None,
                        mensaje=f'{rng.choice(FRASES)} (aviso {i})', url=f'/tareas/{rng.choice(tickets).pk}/', leida=rng.random() < .5)

    # ── Jornadas ─────────────────────────────────────────────────────────────
    def jornadas(self):
        from cuentas.models import Membresia
        from jor_actividades.models import CategoriaActividad, Etiqueta, ItemActividad
        from jor_diario.models import Ausencia, Jornada, NotaCalendario, ReporteDiario
        from jor_empleados.models import ConfigJornadas, Perfil
        from mje_mensajes.models import Mensaje

        rng, n, ahora = self.rng, self.count, timezone.now()

        for e in self.empresas:
            _, creado = ConfigJornadas.objects.get_or_create(empresa=e)
            if creado:
                self.tick(ConfigJornadas)
        for m in Membresia.objects.filter(empresa__in=self.empresas).select_related('rol'):
            self.get_or_create(Perfil, membresia=m, defaults=dict(
                cargo=rng.choice(['Ingeniero', 'Técnico', 'Supervisor', 'Topógrafo', 'Analista']),
                hora_entrada=time(rng.choice([7, 8, 9]), 0),
                exige_reporte=rng.random() < .5, haber_basico=Decimal(rng.randint(3000, 12000)),
                ciudad_catering=rng.choice(['NONE', 'LPZ', 'CBA', 'SCZ']), numero_item=rng.randint(1, 50),
                activo=True))
        perfiles = {e.pk: list(Perfil.objects.filter(membresia__empresa=e, activo=True).exclude(membresia__rol__rol_base='OBSERVADOR')
                               .select_related('membresia__user')) for e in self.empresas}

        # Categorías y etiquetas de actividad
        cats = ['reuniones', 'desarrollo', 'soporte', 'otros', 'campo', 'capacitacion']
        for e in self.empresas:
            for i in range(max(4, self.per)):
                cod = cats[i] if i < len(cats) else f'cat{i}'
                self.get_or_create(CategoriaActividad, empresa=e, codigo=cod, defaults=dict(
                    etiqueta=cod.capitalize(), color='#%06x' % rng.randint(0, 0xFFFFFF), orden=i, protegida=cod == 'otros'))
        for i in range(self.faltan(Etiqueta.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            tipo = Etiqueta.Tipo.values[i % 3]
            nombre = f'{tipo.capitalize()} {rng.choice(APELLIDOS)} {i}'
            canon = Etiqueta.objects.filter(empresa=e, tipo=tipo, canonica=None).first() if i % 4 == 3 else None
            self.create(Etiqueta, empresa=e, tipo=tipo, nombre=nombre, clave=nombre.lower(), canonica=canon,
                        codigo=f'E{i}', ignorada=rng.random() < .1)

        # Jornadas (una en curso como máximo por perfil), reportes e ítems
        for i in range(self.faltan(Jornada.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            perfil = rng.choice(perfiles[e.pk])
            dias = i // self.E + 1
            inicio = self.dt(dias, 8, rng.randint(0, 40))
            en_curso = i == 0 and not Jornada.objects.filter(perfil=perfil, estado='en_curso').exists()
            if en_curso:
                inicio = ahora - timedelta(hours=2)
            dur = rng.randint(300, 540)
            estado = 'en_curso' if en_curso else rng.choice(['completada'] * 4 + ['incompleta'])
            self.create(Jornada, empresa=e, perfil=perfil, proyecto=rng.choice(self.proyectos[e.pk]), inicio=inicio,
                        fin=None if en_curso else inicio + timedelta(minutes=dur),
                        duracion_min=None if en_curso else dur, estado=estado, cierre_auto=estado == 'incompleta',
                        lat_inicio=Decimal('-16.500000'), lon_inicio=Decimal('-68.150000'),
                        lat_fin=None if en_curso else Decimal('-16.510000'), lon_fin=None if en_curso else Decimal('-68.140000'))
        jornadas = list(Jornada.objects.filter(empresa__in=self.empresas).order_by('id'))
        cerradas = [j for j in jornadas if j.fin]
        for j in cerradas:
            if self.faltan(ReporteDiario.objects.filter(jornada__in=jornadas)) and not hasattr(j, 'reporte') \
                    and not ReporteDiario.objects.filter(jornada=j).exists():
                self.create(ReporteDiario, jornada=j, realizado='\n'.join(rng.sample(FRASES, 3)),
                            planificado='\n'.join(rng.sample(FRASES, 2)))
        reportes = list(ReporteDiario.objects.filter(jornada__in=jornadas).select_related('jornada'))
        for i in range(self.faltan(ItemActividad.objects.filter(empresa__in=self.empresas))):
            r = reportes[i % len(reportes)]
            tipo = ItemActividad.Tipo.values[(i // len(reportes)) % 2]
            pos = ItemActividad.objects.filter(reporte=r, tipo=tipo).count()
            it = self.create(ItemActividad, empresa=r.jornada.empresa, reporte=r, tipo=tipo, posicion=pos, texto=rng.choice(FRASES),
                             categoria=rng.choice(list(CategoriaActividad.objects.filter(empresa=r.jornada.empresa).values_list('codigo', flat=True))),
                             fuente=rng.choice(ItemActividad.Fuente.values), palabra=rng.choice(['montaje', 'reunión', 'informe']),
                             manual=rng.random() < .3)
            it.etiquetas.set(Etiqueta.objects.filter(empresa=r.jornada.empresa)[:2])

        # Ausencias y calendario
        for i in range(self.faltan(Ausencia.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            desde = timezone.localdate() + timedelta(days=rng.randint(-30, 30))
            estado = rng.choice(Ausencia.Estado.values)
            self.create(Ausencia, empresa=e, perfil=rng.choice(perfiles[e.pk]), desde=desde, hasta=desde + timedelta(days=rng.randint(0, 5)),
                        tipo=rng.choice(Ausencia.Tipo.values), nota='Ausencia de prueba', estado=estado,
                        decidida_por=None if estado == 'pendiente' else rng.choice(self.users),
                        decidida_en=None if estado == 'pendiente' else ahora, creada_por=rng.choice(self.users))
        for i in range(self.faltan(NotaCalendario.objects.filter(empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            self.create(NotaCalendario, empresa=e, fecha=timezone.localdate() + timedelta(days=rng.randint(-20, 40)),
                        texto=rng.choice(['Feriado nacional', 'Cierre de mes', 'Capacitación', 'Auditoría']),
                        tipo=rng.choice(NotaCalendario.Tipo.values), creada_por=rng.choice(self.users))

        # Mensajes (chat): directos entre dos personas de la misma empresa
        from mje_mensajes import servicios as chat
        for i in range(self.faltan(Mensaje.objects.filter(conversacion__empresa__in=self.empresas))):
            e = self.empresas[i % self.E]
            gente = [p.membresia.user for p in perfiles[e.pk]]
            if len(gente) < 2:
                continue
            a, b = rng.sample(gente, 2)
            conv = chat.directo(e, a, b)
            m = self.create(Mensaje, conversacion=conv, autor=a, texto=f'Recordatorio: {rng.choice(FRASES).lower()}.')
            type(conv).objects.filter(pk=conv.pk).update(ultimo_mensaje_en=m.creado)

    # ── Resumen y verificación ───────────────────────────────────────────────
    def resumen(self):
        raiz = str(settings.BASE_DIR)
        propios = [m for m in apps.get_models()
                   if getattr(apps.get_app_config(m._meta.app_label), 'path', '').startswith(raiz)
                   and 'site-packages' not in apps.get_app_config(m._meta.app_label).path]
        self.stdout.write(f'\n{"Modelo":42}{"creadas":>9}{"total":>8}')
        vacios = []
        for m in sorted(propios, key=lambda m: m._meta.label):
            total = m.objects.count()
            self.stdout.write(f'{m._meta.label:42}{self.creados.get(m._meta.label, 0):>9}{total:>8}')
            if not total:
                vacios.append(m._meta.label)
        self.stdout.write(f'\nUsuarios junk: junk_00@example.com … (clave «{PASSWORD}»). Empresas: EMBOL y PTI.')
        if vacios:
            self.stdout.write(self.style.WARNING('Modelos sin filas: ' + ', '.join(vacios)))
        else:
            self.stdout.write(self.style.SUCCESS('Todos los modelos propios tienen filas.'))

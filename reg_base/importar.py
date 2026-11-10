"""Importador de datos de Registros desde reg.tekon-rl.cl (producción) hacia una empresa de skygroup.

Lee los JSONL que deja `scripts/traer_legacy_reg.sh` (una línea = una fila de la tabla original, vía `row_to_json`) y
los archivos de media. Es idempotente: lo que ya trae `legacy_source='reg'` + `legacy_id` se reutiliza; la
configuración (pasos, widgets, plantillas) se busca por clave natural."""
import io
import json
import os
from collections import Counter, defaultdict
from datetime import timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from proyectos.models import Proyecto

FUENTE = 'reg'
# Estados de obra del sistema legacy → estado del proyecto.
ESTADO_OBRA_LEGACY = {'construccion': 'CONSTRUCCION', 'paralizado': 'PARALIZADO',
                      'cancelado': 'CANCELADO', 'concluido': 'CONCLUIDO'}

# Rol de skygroup según el `user_type` original: (nombre del RolEmpresa, rol base si hay que crearlo).
ROLES = {
    'ADMINISTRADOR': ('Coordinador', 'COORDINADOR'),
    '': ('Coordinador', 'COORDINADOR'),
    'ITO': ('ITO', 'MIEMBRO'),
    'SEARCHER': ('Buscador', 'MIEMBRO'),
    'VISITA': ('Observador', 'OBSERVADOR'),
}
UBICACIONES = (('Mandato', 'man'), ('Ingeniería', 'ing'), ('Construcción', 'con'))
CAMPOS_NUMERICOS = {'lat', 'lon', 'accuracy', 'lat1', 'lon1', 'lat2', 'lon2', 'distancia_metros'}


def leer_jsonl(ruta):
    if not os.path.exists(ruta):
        return []
    with open(ruta, encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def _fecha(valor):
    return parse_date(valor) if valor else None


def _fechahora(valor):
    if not valor:
        return None
    dt = parse_datetime(valor)
    if dt is not None and timezone.is_naive(dt):
        dt = timezone.make_aware(dt, dt_timezone.utc)
    return dt


def _decimal(valor, lugares=6):
    if valor in (None, ''):
        return None
    try:
        return round(Decimal(str(valor)), lugares)
    except InvalidOperation:
        return None


def _numero(valor):
    if isinstance(valor, str):
        try:
            return float(valor.replace(',', '.'))
        except ValueError:
            return valor
    return valor


def _json(valor, defecto):
    """Los JSONField llegan ya decodificados, pero tolera texto JSON."""
    if isinstance(valor, str):
        try:
            return json.loads(valor)
        except ValueError:
            return defecto
    return defecto if valor is None else valor


def opcional_de_etapa(clave, paso, slug, config):
    """Copia de `config` con `opcional` si el widget es de una etapa opcional de Construcción.

    En reg las etapas `ETAPAS_OPCIONALES` (el paso eléctrico y las fotos del libro de obras) nunca contaban para que
    una visita estuviera completa; en skygroup eso se expresa con `opcional` en el widget. Sin esta marca la plantilla
    importada exigiría esas fotos y ninguna visita quedaría «completa»."""
    from reg_construccion.models import ETAPAS_OPCIONALES
    config = dict(config or {})
    etapa = config.get('etapa') or ('obra_libro' if slug == 'camera_libro_widget' else '')
    if clave == 'construccion' and (paso in ETAPAS_OPCIONALES or etapa in ETAPAS_OPCIONALES):
        config['opcional'] = True
    return config


def _firma(widgets):
    return tuple(sorted((w['widget_slug'], json.dumps(w.get('config') or {}, sort_keys=True)) for w in widgets))


def claves_de_widget(slug, config):
    """Claves planas de `DatoPaso.datos` (original) que pertenecen a cada tipo de widget."""
    from reg_actividades.widgets import poste
    from reg_actividades.widgets.form_dinamico import parsear_campos
    if slug == 'ubicacion_widget':
        return ['lat', 'lon', 'accuracy']
    if slug == 'distancia_widget':
        return ['lat1', 'lon1', 'lat2', 'lon2', 'distancia_metros']
    if slug == 'lista_widget':
        return ['entradas']
    if slug == 'comentario_widget':
        return ['comentario']
    if slug == 'poste_form_widget':
        return list(poste.TEXTOS) + [c for c, _ in poste.TOGGLES]
    if slug == 'tabla_avance_widget':
        return ['plantilla', 'partidas']
    if slug == 'form_dinamico_widget':
        return [c['nombre'] for c in parsear_campos((config or {}).get('campos', ''))]
    return []


def anidar(planos, widgets):
    """Pasa los datos planos del original a `{widget_slug: {…}}`. `widgets` = [(slug, config)] del paso.
    Devuelve (anidado, claves_sin_dueño)."""
    from reg_actividades.widgets import poste
    from reg_actividades.widgets.form_dinamico import parsear_campos
    planos = dict(planos or {})
    salida, usadas = {}, set()
    for slug, config in widgets:
        if isinstance(planos.get(slug), dict):          # ya venía anidado
            salida[slug] = planos[slug]
            usadas.add(slug)
            continue
        bloque = {}
        toggles = {c for c, _ in poste.TOGGLES} if slug == 'poste_form_widget' else set()
        if slug == 'form_dinamico_widget':
            toggles = {c['nombre'] for c in parsear_campos((config or {}).get('campos', '')) if c['tipo'] == 'toggle'}
        for clave in claves_de_widget(slug, config):
            if clave not in planos:
                continue
            valor = planos[clave]
            usadas.add(clave)
            if clave in toggles:
                valor = valor in (True, 'true', 'True', 'on', '1', 1)
            elif slug in ('ubicacion_widget', 'distancia_widget') and clave in CAMPOS_NUMERICOS:
                valor = _numero(valor)
            elif clave == 'partidas' or (clave == 'entradas' and isinstance(valor, str)):
                valor = _json(valor, [])
            bloque[clave] = valor
        if bloque:
            salida[slug] = bloque
    return salida, [k for k in planos if k not in usadas]


class Importador:
    def __init__(self, empresa, directorio, media=None, con_archivos=True, salida=None, desde=None):
        self.desde = desde   # solo crea registros con fecha >= desde
        self.empresa = empresa
        self.dir = directorio
        self.media = media
        self.con_archivos = con_archivos and bool(media)
        self.salida = salida or (lambda *_: None)
        self.avisos = []
        self.n = Counter()          # contadores «creados»
        self.omitidos = Counter()
        # mapas legacy_id → objeto nuevo
        self.usuarios, self.contratistas, self.proyectos = {}, {}, {}
        self.reg_txtss, self.reg_constr = {}, {}
        self.slug_pasodef, self.slug_tipo_nombre = {}, {}
        self.tipo_de_registro = {}        # (clave, legacy_id) → TipoActividad legacy id
        self.cts = {}

    # ── utilidades ────────────────────────────────────────────────────────────
    def aviso(self, texto):
        self.avisos.append(texto)

    def tabla(self, nombre):
        return leer_jsonl(os.path.join(self.dir, f'{nombre}.jsonl'))

    def info(self, texto):
        self.salida(texto)

    # ── limpieza de datos de ejemplo ──────────────────────────────────────────
    def limpiar(self):
        from proyectos.models import Proyecto
        from reg_actividades.models import ImagenMapa, Paso, Plantilla
        from reg_construccion.models import RegConstruccion
        from reg_txtss.models import RegTxtss
        e = self.empresa
        for modelo in (RegTxtss, RegConstruccion):
            for r in modelo.objects.filter(empresa=e).exclude(legacy_source=FUENTE):
                r.delete()          # arrastra fotos y datos de pasos (GenericRelation)
        for m in ImagenMapa.objects.filter(empresa=e).exclude(legacy_source=FUENTE):
            m.delete()
        # El Proyecto es común a los 3 módulos: solo se borra el de ejemplo, nunca uno que ya use Tareas o Jornadas.
        Proyecto.objects.filter(empresa=e, tickets__isnull=True, jornadas__isnull=True).exclude(legacy_source=FUENTE).delete()
        if Proyecto.objects.filter(empresa=e, legacy_source=FUENTE).exists():
            self.aviso('Ya hay datos importados: se conservan los pasos y plantillas (solo se borró el ejemplo).')
            return
        Plantilla.objects.filter(empresa=e).delete()
        Paso.objects.filter(empresa=e).delete()

    # ── 1. contratistas ───────────────────────────────────────────────────────
    def contratistas_(self):
        from empresas.models import Contratista
        existentes = {c.legacy_id: c for c in Contratista.objects.filter(empresa=self.empresa, legacy_source=FUENTE)}
        for fila in self.tabla('core_contractor'):
            c = existentes.get(fila['id'])
            if c is None:
                c = Contratista.objects.filter(empresa=self.empresa, codigo__iexact=fila['code'], is_deleted=False).first()
            if c is None:
                c = Contratista.objects.create(
                    empresa=self.empresa, nombre=fila['name'], codigo=fila['code'], activo=fila.get('is_active', True),
                    is_deleted=fila.get('is_deleted', False), legacy_source=FUENTE, legacy_id=fila['id'])
                self.n['contratistas'] += 1
            self.contratistas[fila['id']] = c

    # ── 2. usuarios y membresías ──────────────────────────────────────────────
    def usuarios_(self):
        from cuentas.models import Membresia, RolEmpresa, User
        roles = {r.nombre.lower(): r for r in RolEmpresa.objects.filter(empresa=self.empresa)}

        def rol(tipo):
            nombre, base = ROLES.get(tipo, ROLES['ITO'])
            if nombre.lower() not in roles:
                roles[nombre.lower()] = RolEmpresa.objects.create(empresa=self.empresa, nombre=nombre, rol_base=base)
            return roles[nombre.lower()]

        sin_correo = 0
        for fila in self.tabla('users_user'):
            email = (fila.get('email') or '').strip().lower()
            if not email:
                email = f"{fila['username']}@reg.legacy".lower()
                sin_correo += 1
            user = User.objects.filter(email__iexact=email).first()
            if user is None:
                user = User(email=email, first_name=fila.get('first_name') or '', last_name=fila.get('last_name') or '',
                            telefono=(fila.get('phone') or '')[:30], is_active=fila.get('is_active', True) and not fila.get('is_deleted'),
                            legacy_source=FUENTE, legacy_id=fila['id'])
                user.password = fila.get('password') or ''
                if not user.password:
                    user.set_unusable_password()
                user.save()
                self.n['usuarios'] += 1
            self.usuarios[fila['id']] = user
            if _json(fila.get('report_access'), []):
                self.aviso(f'{email}: tenía «report_access» limitado ({fila["report_access"]}); en skygroup no existe, '
                           'revisa su rol y acceso al módulo.')
            tipo = '' if fila.get('is_superuser') else (fila.get('user_type') or '')
            m, creada = Membresia.objects.get_or_create(
                user=user, empresa=self.empresa,
                defaults={'rol': rol(tipo), 'contratista': self.contratistas.get(fila.get('contractor_id')),
                          'activa': user.is_active})
            self.n['membresías'] += creada
        if sin_correo:
            self.aviso(f'{sin_correo} usuario(s) sin correo: se usó «<usuario>@reg.legacy». Corrígelos en el admin.')

    # ── 3. sitios → proyectos ─────────────────────────────────────────────────
    def proyectos_(self):
        from proyectos.models import Proyecto, ProyectoUbicacion, TipoProyecto
        tipos = {}
        for nombre in ('Poste', 'Torre'):
            tipos[nombre.upper()], _ = TipoProyecto.objects.get_or_create(empresa=self.empresa, nombre__iexact=nombre,
                                                                         defaults={'nombre': nombre})
        existentes = {p.legacy_id: p for p in Proyecto.objects.filter(empresa=self.empresa, legacy_source=FUENTE)}
        codigos = {c.lower() for c in Proyecto.objects.filter(empresa=self.empresa, is_deleted=False)
                   .values_list('codigo', flat=True)}
        for s in self.tabla('core_site'):
            p = existentes.get(s['id'])
            if p is None:
                codigo = ((s.get('pti_cell_id') or '').strip() or s['name'].strip())[:40]
                if codigo.lower() in codigos and not s.get('is_deleted'):
                    codigo = f"{codigo[:34]}-{s['id']}"
                    self.aviso(f'Código duplicado en «{s["name"]}»: se usó {codigo}.')
                p = Proyecto.objects.create(
                    empresa=self.empresa, nombre=s['name'][:160], codigo=codigo,
                    codigo_operador=(s.get('operator_id') or '')[:60], tipo=tipos.get((s.get('tipo_sitio') or '').upper()),
                    region=(s.get('region') or '')[:80], comuna=(s.get('comuna') or '')[:80], descripcion=s.get('tipo_estructura') or '',
                    is_deleted=bool(s.get('is_deleted')), legacy_source=FUENTE, legacy_id=s['id'])
                if not p.is_deleted:
                    codigos.add(codigo.lower())
                self.n['proyectos'] += 1
            self.proyectos[s['id']] = p
            for etiqueta, sufijo in UBICACIONES:
                la, lo = _decimal(s.get(f'lat_{sufijo}')), _decimal(s.get(f'lon_{sufijo}'))
                if la is not None and lo is not None:
                    _, creada = ProyectoUbicacion.objects.get_or_create(
                        proyecto=p, etiqueta=etiqueta, defaults={'lat': la, 'lon': lo})
                    self.n['ubicaciones'] += creada

    # ── 4. configuración: pasos, widgets, plantillas ──────────────────────────
    def _destino_tipo(self, ta):
        """(tipo_registro, nombre del tipo de proyecto | None) de un TipoActividad original."""
        ns = ta['app_namespace']
        clave = 'construccion' if ns.startswith('reg_construccion') else 'txtss' if ns.startswith('reg_txtss') else None
        if clave is None:
            self.aviso(f'Tipo de actividad «{ns}» no corresponde a un módulo conocido: se omite.')
            return None, None
        return clave, (ta.get('tipo_sitio') or '').title() or None

    def configuracion_(self):
        from proyectos.models import TipoProyecto
        from reg_actividades import widgets as registro_widgets
        from reg_actividades.models import Paso, PasoAsignado, PasoWidget, Plantilla
        tipos_act = {t['id']: t for t in self.tabla('actividades_tipoactividad')}
        defs = {d['id']: d for d in self.tabla('actividades_pasodefinicion')}
        widgets_de = defaultdict(list)
        for w in self.tabla('actividades_pasowidget'):
            widgets_de[w['pasodef_id']].append(w)
        for lista in widgets_de.values():
            lista.sort(key=lambda w: (w.get('orden', 0), w['id']))
        asignaciones = defaultdict(list)
        for c in self.tabla('actividades_configpaso'):
            asignaciones[c['tipo_id']].append(c)

        firmas, tipo_de_paso = {}, {}
        for tid in sorted(tipos_act):
            ta = tipos_act[tid]
            clave, tipo_nombre = self._destino_tipo(ta)
            if clave is None:
                continue
            tipo_proy = TipoProyecto.objects.filter(empresa=self.empresa, nombre__iexact=tipo_nombre).first() if tipo_nombre else None
            self.tipo_de_registro[(clave, (tipo_nombre or '').upper())] = tid
            plantilla = Plantilla.objects.filter(empresa=self.empresa, tipo_registro=clave, tipo_proyecto=tipo_proy,
                                                 nombre=ta['nombre'][:100]).first()
            if plantilla is None:
                activa = bool(ta.get('activo', True)) and not Plantilla.objects.filter(
                    empresa=self.empresa, tipo_registro=clave, tipo_proyecto=tipo_proy, activa=True).exists()
                plantilla = Plantilla.objects.create(
                    empresa=self.empresa, nombre=ta['nombre'][:100], descripcion=ta.get('descripcion') or '',
                    tipo_registro=clave, tipo_proyecto=tipo_proy, activa=activa)
                self.n['plantillas'] += 1
            for cp in sorted(asignaciones[tid], key=lambda c: (c.get('orden', 0), c['id'])):
                d = defs.get(cp['pasodef_id'])
                if d is None:
                    continue
                if d['id'] not in self.slug_pasodef:
                    ws = [w for w in widgets_de[d['id']] if registro_widgets.obtener(w['widget_slug'])]
                    for w in widgets_de[d['id']]:
                        if not registro_widgets.obtener(w['widget_slug']):
                            self.aviso(f'Widget «{w["widget_slug"]}» (paso {d["nombre"]}) no existe en skygroup: omitido.')
                    sig = _firma(ws)
                    slug = d['nombre'][:50]
                    if slug in firmas and firmas[slug] != sig:
                        slug = f"{slug[:42]}-{(tipo_nombre or clave).lower()}"
                        if slug in firmas and firmas[slug] != sig:
                            slug = f"{slug[:40]}-{d['id']}"
                    firmas[slug] = sig
                    paso, creado = Paso.objects.get_or_create(
                        empresa=self.empresa, nombre=slug,
                        defaults={'titulo': d['titulo'][:100], 'descripcion': d.get('descripcion') or ''})
                    if creado:
                        self.n['pasos'] += 1
                        for w in ws:
                            PasoWidget.objects.create(
                                paso=paso, widget_slug=w['widget_slug'], orden=w.get('orden', 0),
                                config=opcional_de_etapa(clave, d['nombre'], w['widget_slug'], _json(w.get('config'), {})))
                    self.slug_pasodef[d['id']] = slug
                    tipo_de_paso.setdefault(slug, tid)
                slug = self.slug_pasodef[d['id']]
                self.slug_tipo_nombre[(tid, d['nombre'])] = slug
                PasoAsignado.objects.get_or_create(
                    plantilla=plantilla, paso=Paso.objects.get(empresa=self.empresa, nombre=slug),
                    defaults={'orden': cp.get('orden', 0)})
        # Los widgets de mapa nombran otros pasos: reescribir con los slugs definitivos.
        for pw in PasoWidget.objects.filter(paso__empresa=self.empresa, widget_slug__in=('mapa_1p', 'mapa_2_puntos')):
            tid = tipo_de_paso.get(pw.paso.nombre)
            cambio = False
            for k in ('paso', 'paso1', 'paso2'):
                nuevo = self.slug_tipo_nombre.get((tid, pw.config.get(k)))
                if nuevo and nuevo != pw.config.get(k):
                    pw.config[k], cambio = nuevo, True
            if cambio:
                pw.save(update_fields=['config'])

    # ── 5. registros ──────────────────────────────────────────────────────────
    def _tipo_legacy(self, clave, sitio):
        """TipoActividad original que aplica a un registro (para renombrar sus pasos)."""
        tipo_sitio = 'TORRE' if clave == 'construccion' else (sitio.get('tipo_sitio') or '').upper()
        return self.tipo_de_registro.get((clave, tipo_sitio))

    def registros_(self):
        from reg_construccion.models import RegConstruccion
        from reg_txtss.models import RegTxtss
        sitios = {s['id']: s for s in self.tabla('core_site')}
        self.tipo_reg = {}      # (clave, nuevo pk) → tipo de actividad original
        for clave, modelo, destino, tabla in (('txtss', RegTxtss, self.reg_txtss, 'reg_txtss_regtxtss'),
                                              ('construccion', RegConstruccion, self.reg_constr, 'reg_construccion_regconstruccion')):
            existentes = {r.legacy_id: r for r in modelo.objects.filter(empresa=self.empresa, legacy_source=FUENTE)}
            for f in self.tabla(tabla):
                r = existentes.get(f['id'])
                if r is None:
                    if self.desde and (_fecha(f['fecha']) or self.desde) < self.desde:
                        continue
                    if f.get('sitio_id') not in self.proyectos:
                        self.omitidos[f'{clave} sin sitio'] += 1
                        continue
                    campos = dict(
                        empresa=self.empresa, proyecto=self.proyectos[f['sitio_id']], user=self.usuarios.get(f.get('user_id')),
                        fecha=_fecha(f['fecha']), is_active=f.get('is_active', True), is_deleted=bool(f.get('is_deleted')),
                        concluido=bool(f.get('concluido')), legacy_source=FUENTE, legacy_id=f['id'])
                    if clave == 'txtss':
                        campos['alternativa'] = f.get('alternativa') or 'A'
                    else:
                        campos.update(contratista=self.contratistas.get(f.get('contratista_id')),
                                      nombre_obra=(f.get('proyecto') or '')[:120], descripcion=(f.get('descripcion') or '')[:255],
                                      revision=f.get('revision') or 0)
                        if f.get('estado_obra') in ESTADO_OBRA_LEGACY:   # el estado de la obra vive ahora en el proyecto
                            campos_estado = ESTADO_OBRA_LEGACY[f['estado_obra']]
                            Proyecto.objects.filter(pk=campos['proyecto'].pk).update(estado=campos_estado)
                    r = modelo(**campos)
                    try:
                        with transaction.atomic():
                            modelo.objects.bulk_create([r])      # sin save(): ni full_clean ni señales
                    except IntegrityError:
                        self.omitidos[f'{clave} duplicado'] += 1
                        self.aviso(f'{clave} #{f["id"]} (sitio {f["sitio_id"]}, {f["fecha"]}) choca con otro registro: omitido.')
                        continue
                    ts = _fechahora(f.get('created_at'))
                    if ts:
                        modelo.objects.filter(pk=r.pk).update(created_at=ts, updated_at=_fechahora(f.get('updated_at')) or ts)
                    self.n[f'registros {clave}'] += 1
                destino[f['id']] = r
                self.tipo_reg[(clave, r.pk)] = self._tipo_legacy(clave, sitios[f['sitio_id']]) if f.get('sitio_id') in sitios else None
        self.cts = {}
        for ct in self.tabla('django_content_type'):
            self.cts[ct['id']] = (ct['app_label'], ct['model'])

    def _registro_de(self, ct_id, object_id):
        """(clave, registro nuevo) para una referencia genérica del original."""
        destino = {('reg_txtss', 'regtxtss'): ('txtss', self.reg_txtss),
                   ('reg_construccion', 'regconstruccion'): ('construccion', self.reg_constr)}.get(self.cts.get(ct_id))
        if destino is None:
            return None, None
        return destino[0], destino[1].get(object_id)

    def _etapa(self, clave, registro, etapa):
        tid = self.tipo_reg.get((clave, registro.pk))
        return self.slug_tipo_nombre.get((tid, etapa), etapa)

    # ── 6. datos de pasos ─────────────────────────────────────────────────────
    def datos_pasos_(self):
        from reg_actividades.models import DatoPaso, PasoWidget
        from reg_actividades.widgets.base import _lleno
        widgets = defaultdict(list)
        for pw in PasoWidget.objects.filter(paso__empresa=self.empresa).select_related('paso').order_by('orden', 'id'):
            widgets[pw.paso.nombre].append((pw.widget_slug, pw.config))
        sin_dueno = Counter()
        for f in self.tabla('actividades_datopaso'):
            clave, r = self._registro_de(f['content_type_id'], f['object_id'])
            if r is None:
                continue
            ct = ContentType.objects.get_for_model(type(r))
            paso = self._etapa(clave, r, f['paso_nombre'])
            if DatoPaso.objects.filter(content_type=ct, object_id=r.pk, paso_nombre=paso).exists():
                continue
            anidado, huerfanas = anidar(_json(f.get('datos'), {}), widgets.get(paso, []))
            if huerfanas:
                anidado['_legacy'] = {k: _json(f['datos'], {}).get(k) for k in huerfanas}
                sin_dueno[paso] += len(huerfanas)
            tiene = any(_lleno(v) for slug, b in anidado.items() if slug != '_legacy' for v in b.values())
            DatoPaso.objects.bulk_create([DatoPaso(empresa=self.empresa, content_type=ct, object_id=r.pk,
                                                   paso_nombre=paso, datos=anidado, tiene_datos=tiene)])
            self.n['datos de pasos'] += 1
        for paso, k in sin_dueno.items():
            self.aviso(f'Paso «{paso}»: {k} valor(es) sin widget que los reclame; quedaron en «_legacy» del dato.')

    # ── 7-8. fotos y mapas ────────────────────────────────────────────────────
    def _leer_archivo(self, ruta_relativa):
        ruta = os.path.join(self.media, ruta_relativa or '')
        if not ruta_relativa or not os.path.isfile(ruta):
            return None, ruta_relativa
        with open(ruta, 'rb') as fh:
            return fh.read(), ruta_relativa

    def fotos_(self):
        if not self.con_archivos:
            return
        from reg_fotos.models import Foto
        from reg_fotos.servicios import _miniatura
        from PIL import Image
        hechas = set(Foto.objects.filter(empresa=self.empresa, legacy_source=FUENTE).values_list('legacy_id', flat=True))
        orden_por = defaultdict(int)
        for f in sorted(self.tabla('photos_photos'), key=lambda x: (x['object_id'], x.get('orden') or 0, x['id'])):
            if f['id'] in hechas or f.get('is_deleted'):
                continue
            clave, r = self._registro_de(f['content_type_id'], f['object_id'])
            if r is None:
                self.omitidos['fotos sin registro'] += 1
                continue
            datos, ruta = self._leer_archivo(f.get('imagen'))
            if datos is None:
                self.omitidos['fotos sin archivo'] += 1
                continue
            etapa = self._etapa(clave, r, f['etapa'])
            ct = ContentType.objects.get_for_model(type(r))
            foto = Foto(empresa=self.empresa, content_type=ct, object_id=r.pk, etapa=etapa,
                        descripcion=(f.get('descripcion') or '')[:128], orden=f.get('orden') or 0, tamano=len(datos),
                        exif_lat=f.get('exif_lat'), exif_lon=f.get('exif_lon'), exif_fecha=_fechahora(f.get('exif_datetime')),
                        legacy_source=FUENTE, legacy_id=f['id'])
            nombre = os.path.basename(ruta)
            foto.imagen.save(nombre, ContentFile(datos), save=False)
            try:
                with Image.open(io.BytesIO(datos)) as img:
                    foto.miniatura.save(os.path.splitext(nombre)[0] + '.jpg', ContentFile(_miniatura(img)), save=False)
            except Exception:
                self.aviso(f'Foto #{f["id"]}: no se pudo generar la miniatura.')
            Foto.objects.bulk_create([foto])
            ts = _fechahora(f.get('created_at'))
            if ts:
                Foto.objects.filter(pk=foto.pk).update(creada=ts)
            self.n['fotos'] += 1

    def mapas_(self):
        if not self.con_archivos:
            return
        from reg_actividades.models import ImagenMapa
        hechas = set(ImagenMapa.objects.filter(empresa=self.empresa, legacy_source=FUENTE).values_list('legacy_id', flat=True))
        for f in self.tabla('core_googlemapsimage'):
            if f['id'] in hechas or f.get('is_deleted'):
                continue
            clave, r = self._registro_de(f['content_type_id'], f['object_id'])
            if r is None:
                self.omitidos['mapas sin registro'] += 1
                continue
            datos, ruta = self._leer_archivo(f.get('imagen'))
            if datos is None:
                self.omitidos['mapas sin archivo'] += 1
                continue
            puntos = _json(f.get('coordenadas_json'), [])
            m = ImagenMapa(empresa=self.empresa, content_type=ContentType.objects.get_for_model(type(r)), object_id=r.pk,
                           etapa=self._etapa(clave, r, f['etapa']), zoom=f.get('zoom') or 17, maptype=f.get('maptype') or 'hybrid',
                           scale=f.get('scale') or 2, tamano=f.get('tamano') or '640x640',
                           coordenadas=puntos if isinstance(puntos, list) else [],
                           distancia_total_metros=f.get('distancia_total_metros'), desfase_metros=f.get('desfase_metros'),
                           legacy_source=FUENTE, legacy_id=f['id'])
            m.imagen.save(os.path.basename(ruta), ContentFile(datos), save=False)
            try:
                with transaction.atomic():
                    ImagenMapa.objects.bulk_create([m])
            except IntegrityError:
                m.imagen.delete(save=False)
                self.omitidos['mapas duplicados'] += 1
                continue
            self.n['mapas'] += 1

    # ── 9. recálculo ──────────────────────────────────────────────────────────
    def recalcular_(self):
        from reg_construccion.models import PASO_AVANCE, RegConstruccion
        from reg_construccion.signals import recalcular_completo
        from reg_actividades.widgets.tabla_avance import recalcular_avance
        for pid in set(RegConstruccion.objects.filter(empresa=self.empresa, is_deleted=False)
                       .values_list('proyecto_id', flat=True)):
            recalcular_avance(RegConstruccion, pid, self.empresa.pk, PASO_AVANCE)
        for pk in RegConstruccion.objects.filter(empresa=self.empresa, is_deleted=False).values_list('pk', flat=True):
            recalcular_completo(pk)

    # ── orquestación ──────────────────────────────────────────────────────────
    def ejecutar(self, limpiar=False):
        pasos = [('limpiar', self.limpiar) if limpiar else None,
                 ('contratistas', self.contratistas_), ('usuarios', self.usuarios_), ('proyectos', self.proyectos_),
                 ('configuración', self.configuracion_), ('registros', self.registros_), ('datos de pasos', self.datos_pasos_),
                 ('fotos', self.fotos_), ('mapas', self.mapas_), ('recálculo', self.recalcular_)]
        for paso in filter(None, pasos):
            self.info(f'→ {paso[0]}…')
            paso[1]()
        # Lo importado es de los tipos TX/TSS y Construcción: sin activarlos en la empresa quedaría oculto.
        from . import tipos
        for clave in ('txtss', 'construccion'):
            tipos.habilitar(self.empresa, clave)
        return self.n, self.omitidos, self.avisos

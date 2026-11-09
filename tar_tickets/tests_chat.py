import io
import shutil
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from notificaciones.models import Notificacion
from tar_adjuntos.models import Adjunto

from .models import Asignacion, Comentario, Ticket

E = Ticket.Estado
STORAGES_TEST = {
    'default': {'BACKEND': 'archivos.storage.HybridMediaStorage'},
    'privado': {'BACKEND': 'archivos.storage.HybridPrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def usuario(email, empresa, rol_base):
    u = User.objects.create_user(email, 'x', first_name=email.split('@')[0].title())
    agregar_miembro(u, empresa, rol_por_base(empresa, rol_base))
    return u


def png(color=(200, 30, 30), tam=(40, 40)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', tam, color).save(buf, 'PNG')
    return buf.getvalue()


def pdf():
    import pymupdf
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), 'Hola')
    datos = doc.tobytes()
    doc.close()
    return datos


def subida(nombre, datos, tipo):
    return SimpleUploadedFile(nombre, datos, content_type=tipo)


class BaseChat(TestCase):
    """Empresa embol con director, 2 ejecutores, 1 lector y otra empresa; MEDIA_ROOT temporal."""

    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Embol', slug='embol', modulos=['tar'])
        cls.b = crear_empresa(nombre='Otra', slug='otra', modulos=['tar'])
        cls.director = usuario('dir@example.com', cls.a, RolBase.COORDINADOR)
        cls.ejec1 = usuario('ejec1@example.com', cls.a, RolBase.MIEMBRO)
        cls.ejec2 = usuario('ejec2@example.com', cls.a, RolBase.MIEMBRO)
        cls.lector = usuario('lector@example.com', cls.a, RolBase.OBSERVADOR)
        cls.director_b = usuario('dirb@example.com', cls.b, RolBase.COORDINADOR)

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.addCleanup(cache.clear)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        ctx = override_settings(
            MEDIA_ROOT=str(self.tmp), STORAGES=STORAGES_TEST, SECURE_SSL_REDIRECT=False,
            CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
        )
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.t = self.ticket()
        self.asignar(self.t, self.ejec1)

    def ticket(self, titulo='Tarea', empresa=None, creador=None, **kw):
        return Ticket.objects.create(empresa=empresa or self.a, titulo=titulo, solicitante='C',
                                     creador=creador or self.director, **kw)

    def asignar(self, t, user, tipo='EJECUTOR', estado=E.POR_HACER):
        a = Asignacion.objects.create(ticket=t, user=user, tipo=tipo, estado=estado)
        t.recalcular_estado()
        return a

    def url(self, ruta, t=None):
        return f'/embol/tareas/{(t or self.t).pk}{ruta}'

    def comentar(self, user, texto='Hola', archivos=(), ajax=False, t=None):
        self.client.force_login(user)
        datos = {'texto': texto}
        if archivos:
            datos['files'] = list(archivos)
        extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if ajax else {}
        return self.client.post(self.url('/comentar/', t), datos, **extra)

    def archivos_en_disco(self):
        return sorted(p for p in (self.tmp / 'privado').rglob('*') if p.is_file()) if (self.tmp / 'privado').exists() else []


class ChatTests(BaseChat):
    def test_participante_comenta_y_se_avisa_a_los_demas(self):
        r = self.comentar(self.ejec1, 'Avance 50%')
        self.assertRedirects(r, self.url('/') + '#chat-compose', fetch_redirect_response=False)
        c = Comentario.objects.get()
        self.assertEqual((c.autor, c.texto, c.ticket), (self.ejec1, 'Avance 50%', self.t))
        self.assertTrue(Notificacion.objects.filter(destinatario=self.director, mensaje__contains='comentó').exists())
        self.assertFalse(Notificacion.objects.filter(destinatario=self.ejec1).exists())  # no a sí mismo

    def test_ajax_devuelve_html_e_id(self):
        r = self.comentar(self.ejec1, 'por ajax', ajax=True)
        d = r.json()
        self.assertTrue(d['ok'])
        self.assertIn('por ajax', d['html'])
        self.assertEqual(d['comment_id'], Comentario.objects.get().pk)

    def test_mensaje_vacio_rechazado(self):
        self.assertEqual(self.comentar(self.ejec1, '   ', ajax=True).status_code, 400)
        self.assertEqual(Comentario.objects.count(), 0)

    def test_solo_adjunto_sin_texto_es_valido(self):
        r = self.comentar(self.ejec1, '', archivos=[subida('foto.png', png(), 'image/png')], ajax=True)
        self.assertTrue(r.json()['ok'])
        self.assertEqual(Adjunto.objects.get().comentario.texto, '')

    def test_quien_no_participa_ni_escribe_no_puede(self):
        self.assertEqual(self.comentar(self.ejec2, 'intruso').status_code, 403)   # no participa
        self.assertEqual(self.comentar(self.lector, 'solo lee').status_code, 403)  # ve todo pero sin chat.write
        self.assertEqual(Comentario.objects.count(), 0)

    def test_otra_empresa_no_existe(self):
        self.client.force_login(self.director_b)
        self.assertEqual(self.client.post(f'/otra/tareas/{self.t.pk}/comentar/', {'texto': 'x'}).status_code, 404)

    def test_autoriza_el_texto_con_urls_sin_inyectar_html(self):
        self.comentar(self.ejec1, 'mira https://x.cl/a?b=1 <script>alert(1)</script>')
        self.client.force_login(self.director)
        html = self.client.get(self.url('/')).content.decode()
        self.assertIn('href="https://x.cl/a?b=1"', html)
        self.assertIn('rel="noopener noreferrer"', html)
        self.assertNotIn('<script>alert(1)</script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_editar_solo_el_ultimo_mensaje_y_solo_el_autor(self):
        self.comentar(self.ejec1, 'primero')
        self.comentar(self.ejec1, 'segundo')
        primero, segundo = Comentario.objects.order_by('pk')
        self.client.force_login(self.ejec1)
        self.assertEqual(self.client.post(f'/embol/tareas/comentario/{primero.pk}/editar/', {'texto': 'x'}).status_code, 403)
        self.client.post(f'/embol/tareas/comentario/{segundo.pk}/editar/', {'texto': 'segundo (editado)'})
        segundo.refresh_from_db()
        self.assertEqual(segundo.texto, 'segundo (editado)')
        self.asignar(self.t, self.ejec2)
        self.client.force_login(self.ejec2)  # otro participante no edita el mensaje ajeno
        self.assertEqual(self.client.post(f'/embol/tareas/comentario/{segundo.pk}/editar/', {'texto': 'hack'}).status_code, 403)

    def test_el_director_modera_el_ultimo_mensaje_ajeno(self):
        self.comentar(self.ejec1, 'malo')
        c = Comentario.objects.get()
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/comentario/{c.pk}/borrar/')
        self.assertFalse(Comentario.objects.exists())

    def test_historial_pagina_hacia_atras(self):
        for i in range(25):
            Comentario.objects.create(ticket=self.t, autor=self.ejec1, texto=f'msg {i:02d}')
        self.client.force_login(self.director)
        html = self.client.get(self.url('/')).content.decode()
        self.assertIn('msg 24', html)
        self.assertNotIn('msg 00', html)
        self.assertIn('Cargar mensajes anteriores', html)
        primero_visible = Comentario.objects.order_by('-pk')[19].pk
        d = self.client.get(self.url('/comentarios/'), {'before': primero_visible}).json()
        self.assertIn('msg 00', d['html'])
        self.assertFalse(d['has_older'])

    def test_comentarios_nuevos_desde(self):
        c1 = Comentario.objects.create(ticket=self.t, autor=self.ejec1, texto='uno')
        Comentario.objects.create(ticket=self.t, autor=self.ejec1, texto='dos')
        self.client.force_login(self.director)
        d = self.client.get(self.url('/comentarios/nuevos/'), {'after': c1.pk}).json()
        self.assertIn('dos', d['html'])
        self.assertNotIn('uno', d['html'])

    def test_parametros_invalidos_y_permisos_de_los_fragmentos(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(self.url('/comentarios/'), {'before': 'x'}).status_code, 400)
        self.assertEqual(self.client.get(self.url('/comentarios/nuevos/')).status_code, 400)
        self.client.force_login(self.ejec2)  # no participa
        self.assertEqual(self.client.get(self.url('/comentarios/'), {'before': 9999}).status_code, 403)

    def test_el_hilo_del_hijo_incluye_mensajes_del_padre_como_heredados(self):
        hijo = self.t.crear_hijo(titulo='Hijo', solicitante='C', creador=self.director)
        Comentario.objects.create(ticket=self.t, autor=self.director, texto='mensaje del padre')
        self.client.force_login(self.director)
        html = self.client.get(f'/embol/tareas/{hijo.pk}/').content.decode()
        self.assertIn('mensaje del padre', html)
        self.assertIn(self.t.clave, html)


class AdjuntosTests(BaseChat):
    def subir(self, user=None, nombre='foto.png', datos=None, tipo='image/png', texto='con archivo'):
        return self.comentar(user or self.ejec1, texto, archivos=[subida(nombre, datos or png(), tipo)], ajax=True)

    def test_guarda_en_el_almacenamiento_privado_con_ruta_por_empresa(self):
        self.subir()
        a = Adjunto.objects.get()
        self.assertEqual((a.empresa, a.ticket, a.mime_type, a.version_numero), (self.a, self.t, 'image/png', 1))
        self.assertEqual(len(a.sha256), 64)
        self.assertTrue(a.archivo.name.startswith(f'{self.a.pk}/tar/{self.t.pk}/'))
        self.assertEqual(len(self.archivos_en_disco()), 1)
        self.assertEqual(self.archivos_en_disco()[0].read_bytes(), png())

    def test_duplicado_en_el_mismo_mensaje_no_se_guarda_dos_veces(self):
        self.client.force_login(self.ejec1)
        archivo = lambda: subida('a.png', png(), 'image/png')
        r = self.client.post(self.url('/comentar/'), {'texto': 'x', 'files': [archivo(), archivo()]},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(Adjunto.objects.count(), 1)
        self.assertTrue(any('ya estaba adjunto' in w['message'] for w in r.json()['warnings']))

    def test_rechaza_tipos_peligrosos_o_falsos(self):
        casos = [
            ('x.svg', b'<svg onload=alert(1)/>', 'image/svg+xml'),
            ('x.exe', b'MZ\x90', 'application/x-msdownload'),
            ('x.png', b'esto no es una imagen', 'image/png'),   # content-type mentiroso
            ('x.html', b'<script>1</script>', 'text/html'),
        ]
        for nombre, datos, tipo in casos:
            r = self.subir(nombre=nombre, datos=datos, tipo=tipo)
            self.assertEqual(Adjunto.objects.count(), 0, nombre)
            self.assertTrue(r.json()['warnings'], nombre)
        self.assertEqual(self.archivos_en_disco(), [])

    def test_rechaza_archivos_sobre_el_maximo(self):
        with override_settings(ATTACHMENT_MAX_SIZE=100):
            r = self.subir(datos=png(tam=(300, 300)))
        self.assertEqual(Adjunto.objects.count(), 0)
        self.assertIn('máximo', r.json()['warnings'][0]['message'])

    def test_acepta_documentos_de_oficina(self):
        self.subir(nombre='plan.xlsx', datos=b'PK\x03\x04datos',
                   tipo='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertEqual(Adjunto.objects.get().extension, 'xlsx')

    def test_nombre_de_archivo_se_sanea(self):
        self.subir(nombre='../../etc/pas swd<>.png')
        a = Adjunto.objects.get()
        self.assertNotIn('/', a.nombre)
        self.assertNotIn('..', a.nombre)
        self.assertTrue(Path(a.archivo.path).resolve().is_relative_to((self.tmp / 'privado').resolve()))

    def test_servir_exige_poder_ver_el_ticket(self):
        self.subir()
        a = Adjunto.objects.get()
        self.client.force_login(self.ejec1)
        r = self.client.get(f'/embol/tareas/adjunto/{a.pk}/')
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/png'))
        self.assertEqual(b''.join(r.streaming_content), png())
        self.assertEqual(r['Content-Security-Policy'], 'sandbox')
        self.assertIn('private', r['Cache-Control'])
        self.assertIn('inline', r['Content-Disposition'])
        self.client.force_login(self.ejec2)   # miembro de la empresa pero NO participa
        self.assertEqual(self.client.get(f'/embol/tareas/adjunto/{a.pk}/').status_code, 403)
        self.client.force_login(self.director_b)   # otra empresa: ni siquiera existe
        self.assertEqual(self.client.get(f'/otra/tareas/adjunto/{a.pk}/').status_code, 404)

    def test_los_no_raster_se_descargan_en_vez_de_mostrarse(self):
        self.subir(nombre='datos.csv', datos=b'a,b\n1,2', tipo='text/csv')
        a = Adjunto.objects.get()
        self.client.force_login(self.director)
        r = self.client.get(f'/embol/tareas/adjunto/{a.pk}/')
        self.assertIn('attachment', r['Content-Disposition'])

    def test_etag_permite_304(self):
        self.subir()
        a = Adjunto.objects.get()
        self.client.force_login(self.director)
        etag = self.client.get(f'/embol/tareas/adjunto/{a.pk}/')['ETag']
        self.assertEqual(self.client.get(f'/embol/tareas/adjunto/{a.pk}/', HTTP_IF_NONE_MATCH=etag).status_code, 304)

    def test_la_ruta_generica_de_archivos_privados_no_sirve_los_de_tareas(self):
        """Defensa en profundidad: aunque se adivine la ruta, el módulo exige acceso al TICKET."""
        self.subir()
        a = Adjunto.objects.get()
        self.client.force_login(self.ejec2)   # miembro de la empresa, no participa del ticket
        self.assertEqual(self.client.get(f'/archivos/privado/{a.archivo.name}').status_code, 404)
        self.client.force_login(self.ejec1)   # ni siquiera quien sí participa: por esa ruta no se sirve
        self.assertEqual(self.client.get(f'/archivos/privado/{a.archivo.name}').status_code, 404)

    def test_miniatura_de_imagen_se_genera_y_persiste(self):
        self.subir(datos=png(tam=(800, 400)))
        a = Adjunto.objects.get()
        self.client.force_login(self.director)
        r = self.client.get(f'/embol/tareas/adjunto/{a.pk}/miniatura/')
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/png'))
        from PIL import Image
        self.assertLessEqual(max(Image.open(io.BytesIO(r.content)).size), 256)
        self.assertTrue(any('miniaturas' in str(p) for p in self.archivos_en_disco()))
        self.assertEqual(self.client.get(f'/embol/tareas/adjunto/{a.pk}/miniatura/').status_code, 200)  # desde el disco

    def test_miniatura_de_pdf(self):
        self.subir(nombre='doc.pdf', datos=pdf(), tipo='application/pdf')
        a = Adjunto.objects.get()
        self.client.force_login(self.director)
        r = self.client.get(f'/embol/tareas/adjunto/{a.pk}/miniatura/')
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/png'))

    def test_sin_miniatura_para_otros_tipos_ni_sin_permiso(self):
        self.subir(nombre='datos.csv', datos=b'a,b', tipo='text/csv')
        a = Adjunto.objects.get()
        self.client.force_login(self.director)
        self.assertEqual(self.client.get(f'/embol/tareas/adjunto/{a.pk}/miniatura/').status_code, 404)
        self.client.force_login(self.ejec2)
        self.assertEqual(self.client.get(f'/embol/tareas/adjunto/{a.pk}/miniatura/').status_code, 403)

    def test_borrar_adjunto_elimina_el_archivo_y_solo_del_ultimo_mensaje(self):
        self.subir(texto='viejo')
        viejo = Adjunto.objects.get()
        self.subir(datos=png((0, 255, 0)), texto='nuevo')
        nuevo = Adjunto.objects.exclude(pk=viejo.pk).get()
        self.client.force_login(self.ejec1)
        self.assertEqual(self.client.post(f'/embol/tareas/adjunto/{viejo.pk}/borrar/').status_code, 403)
        self.client.post(f'/embol/tareas/adjunto/{nuevo.pk}/borrar/')
        self.assertFalse(Adjunto.objects.filter(pk=nuevo.pk).exists())
        self.assertEqual(len(self.archivos_en_disco()), 1)

    def test_borrar_el_mensaje_o_el_ticket_elimina_los_archivos(self):
        self.subir()
        self.assertEqual(len(self.archivos_en_disco()), 1)
        self.client.force_login(self.director)
        self.client.post(f'/embol/tareas/comentario/{Comentario.objects.get().pk}/borrar/')
        self.assertEqual((Adjunto.objects.count(), self.archivos_en_disco()), (0, []))
        self.subir()
        root = User.objects.create_superuser('root@example.com', 'x')
        self.client.force_login(root)
        self.client.post(self.url('/eliminar/'))
        self.assertEqual((Ticket.objects.filter(pk=self.t.pk).count(), Adjunto.objects.count()), (0, 0))
        self.assertEqual(self.archivos_en_disco(), [])

    def test_solo_superusuario_elimina_tickets(self):
        self.client.force_login(self.director)
        self.assertEqual(self.client.post(self.url('/eliminar/')).status_code, 403)
        self.assertTrue(Ticket.objects.filter(pk=self.t.pk).exists())

    def test_anotar_imagen_crea_un_mensaje_nuevo_con_version_2(self):
        self.subir()
        original = Adjunto.objects.get()
        self.client.force_login(self.director)  # otro usuario anota
        self.client.post(f'/embol/tareas/adjunto/{original.pk}/anotar/',
                         {'image': subida('anot.png', png((0, 0, 255)), 'image/png')})
        # el director no participa pero tiene chat.write + view_all → puede
        nueva = Adjunto.objects.exclude(pk=original.pk).get()
        self.assertEqual((nueva.version_de, nueva.version_numero, nueva.subido_por), (original, 2, self.director))
        self.assertNotEqual(nueva.comentario_id, original.comentario_id)
        self.assertEqual(nueva.comentario.autor, self.director)
        self.assertTrue(nueva.nombre.endswith('-v2.png'))

    def test_anotar_valida_tipo_permiso_y_duplicado(self):
        self.subir(nombre='d.csv', datos=b'a', tipo='text/csv')
        csv = Adjunto.objects.get()
        self.client.force_login(self.director)
        self.assertEqual(self.client.post(f'/embol/tareas/adjunto/{csv.pk}/anotar/',
                                          {'image': subida('a.png', png(), 'image/png')}).status_code, 400)
        self.subir(datos=png((9, 9, 9)))
        img = Adjunto.objects.exclude(pk=csv.pk).get()
        self.client.force_login(self.lector)   # sin chat.write
        self.assertEqual(self.client.post(f'/embol/tareas/adjunto/{img.pk}/anotar/',
                                          {'image': subida('a.png', png(), 'image/png')}).status_code, 403)
        self.client.force_login(self.director)
        self.assertEqual(self.client.post(f'/embol/tareas/adjunto/{img.pk}/anotar/').status_code, 400)  # falta imagen

    def test_galeria_y_pagina_de_mas_adjuntos(self):
        c = Comentario.objects.create(ticket=self.t, autor=self.ejec1, texto='galería')
        for i in range(20):
            Adjunto.objects.create(empresa=self.a, ticket=self.t, comentario=c, nombre=f'f{i}.png', mime_type='image/png',
                                   sha256=f'{i:064d}', archivo=f'{self.a.pk}/tar/{self.t.pk}/f{i}.png')
        self.client.force_login(self.director)
        html = self.client.get(self.url('/')).content.decode()
        self.assertIn('Cargar más imágenes/PDF', html)
        antes = Adjunto.objects.order_by('-pk')[17].pk   # el más antiguo de la primera página de 18
        d = self.client.get(self.url('/adjuntos/'), {'kind': 'thumbs', 'before': antes}).json()
        self.assertTrue(d['ok'])
        self.assertEqual(d['html'].count('adjunto_miniatura') + d['html'].count('/miniatura/'), 2)
        self.assertEqual(self.client.get(self.url('/adjuntos/'), {'kind': 'x', 'before': 1}).status_code, 400)

import io
import json
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from notificaciones.models import Notificacion
from proyectos.models import Proyecto

from . import servicios
from .models import AdjuntoMensaje, Conversacion, Mensaje, Participacion

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False, INTERNAL_API_TOKEN='secreto',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    CHANNEL_LAYERS={'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}},
    STORAGES={
        'default': {'BACKEND': 'archivos.storage.HybridMediaStorage'},
        'privado': {'BACKEND': 'archivos.storage.HybridPrivateStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


def png(nombre='foto.png'):
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(buf, 'PNG')
    return SimpleUploadedFile(nombre, buf.getvalue(), content_type='image/png')


@override_settings(**AJUSTES)
class ChatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Solo el módulo Mensajería habilitado (el chat no depende de reg/tar/jor).
        cls.e = crear_empresa(nombre='Tekon', slug='tekon', modulos=['msj'])
        cls.otra = crear_empresa(nombre='Otra', slug='otra', modulos=['msj'])
        mk = lambda mail, rol, emp=cls.e: (lambda u: (u, agregar_miembro(u, emp, rol_por_base(emp, rol))))(
            User.objects.create_user(mail, 'x'))
        cls.jefe, cls.m_jefe = mk('jefe@x.cl', RolBase.COORDINADOR)
        cls.ana, cls.m_ana = mk('ana@x.cl', RolBase.MIEMBRO)
        cls.beto, cls.m_beto = mk('beto@x.cl', RolBase.MIEMBRO)
        cls.ext, _ = mk('ext@x.cl', RolBase.COORDINADOR, cls.otra)
        cls.p = Proyecto.objects.create(empresa=cls.e, nombre='Torre Norte', codigo='TN')
        cls.p.equipo.add(cls.m_ana)

    def setUp(self):
        # Los adjuntos van a un MEDIA_ROOT temporal, nunca a la carpeta media/ real.
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=tmp)
        ctx.enable()
        self.addCleanup(ctx.disable)

    # ── Visibilidad ──
    def test_general_lo_ve_toda_la_empresa_y_nadie_de_fuera(self):
        g = servicios.general(self.e)
        self.assertTrue(all(servicios.puede_ver(u, g) for u in (self.jefe, self.ana, self.beto)))
        self.assertFalse(servicios.puede_ver(self.ext, g))

    def test_proyecto_solo_equipo_y_coordinadores(self):
        c = servicios.de_proyecto(self.p)
        self.assertTrue(servicios.puede_ver(self.ana, c))     # del equipo
        self.assertTrue(servicios.puede_ver(self.jefe, c))    # coordinador
        self.assertFalse(servicios.puede_ver(self.beto, c))   # ni equipo ni coordinador
        self.client.force_login(self.beto)
        self.assertEqual(self.client.get(f'/tekon/mensajes/c/{c.pk}/').status_code, 404)

    def test_directo_unico_por_par_y_privado(self):
        a = servicios.directo(self.e, self.ana, self.beto)
        b = servicios.directo(self.e, self.beto, self.ana)
        self.assertEqual(a.pk, b.pk)
        self.assertTrue(servicios.puede_ver(self.ana, a))
        self.assertFalse(servicios.puede_ver(self.jefe, a))   # ni el coordinador lee directos ajenos
        with self.assertRaises(servicios.ErrorMensaje):
            servicios.directo(self.e, self.ana, self.ana)

    def test_conversacion_de_otra_empresa_es_404(self):
        g = servicios.general(self.e)
        self.client.force_login(self.ext)
        self.assertEqual(self.client.get(f'/otra/mensajes/c/{g.pk}/').status_code, 404)

    def test_panel_lista_solo_lo_visible(self):
        servicios.de_proyecto(self.p)
        servicios.directo(self.e, self.ana, self.beto)
        self.client.force_login(self.beto)
        html = self.client.get('/tekon/mensajes/panel/').content.decode()
        self.assertIn('General', html)
        self.assertNotIn('Torre Norte', html)
        self.client.force_login(self.ana)
        self.assertIn('Torre Norte', self.client.get('/tekon/mensajes/panel/').content.decode())

    # ── Enviar, menciones y notificaciones ──
    def test_enviar_por_http_y_html_escapado(self):
        g = servicios.general(self.e)
        self.client.force_login(self.ana)
        r = self.client.post(f'/tekon/mensajes/c/{g.pk}/enviar/', {'texto': '<b>hola</b> https://x.cl/a'})
        self.assertEqual(r.status_code, 200)
        html = r.json()['html']
        self.assertIn('&lt;b&gt;hola&lt;/b&gt;', html)
        self.assertIn('href="https://x.cl/a"', html)
        self.assertEqual(Mensaje.objects.get().autor, self.ana)

    def test_mensaje_vacio_o_enorme_se_rechaza(self):
        g = servicios.general(self.e)
        self.client.force_login(self.ana)
        for texto in ('  ', 'a' * (servicios.MAX_TEXTO + 1)):
            r = self.client.post(f'/tekon/mensajes/c/{g.pk}/enviar/', {'texto': texto})
            self.assertEqual(r.status_code, 400)
        self.assertEqual(Mensaje.objects.count(), 0)

    def test_mencion_notifica_solo_al_mencionado_que_puede_ver(self):
        c = servicios.de_proyecto(self.p)
        # @beto no está en el equipo (no ve el canal) → no se le menciona; @jefe sí (coordinador).
        m = servicios.enviar(c, self.ana, 'Hola @jefe y @beto, revisen')
        self.assertEqual(list(m.menciones.all()), [self.jefe])
        self.assertEqual(Notificacion.objects.filter(destinatario=self.jefe).count(), 1)
        self.assertEqual(Notificacion.objects.filter(destinatario=self.beto).count(), 0)
        self.assertEqual(Notificacion.objects.filter(destinatario=self.ana).count(), 0)   # no se auto-notifica

    def test_mencion_resaltada_solo_si_es_real(self):
        g = servicios.general(self.e)
        m = servicios.enviar(g, self.ana, 'Hola @beto y @fantasma')
        from .templatetags.mensajes_extras import mensaje_html
        html = mensaje_html(Mensaje.objects.prefetch_related('menciones').get(pk=m.pk))
        self.assertIn('<span class="mencion">@beto</span>', html)
        self.assertNotIn('mencion">@fantasma', html)

    def test_directo_avisa_una_vez_hasta_que_lo_lea(self):
        c = servicios.directo(self.e, self.ana, self.beto)
        servicios.enviar(c, self.ana, 'uno')
        servicios.enviar(c, self.ana, 'dos')
        self.assertEqual(Notificacion.objects.filter(destinatario=self.beto).count(), 1)
        servicios.marcar_leido(c, self.beto)
        servicios.enviar(c, self.ana, 'tres')
        self.assertEqual(Notificacion.objects.filter(destinatario=self.beto).count(), 2)

    # ── No leídos ──
    def test_no_leidos_y_marcar_leido(self):
        g = servicios.general(self.e)
        servicios.enviar(g, self.ana, 'a')
        servicios.enviar(g, self.ana, 'b')
        self.assertEqual(servicios.no_leidos(self.beto, self.e)[0], 2)
        self.assertEqual(servicios.no_leidos(self.ana, self.e)[0], 0)   # lo propio nunca cuenta
        self.client.force_login(self.beto)
        r = self.client.post(f'/tekon/mensajes/c/{g.pk}/leido/')
        self.assertEqual(r.json()['total'], 0)

    def test_historia_previa_no_cuenta_como_no_leida(self):
        g = servicios.general(self.e)
        Mensaje.objects.create(conversacion=g, autor=self.ana, texto='viejo')   # sin participaciones aún
        self.assertEqual(servicios.no_leidos(self.beto, self.e)[0], 0)
        servicios.enviar(g, self.ana, 'nuevo')
        self.assertEqual(servicios.no_leidos(self.beto, self.e)[0], 1)

    def test_no_leidos_no_incluye_canales_que_no_ve(self):
        c = servicios.de_proyecto(self.p)
        servicios.enviar(c, self.ana, 'secreto')
        self.assertEqual(servicios.no_leidos(self.beto, self.e)[0], 0)
        self.assertEqual(servicios.no_leidos(self.jefe, self.e)[0], 1)

    def test_contador_en_la_barra_superior(self):
        servicios.enviar(servicios.general(self.e), self.ana, 'hola')
        self.client.force_login(self.beto)
        r = self.client.get('/tekon/')
        self.assertEqual(r.context['mensajes_no_leidos'], 1)

    # ── Editar y borrar ──
    def test_solo_el_autor_edita_y_borra(self):
        g = servicios.general(self.e)
        m = servicios.enviar(g, self.ana, 'original')
        self.client.force_login(self.beto)
        self.assertEqual(self.client.post(f'/tekon/mensajes/m/{m.pk}/editar/', {'texto': 'x'}).status_code, 403)
        self.assertEqual(self.client.post(f'/tekon/mensajes/m/{m.pk}/borrar/').status_code, 403)
        self.client.force_login(self.ana)
        self.assertEqual(self.client.post(f'/tekon/mensajes/m/{m.pk}/editar/', {'texto': 'nuevo'}).status_code, 200)
        m.refresh_from_db()
        self.assertEqual((m.texto, bool(m.editado)), ('nuevo', True))
        self.assertEqual(self.client.post(f'/tekon/mensajes/m/{m.pk}/borrar/').status_code, 200)
        self.assertFalse(Mensaje.objects.filter(pk=m.pk).exists())

    # ── Adjuntos ──
    def test_adjunto_imagen_se_guarda_y_sirve_con_permisos(self):
        c = servicios.de_proyecto(self.p)
        self.client.force_login(self.ana)
        r = self.client.post(f'/tekon/mensajes/c/{c.pk}/enviar/', {'texto': '', 'files': png()})
        self.assertEqual(r.status_code, 200, r.content)
        adj = AdjuntoMensaje.objects.get()
        self.assertTrue(adj.archivo.name.startswith(f'{self.e.pk}/msj/{c.pk}/'))
        self.assertEqual(self.client.get(f'/tekon/mensajes/adjunto/{adj.pk}/').status_code, 200)
        self.assertEqual(self.client.get(f'/tekon/mensajes/adjunto/{adj.pk}/miniatura/')['Content-Type'], 'image/png')
        self.client.force_login(self.beto)   # no ve el canal del proyecto
        self.assertEqual(self.client.get(f'/tekon/mensajes/adjunto/{adj.pk}/').status_code, 404)

    def test_ruta_generica_de_archivos_no_sirve_adjuntos_del_chat(self):
        c = servicios.general(self.e)
        servicios.enviar(c, self.ana, '', [png()])
        adj = AdjuntoMensaje.objects.get()
        self.client.force_login(self.beto)
        self.assertEqual(self.client.get(f'/archivos/privado/{adj.archivo.name}').status_code, 404)

    def test_adjuntos_invalidos(self):
        g = servicios.general(self.e)
        svg = SimpleUploadedFile('x.svg', b'<svg/>', content_type='image/svg+xml')
        falsa = SimpleUploadedFile('x.png', b'no soy imagen', content_type='image/png')
        for f in (svg, falsa):
            with self.assertRaises(servicios.ErrorMensaje):
                servicios.enviar(g, self.ana, 'hola', [f])
        with self.assertRaises(servicios.ErrorMensaje):
            servicios.enviar(g, self.ana, 'hola', [png() for _ in range(servicios.MAX_ADJUNTOS + 1)])
        self.assertEqual(Mensaje.objects.count(), 0)

    def test_borrar_mensaje_borra_el_archivo(self):
        g = servicios.general(self.e)
        m = servicios.enviar(g, self.ana, '', [png()])
        nombre = AdjuntoMensaje.objects.get().archivo.name
        almacen = AdjuntoMensaje.objects.get().archivo.storage
        self.assertTrue(almacen.exists(nombre))
        servicios.borrar(m)
        self.assertFalse(almacen.exists(nombre))

    # ── Personas y paginación ──
    def test_personas_para_mencionar_son_las_de_la_conversacion(self):
        c = servicios.de_proyecto(self.p)
        self.client.force_login(self.ana)
        nombres = [p['handle'] for p in self.client.get(f'/tekon/mensajes/personas/?c={c.pk}').json()['personas']]
        self.assertEqual(nombres, ['jefe'])   # beto no ve el canal; ana es quien escribe
        todos = [p['handle'] for p in self.client.get('/tekon/mensajes/personas/').json()['personas']]
        self.assertCountEqual(todos, ['jefe', 'beto'])

    def test_paginacion_hacia_atras(self):
        g = servicios.general(self.e)
        for i in range(servicios.POR_PAGINA + 5):
            Mensaje.objects.create(conversacion=g, autor=self.ana, texto=f'm{i}')
        self.client.force_login(self.beto)
        r = self.client.get(f'/tekon/mensajes/c/{g.pk}/')
        self.assertContains(r, f'm{servicios.POR_PAGINA + 4}')
        self.assertNotContains(r, '>m0<')
        primero = r.context['primero_id']
        r2 = self.client.get(f'/tekon/mensajes/c/{g.pk}/antiguos/?antes={primero}')
        self.assertEqual(r2['X-Hay-Mas'], '0')
        self.assertContains(r2, 'm0')

    def test_nuevos_desde_un_id(self):
        g = servicios.general(self.e)
        a = servicios.enviar(g, self.ana, 'uno')
        servicios.enviar(g, self.ana, 'dos')
        self.client.force_login(self.beto)
        r = self.client.get(f'/tekon/mensajes/c/{g.pk}/nuevos/?despues={a.pk}')
        self.assertContains(r, 'dos')
        self.assertNotContains(r, 'uno')

    # ── Compatibilidad ──
    def test_api_cerrar_dia_sigue_respondiendo(self):
        for ruta in ('/api/mensajes/interno/cerrar-dia/', '/api/jor/interno/mensajes/cerrar-dia/'):
            r = self.client.post(ruta, json.dumps({}), content_type='application/json', HTTP_X_INTERNAL_TOKEN='secreto')
            self.assertEqual(r.status_code, 200, ruta)

    def test_aviso_sistema_va_a_la_campana(self):
        servicios.aviso_sistema(self.e, self.ana, 'Se cerró tu jornada', url='/jornadas/')
        self.assertEqual(Notificacion.objects.get(destinatario=self.ana).mensaje, 'Se cerró tu jornada')

    def test_no_hay_pagina_propia_la_ventana_flotante_esta_en_todas_las_pantallas(self):
        self.client.force_login(self.ana)
        r = self.client.get('/tekon/')
        self.assertContains(r, 'id="msj"')
        self.assertContains(r, 'js/mensajeria.js')
        self.assertContains(r, 'data-accion="mensajeria"')
        # El enlace de una notificación no muestra una página: lleva al inicio con la ventana abierta.
        self.assertRedirects(self.client.get('/tekon/mensajes/?c=5'), '/tekon/?c=5', fetch_redirect_response=False)
        self.assertRedirects(self.client.get('/tekon/mensajes/?c=abc'), '/tekon/?msj=1', fetch_redirect_response=False)
        self.assertRedirects(self.client.get('/tekon/mensajes/'), '/tekon/?msj=1', fetch_redirect_response=False)

    def test_observador_puede_leer_y_escribir(self):
        obs = User.objects.create_user('obs@x.cl', 'x')
        agregar_miembro(obs, self.e, rol_por_base(self.e, RolBase.OBSERVADOR))
        g = servicios.general(self.e)
        self.client.force_login(obs)
        self.assertEqual(self.client.get(f'/tekon/mensajes/c/{g.pk}/').status_code, 200)
        self.assertEqual(self.client.post(f'/tekon/mensajes/c/{g.pk}/enviar/', {'texto': 'hola'}).status_code, 200)

    def test_el_menu_y_el_lanzador_incluyen_el_modulo(self):
        self.client.force_login(self.ana)
        r = self.client.get('/tekon/')
        tarjeta = next(t for t in r.context['lanzador_modulos'] if t['codigo'] == 'msj')
        self.assertEqual((tarjeta['estado'], tarjeta['accion']), ('disponible', 'mensajeria'))   # abre la ventana, no navega
        self.assertContains(r, 'data-accion="mensajeria" aria-haspopup="dialog" aria-controls="msj"')
        # Sin páginas propias: no figura como aplicación en la barra lateral ni en el selector.
        self.assertNotIn('msj', [a['codigo'] for a in r.context['apps_menu']])

    def test_boton_de_chat_del_proyecto_solo_si_puede_verlo(self):
        self.client.force_login(self.ana)                      # del equipo
        self.assertContains(self.client.get(f'/tekon/proyectos/{self.p.pk}/'), f'data-msj-proyecto="{self.p.pk}"')
        self.client.force_login(self.beto)                     # fuera del equipo
        self.assertNotContains(self.client.get(f'/tekon/proyectos/{self.p.pk}/'), 'data-msj-proyecto')


@override_settings(**AJUSTES)
class ModuloTests(TestCase):
    """El chat es un módulo: se enciende por empresa y por persona."""

    @classmethod
    def setUpTestData(cls):
        cls.on = crear_empresa(nombre='On', slug='on', modulos=['msj'])
        cls.off = crear_empresa(nombre='Off', slug='off', modulos=['tar'])
        mk = lambda mail, emp: (lambda u: (u, agregar_miembro(u, emp, rol_por_base(emp, RolBase.MIEMBRO))))(
            User.objects.create_user(mail, 'x'))
        cls.ana, cls.m_ana = mk('ana@x.cl', cls.on)
        cls.otro, _ = mk('otro@x.cl', cls.off)

    def test_empresa_sin_el_modulo_no_tiene_chat(self):
        g = servicios.general(self.off)
        self.client.force_login(self.otro)
        for ruta in ('/off/mensajes/', '/off/mensajes/panel/', f'/off/mensajes/c/{g.pk}/', '/off/mensajes/resumen/'):
            self.assertEqual(self.client.get(ruta).status_code, 404, ruta)
        r = self.client.get('/off/')
        self.assertNotContains(r, 'id="msj"')
        self.assertNotContains(r, 'data-accion="mensajeria"')
        self.assertNotContains(r, 'js/mensajeria.js')
        self.assertFalse(r.context['msj_activo'])
        tarjeta = next(t for t in r.context['lanzador_modulos'] if t['codigo'] == 'msj')
        self.assertEqual(tarjeta['estado'], 'no_habilitado')

    def test_persona_con_el_modulo_deshabilitado_pierde_el_acceso(self):
        from cuentas.models import AccesoModulo
        AccesoModulo.objects.create(membresia=self.m_ana, modulo='msj', habilitado=False)
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get('/on/mensajes/').status_code, 403)
        r = self.client.get('/on/')
        self.assertFalse(r.context['msj_activo'])
        self.assertNotContains(r, 'id="msj"')

    def test_rol_sin_la_capacidad_usar_no_entra(self):
        from cuentas.models import RolPermiso
        RolPermiso.objects.create(rol_empresa=self.m_ana.rol, capacidad='msj.usar', habilitado=False)
        from cuentas.capacidades import invalidar_rol
        invalidar_rol(self.m_ana.rol_id)
        self.client.force_login(self.ana)
        self.assertEqual(self.client.get('/on/mensajes/panel/').status_code, 403)

    def test_el_aviso_de_sistema_no_depende_del_modulo(self):
        servicios.aviso_sistema(self.off, self.otro, 'Aviso', url='/jornadas/')
        self.assertEqual(Notificacion.objects.get(destinatario=self.otro).mensaje, 'Aviso')

    def test_empresa_nueva_trae_el_modulo_por_defecto(self):
        from empresas.models import modulos_default
        self.assertIn('msj', modulos_default())

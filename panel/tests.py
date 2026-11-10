from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from archivos.models import MediaStorageConfig, TareaMigracionMedia
from cuentas import capacidades
from cuentas.models import Membresia, RolEmpresa, RolPermiso, User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from empresas.models import Contratista, Empresa

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(**AJUSTES)
class PanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        capacidades.registrar('tst', {'tst.crear': ('Crear tickets', {RolBase.COORDINADOR, RolBase.MIEMBRO})})
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', termino_proyecto_singular='Sitio',
                              termino_proyecto_plural='Sitios', modulos=['tar', 'jor'])
        cls.b = crear_empresa(nombre='Embol', slug='embol')
        cls.pmo = User.objects.create_user('pmo@example.com', 'x')
        cls.m_pmo = agregar_miembro(cls.pmo, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.miembro = User.objects.create_user('miembro@example.com', 'x')
        cls.m_miembro = agregar_miembro(cls.miembro, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))
        cls.pmo_b = User.objects.create_user('pmob@example.com', 'x')
        cls.m_pmo_b = agregar_miembro(cls.pmo_b, cls.b, rol_por_base(cls.b, RolBase.COORDINADOR))
        cls.root = User.objects.create_superuser('root@example.com', 'x')

    def setUp(self):
        cache.clear()  # get_media_config() cachea; el rollback de TestCase no la invalida
        self.addCleanup(cache.clear)

    def vaciar_modulo(self, modulo):
        """Quita las entradas reales de un módulo (para probar el estado «Próximamente»), restaurándolas al terminar."""
        from panel import menu
        antes = list(menu._ITEMS)
        self.addCleanup(lambda: menu._ITEMS.__setitem__(slice(None), antes))
        menu._ITEMS[:] = [i for i in antes if i['modulo'] != modulo]

    # ── Gestión rápida desde la pantalla principal de la empresa ──
    def test_miembro_rapido_cambia_rol_contratista_y_estado(self):
        self.client.force_login(self.pmo)
        url = f'/tekon/config/miembros/{self.m_miembro.pk}/rapido/'
        coord = rol_por_base(self.a, RolBase.COORDINADOR)
        self.assertRedirects(self.client.post(url, {'rol': coord.pk, 'next': '/tekon/'}), '/tekon/', fetch_redirect_response=False)
        self.m_miembro.refresh_from_db()
        self.assertEqual(self.m_miembro.rol, coord)
        self.client.post(url, {'alternar_activa': '1'})
        self.m_miembro.refresh_from_db()
        self.assertFalse(self.m_miembro.activa)
        self.client.post(url, {'rol': rol_por_base(self.b, RolBase.COORDINADOR).pk})   # rol de otra empresa: se ignora
        self.m_miembro.refresh_from_db()
        self.assertEqual(self.m_miembro.rol, coord)

    def test_editar_miembro_guarda_nombre_y_telefono(self):
        self.client.force_login(self.pmo)
        url = f'/tekon/config/miembros/{self.m_miembro.pk}/'
        r = self.client.post(url, {'first_name': 'Ana', 'last_name': 'Pérez', 'telefono': '+56 9 1111',
                                   'rol': self.m_miembro.rol.pk, 'contratista': '', 'activa': 'on'})
        self.assertRedirects(r, '/tekon/config/miembros/', fetch_redirect_response=False)
        self.miembro.refresh_from_db()
        self.assertEqual((self.miembro.first_name, self.miembro.last_name, self.miembro.telefono), ('Ana', 'Pérez', '+56 9 1111'))

    def test_lista_de_usuarios_se_ordena_por_columna(self):
        self.client.force_login(self.pmo)

        def correos(qs=''):
            r = self.client.get('/tekon/config/miembros/' + qs)
            return [m.user.email for m in r.context['lista']]

        self.assertEqual(correos('?orden=usuario'), ['miembro@example.com', 'pmo@example.com'])
        self.assertEqual(correos('?orden=usuario&dir=desc'), ['pmo@example.com', 'miembro@example.com'])
        self.assertEqual(len(correos('?orden=inventado;drop')), 2)                      # columna inválida: se ignora
        r = self.client.get('/tekon/config/miembros/?orden=rol')
        self.assertContains(r, '?orden=rol&amp;dir=desc')                                # reclic invierte
        self.assertContains(r, 'aria-sort="ascending"')

    def test_la_tabla_trae_toggle_y_selectores_en_linea(self):
        self.client.force_login(self.pmo)
        html = self.client.get('/tekon/config/miembros/').content.decode()
        self.assertIn('toggle toggle-success', html)
        self.assertIn('data-autoenviar-select', html)

    def test_miembro_rapido_no_deja_desactivarse_ni_redirigir_fuera(self):
        self.client.force_login(self.pmo)
        r = self.client.post(f'/tekon/config/miembros/{self.m_pmo.pk}/rapido/', {'alternar_activa': '1', 'next': 'https://evil.example/'})
        self.assertRedirects(r, '/tekon/config/miembros/', fetch_redirect_response=False)
        self.m_pmo.refresh_from_db()
        self.assertTrue(self.m_pmo.activa)
        self.client.force_login(self.miembro)
        self.assertEqual(self.client.post(f'/tekon/config/miembros/{self.m_pmo.pk}/rapido/', {'alternar_activa': '1'}).status_code, 403)

    # ── Acceso ──
    def test_paginas_de_configuracion_renderizan_para_el_pmo(self):
        self.client.force_login(self.pmo)
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        for url in ('/tekon/', '/tekon/config/marca/', '/tekon/config/miembros/', '/tekon/config/miembros/nuevo/',
                    f'/tekon/config/miembros/{self.m_miembro.pk}/', '/tekon/config/roles/', '/tekon/config/roles/nuevo/',
                    f'/tekon/config/roles/{rol.pk}/', f'/tekon/config/roles/{rol.pk}/permisos/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_miembro_sin_capacidad_recibe_403(self):
        self.client.force_login(self.miembro)
        for url in ('/tekon/config/marca/', '/tekon/config/miembros/', '/tekon/config/roles/'):
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_panel_global_solo_superusuario(self):
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.get('/panel/').status_code, 403)
        self.assertEqual(self.client.get('/panel/almacenamiento/').status_code, 403)
        self.client.force_login(self.root)
        for url in ('/panel/', '/panel/empresas/nueva/', f'/panel/empresas/{self.a.pk}/', '/panel/almacenamiento/'):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_pmo_no_toca_datos_de_otra_empresa(self):
        self.client.force_login(self.pmo)
        # Con el prefijo de su propia empresa, un pk ajeno no existe.
        self.assertEqual(self.client.get(f'/tekon/config/miembros/{self.m_pmo_b.pk}/').status_code, 404)
        rol_b = rol_por_base(self.b, RolBase.MIEMBRO)
        self.assertEqual(self.client.get(f'/tekon/config/roles/{rol_b.pk}/permisos/').status_code, 404)
        self.assertEqual(self.client.post(f'/tekon/config/roles/{rol_b.pk}/', {'nombre': 'X', 'orden': 0}).status_code, 404)
        # Y no entra a la configuración de la otra empresa.
        self.assertEqual(self.client.get('/embol/config/miembros/').status_code, 403)

    def test_config_de_empresa_no_existe_sin_prefijo(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/config/marca/').status_code, 404)

    # ── Menú por aplicaciones ──
    def _menu(self, user, path, empresa=None):
        from django.test import RequestFactory
        from panel.menu import construir_menu
        req = RequestFactory().get(path)
        req.user, req.empresa = user, empresa
        req.path_info = path.split('/', 2)[2] and '/' + path.split('/', 2)[2] if empresa else path
        return construir_menu(req)

    def test_cada_modulo_es_una_aplicacion_con_estado_proximamente(self):
        self.vaciar_modulo('jor')
        m = self._menu(self.pmo, '/tekon/', self.a)  # Tekon tiene «tar» y «jor»
        codigos = [a['codigo'] for a in m['apps']]
        self.assertEqual(codigos, ['inicio', 'jor', 'tar'])  # «Configuración» vive en Inicio; Plataforma, fuera
        self.assertTrue(next(a for a in m['apps'] if a['codigo'] == 'tar')['disponible'])
        self.assertFalse(next(a for a in m['apps'] if a['codigo'] == 'jor')['disponible'])  # aún sin pantallas
        self.assertEqual(m['app_activa']['codigo'], 'inicio')
        self.assertEqual([i['nombre'] for i in m['items']],
                         ['Módulos', 'Sitios', 'Contratistas', 'Usuarios', 'Sedes', 'Alta por dominio', 'Cargos y permisos', 'Marca'])

    def test_inicio_reune_la_informacion_de_la_empresa(self):
        m = self._menu(self.pmo, '/tekon/config/miembros/', self.a)
        self.assertEqual(m['app_activa']['codigo'], 'inicio')
        self.assertEqual([i['nombre'] for i in m['items']],
                         ['Módulos', 'Sitios', 'Contratistas', 'Usuarios', 'Sedes', 'Alta por dominio', 'Cargos y permisos', 'Marca'])
        # Un Miembro no administra nada: solo ve Inicio y los proyectos.
        m = self._menu(self.miembro, '/tekon/', self.a)
        self.assertEqual([i['nombre'] for i in m['items']], ['Módulos', 'Sitios'])

    def test_plataforma_solo_para_el_superusuario_y_fuera_de_las_empresas(self):
        root = User.objects.create_superuser('root@x.cl', 'x')
        m = self._menu(root, '/tekon/', self.a)
        self.assertNotIn('plataforma', [a['codigo'] for a in m['apps']])        # no está en la empresa
        m = self._menu(root, '/tekon/panel/', self.a)
        self.assertEqual(m['app_activa']['codigo'], 'plataforma')              # sí mientras se usa
        self.assertEqual([i['nombre'] for i in m['items']], ['Empresas', 'Administradores', 'Almacenamiento', 'Correo'])
        self.assertNotIn('plataforma', [a['codigo'] for a in self._menu(self.pmo, '/tekon/panel/', self.a)['apps']])

    def test_entradas_registradas_hacen_disponible_la_app(self):
        from panel import menu
        self.vaciar_modulo('jor')
        menu.registrar_item('jor', 'Mi jornada', 'home', 'clock', capacidad='tst.crear')
        m = self._menu(self.miembro, '/tekon/jornadas/', self.a)  # el rol Miembro tiene la capacidad
        self.assertEqual(m['app_activa']['codigo'], 'jor')
        self.assertTrue(next(a for a in m['apps'] if a['codigo'] == 'jor')['disponible'])
        self.assertEqual([i['nombre'] for i in m['items']], ['Mi jornada'])

    def test_app_oculta_si_el_usuario_no_tiene_ninguna_entrada(self):
        from panel import menu
        self.vaciar_modulo('jor')
        menu.registrar_item('jor', 'Admin', 'home', 'clock', capacidad='cuentas.roles.manage')
        m = self._menu(self.miembro, '/tekon/', self.a)  # el Miembro no administra roles
        self.assertNotIn('jor', [a['codigo'] for a in m['apps']])

    def test_secciones_capacidad_alternativa_y_activo_en(self):
        from panel import menu
        self.vaciar_modulo('jor')
        menu.registrar_item('jor', 'Inicio', 'home', 'clock', orden=10)
        menu.registrar_item('jor', 'Informe', 'panel:miembros', 'chart', orden=20, seccion='Informes')
        menu.registrar_item('jor', 'Ajustes', 'panel:roles', 'settings', orden=30, seccion='Ajustes',
                            capacidad=('cuentas.roles.manage', 'cuentas.usuarios.manage'),
                            activo_en=('jor_actividades:categorias',))
        m = self._menu(self.pmo, '/tekon/jornadas/', self.a)
        self.assertEqual([(i['nombre'], i['seccion']) for i in m['items']],
                         [('Inicio', ''), ('Informe', 'Informes'), ('Ajustes', 'Ajustes')])
        # El Miembro no tiene ninguna de las dos capacidades alternativas: la entrada no aparece.
        mm = self._menu(self.miembro, '/tekon/jornadas/', self.a)
        self.assertNotIn('Ajustes', [i['nombre'] for i in mm['items']])
        # Una ruta de `activo_en` marca activa la entrada (el middleware de empresa deja `path` sin el prefijo).
        from django.test import RequestFactory
        req = RequestFactory().get('/jornadas/categorias/')
        req.user, req.empresa = self.pmo, self.a
        ajustes = next(i for i in menu.construir_menu(req)['items'] if i['nombre'] == 'Ajustes')
        self.assertTrue(ajustes['activo'])

    def test_miembro_no_ve_configuracion(self):
        m = self._menu(self.miembro, '/tekon/', self.a)
        self.assertNotIn('config', [a['codigo'] for a in m['apps']])

    def test_superusuario_ve_plataforma(self):
        m = self._menu(self.root, '/panel/')
        self.assertEqual(m['app_activa']['codigo'], 'plataforma')
        self.assertEqual([i['nombre'] for i in m['items']], ['Empresas', 'Administradores', 'Almacenamiento', 'Correo'])

    def test_lanzador_de_inicio_muestra_las_apps(self):
        self.vaciar_modulo('jor')
        self.client.force_login(self.pmo)
        html = self.client.get('/tekon/').content.decode()
        # Un módulo no habilitado no se muestra a la empresa; Tekon solo tiene «tar» activo (y «jor» sin pantallas).
        for nombre in ('Tareas', 'Asistencia'):
            self.assertIn(nombre, html)
        self.assertNotIn('No habilitado para Tekon', html)  # Registros: oculto
        self.assertIn('Próximamente', html)
        # El superusuario sí lo ve (atenuado) para saber que existe.
        self.client.force_login(self.root)
        self.assertIn('No habilitado para Tekon', self.client.get('/tekon/').content.decode())
        self.client.force_login(self.pmo)
        for seccion in ('Contratistas', 'Roles', 'Usuarios'):   # la información de la empresa
            self.assertIn(seccion, html)
        self.assertNotIn('Plataforma', html)
        self.assertNotIn('Administración', html)

    def test_lanzador_marca_el_estado_de_cada_modulo(self):
        self.vaciar_modulo('jor')
        self.client.force_login(self.pmo)
        estados = {m['codigo']: m['estado'] for m in self.client.get('/tekon/').context['lanzador_modulos']}
        self.assertEqual(estados, {'reg': 'no_habilitado', 'tar': 'disponible', 'jor': 'proximamente', 'msj': 'no_habilitado',
                                   'apu': 'no_habilitado'})

    def test_apu_se_anuncia_como_proximamente(self):
        # Módulo activo y sin pantallas: tarjeta «Próximamente», sin enlace y sin entradas en la barra lateral.
        Empresa.objects.filter(pk=self.a.pk).update(modulos=['tar', 'apu'])
        from django.core.cache import cache
        cache.clear()
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/')
        tarjeta = next(t for t in r.context['lanzador_modulos'] if t['codigo'] == 'apu')
        self.assertEqual((tarjeta['estado'], tarjeta['url'], tarjeta['nombre']),
                         ('proximamente', '', 'APU IA'))
        self.assertContains(r, 'Análisis de Precios Unitarios')
        self.assertContains(r, 'class="mod-ia"')                  # «con IA» resaltado dentro del título
        self.assertContains(r, '<span class="mod-cinta">Próximamente</span>')   # cinta en la esquina de la tarjeta
        self.assertNotContains(r, 'badge badge-ghost badge-sm">Próximamente')

    def test_cada_modulo_tiene_su_propio_color_pastel(self):
        self.vaciar_modulo('jor')
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/')
        clases = {m['codigo']: m['clases'] for m in r.context['lanzador_modulos']}
        self.assertEqual(clases, {'reg': 'mod-chip mod-reg', 'tar': 'mod-chip mod-tar', 'jor': 'mod-chip mod-jor',
                                  'msj': 'mod-chip mod-msj', 'apu': 'mod-chip mod-apu'})
        self.assertEqual(len(set(clases.values())), 5)                      # cinco colores distintos
        html = r.content.decode()
        for c in ('mod-tar', 'mod-jor'):
            self.assertIn(c, html)
        self.assertNotIn('mod-reg', html)       # Registros no está habilitado: no se muestra
        # En un módulo, el shell lleva su código para que barra lateral y cabecera tomen su color.
        self.assertIn('data-modulo="tar"', self.client.get('/tekon/tareas/').content.decode())

    def test_portada_publica_presenta_los_tres_modulos(self):
        html = self.client.get('/').content.decode()
        for nombre in ('Registros', 'Tareas', 'Asistencia', 'Iniciar sesión'):
            self.assertIn(nombre, html)

    # ── Empresas ──
    def test_superusuario_crea_empresa_con_roles_y_termino(self):
        self.client.force_login(self.root)
        r = self.client.post('/panel/empresas/nueva/', {
            'nombre': 'Nueva', 'slug': 'nueva', 'activa': 'on', 'modulos': ['reg', 'tar'],
            'termino_proyecto_singular': 'Sitio', 'termino_proyecto_plural': 'Sitios',
        })
        self.assertRedirects(r, '/panel/', fetch_redirect_response=False)
        e = Empresa.objects.get(slug='nueva')
        self.assertEqual(e.modulos, ['reg', 'tar'])
        self.assertEqual(e.roles.count(), len(RolBase))
        self.assertEqual(self.client.get('/panel/').status_code, 200)

    def test_tipos_de_proyecto_al_crear_empresa(self):
        self.client.force_login(self.root)
        datos = {'nombre': 'Tel', 'slug': 'tel', 'activa': 'on', 'modulos': ['reg'],
                 'termino_proyecto_singular': 'Sitio', 'termino_proyecto_plural': 'Sitios'}
        self.client.post('/panel/empresas/nueva/', {**datos, 'tipos_proyecto': 'Poste, torre\n  Torre ;Poste'})
        self.assertEqual(list(Empresa.objects.get(slug='tel').tipos_proyecto.values_list('nombre', flat=True)),
                         ['Poste', 'torre'])
        # En blanco es válido: se definen después.
        self.client.post('/panel/empresas/nueva/', {**datos, 'nombre': 'Vacía', 'slug': 'vacia'})
        self.assertEqual(Empresa.objects.get(slug='vacia').tipos_proyecto.count(), 0)
        # Una empresa existente no ofrece el campo.
        self.assertNotContains(self.client.get(f'/panel/empresas/{Empresa.objects.get(slug="tel").pk}/'), 'tipos_proyecto')

    def test_slug_reservado_rechazado_en_el_formulario(self):
        self.client.force_login(self.root)
        r = self.client.post('/panel/empresas/nueva/', {
            'nombre': 'X', 'slug': 'panel', 'activa': 'on', 'termino_proyecto_singular': 'P', 'termino_proyecto_plural': 'Ps',
        })
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Empresa.objects.filter(slug='panel').exists())

    def test_pmo_edita_marca_y_termino(self):
        self.client.force_login(self.pmo)
        r = self.client.post('/tekon/config/marca/', {
            'nombre_marca': 'Tekon RL', 'color_primario': '#e60000',
            'termino_proyecto_singular': 'Torre', 'termino_proyecto_plural': 'Torres',
        })
        self.assertRedirects(r, '/tekon/config/marca/', fetch_redirect_response=False)
        self.a.refresh_from_db()
        self.assertEqual((self.a.nombre_marca, self.a.termino_proyecto_plural), ('Tekon RL', 'Torres'))
        self.assertIn('Torres', self.client.get('/tekon/config/marca/').content.decode())

    def test_pmo_no_puede_cambiar_slug_ni_modulos(self):
        self.client.force_login(self.pmo)
        self.client.post('/tekon/config/marca/', {
            'slug': 'otro', 'modulos': ['reg', 'tar', 'jor'],
            'termino_proyecto_singular': 'Sitio', 'termino_proyecto_plural': 'Sitios',
        })
        self.a.refresh_from_db()
        self.assertEqual((self.a.slug, self.a.modulos), ('tekon', ['tar', 'jor']))

    # ── Miembros ──
    def test_agregar_miembro_nuevo_envia_invitacion(self):
        self.client.force_login(self.pmo)
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        with self.captureOnCommitCallbacks(execute=True):
            r = self.client.post('/tekon/config/miembros/nuevo/', {'email': 'Nuevo@Example.com', 'rol': rol.pk, 'enviar_correo': 'on'})
        self.assertRedirects(r, '/tekon/config/miembros/', fetch_redirect_response=False)
        u = User.objects.get(email='nuevo@example.com')
        self.assertFalse(u.has_usable_password())
        self.assertTrue(Membresia.objects.filter(user=u, empresa=self.a, activa=True).exists())
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/tekon/acceso/recuperar/', mail.outbox[0].body)

    def test_no_se_asigna_rol_de_otra_empresa(self):
        self.client.force_login(self.pmo)
        rol_b = rol_por_base(self.b, RolBase.MIEMBRO)
        r = self.client.post('/tekon/config/miembros/nuevo/', {'email': 'x@example.com', 'rol': rol_b.pk})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email='x@example.com').exists())

    def test_cambiar_rol_y_no_autodesactivarse(self):
        self.client.force_login(self.pmo)
        director = rol_por_base(self.a, RolBase.COORDINADOR)
        self.client.post(f'/tekon/config/miembros/{self.m_miembro.pk}/', {'rol': director.pk, 'activa': 'on'})
        self.m_miembro.refresh_from_db()
        self.assertEqual(self.m_miembro.rol, director)
        self.client.post(f'/tekon/config/miembros/{self.m_pmo.pk}/', {'rol': self.m_pmo.rol_id})  # activa ausente
        self.m_pmo.refresh_from_db()
        self.assertTrue(self.m_pmo.activa)

    # ── Roles ──
    def test_crear_rol_personalizado_ITO_y_ajustar_permisos(self):
        self.client.force_login(self.pmo)
        self.a.modulos = ['tar', 'jor', 'tst']   # la matriz solo guarda las capacidades de módulos activos
        self.a.save()
        r = self.client.post('/tekon/config/roles/nuevo/', {
            'nombre': 'ITO', 'rol_base': RolBase.MIEMBRO, 'orden': 5, 'activo': 'on',
        })
        ito = RolEmpresa.objects.get(empresa=self.a, nombre='ITO')
        self.assertRedirects(r, f'/tekon/config/roles/{ito.pk}/permisos/', fetch_redirect_response=False)
        # Se desmarca una capacidad que el rol base sí tiene → queda UNA diferencia en BD.
        marcadas = [c for c in capacidades._conjunto_rol(ito) if c != 'tst.crear']
        self.client.post(f'/tekon/config/roles/{ito.pk}/permisos/', {'cap': marcadas})
        self.assertEqual(
            list(RolPermiso.objects.filter(rol_empresa=ito).values_list('capacidad', 'habilitado')),
            [('tst.crear', False)],
        )
        agregar_miembro(self.miembro, self.a, ito)
        u = User.objects.get(pk=self.miembro.pk)
        self.assertFalse(capacidades.tiene_capacidad(u, 'tst.crear', self.a))

    def test_matriz_conserva_excepciones_de_modulos_desactivados(self):
        self.client.force_login(self.pmo)
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=rol, capacidad='tst.crear', habilitado=False)
        # 'tst' no está en los módulos de la empresa: no aparece en la matriz y su excepción debe sobrevivir.
        self.client.post(f'/tekon/config/roles/{rol.pk}/permisos/', {'cap': ['proyectos.view']})
        self.assertTrue(RolPermiso.objects.filter(rol_empresa=rol, capacidad='tst.crear', habilitado=False).exists())

    def test_nombre_de_rol_duplicado_rechazado(self):
        self.client.force_login(self.pmo)
        r = self.client.post('/tekon/config/roles/nuevo/', {'nombre': 'coordinador', 'rol_base': RolBase.COORDINADOR, 'orden': 0, 'activo': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.a.roles.filter(nombre__iexact='coordinador').count(), 1)

    def test_rol_base_no_se_cambia_al_editar(self):
        self.client.force_login(self.pmo)
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        self.client.post(f'/tekon/config/roles/{rol.pk}/', {'nombre': 'Equipo', 'rol_base': RolBase.COORDINADOR, 'orden': 1, 'activo': 'on'})
        rol.refresh_from_db()
        self.assertEqual((rol.nombre, rol.rol_base), ('Equipo', RolBase.MIEMBRO))

    # ── Almacenamiento ──
    def test_migrar_sin_s3_no_lanza_proceso(self):
        self.client.force_login(self.root)
        with mock.patch('panel.views.subprocess.Popen') as popen:
            self.client.post('/panel/almacenamiento/migrar/')
        popen.assert_not_called()

    def test_migrar_con_s3_lanza_el_comando_con_las_opciones(self):
        MediaStorageConfig.objects.create(mode='s3', s3_bucket='b', s3_access_key='k', s3_secret_key='s')
        self.client.force_login(self.root)
        with mock.patch('panel.views.subprocess.Popen') as popen:
            self.client.post('/panel/almacenamiento/migrar/', {'dry_run': 'on', 'antiguedad': '7'})
        args = popen.call_args.args[0]
        self.assertEqual(args[2:], ['media_a_cdn', '--dry-run', '--antiguedad', '7'])

    def test_migrar_rechaza_si_hay_una_en_curso(self):
        MediaStorageConfig.objects.create(mode='s3', s3_bucket='b', s3_access_key='k', s3_secret_key='s')
        TareaMigracionMedia.objects.create(estado='EN_CURSO')
        self.client.force_login(self.root)
        with mock.patch('panel.views.subprocess.Popen') as popen:
            self.client.post('/panel/almacenamiento/migrar/')
        popen.assert_not_called()

    def test_migrar_exige_post(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/panel/almacenamiento/migrar/').status_code, 405)

    def test_eliminar_cargo_en_uso_pasa_miembros_a_otro(self):
        viejo = RolEmpresa.objects.create(empresa=self.a, nombre='Viejo', rol_base=RolBase.MIEMBRO)
        nuevo = RolEmpresa.objects.create(empresa=self.a, nombre='Nuevo', rol_base=RolBase.MIEMBRO)
        u = User.objects.create_user('v@example.com', 'x')
        m = agregar_miembro(u, self.a, viejo)
        self.client.force_login(self.pmo)
        url = f'/tekon/config/roles/{viejo.pk}/eliminar/'
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url)   # sin destino: no borra
        self.assertTrue(RolEmpresa.objects.filter(pk=viejo.pk).exists())
        self.client.post(url, {'destino': nuevo.pk})
        self.assertFalse(RolEmpresa.objects.filter(pk=viejo.pk).exists())
        m.refresh_from_db()
        self.assertEqual(m.rol, nuevo)

    # ── Administradores de sistema (Plataforma) ──
    def test_administradores_solo_superusuario(self):
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.get('/panel/administradores/').status_code, 403)
        self.assertEqual(self.client.post('/panel/administradores/nuevo/', {'email': 'x@example.com'}).status_code, 403)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/panel/administradores/').status_code, 200)

    def test_admin_de_sistema_gestiona_su_empresa_sin_ser_miembro_y_no_las_demas(self):
        self.client.force_login(self.root)
        r = self.client.post('/panel/administradores/nuevo/', {
            'email': 'adm@example.com', 'empresas': [self.a.pk]})
        self.assertEqual(r.status_code, 302)
        adm = User.objects.get(email='adm@example.com')
        self.assertFalse(adm.is_superuser)
        self.assertEqual(list(adm.empresas_administradas.all()), [self.a])
        self.client.force_login(adm)
        self.assertEqual(self.client.get('/tekon/config/miembros/').status_code, 200)
        self.assertEqual(self.client.get('/tekon/config/roles/').status_code, 200)
        self.assertEqual(self.client.get('/embol/config/miembros/').status_code, 403)
        self.assertEqual(self.client.get('/panel/administradores/').status_code, 403)
        adm = User.objects.get(pk=adm.pk)   # sin la memoización de request
        self.assertTrue(capacidades.tiene_capacidad(adm, 'cuentas.usuarios.manage', self.a))
        self.assertFalse(capacidades.tiene_capacidad(adm, 'tst.crear', self.a))   # los módulos exigen ser miembro
        self.assertFalse(capacidades.tiene_capacidad(adm, 'cuentas.usuarios.manage', self.b))
        from empresas.tenancy import empresas_de
        self.assertEqual(empresas_de(adm), [self.a])

    def test_quitar_administrador_corta_el_acceso(self):
        adm = User.objects.create_user('adm2@example.com', 'x')
        adm.empresas_administradas.add(self.a)
        self.client.force_login(self.root)
        self.client.post(f'/panel/administradores/{adm.pk}/quitar/')
        self.assertFalse(adm.empresas_administradas.exists())
        self.client.force_login(adm)
        self.assertEqual(self.client.get('/tekon/config/miembros/').status_code, 403)

    def test_puesto_se_edita_desde_usuarios(self):
        from jor_empleados.models import Perfil
        self.client.force_login(self.miembro)
        self.assertEqual(self.client.post(f'/tekon/config/miembros/{self.m_miembro.pk}/rapido/', {'puesto': 'X'}).status_code, 403)
        self.client.force_login(self.pmo)
        self.client.post(f'/tekon/config/miembros/{self.m_miembro.pk}/rapido/', {'puesto': '  Supervisor   Civil '})
        self.assertEqual(Perfil.de(self.m_miembro).cargo, 'Supervisor Civil')   # el cargo es «Ejecutor»: no se repite
        self.client.post(f'/tekon/config/miembros/{self.m_miembro.pk}/rapido/', {'puesto': 'Ejecutor Civil'})
        perfil = Perfil.de(self.m_miembro)
        self.assertEqual((perfil.cargo, perfil.cargo_completo), ('Civil', 'Ejecutor - Civil'))
        r = self.client.get('/tekon/config/miembros/')   # tekon tiene el módulo jor
        self.assertContains(r, 'name="puesto"')
        self.assertContains(r, '<option value="Civil">')
        self.client.get('/tekon/config/miembros/?orden=puesto&dir=asc')
        self.b.modulos = ['tar']   # sin Asistencia no hay puesto
        self.b.save()
        cache.clear()
        self.client.force_login(self.pmo_b)
        self.assertNotContains(self.client.get('/embol/config/miembros/'), 'name="puesto"')


@override_settings(**AJUSTES)
class ContratistasTests(TestCase):
    """«Empresa» es el cliente de la plataforma; dentro de ella, las organizaciones externas son
    «contratistas» (nunca se las llama «empresa»)."""

    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon')
        cls.b = crear_empresa(nombre='Embol', slug='embol')
        cls.pmo = User.objects.create_user('pmo@example.com', 'x')
        agregar_miembro(cls.pmo, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.miembro = User.objects.create_user('miembro@example.com', 'x')
        agregar_miembro(cls.miembro, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))
        cls.ca = Contratista.objects.create(empresa=cls.a, nombre='Redes SA', codigo='red')
        cls.cb = Contratista.objects.create(empresa=cls.b, nombre='Otra SA', codigo='RED')

    def setUp(self):
        cache.clear()
        self.client.force_login(self.pmo)

    def test_el_codigo_se_normaliza_y_es_unico_por_empresa(self):
        self.assertEqual(self.ca.codigo, 'RED')
        self.assertEqual(Contratista.objects.filter(codigo='RED').count(), 2)  # otra empresa: permitido
        r = self.client.post('/tekon/config/contratistas/nuevo/', {'nombre': 'Duplicado', 'codigo': 'red', 'activo': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Contratista.objects.filter(empresa=self.a).count(), 1)

    def test_crear_y_editar(self):
        r = self.client.post('/tekon/config/contratistas/nuevo/', {'nombre': 'Torres SpA', 'codigo': 'tor', 'activo': 'on'})
        self.assertRedirects(r, '/tekon/config/contratistas/', fetch_redirect_response=False)
        c = Contratista.objects.get(empresa=self.a, codigo='TOR')
        self.client.post(f'/tekon/config/contratistas/{c.pk}/', {'nombre': 'Torres Chile', 'codigo': 'TOR'})
        c.refresh_from_db()
        self.assertEqual((c.nombre, c.activo), ('Torres Chile', False))

    def test_la_pantalla_dice_contratista_y_no_empresa_para_los_contratistas(self):
        html = self.client.get('/tekon/config/contratistas/').content.decode()
        self.assertIn('Contratistas', html)
        self.assertIn('Redes SA', html)
        self.assertNotIn('Otra SA', html)  # el de otra empresa no aparece
        html = self.client.get('/tekon/config/miembros/nuevo/').content.decode()
        self.assertIn('Contratista', html)

    def test_no_se_toca_un_contratista_de_otra_empresa(self):
        for url in (f'/tekon/config/contratistas/{self.cb.pk}/', ):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(f'/tekon/config/contratistas/{self.cb.pk}/eliminar/').status_code, 404)
        self.cb.refresh_from_db()
        self.assertFalse(self.cb.is_deleted)

    def test_solo_quien_administra_accede(self):
        self.client.force_login(self.miembro)
        self.assertEqual(self.client.get('/tekon/config/contratistas/').status_code, 403)
        self.assertEqual(self.client.post('/tekon/config/contratistas/nuevo/', {'nombre': 'x', 'codigo': 'x'}).status_code, 403)

    def test_asignar_contratista_a_un_miembro(self):
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        self.client.post('/tekon/config/miembros/nuevo/', {'email': 'nuevo@example.com', 'rol': rol.pk, 'contratista': self.ca.pk})
        m = Membresia.objects.get(user__email='nuevo@example.com', empresa=self.a)
        self.assertEqual(m.contratista, self.ca)
        self.assertIn('Redes SA', self.client.get('/tekon/config/miembros/').content.decode())
        # Cambiarlo / quitarlo desde la edición.
        self.client.post(f'/tekon/config/miembros/{m.pk}/', {'rol': rol.pk, 'activa': 'on'})  # sin contratista
        m.refresh_from_db()
        self.assertIsNone(m.contratista)

    def test_no_se_asigna_un_contratista_de_otra_empresa(self):
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        r = self.client.post('/tekon/config/miembros/nuevo/', {'email': 'x@example.com', 'rol': rol.pk, 'contratista': self.cb.pk})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(User.objects.filter(email='x@example.com').exists())
        m = Membresia(user=self.miembro, empresa=self.a, rol=rol, contratista=self.cb)
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            m.full_clean()

    def test_reactivar_sin_indicarlo_no_borra_el_contratista(self):
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        agregar_miembro(self.miembro, self.a, rol, self.ca)
        agregar_miembro(self.miembro, self.a, rol)  # sin contratista: lo conserva
        self.assertEqual(Membresia.objects.get(user=self.miembro, empresa=self.a).contratista, self.ca)

    def test_eliminar_exige_no_tener_miembros_activos_y_es_logico(self):
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        agregar_miembro(self.miembro, self.a, rol, self.ca)
        self.client.post(f'/tekon/config/contratistas/{self.ca.pk}/eliminar/')
        self.ca.refresh_from_db()
        self.assertFalse(self.ca.is_deleted)  # tiene un miembro activo
        Membresia.objects.filter(user=self.miembro).update(activa=False)
        self.client.post(f'/tekon/config/contratistas/{self.ca.pk}/eliminar/')
        self.ca.refresh_from_db()
        self.assertTrue(self.ca.is_deleted)
        # El código queda libre para crear otro.
        r = self.client.post('/tekon/config/contratistas/nuevo/', {'nombre': 'Nuevo Redes', 'codigo': 'RED', 'activo': 'on'})
        self.assertEqual(r.status_code, 302)

    def test_aparece_en_el_menu_de_configuracion(self):
        r = self.client.get('/tekon/config/contratistas/')
        self.assertIn('Contratistas', [i['nombre'] for i in r.context['menu_lateral']])


@override_settings(**AJUSTES)
class PapeleraContratistasTests(TestCase):
    def setUp(self):
        from empresas.models import Contratista, Empresa
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.emp = Empresa.objects.create(nombre='Acme', slug='acme')
        self.c = Contratista.objects.create(empresa=self.emp, nombre='Borrado SA', codigo='B1', is_deleted=True, activo=False)
        self.su = U.objects.create_superuser('su@x.cl', 'x')

    def test_superusuario_ve_eliminados_y_restaura(self):
        self.client.force_login(self.su)
        r = self.client.get('/acme/config/contratistas/')
        self.assertContains(r, 'Borrado SA')
        r = self.client.post(f'/acme/config/contratistas/{self.c.pk}/restaurar/')
        self.assertEqual(r.status_code, 302)
        self.c.refresh_from_db()
        self.assertFalse(self.c.is_deleted)

    def test_alternar_activo(self):
        from empresas.models import Contratista
        self.client.force_login(self.su)
        c2 = Contratista.objects.create(empresa=self.emp, nombre='Vivo', codigo='V1')
        self.client.post(f'/acme/config/contratistas/{c2.pk}/alternar/')
        c2.refresh_from_db()
        self.assertFalse(c2.activo)


@override_settings(**AJUSTES)
class SedesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon')
        cls.b = crear_empresa(nombre='Embol', slug='embol')
        cls.pmo = User.objects.create_user('pmo@example.com', 'x')
        cls.m_pmo = agregar_miembro(cls.pmo, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.otro = User.objects.create_user('otro@example.com', 'x')
        cls.m_otro = agregar_miembro(cls.otro, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))

    def test_crear_sede_sin_repetir_nombre(self):
        from empresas.models import Sede
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.post('/tekon/config/sedes/nueva/', {'nombre': 'La Paz', 'activo': 'on'}).status_code, 302)
        r = self.client.post('/tekon/config/sedes/nueva/', {'nombre': 'la paz', 'activo': 'on'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Sede.objects.filter(empresa=self.a).count(), 1)

    def test_asignar_sede_desde_la_tabla_y_solo_de_la_empresa(self):
        from empresas.models import Sede
        s = Sede.objects.create(empresa=self.a, nombre='Santiago')
        ajena = Sede.objects.create(empresa=self.b, nombre='Cochabamba')
        self.client.force_login(self.pmo)
        url = f'/tekon/config/miembros/{self.m_otro.pk}/rapido/'
        self.client.post(url, {'sede': s.pk})
        self.m_otro.refresh_from_db()
        self.assertEqual(self.m_otro.sede, s)
        self.client.post(url, {'sede': ajena.pk})        # de otra empresa: se rechaza
        self.m_otro.refresh_from_db()
        self.assertEqual(self.m_otro.sede, s)
        self.client.post(url, {'sede': ''})              # vacía = sin sede (es opcional)
        self.m_otro.refresh_from_db()
        self.assertIsNone(self.m_otro.sede)
        self.assertContains(self.client.get('/tekon/config/miembros/'), '>Sede<')

    def test_no_se_elimina_una_sede_con_miembros(self):
        from empresas.models import Sede
        s = Sede.objects.create(empresa=self.a, nombre='Santiago')
        self.m_otro.sede = s
        self.m_otro.save()
        self.client.force_login(self.pmo)
        self.client.post(f'/tekon/config/sedes/{s.pk}/eliminar/')
        self.assertTrue(Sede.objects.filter(pk=s.pk).exists())
        self.m_otro.sede = None
        self.m_otro.save()
        self.client.post(f'/tekon/config/sedes/{s.pk}/eliminar/')
        self.assertFalse(Sede.objects.filter(pk=s.pk).exists())


class ProveedorDelServicioTests(TestCase):
    """Logo del proveedor (p. ej. Redline): opcional, lo define solo el superusuario y se ve en el pie de la app."""

    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', termino_proyecto_singular='Sitio',
                              termino_proyecto_plural='Sitios', modulos=['tar'])
        cls.pmo = User.objects.create_user('pmo@example.com', 'x')
        agregar_miembro(cls.pmo, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.root = User.objects.create_superuser('root@example.com', 'x')

    def setUp(self):
        import shutil
        import tempfile
        cache.clear()
        self.addCleanup(cache.clear)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=tmp, **AJUSTES)
        ctx.enable()
        self.addCleanup(ctx.disable)

    @staticmethod
    def _logo():
        from io import BytesIO

        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        b = BytesIO()
        Image.new('RGB', (120, 40), 'red').save(b, 'PNG')
        return SimpleUploadedFile('redline.png', b.getvalue(), content_type='image/png')

    def _datos(self, **extra):
        return {'nombre': 'Tekon', 'slug': 'tekon', 'activa': 'on', 'modulos': ['tar'],
                'termino_proyecto_singular': 'Sitio', 'termino_proyecto_plural': 'Sitios', **extra}

    def test_es_opcional(self):
        self.client.force_login(self.root)
        r = self.client.post(f'/panel/empresas/{self.a.pk}/', self._datos())
        self.assertEqual(r.status_code, 302)
        self.a.refresh_from_db()
        self.assertFalse(self.a.logo_proveedor)
        self.assertNotContains(self.client.get('/tekon/'), 'Powered by')

    def test_el_superusuario_lo_define_y_aparece_en_el_pie(self):
        self.client.force_login(self.root)
        r = self.client.post(f'/panel/empresas/{self.a.pk}/', self._datos(nombre_proveedor='Redline', logo_proveedor=self._logo()))
        self.assertEqual(r.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.nombre_proveedor, 'Redline')
        self.assertEqual(self.a.logo_proveedor.name, 'branding/tekon/proveedor.png')
        pagina = self.client.get('/tekon/').content.decode()
        self.assertIn('Powered by', pagina)
        self.assertIn('/media/branding/tekon/proveedor.png', pagina)

    def test_el_formulario_de_marca_del_coordinador_no_lo_incluye(self):
        self.client.force_login(self.pmo)
        self.assertNotContains(self.client.get('/tekon/config/marca/'), 'logo_proveedor')
        self.client.post('/tekon/config/marca/', {
            'termino_proyecto_singular': 'Sitio', 'termino_proyecto_plural': 'Sitios',
            'nombre_proveedor': 'Otro', 'logo_proveedor': self._logo(),
        })
        self.a.refresh_from_db()
        self.assertEqual((self.a.nombre_proveedor, bool(self.a.logo_proveedor)), ('', False))

    def test_el_login_muestra_al_proveedor(self):
        self.a.logo_proveedor.save('p.png', self._logo(), save=True)
        self.assertContains(self.client.get('/tekon/acceso/login/'), 'Powered by')


@override_settings(**AJUSTES)
class MiembrosAjaxTests(TestCase):
    """La tabla de usuarios se actualiza sin recargar la página: las acciones responden JSON si piden AJAX."""

    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', modulos=['tar'])
        cls.pmo = User.objects.create_user('pmo@example.com', 'x')
        cls.m_pmo = agregar_miembro(cls.pmo, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.otro = User.objects.create_user('otro@example.com', 'x')
        cls.m_otro = agregar_miembro(cls.otro, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.client.force_login(self.pmo)

    def post(self, accion, datos=None, ajax=True):
        extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if ajax else {}
        return self.client.post(f'/tekon/config/miembros/{self.m_otro.pk}/{accion}/', datos or {}, **extra)

    def test_cambia_el_cargo_y_responde_json_sin_redirigir(self):
        coord = rol_por_base(self.a, RolBase.COORDINADOR)
        r = self.post('rapido', {'rol': coord.pk})
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/json'))
        d = r.json()
        self.assertTrue(d['ok'])
        self.assertEqual(d['mensajes'][0]['tipo'], 'success')
        self.assertIn('otro@example.com', d['mensajes'][0]['texto'])
        self.m_otro.refresh_from_db()
        self.assertEqual(self.m_otro.rol, coord)

    def test_los_mensajes_no_se_acumulan_para_la_siguiente_pagina(self):
        self.post('rapido', {'alternar_activa': '1'})
        self.assertNotContains(self.client.get('/tekon/config/miembros/'), 'activado')

    def test_un_error_responde_ok_falso(self):
        d = self.post('rapido', {'rol': '99999'}).json()
        self.assertFalse(d['ok'])
        self.assertEqual(d['mensajes'][0]['tipo'], 'error')

    def test_sin_ajax_sigue_redirigiendo(self):
        r = self.post('rapido', {'alternar_activa': '1'}, ajax=False)
        self.assertRedirects(r, '/tekon/config/miembros/', fetch_redirect_response=False)

    def test_reinvitar_tambien_responde_json(self):
        d = self.post('reinvitar').json()   # ya tiene contraseña → aviso, no error
        self.assertTrue(d['ok'])
        self.assertEqual(d['mensajes'][0]['tipo'], 'warning')

    def test_sin_permiso_no_cambia_nada(self):
        self.client.force_login(self.otro)
        self.assertEqual(self.post('rapido', {'alternar_activa': '1'}).status_code, 403)

    def test_la_pagina_usa_ajax_y_todo_el_ancho(self):
        h = self.client.get('/tekon/config/miembros/').content.decode()
        self.assertIn('data-ajax', h)
        for zona in ('miembros-resumen', 'miembros-tabla', 'miembros-lista'):
            self.assertIn(f'data-refrescar="{zona}"', h)
        self.assertIn('max-w-none', h)
        self.assertNotIn('max-w-6xl flex min-h-0', h)       # el ancho máximo ya no limita esta página


    def test_el_resumen_por_cargo_y_sede_cuenta_solo_activos(self):
        from empresas.models import Sede
        sede = Sede.objects.create(empresa=self.a, nombre='Central')
        self.m_otro.sede = sede
        self.m_otro.activa = False
        self.m_otro.save()
        r = self.client.get('/tekon/config/miembros/').context['resumen']
        self.assertEqual((r['total'], r['activos']), (2, 1))
        self.assertEqual(r['por_cargo'], [('Coordinador', 1)])          # el inactivo (Ejecutor) no se cuenta
        self.assertEqual(r['por_sede'], [('Sin sede', 1)])              # ni su sede
        self.m_otro.activa = True
        self.m_otro.save()
        r = self.client.get('/tekon/config/miembros/').context['resumen']
        self.assertEqual(dict(r['por_sede']), {'Central': 1, 'Sin sede': 1})

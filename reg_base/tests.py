from datetime import date

from django.core.cache import cache
from django.test import TestCase, override_settings

from cuentas.models import RolEmpresa, RolPermiso, User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from empresas.models import Contratista
from proyectos.models import Proyecto, TipoProyecto

from . import alcance, estado, tipos

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


def persona(email, empresa, rol_base, contratista=None):
    u = User.objects.create_user(email, 'x', first_name=email.split('@')[0].title())
    agregar_miembro(u, empresa, rol_por_base(empresa, rol_base), contratista)
    return u


@override_settings(**AJUSTES)
class BaseRegistros(TestCase):
    """Empresa «tekon» (con Registros) con 2 contratistas, todos los roles y proyectos Poste/Torre."""

    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', modulos=['reg'], termino_proyecto_singular='Sitio',
                              termino_proyecto_plural='Sitios')
        cls.b = crear_empresa(nombre='Otra', slug='otra', modulos=['reg'])
        for empresa in (cls.a, cls.b):   # los tipos de registro se activan por empresa
            for clave in ('txtss', 'construccion'):
                tipos.habilitar(empresa, clave)
        cls.c1 = Contratista.objects.create(empresa=cls.a, nombre='Redes SA', codigo='C1')
        cls.c2 = Contratista.objects.create(empresa=cls.a, nombre='Torres SpA', codigo='C2')
        cls.pmo = persona('pmo@x.cl', cls.a, RolBase.COORDINADOR)
        cls.root = User.objects.create_superuser('root_cfg@x.cl', 'x')   # la configuración es solo del superusuario
        cls.patro = persona('patro@x.cl', cls.a, RolBase.OBSERVADOR)
        cls.dir1 = persona('dir1@x.cl', cls.a, RolBase.COORDINADOR, cls.c1)
        cls.dir2 = persona('dir2@x.cl', cls.a, RolBase.COORDINADOR, cls.c2)
        cls.dir_solo = persona('dirsolo@x.cl', cls.a, RolBase.COORDINADOR)       # director sin contratista
        cls.ito1 = persona('ito1@x.cl', cls.a, RolBase.MIEMBRO, cls.c1)
        cls.ito2 = persona('ito2@x.cl', cls.a, RolBase.MIEMBRO, cls.c1)
        cls.ito3 = persona('ito3@x.cl', cls.a, RolBase.MIEMBRO, cls.c2)
        cls.visita = persona('visita@x.cl', cls.a, RolBase.OBSERVADOR)
        cls.pmo_b = persona('pmob@x.cl', cls.b, RolBase.COORDINADOR)
        cls.poste = TipoProyecto.objects.create(empresa=cls.a, nombre='Poste')
        cls.torre = TipoProyecto.objects.create(empresa=cls.a, nombre='Torre')
        cls.p1 = Proyecto.objects.create(empresa=cls.a, nombre='Poste Norte', codigo='P1', tipo=cls.poste)
        cls.t1 = Proyecto.objects.create(empresa=cls.a, nombre='Torre Sur', codigo='T1', tipo=cls.torre)
        cls.t2 = Proyecto.objects.create(empresa=cls.a, nombre='Torre Este', codigo='T2', tipo=cls.torre)
        cls.pb = Proyecto.objects.create(empresa=cls.b, nombre='Ajeno', codigo='B1')

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)


class AlcanceTests(BaseRegistros):
    def setUp(self):
        super().setUp()
        from reg_txtss.models import RegTxtss
        self.M = RegTxtss
        mk = lambda p, u, e=None: RegTxtss.objects.create(empresa=e or self.a, proyecto=p, user=u)
        self.r1, self.r2 = mk(self.p1, self.ito1), mk(self.t1, self.ito2)
        self.r3 = mk(self.t2, self.ito3)
        self.rb = RegTxtss.objects.create(empresa=self.b, proyecto=self.pb, user=self.pmo_b)

    def ids(self, user, empresa=None):
        return set(alcance.registros_visibles(user, empresa or self.a, self.M.objects.all()).values_list('pk', flat=True))

    def test_miembro_solo_ve_lo_suyo(self):
        self.assertEqual(self.ids(self.ito1), {self.r1.pk})
        self.assertEqual(self.ids(self.ito3), {self.r3.pk})

    def test_director_ve_los_de_su_contratista_y_no_los_de_otro(self):
        self.assertEqual(self.ids(self.dir1), {self.r1.pk, self.r2.pk})
        self.assertEqual(self.ids(self.dir2), {self.r3.pk})

    def test_coordinador_sin_contratista_ve_toda_la_empresa(self):
        self.assertEqual(self.ids(self.dir_solo), {self.r1.pk, self.r2.pk, self.r3.pk})

    def test_coordinador_acotado_no_tiene_capacidades_de_empresa(self):
        from cuentas.capacidades import tiene_capacidad
        for cap in ('reg.alcance.todo', 'cuentas.usuarios.manage'):
            self.assertTrue(tiene_capacidad(self.dir_solo, cap, self.a), cap)
            self.assertFalse(tiene_capacidad(self.dir1, cap, self.a), cap)
        self.assertTrue(tiene_capacidad(self.dir1, 'reg.alcance.contratista', self.a))
        self.assertFalse(tiene_capacidad(self.dir_solo, 'reg.config.manage', self.a))   # solo el superusuario

    def test_coordinador_observador_y_visita_ven_toda_la_empresa(self):
        todos = {self.r1.pk, self.r2.pk, self.r3.pk}
        for u in (self.pmo, self.patro, self.visita):
            self.assertEqual(self.ids(u), todos, u.email)

    def test_nunca_se_ve_otra_empresa_ni_siquiera_con_alcance_total(self):
        self.assertNotIn(self.rb.pk, self.ids(self.pmo))
        self.assertEqual(self.ids(self.pmo_b, self.b), {self.rb.pk})
        root = User.objects.create_superuser('root@x.cl', 'x')
        self.assertEqual(self.ids(root), {self.r1.pk, self.r2.pk, self.r3.pk})   # superusuario: la empresa pedida

    def test_los_eliminados_no_se_ven(self):
        self.r1.soft_delete()
        self.assertNotIn(self.r1.pk, self.ids(self.pmo))

    def test_la_persona_de_varias_empresas_no_cruza_contratistas(self):
        """Un Coordinador de C1 en Tekon que es Miembro de «Otra» no hereda alcance allá."""
        agregar_miembro(self.dir1, self.b, rol_por_base(self.b, RolBase.MIEMBRO))
        self.assertEqual(self.ids(self.dir1, self.b), set())

    def test_escritura_exige_permiso_alcance_y_no_estar_concluido(self):
        self.assertTrue(alcance.puede_escribir(self.ito1, self.r1))
        self.assertFalse(alcance.puede_escribir(self.ito1, self.r2))      # fuera de alcance
        self.assertFalse(alcance.puede_escribir(self.visita, self.r1))    # ve pero no escribe
        self.assertFalse(alcance.puede_escribir(self.patro, self.r1))
        self.r1.concluido = True
        self.assertFalse(alcance.puede_escribir(self.ito1, self.r1))      # concluido = solo lectura

    def test_responsables_posibles(self):
        emails = lambda u: sorted(x.email for x in alcance.responsables_posibles(u, self.a))
        self.assertEqual(emails(self.pmo), ['ito1@x.cl', 'ito2@x.cl', 'ito3@x.cl'])
        self.assertEqual(emails(self.dir1), ['ito1@x.cl', 'ito2@x.cl'])    # solo su contratista
        self.assertEqual(emails(self.dir2), ['ito3@x.cl'])

    def test_un_rol_personalizado_puede_ampliar_el_alcance(self):
        rol = RolEmpresa.objects.create(empresa=self.a, nombre='Supervisor', rol_base=RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=rol, capacidad='reg.alcance.todo', habilitado=True)
        u = User.objects.create_user('sup@x.cl', 'x')
        agregar_miembro(u, self.a, rol)
        self.assertEqual(self.ids(u), {self.r1.pk, self.r2.pk, self.r3.pk})


class EstadoTests(BaseRegistros):
    def test_sin_datos_es_rojo_concluido_es_verde(self):
        from reg_txtss.models import RegTxtss
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        self.assertEqual(estado.color_estado(RegTxtss.objects.with_estado().get(pk=r.pk)), 'rojo')
        r.concluido = True
        r.save()
        self.assertEqual(estado.color_estado(RegTxtss.objects.with_estado().get(pk=r.pk)), 'verde')

    def test_las_fuentes_de_datos_de_otras_apps_vuelven_amarillo(self):
        from django.db.models import Exists, OuterRef
        from reg_txtss.models import RegTxtss
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        otra = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        # Fuente de prueba: «tiene datos» si el proyecto es p1 (simula fotos/pasos).
        fuente = lambda modelo: Exists(modelo.objects.filter(pk=OuterRef('pk'), proyecto=self.p1))
        estado.registrar_fuente(fuente)
        self.addCleanup(estado._FUENTES.remove, fuente)
        qs = {x.pk: estado.color_estado(x) for x in RegTxtss.objects.with_estado()}
        self.assertEqual((qs[r.pk], qs[otra.pk]), ('amarillo', 'rojo'))
        RegTxtss.objects.filter(pk=r.pk).update(concluido=True)
        self.assertEqual(estado.color_estado(RegTxtss.objects.with_estado().get(pk=r.pk)), 'verde')   # concluido gana

    def test_dos_fuentes_se_combinan_con_o(self):
        from django.db.models import Exists, OuterRef
        from reg_txtss.models import RegTxtss
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        f1 = lambda m: Exists(m.objects.filter(pk=OuterRef('pk'), proyecto__codigo='NO-EXISTE'))
        f2 = lambda m: Exists(m.objects.filter(pk=OuterRef('pk'), proyecto__codigo='P1'))
        for f in (f1, f2):
            estado.registrar_fuente(f)
            self.addCleanup(estado._FUENTES.remove, f)
        self.assertEqual(estado.color_estado(RegTxtss.objects.with_estado().get(pk=r.pk)), 'amarillo')


class ConfigYModuloTests(BaseRegistros):
    def test_solo_el_superusuario_configura(self):
        for u in (self.pmo, self.dir1, self.ito1, self.visita):
            self.client.force_login(u)
            self.assertEqual(self.client.get('/tekon/registros/config/').status_code, 403, u.email)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get('/tekon/registros/config/').status_code, 200)

    def test_configuracion_titula_por_el_termino_y_muestra_el_tipo_por_defecto(self):
        self.client.force_login(self.root)
        html = self.client.get('/tekon/registros/config/').content.decode()
        self.assertIn('Tipo de Sitio', html)                    # el término de esta empresa
        self.assertNotIn('Tipo con Construcción', html)         # eso no aplica
        self.assertNotIn('Tipo por defecto', html)              # hay tipos definidos (Poste, Torre)
        from proyectos.models import Proyecto
        Proyecto.objects.filter(empresa=self.a).update(tipo=None)
        self.a.tipos_proyecto.all().delete()
        html = self.client.get('/tekon/registros/config/').content.decode()
        self.assertIn('Tipo por defecto', html)
        self.a.termino_proyecto_singular = 'Proyecto'
        self.a.save()
        self.assertIn('Tipo de Proyecto', self.client.get('/tekon/registros/config/').content.decode())

    def test_define_y_elimina_tipos_desde_la_configuracion(self):
        self.client.force_login(self.root)
        r = self.client.post('/tekon/registros/config/', {'accion': 'tipo', 'nombre': 'Rooftop', 'orden': 5})
        self.assertRedirects(r, '/tekon/registros/config/', fetch_redirect_response=False)
        rooftop = TipoProyecto.objects.get(empresa=self.a, nombre='Rooftop')
        self.assertEqual(self.client.post('/tekon/registros/config/', {'accion': 'tipo', 'nombre': 'rooftop'}).status_code, 200)  # repetido
        self.client.post(f'/tekon/registros/config/tipos/{self.torre.pk}/eliminar/')   # tiene proyectos: no se borra
        self.assertTrue(TipoProyecto.objects.filter(pk=self.torre.pk).exists())
        self.client.post(f'/tekon/registros/config/tipos/{rooftop.pk}/eliminar/')
        self.assertFalse(TipoProyecto.objects.filter(pk=rooftop.pk).exists())
        ajeno = TipoProyecto.objects.create(empresa=self.b, nombre='Ajeno')
        self.assertEqual(self.client.post(f'/tekon/registros/config/tipos/{ajeno.pk}/eliminar/').status_code, 404)
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.post(f'/tekon/registros/config/tipos/{self.poste.pk}/eliminar/').status_code, 403)

    def test_modulo_no_habilitado_es_404(self):
        sin = crear_empresa(nombre='Sin', slug='sinreg', modulos=['tar'])
        u = persona('x@sin.cl', sin, RolBase.COORDINADOR)
        self.client.force_login(u)
        for url in ('/sinreg/registros/', '/sinreg/registros/txtss/', '/sinreg/registros/construccion/'):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_inicio_resume_solo_lo_que_ve_cada_rol(self):
        from reg_txtss.models import RegTxtss
        RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito3, concluido=True)
        self.client.force_login(self.ito1)
        tarjetas = {t['nombre']: t for t in self.client.get('/tekon/registros/').context['tarjetas']}
        self.assertEqual((tarjetas['TX/TSS Poste']['reportes'], tarjetas['TX/TSS Poste']['vacios'], tarjetas['TX/TSS Poste']['sitios']), (1, 1, 1))
        self.client.force_login(self.pmo)
        tarjetas = {t['nombre']: t for t in self.client.get('/tekon/registros/').context['tarjetas']}
        poste, torre = tarjetas['TX/TSS Poste'], tarjetas['TX/TSS Torre']   # una tarjeta por tipo de proyecto
        self.assertEqual((poste['reportes'], poste['vacios'], poste['concluidos'], poste['sitios']), (1, 1, 0, 1))
        self.assertEqual((torre['reportes'], torre['vacios'], torre['concluidos'], torre['sitios']), (1, 0, 1, 1))
        self.assertFalse(tarjetas['Construcción']['con_estados'])   # construcción no usa vacío/en proceso/concluido

    def test_menu_del_modulo_segun_capacidades(self):
        nombres = lambda u: [i['nombre'] for i in (self.client.force_login(u) or self.client.get('/tekon/registros/')).context['menu_lateral']]
        for u in (self.pmo, self.ito1):   # Configuración, Pasos y Plantillas son solo del superusuario
            for admin in ('Configuración', 'Tipos de registro', 'Pasos', 'Plantillas'):
                self.assertNotIn(admin, nombres(u), (u.email, admin))
        self.assertEqual(nombres(self.root)[-3:], ['Configuración', 'Pasos', 'Plantillas'])
        self.assertEqual(nombres(self.ito1), ['Resumen', 'TX/TSS Poste', 'TX/TSS Torre', 'Construcción',
                                              'Supervisión Campo', 'Hallazgos'])   # una entrada por tipo de proyecto; solo los tipos activos

    def test_registros_aparece_como_aplicacion_disponible(self):
        self.client.force_login(self.ito1)
        estados = {m['codigo']: m['estado'] for m in self.client.get('/tekon/').context['lanzador_modulos']}
        self.assertEqual(estados['reg'], 'disponible')


class PanelConstruccionTests(BaseRegistros):
    """Panel de Construcción del inicio de Registros (port del dashboard de reg.tekon-rl.cl)."""

    def setUp(self):
        super().setUp()
        from datetime import timedelta
        from django.utils import timezone
        from proyectos.models import ProyectoUbicacion
        from reg_construccion.models import RegConstruccion
        hoy = timezone.localdate()
        ProyectoUbicacion.objects.create(proyecto=self.p1, etiqueta='Mandato', lat='-33.1', lon='-70.1')
        ProyectoUbicacion.objects.create(proyecto=self.p1, etiqueta='Construcción', lat='-33.5', lon='-70.5')
        self.t2.estado = Proyecto.Estado.CONCLUIDO
        self.t2.save()
        # (el avance lo recalcula la tabla de avance al guardar, por eso se fija con update)
        # p1: en obra, última visita hace 20 días al 40 %; t1: en obra, visita reciente al 80 %; t2: concluido.
        RegConstruccion.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1, contratista=self.c1,
                                       fecha=hoy - timedelta(days=20), avance_pct=40)
        RegConstruccion.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito3, contratista=self.c2,
                                       fecha=hoy - timedelta(days=2), avance_pct=80)
        RegConstruccion.objects.create(empresa=self.a, proyecto=self.t2, user=self.ito3, contratista=self.c2,
                                       fecha=hoy - timedelta(days=5), avance_pct=100, concluido=True)
        for proyecto, pct in ((self.p1, 40), (self.t1, 80), (self.t2, 100)):
            RegConstruccion.objects.filter(proyecto=proyecto).update(avance_pct=pct)

    def contexto(self, user):
        self.client.force_login(user)
        return self.client.get('/tekon/registros/').context

    def test_kpis_y_listas_para_quien_ve_todo(self):
        c = self.contexto(self.pmo)
        k = c['kpis']
        self.assertEqual((k['proyectos'], k['en_obra'], k['concluidos']), (3, 2, 1))
        self.assertEqual(k['avance_en_obra'], 60)
        self.assertEqual((k['visitas_30'], k['total_visitas'], k['sin_visita'], k['sin_concluir']), (3, 3, 1, 2))
        self.assertEqual([f['proyecto__codigo'] for f in c['menor_avance']], ['P1', 'T1'])
        self.assertEqual([f['proyecto__codigo'] for f in c['sin_visita_reciente']], ['P1'])
        self.assertEqual({g['codigo']: g['proyectos'] for g in c['contratistas']}, {'C1': 1, 'C2': 2})
        self.assertEqual(sum(e['n'] for e in c['estados']), 3)

    def test_el_alcance_acota_el_panel(self):
        self.assertEqual(self.contexto(self.ito1)['kpis']['proyectos'], 1)     # solo lo suyo
        self.assertEqual(self.contexto(self.dir2)['kpis']['proyectos'], 2)     # solo su contratista
        self.assertEqual(self.contexto(self.dir1)['kpis']['proyectos'], 1)

    def test_mapa_prefiere_la_ubicacion_de_construccion(self):
        puntos = {p['codigo']: p for p in self.contexto(self.pmo)['puntos']}
        self.assertEqual(list(puntos), ['P1'])   # los demás no tienen ubicación
        self.assertEqual((puntos['P1']['lat'], puntos['P1']['lon']), (-33.5, -70.5))
        self.assertIn('Redes SA', puntos['P1']['detalle'])

    def test_otra_empresa_no_ve_datos_ajenos(self):
        self.client.force_login(self.pmo_b)
        c = self.client.get('/otra/registros/').context
        self.assertEqual(c['kpis']['proyectos'], 0)
        self.assertEqual(c['puntos'], [])
        self.assertEqual(c['actividad'], [])

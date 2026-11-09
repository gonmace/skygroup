from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings

from empresas.models import Empresa

from . import capacidades
from .capacidades import requiere_capacidad, tiene_capacidad, usuarios_con_capacidad
from .models import AccesoModulo, Membresia, RolEmpresa, RolPermiso, User, UsuarioPermiso
from .roles import RolBase
from .services import agregar_miembro, crear_empresa, rol_por_base

CACHE_LOCAL = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}


@override_settings(CACHES=CACHE_LOCAL)
class CapacidadesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        capacidades.registrar('tst', {
            'tst.crear': ('Crear tickets', {RolBase.COORDINADOR, RolBase.MIEMBRO}),
            'tst.ver': ('Ver dashboard', {RolBase.COORDINADOR}),
        })
        cls.a = crear_empresa(nombre='Empresa A', slug='emp-a')
        cls.b = crear_empresa(nombre='Empresa B', slug='emp-b')
        cls.user = User.objects.create_user('ana@example.com', 'x')
        cls.membresia = agregar_miembro(cls.user, cls.a, rol_por_base(cls.a, RolBase.MIEMBRO))

    def setUp(self):
        capacidades.invalidar_rol(self.membresia.rol_id)
        self.user = User.objects.get(pk=self.user.pk)  # sin memos

    def test_default_del_rol_base(self):
        self.assertTrue(tiene_capacidad(self.user, 'tst.crear', self.a))
        self.assertFalse(tiene_capacidad(self.user, 'tst.ver', self.a))

    def test_sin_membresia_en_otra_empresa(self):
        self.assertFalse(tiene_capacidad(self.user, 'tst.crear', self.b))

    def test_superusuario_todo(self):
        root = User.objects.create_superuser('root@example.com', 'x')
        self.assertTrue(tiene_capacidad(root, 'tst.ver', self.b))

    def test_rol_empresa_personalizado_hereda_y_ajusta(self):
        from .models import RolEmpresa
        ito = RolEmpresa.objects.create(empresa=self.a, nombre='ITO', rol_base=RolBase.MIEMBRO)
        buscador = RolEmpresa.objects.create(empresa=self.a, nombre='Buscador', rol_base=RolBase.MIEMBRO)
        RolPermiso.objects.create(rol_empresa=buscador, capacidad='tst.crear', habilitado=False)
        RolPermiso.objects.create(rol_empresa=ito, capacidad='tst.ver', habilitado=True)

        m = Membresia.objects.get(pk=self.membresia.pk)
        m.rol = ito
        m.save()
        u = User.objects.get(pk=self.user.pk)
        self.assertTrue(tiene_capacidad(u, 'tst.crear', self.a))
        self.assertTrue(tiene_capacidad(u, 'tst.ver', self.a))

        m.rol = buscador
        m.save()
        u = User.objects.get(pk=self.user.pk)
        self.assertFalse(tiene_capacidad(u, 'tst.crear', self.a))

    def test_excepcion_por_persona_prevalece(self):
        UsuarioPermiso.objects.create(membresia=self.membresia, capacidad='tst.crear', habilitado=False)
        u = User.objects.get(pk=self.user.pk)
        self.assertFalse(tiene_capacidad(u, 'tst.crear', self.a))

    def test_cache_se_invalida_al_editar_la_matriz(self):
        self.assertTrue(tiene_capacidad(self.user, 'tst.crear', self.a))
        RolPermiso.objects.create(rol_empresa=self.membresia.rol, capacidad='tst.crear', habilitado=False)
        u = User.objects.get(pk=self.user.pk)
        self.assertFalse(tiene_capacidad(u, 'tst.crear', self.a))

    def test_acceso_modulo_deshabilitado_y_override(self):
        director = rol_por_base(self.a, RolBase.COORDINADOR)
        AccesoModulo.objects.create(membresia=self.membresia, modulo='tst', rol_override=director)
        u = User.objects.get(pk=self.user.pk)
        self.assertTrue(tiene_capacidad(u, 'tst.ver', self.a))
        AccesoModulo.objects.filter(membresia=self.membresia).update(habilitado=False)
        u = User.objects.get(pk=self.user.pk)
        self.assertFalse(tiene_capacidad(u, 'tst.crear', self.a))

    def test_membresia_inactiva_o_empresa_inactiva(self):
        Membresia.objects.filter(pk=self.membresia.pk).update(activa=False)
        u = User.objects.get(pk=self.user.pk)
        self.assertFalse(tiene_capacidad(u, 'tst.crear', self.a))

    def test_rol_de_otra_empresa_rechazado(self):
        m = Membresia(user=self.user, empresa=self.b, rol=rol_por_base(self.a, RolBase.COORDINADOR))
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            m.full_clean()

    def test_usuarios_con_capacidad(self):
        self.assertIn(self.user, usuarios_con_capacidad(self.a, 'tst.crear'))
        self.assertEqual(usuarios_con_capacidad(self.b, 'tst.crear'), [])

    def test_decorador(self):
        @requiere_capacidad('tst.ver')
        def vista(request):
            return 'ok'

        req = RequestFactory().get('/')
        req.user, req.empresa = self.user, self.a
        with self.assertRaises(PermissionDenied):
            vista(req)

    def test_clave_no_registrada(self):
        with self.assertRaises(KeyError):
            tiene_capacidad(self.user, 'no.existe', self.a)

    def test_email_unico_sin_distinguir_mayusculas(self):
        from django.db import IntegrityError, transaction
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user('ANA@example.com', 'x')

    def test_login_por_email(self):
        from django.contrib.auth import authenticate
        req = RequestFactory().post('/acceso/login/')
        self.assertEqual(authenticate(req, username='ANA@example.com', password='x'), self.user)
        self.assertIsNone(authenticate(req, username='ana@example.com', password='mal'))


class RolesRaciTests(TestCase):
    def test_raci_cubre_todos_los_roles_base(self):
        from .roles import RACI_LETRA
        self.assertEqual(set(RACI_LETRA), set(RolBase))
        self.assertEqual(sorted(RACI_LETRA.values()), ['A', 'C', 'I', 'R'])

    def test_empresa_nueva_siembra_los_cuatro_roles(self):
        e = crear_empresa(nombre='Empresa R', slug='emp-r')
        self.assertEqual(sorted(e.roles.values_list('rol_base', flat=True)), sorted(RolBase.values))

    @override_settings(CACHES=CACHE_LOCAL)
    def test_coordinador_acotado_pierde_las_capacidades_de_empresa(self):
        from empresas.models import Contratista
        e = crear_empresa(nombre='Empresa C', slug='emp-c')
        c = Contratista.objects.create(empresa=e, nombre='Redes SA', codigo='C1')
        jefe = User.objects.create_user('jefe@example.com', 'x')
        agregar_miembro(jefe, e, rol_por_base(e, RolBase.COORDINADOR))
        acotado = User.objects.create_user('acotado@example.com', 'x')
        m = agregar_miembro(acotado, e, rol_por_base(e, RolBase.COORDINADOR), c)
        self.assertTrue(tiene_capacidad(User.objects.get(pk=jefe.pk), 'cuentas.usuarios.manage', e))
        self.assertFalse(tiene_capacidad(User.objects.get(pk=acotado.pk), 'cuentas.usuarios.manage', e))
        self.assertFalse(tiene_capacidad(User.objects.get(pk=acotado.pk), 'proyectos.manage', e))
        self.assertFalse(tiene_capacidad(User.objects.get(pk=acotado.pk), 'jor.reportes.ver', e))
        self.assertFalse(tiene_capacidad(User.objects.get(pk=acotado.pk), 'tar.tickets.view_all', e))
        # Una excepción por persona sí puede devolvérsela.
        UsuarioPermiso.objects.create(membresia=m, capacidad='cuentas.usuarios.manage', habilitado=True)
        self.assertTrue(tiene_capacidad(User.objects.get(pk=acotado.pk), 'cuentas.usuarios.manage', e))

    @override_settings(CACHES=CACHE_LOCAL)
    def test_solo_el_coordinador_se_acota_por_contratista(self):
        from empresas.models import Contratista
        e = crear_empresa(nombre='Empresa D', slug='emp-d')
        c = Contratista.objects.create(empresa=e, nombre='Redes SA', codigo='C1')
        obs = User.objects.create_user('obs@example.com', 'x')
        agregar_miembro(obs, e, rol_por_base(e, RolBase.OBSERVADOR), c)
        # Un Observador con contratista conserva su alcance normal (ve todo en Registros).
        self.assertTrue(tiene_capacidad(User.objects.get(pk=obs.pk), 'reg.alcance.todo', e))


class MigracionRolesRaciTests(TransactionTestCase):
    """0003_roles_raci: fusiona los roles sembrados PMBOK en los 4 roles RACI."""

    def test_fusiona_y_conserva_membresias(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        ex = MigrationExecutor(connection)
        ex.migrate([('cuentas', '0002_membresia_contratista')])
        apps = ex.loader.project_state([('cuentas', '0002_membresia_contratista')]).apps
        Empresa_, RolEmpresa_, User_, Membresia_ = (
            apps.get_model('empresas', 'Empresa'), apps.get_model('cuentas', 'RolEmpresa'),
            apps.get_model('cuentas', 'User'), apps.get_model('cuentas', 'Membresia'))
        emp = Empresa_.objects.create(nombre='Vieja', slug='vieja')
        RolEmpresa_.objects.filter(empresa=emp).delete()
        roles = {}
        for orden, (nombre, base) in enumerate([('PMO', 'PMO'), ('Patrocinador', 'PATROCINADOR'),
                                                ('Director de Proyecto', 'DIRECTOR'), ('Especialista', 'ESPECIALISTA'),
                                                ('Miembro del equipo', 'MIEMBRO'), ('Interesado', 'INTERESADO'),
                                                ('Supervisor', 'DIRECTOR')]):
            roles[nombre] = RolEmpresa_.objects.create(empresa=emp, nombre=nombre, rol_base=base, orden=orden)
        u = User_.objects.create(email='v@x.cl')
        Membresia_.objects.create(user=u, empresa=emp, rol=roles['Director de Proyecto'])

        ex = MigrationExecutor(connection)
        ex.migrate([('cuentas', '0003_roles_raci')])
        estado = ex.loader.project_state([('cuentas', '0003_roles_raci')]).apps   # el modelo real ya tiene columnas posteriores
        nuevo = {r.nombre: r.rol_base for r in estado.get_model('cuentas', 'RolEmpresa').objects.filter(empresa__slug='vieja')}
        self.assertEqual(nuevo, {'Coordinador': 'COORDINADOR', 'Observador': 'OBSERVADOR', 'Especialista': 'ESPECIALISTA',
                                 'Miembro del equipo': 'MIEMBRO', 'Supervisor': 'COORDINADOR'})
        # Membresia real ya trae columnas de migraciones posteriores (p. ej. sede): se lee con el estado de 0003.
        Membresia_0003 = ex.loader.project_state([('cuentas', '0003_roles_raci')]).apps.get_model('cuentas', 'Membresia')
        self.assertEqual(Membresia_0003.objects.get(user__email='v@x.cl').rol.nombre, 'Coordinador')


@override_settings(
    SECURE_SSL_REDIRECT=False, CACHES=CACHE_LOCAL,
    STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
              'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}},
)
class ImpersonacionTests(TestCase):
    """Solo un superusuario real puede ver la app como otro usuario."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        U = get_user_model()
        self.root = U.objects.create_superuser(email='root@x.com', password='x-pass-1234')
        self.otro_root = U.objects.create_superuser(email='root2@x.com', password='x-pass-1234')
        self.normal = U.objects.create_user(email='normal@x.com', password='x-pass-1234')
        self.inactivo = U.objects.create_user(email='off@x.com', password='x-pass-1234', is_active=False)
        self.url = lambda u: f'/acceso/impersonar/{u.pk}/'

    def test_superusuario_impersona_y_deja_de_impersonar(self):
        self.client.force_login(self.root)
        r = self.client.post(self.url(self.normal))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.session['impersonar_id'], self.normal.pk)
        r = self.client.post('/acceso/impersonar/detener/')
        self.assertEqual(r.status_code, 302)
        self.assertNotIn('impersonar_id', self.client.session)

    def test_request_user_es_el_objetivo_mientras_dura(self):
        from django.test import RequestFactory
        from cuentas.impersonacion import ImpersonacionMiddleware
        visto = {}

        def vista(request):
            visto['user'], visto['imp'] = request.user, request.impersonador
            return None
        self.client.force_login(self.root)
        self.client.post(self.url(self.normal))
        rf = RequestFactory().get('/')
        rf.session = self.client.session
        rf.user = self.root
        ImpersonacionMiddleware(vista)(rf)
        self.assertEqual((visto['user'], visto['imp']), (self.normal, self.root))

    def test_usuario_normal_no_puede(self):
        self.client.force_login(self.normal)
        self.assertEqual(self.client.post(self.url(self.otro_root)).status_code, 404)
        self.assertEqual(self.client.post(self.url(self.normal)).status_code, 404)
        self.assertNotIn('impersonar_id', self.client.session)

    def test_el_administrador_de_empresa_no_puede(self):
        """El Coordinador (administrador de la empresa) no es superusuario: no impersona ni ve el botón."""
        from cuentas.roles import RolBase
        from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
        e = crear_empresa(nombre='Tekon', slug='tekon', modulos=['tar'])
        admin = get_user_model().objects.create_user(email='admin@x.com', password='x-pass-1234')
        agregar_miembro(admin, e, rol_por_base(e, RolBase.COORDINADOR))
        agregar_miembro(self.normal, e, rol_por_base(e, RolBase.MIEMBRO))
        self.client.force_login(admin)
        self.assertEqual(self.client.post(self.url(self.normal)).status_code, 404)
        self.assertNotIn('impersonar_id', self.client.session)
        self.assertNotContains(self.client.get('/tekon/config/miembros/'), '/acceso/impersonar/')
        self.client.force_login(self.root)
        self.assertContains(self.client.get('/tekon/config/miembros/'), '/acceso/impersonar/')

    def test_no_se_impersona_superusuario_ni_inactivo(self):
        self.client.force_login(self.root)
        self.assertEqual(self.client.post(self.url(self.otro_root)).status_code, 404)
        self.assertEqual(self.client.post(self.url(self.inactivo)).status_code, 404)

    def test_solo_post_y_requiere_login(self):
        self.assertEqual(self.client.post(self.url(self.normal)).status_code, 302)  # → login
        self.assertNotIn('impersonar_id', self.client.session)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(self.url(self.normal)).status_code, 405)

    def test_sesion_invalida_se_descarta(self):
        self.client.force_login(self.normal)
        s = self.client.session
        s['impersonar_id'] = self.otro_root.pk  # un no-superusuario no puede heredar impersonación
        s.save()
        self.client.post('/acceso/impersonar/detener/')
        self.assertNotIn('impersonar_id', self.client.session)


class InicialesTests(TestCase):
    def test_iniciales_de_nombre_y_apellido(self):
        def u(nombre='', apellido='', correo='x@example.com'):
            return User(first_name=nombre, last_name=apellido, email=correo)
        self.assertEqual(u('Ana María', 'Pérez Soto').iniciales, 'AP')   # primera palabra de cada uno
        self.assertEqual(u('ana', 'pérez').iniciales, 'AP')               # siempre en mayúscula
        self.assertEqual(u('Ana', '').iniciales, 'A')                     # falta el apellido
        self.assertEqual(u('', 'Pérez').iniciales, 'P')                   # falta el nombre
        self.assertEqual(u('', '', 'zeta@example.com').iniciales, 'Z')    # sin nombre: el correo

    def test_la_jerarquia_sigue_el_orden_raci(self):
        j = {rb: RolEmpresa(rol_base=rb).jerarquia for rb in RolBase.values}
        self.assertEqual(sorted(j, key=j.get),
                         [RolBase.COORDINADOR, RolBase.MIEMBRO, RolBase.ESPECIALISTA, RolBase.OBSERVADOR])   # A > R > C > I
        self.assertEqual(sorted(j.values()), [0, 1, 2, 3])

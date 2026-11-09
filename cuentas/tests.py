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


from unittest import mock  # noqa: E402

from .models import NextcloudConfig, NextcloudVinculo  # noqa: E402

STORAGES_TEST = {'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
                 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}}


def uid_nc(user, empresa):
    v = NextcloudVinculo.objects.filter(user=user, empresa=empresa).first()
    return v.uid if v else ''


def vincular_nc(user, empresa, uid):
    NextcloudVinculo.objects.update_or_create(user=user, empresa=empresa, defaults={'uid': uid})


class _NextcloudBase(TestCase):
    """Utilidades del flujo OAuth con Nextcloud simulado."""

    def setUp(self):
        p = mock.patch('cuentas.nextcloud._ips', return_value={'93.184.216.34'})   # DNS público simulado
        p.start()
        self.addCleanup(p.stop)

    def _iniciar(self, ruta):
        r = self.client.get(ruta)
        self.assertEqual(r.status_code, 302)
        return self.client.session['nextcloud_oauth']['state'], r

    def _callback(self, state, uid, email='', grupos=(), nombre='Ana'):
        post = mock.Mock(status_code=200, json=lambda: {'access_token': 't', 'user_id': uid}, raise_for_status=lambda: None)
        get = mock.Mock(status_code=200, json=lambda: {'ocs': {'data': {'email': email, 'displayname': nombre, 'groups': list(grupos)}}})
        with mock.patch('cuentas.nextcloud.requests.post', return_value=post), \
                mock.patch('cuentas.nextcloud.requests.get', return_value=get):
            return self.client.get('/acceso/nextcloud/callback/', {'code': 'c', 'state': state})


@override_settings(CACHES=CACHE_LOCAL, SITE_URL='https://app.example.com', STORAGES=STORAGES_TEST)
class NextcloudLoginTests(_NextcloudBase):
    """Entrar con Nextcloud solo con cuentas YA vinculadas; cada empresa con su propio servidor."""

    @classmethod
    def setUpTestData(cls):
        cls.emp = crear_empresa(nombre='Empresa NC', slug='emp-nc')
        cls.otra = crear_empresa(nombre='Otra', slug='otra-nc')
        cls.user = User.objects.create_user('ana@example.com', 'x')
        agregar_miembro(cls.user, cls.emp, rol_por_base(cls.emp, RolBase.MIEMBRO))
        cls.cfg = NextcloudConfig.objects.create(
            empresa=cls.emp, activo=True, servidor_url='https://nc.example.com/', client_id='cid', client_secret='sec')

    def _iniciar(self, ruta='/emp-nc/acceso/nextcloud/'):
        return super()._iniciar(ruta)

    def _cb(self, state, uid='ana', email='ana@example.com'):
        return self._callback(state, uid, email)

    def test_boton_segun_empresa(self):
        self.assertContains(self.client.get('/emp-nc/acceso/login/'), 'Entrar con Nextcloud')
        self.assertNotContains(self.client.get('/acceso/login/'), 'Entrar con Nextcloud')     # la raíz no tiene config propia
        self.assertNotContains(self.client.get('/otra-nc/acceso/login/'), 'Entrar con Nextcloud')
        NextcloudConfig.objects.update(activo=False)
        self.assertNotContains(self.client.get('/emp-nc/acceso/login/'), 'Entrar con Nextcloud')

    def test_iniciar_deshabilitado_404(self):
        self.assertEqual(self.client.get('/otra-nc/acceso/nextcloud/').status_code, 404)

    def test_iniciar_redirige_con_state(self):
        state, r = self._iniciar()
        self.assertTrue(r['Location'].startswith('https://nc.example.com/apps/oauth2/authorize?'))
        self.assertIn(f'state={state}', r['Location'])
        self.assertIn('redirect_uri=https%3A%2F%2Fapp.example.com%2Facceso%2Fnextcloud%2Fcallback%2F', r['Location'])

    def test_el_correo_de_nextcloud_no_inicia_sesion_ni_vincula(self):
        state, _ = self._iniciar()
        r = self._cb(state)                              # mismo correo que ana@example.com, pero uid sin vincular
        self.assertRedirects(r, '/emp-nc/acceso/login/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(uid_nc(self.user, self.emp), '')

    def test_login_por_uid_ya_vinculado(self):
        vincular_nc(self.user, self.emp, 'ana')
        state, _ = self._iniciar()
        self._cb(state, email='')
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_state_invalido(self):
        self._iniciar()
        r = self._cb('otro')
        self.assertRedirects(r, '/emp-nc/acceso/login/', fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_por_defecto_no_se_crean_cuentas(self):
        self.assertFalse(NextcloudConfig.de(self.emp).crear_cuentas)
        state, _ = self._iniciar()
        n = User.objects.count()
        self._cb(state, uid='nadie@example.com', email='nadie@example.com')
        self.assertEqual(User.objects.count(), n)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_cuenta_dada_de_alta_por_un_admin_se_vincula_sola_al_primer_ingreso(self):
        """Usuarios nuevos del futuro: el admin los da de alta y el primer ingreso con Nextcloud los enlaza (no crea nada)."""
        nuevo = User.objects.create_user('luis@example.com', 'x')
        agregar_miembro(nuevo, self.emp, rol_por_base(self.emp, RolBase.MIEMBRO))
        n = User.objects.count()
        state, _ = self._iniciar()
        r = self._cb(state, uid='luis@example.com', email='')
        self.assertRedirects(r, '/emp-nc/', fetch_redirect_response=False)
        self.assertEqual(uid_nc(nuevo, self.emp), 'luis@example.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), nuevo.pk)
        self.assertEqual(User.objects.count(), n)

    def test_cuenta_compartida_con_otra_empresa_no_se_enlaza_sola(self):
        """Un Nextcloud de UNA empresa no puede declarar suya una cuenta que también es de otra (toma de cuenta)."""
        comp = User.objects.create_user('comp@example.com', 'x')
        agregar_miembro(comp, self.emp, rol_por_base(self.emp, RolBase.MIEMBRO))
        agregar_miembro(comp, self.otra, rol_por_base(self.otra, RolBase.MIEMBRO))
        state, _ = self._iniciar()
        self._cb(state, uid='comp@example.com', email='')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(uid_nc(comp, self.emp), '')

    def test_no_se_enlaza_sin_membresia_ni_con_uid_sin_forma_de_correo_ni_privilegiados(self):
        sin = User.objects.create_user('sin@example.com', 'x')                         # existe pero no es de esta empresa
        agregar_miembro(sin, self.otra, rol_por_base(self.otra, RolBase.MIEMBRO))
        su = User.objects.create_superuser('boss@example.com', 'x')
        agregar_miembro(su, self.emp, rol_por_base(self.emp, RolBase.COORDINADOR))
        for uid in ('sin@example.com', 'ana', 'boss@example.com'):
            state, _ = self._iniciar()
            self._cb(state, uid=uid, email='')
            self.assertNotIn('_auth_user_id', self.client.session)
        self.assertFalse(NextcloudVinculo.objects.exists())

    def test_cuenta_inactiva_o_eliminada_rechazada(self):
        vincular_nc(self.user, self.emp, 'ana')
        for campos in ({'is_active': False}, {'is_deleted': True}):
            User.objects.filter(pk=self.user.pk).update(**campos)
            state, _ = self._iniciar()
            self._cb(state)
            self.assertNotIn('_auth_user_id', self.client.session)
            User.objects.filter(pk=self.user.pk).update(is_active=True, is_deleted=False)

    def test_privilegiados_nunca_entran_por_nextcloud_ni_con_vinculo_fijado_a_mano(self):
        """El admin del Nextcloud de una empresa no debe poder abrir sesión como staff/superusuario de la plataforma."""
        su = User.objects.create_superuser('jefe@example.com', 'x')
        state, _ = self._iniciar()
        self._cb(state, uid='intruso', email='jefe@example.com')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(uid_nc(su, self.emp), '')
        vincular_nc(su, self.emp, 'jefe')                # aunque un admin lo haya fijado a mano
        state, _ = self._iniciar()
        self._cb(state, uid='jefe', email='')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_el_mismo_uid_en_otra_empresa_es_otra_persona(self):
        """Cada empresa tiene su propio servidor: un uid vinculado en una no entra en la otra."""
        NextcloudConfig.objects.create(empresa=self.otra, activo=True, servidor_url='https://otro.example.com',
                                       client_id='c2', client_secret='s2')
        vincular_nc(self.user, self.emp, 'ana')
        otro = User.objects.create_user('ana2@example.com', 'x')
        agregar_miembro(otro, self.otra, rol_por_base(self.otra, RolBase.MIEMBRO))
        state, _ = self._iniciar('/otra-nc/acceso/nextcloud/')
        self._cb(state)
        self.assertNotIn('_auth_user_id', self.client.session)
        vincular_nc(otro, self.otra, 'ana')
        state, _ = self._iniciar('/otra-nc/acceso/nextcloud/')
        self._cb(state)
        self.assertEqual(int(self.client.session['_auth_user_id']), otro.pk)

    # ── Vincular desde la sesión iniciada ──
    def _vincular(self, uid='ana'):
        r = self.client.post('/emp-nc/acceso/nextcloud/vincular/')
        self.assertEqual(r.status_code, 302)
        return self._cb(self.client.session['nextcloud_oauth']['state'], uid=uid)

    def test_vincular_exige_sesion_y_post(self):
        r = self.client.post('/emp-nc/acceso/nextcloud/vincular/')
        self.assertEqual(r.status_code, 302)
        self.assertIn('login', r['Location'])
        self.assertNotIn('nextcloud_oauth', self.client.session)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get('/emp-nc/acceso/nextcloud/vincular/').status_code, 405)

    def test_vincular_guarda_el_uid_y_luego_se_entra_con_el_(self):
        self.client.force_login(self.user)
        r = self._vincular('ana')
        self.assertRedirects(r, '/emp-nc/', fetch_redirect_response=False)
        self.assertEqual(uid_nc(self.user, self.emp), 'ana')
        self.client.logout()
        state, _ = self._iniciar()
        self._cb(state)
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.pk)

    def test_no_se_puede_vincular_un_uid_de_otro_usuario(self):
        otro = User.objects.create_user('otro@example.com', 'x')
        vincular_nc(otro, self.emp, 'ana')
        self.client.force_login(self.user)
        self._vincular('ana')
        self.assertEqual(uid_nc(self.user, self.emp), '')

    def test_vincular_falla_si_la_sesion_cambia_a_mitad(self):
        self.client.force_login(self.user)
        self.client.post('/emp-nc/acceso/nextcloud/vincular/')
        state = self.client.session['nextcloud_oauth']['state']
        otro = User.objects.create_user('otro2@example.com', 'x')
        self.client.force_login(otro)
        self._cb(state)
        self.assertEqual(uid_nc(otro, self.emp), '')

    def test_desvincular(self):
        vincular_nc(self.user, self.emp, 'ana')
        self.client.force_login(self.user)
        self.client.post('/emp-nc/acceso/nextcloud/desvincular/')
        self.assertEqual(uid_nc(self.user, self.emp), '')

    def test_el_menu_ofrece_vincular_o_desvincular(self):
        self.client.force_login(self.user)
        self.assertContains(self.client.get('/emp-nc/'), 'Vincular Nextcloud')
        vincular_nc(self.user, self.emp, 'ana')
        self.assertContains(self.client.get('/emp-nc/'), 'Desvincular Nextcloud')

    def test_next_externo_se_ignora(self):
        self.client.get('/emp-nc/acceso/nextcloud/?next=https://evil.com/')
        self.assertEqual(self.client.session['nextcloud_oauth']['next'], '')


@override_settings(CACHES=CACHE_LOCAL, STORAGES=STORAGES_TEST)
class NextcloudPanelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.emp = crear_empresa(nombre='Empresa Panel NC', slug='emp-pnc')
        cls.otra = crear_empresa(nombre='Otra Panel', slug='otra-pnc')

    def setUp(self):
        p = mock.patch('cuentas.nextcloud._ips', return_value={'93.184.216.34'})
        p.start()
        self.addCleanup(p.stop)

    def test_solo_el_superusuario_y_cada_empresa_tiene_la_suya(self):
        admin = User.objects.create_user('n@example.com', 'x')
        agregar_miembro(admin, self.emp, rol_por_base(self.emp, RolBase.COORDINADOR))   # ni el admin de la empresa
        self.client.force_login(admin)
        self.assertEqual(self.client.get('/emp-pnc/config/nextcloud/').status_code, 403)
        su = User.objects.create_superuser('su@example.com', 'x')
        self.client.force_login(su)
        datos = {'activo': 'on', 'servidor_url': 'https://nc.example.com', 'client_id': 'a', 'client_secret': 's1',
                 'texto_boton': 'Entrar con Nextcloud'}
        self.assertEqual(self.client.post('/emp-pnc/config/nextcloud/', datos).status_code, 302)
        datos['client_secret'] = ''
        self.assertEqual(self.client.post('/emp-pnc/config/nextcloud/', datos).status_code, 302)
        self.assertEqual(NextcloudConfig.de(self.emp).client_secret, 's1')
        self.assertFalse(NextcloudConfig.de(self.emp).crear_cuentas)            # apagado salvo que se active
        self.assertFalse(NextcloudConfig.objects.filter(empresa=self.otra).exists())


    def test_rechaza_servidores_internos_o_sin_https(self):
        su = User.objects.create_superuser('su2@example.com', 'x')
        self.client.force_login(su)
        base = {'activo': 'on', 'client_id': 'a', 'client_secret': 's', 'texto_boton': 'Entrar con Nextcloud'}
        for url in ('http://nc.example.com', 'https://user:pw@nc.example.com', 'ftp://nc.example.com'):
            r = self.client.post('/emp-pnc/config/nextcloud/', {**base, 'servidor_url': url})
            self.assertEqual(r.status_code, 200, url)
        with mock.patch('cuentas.nextcloud._ips', return_value={'169.254.169.254'}):
            self.assertEqual(self.client.post('/emp-pnc/config/nextcloud/', {**base, 'servidor_url': 'https://meta.example.com'}).status_code, 200)
        with mock.patch('cuentas.nextcloud._ips', return_value={'10.0.0.5'}):
            self.assertEqual(self.client.post('/emp-pnc/config/nextcloud/', {**base, 'servidor_url': 'https://interno.example.com'}).status_code, 200)
        self.assertFalse(NextcloudConfig.objects.filter(empresa=self.emp).exists())


@override_settings(CACHES=CACHE_LOCAL, SITE_URL='https://app.example.com', STORAGES=STORAGES_TEST)
class NextcloudAltaAutomaticaTests(_NextcloudBase):
    """Opción APAGADA por defecto: solo con `crear_cuentas` activado se crean cuentas (dominio permitido + grupo admin)."""

    @classmethod
    def setUpTestData(cls):
        from .models import DominioPermitido
        cls.emp = crear_empresa(nombre='Empresa Alta', slug='emp-alta')
        cls.otra = crear_empresa(nombre='Otra Alta', slug='otra-alta')
        cls.cfg = NextcloudConfig.objects.create(
            empresa=cls.emp, activo=True, crear_cuentas=True, servidor_url='https://nc.example.com',
            client_id='cid', client_secret='sec')
        DominioPermitido.objects.create(empresa=cls.emp, dominio='nuevo.com', rol=rol_por_base(cls.emp, RolBase.MIEMBRO))

    def _entrar(self, uid, email='', grupos=(), nombre='Luis Mamani'):
        self.client.get('/emp-alta/acceso/nextcloud/')
        state = self.client.session['nextcloud_oauth']['state']
        return self._callback(state, uid, email, grupos, nombre)

    def test_crea_cuenta_con_el_cargo_del_dominio(self):
        r = self._entrar('luis@nuevo.com')
        self.assertRedirects(r, '/emp-alta/', fetch_redirect_response=False)
        u = User.objects.get(email='luis@nuevo.com')
        self.assertEqual((uid_nc(u, self.emp), u.first_name, u.last_name), ('luis@nuevo.com', 'Luis', 'Mamani'))
        self.assertFalse(u.has_usable_password())
        self.assertEqual(int(self.client.session['_auth_user_id']), u.pk)
        self.assertEqual(list(Membresia.objects.filter(user=u).values_list('empresa__slug', 'rol__rol_base')),
                         [('emp-alta', RolBase.MIEMBRO)])

    def test_el_grupo_administrador_entra_como_coordinador(self):
        NextcloudConfig.objects.update(grupo_admin='Executives')       # opt-in: por defecto está vacío
        self._entrar('jefe@nuevo.com', grupos=['skylog', 'Executives'])
        bases = set(Membresia.objects.filter(user__email='jefe@nuevo.com').values_list('rol__rol_base', flat=True))
        self.assertEqual(bases, {RolBase.COORDINADOR})

    def test_grupo_administrador_vacio_por_defecto(self):
        self.assertEqual(NextcloudConfig.objects.get(empresa=self.emp).grupo_admin, '')
        self._entrar('jefe@nuevo.com', grupos=['skylog', 'Executives'])
        bases = set(Membresia.objects.filter(user__email='jefe@nuevo.com').values_list('rol__rol_base', flat=True))
        self.assertEqual(bases, {RolBase.MIEMBRO})

    def test_no_crea_cuenta_con_el_correo_del_perfil_si_el_uid_no_es_un_correo(self):
        """El correo del perfil lo edita cada persona sin verificarlo: no puede decidir cuenta ni cargo."""
        self._entrar('luis', email='luis@nuevo.com')
        self.assertFalse(User.objects.filter(email='luis@nuevo.com').exists())
        self.assertFalse(NextcloudVinculo.objects.filter(empresa=self.emp, uid='luis').exists())
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_cuenta_con_privilegios_vinculada_no_entra_por_nextcloud(self):
        su = User.objects.create_superuser('root@nuevo.com', 'x')
        agregar_miembro(su, self.emp, rol_por_base(self.emp, RolBase.MIEMBRO))
        NextcloudVinculo.objects.create(empresa=self.emp, user=su, uid='root@nuevo.com')
        self._entrar('root@nuevo.com')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_sin_membresia_activa_no_se_inicia_sesion(self):
        u = User.objects.create_user('baja@nuevo.com', 'x')
        m = agregar_miembro(u, self.emp, rol_por_base(self.emp, RolBase.MIEMBRO))
        NextcloudVinculo.objects.create(empresa=self.emp, user=u, uid='baja@nuevo.com')
        Membresia.objects.filter(user=u, empresa=self.emp).update(activa=False)
        self._entrar('baja@nuevo.com')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_dominio_sin_regla_o_publico_no_crea(self):
        n = User.objects.count()
        for uid in ('x@desconocido.com', 'x@gmail.com'):
            self._entrar(uid)
            self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(User.objects.count(), n)

    def test_dominio_de_otra_empresa_no_alcanza(self):
        from .models import DominioPermitido
        DominioPermitido.objects.create(empresa=self.otra, dominio='solootra.com', rol=rol_por_base(self.otra, RolBase.MIEMBRO))
        self._entrar('x@solootra.com')
        self.assertFalse(User.objects.filter(email='x@solootra.com').exists())

    def test_apagado_no_crea(self):
        NextcloudConfig.objects.update(crear_cuentas=False)
        self._entrar('luis@nuevo.com')
        self.assertFalse(User.objects.filter(email='luis@nuevo.com').exists())

    def test_cuenta_existente_solo_se_vincula_si_el_uid_es_su_correo(self):
        u = User.objects.create_user('ana@nuevo.com', 'x')
        self._entrar('ana', email='ana@nuevo.com')              # uid sin forma de correo: no se toma la cuenta
        self.assertEqual(uid_nc(u, self.emp), '')
        self.assertNotIn('_auth_user_id', self.client.session)
        self._entrar('ana@nuevo.com')
        self.assertEqual(uid_nc(u, self.emp), 'ana@nuevo.com')
        self.assertEqual(int(self.client.session['_auth_user_id']), u.pk)

    def test_cuenta_con_acceso_a_otra_empresa_no_se_vincula_sola_en_el_alta(self):
        comp = User.objects.create_user('comp@nuevo.com', 'x')
        agregar_miembro(comp, self.otra, rol_por_base(self.otra, RolBase.MIEMBRO))
        self._entrar('comp@nuevo.com')
        self.assertEqual(uid_nc(comp, self.emp), '')
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_nunca_duplica_una_cuenta_existente_en_ningun_caso(self):
        """Aunque la creación automática esté ACTIVA: con una cuenta ya existente (activa, inactiva, eliminada, con otro
        uid o con el correo en otras mayúsculas) jamás se crea un usuario nuevo."""
        existentes = {
            'activa@nuevo.com': {}, 'inactiva@nuevo.com': {'is_active': False}, 'borrada@nuevo.com': {'is_deleted': True},
            'Mayus@nuevo.com': {},
        }
        for email, campos in existentes.items():
            u = User.objects.create_user(email, 'x')
            User.objects.filter(pk=u.pk).update(**campos)
        n = User.objects.count()
        intentos = [('activa', 'activa@nuevo.com'), ('inactiva@nuevo.com', ''), ('borrada@nuevo.com', ''),
                    ('mayus@NUEVO.com', ''), ('otro-uid', 'activa@nuevo.com'), ('activa@nuevo.com', '')]
        for uid, email in intentos:
            self._entrar(uid, email=email)
            self.assertEqual(User.objects.count(), n, (uid, email))
            self.assertEqual(User.objects.filter(email__iexact=email or uid).count(), 1, (uid, email))

    def test_cuenta_privilegiada_nunca_se_vincula_sola(self):
        su = User.objects.create_superuser('root@nuevo.com', 'x')
        self._entrar('root@nuevo.com')
        self.assertEqual(uid_nc(su, self.emp), '')
        self.assertNotIn('_auth_user_id', self.client.session)


class VincularNextcloudComandoTests(TestCase):
    def test_simula_y_aplica_sin_crear_cuentas_ni_tocar_privilegiados(self):
        from io import StringIO

        from django.core.management import call_command
        emp = crear_empresa(nombre='Empresa Cmd', slug='emp-cmd')
        ana = User.objects.create_user('ana@x.com', 'x')
        agregar_miembro(ana, emp, rol_por_base(emp, RolBase.MIEMBRO))
        jefe = User.objects.create_superuser('jefe@x.com', 'x')
        agregar_miembro(jefe, emp, rol_por_base(emp, RolBase.COORDINADOR))
        n = User.objects.count()
        call_command('vincular_nextcloud', 'emp-cmd', stdout=StringIO())            # simulación
        self.assertFalse(NextcloudVinculo.objects.exists())
        call_command('vincular_nextcloud', 'emp-cmd', '--aplicar', stdout=StringIO())
        self.assertEqual(uid_nc(ana, emp), 'ana@x.com')
        self.assertEqual(uid_nc(jefe, emp), '')                                     # privilegiada: se omite
        self.assertEqual(User.objects.count(), n)


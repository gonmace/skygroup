"""Alta de usuarios: correos, registro por dominio, bloqueos y eliminación."""
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from cuentas import registro as reg
from cuentas.models import CorreoBloqueado, DominioPermitido, Membresia, User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from panel.tests import AJUSTES
from tar_tickets.models import Ticket


@override_settings(**AJUSTES)
class AltaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', modulos=['tar'])
        cls.coord = User.objects.create_user('coord@tekon.com', 'x')
        agregar_miembro(cls.coord, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.root = User.objects.create_superuser('root@example.com', 'x')
        cls.rol_obs = rol_por_base(cls.a, RolBase.OBSERVADOR)
        DominioPermitido.objects.create(empresa=cls.a, dominio='tekon.com', rol=cls.rol_obs)

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    # ── Correo al agregar ──
    def test_invitacion_a_cuenta_nueva_y_aviso_a_existente(self):
        self.client.force_login(self.coord)
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post('/tekon/config/miembros/nuevo/', {'email': 'n@x.com', 'rol': rol.pk, 'enviar_correo': 'on'})
        self.assertIn('/tekon/acceso/recuperar/', mail.outbox[0].body)
        User.objects.create_user('viejo@x.com', 'x')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post('/tekon/config/miembros/nuevo/', {'email': 'viejo@x.com', 'rol': rol.pk, 'enviar_correo': 'on'})
        self.assertEqual(len(mail.outbox), 2)
        self.assertNotIn('recuperar', mail.outbox[1].body)

    def test_sin_marcar_enviar_no_hay_correo(self):
        self.client.force_login(self.coord)
        rol = rol_por_base(self.a, RolBase.MIEMBRO)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post('/tekon/config/miembros/nuevo/', {'email': 'n@x.com', 'rol': rol.pk})
        self.assertEqual(len(mail.outbox), 0)

    def test_reinvitar_solo_sin_contrasena(self):
        u = User.objects.create(email='p@x.com')
        u.set_unusable_password()
        u.save()
        m = agregar_miembro(u, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        self.client.force_login(self.coord)
        self.client.post(f'/tekon/config/miembros/{m.pk}/reinvitar/')
        self.assertEqual(len(mail.outbox), 1)

    # ── Dominios ──
    def test_dominio_no_admite_coordinador_ni_publicos(self):
        coord = rol_por_base(self.a, RolBase.COORDINADOR)
        with self.assertRaises(ValidationError):
            DominioPermitido(empresa=self.a, dominio='otra.com', rol=coord).full_clean()
        with self.assertRaises(ValidationError):
            DominioPermitido(empresa=self.a, dominio='Gmail.com', rol=self.rol_obs).full_clean()

    def test_registro_envia_enlace_solo_si_permitido(self):
        CorreoBloqueado.objects.create(empresa=self.a, email='mala@tekon.com')
        for email in ('ana@tekon.com', 'mala@tekon.com', 'x@otro.com'):
            r = self.client.post('/tekon/acceso/registro/', {'email': email})
            self.assertContains(r, 'Revisa tu correo')  # misma respuesta siempre
        self.assertEqual([m.to for m in mail.outbox], [['ana@tekon.com']])

    def test_registro_cerrado_sin_dominios(self):
        DominioPermitido.objects.all().delete()
        self.assertEqual(self.client.get('/tekon/acceso/registro/').status_code, 404)

    def test_confirmar_crea_cuenta_con_cargo_del_dominio_y_entra(self):
        token = reg.token_registro('ana@tekon.com', self.a)
        r = self.client.post(f'/tekon/acceso/registro/{token}/', {
            'first_name': 'Ana', 'last_name': 'P', 'new_password1': 'Clave-Segura-93x', 'new_password2': 'Clave-Segura-93x'})
        self.assertEqual(r.status_code, 302)
        m = Membresia.objects.get(user__email='ana@tekon.com', empresa=self.a)
        self.assertEqual(m.rol, self.rol_obs)
        self.assertIn('_auth_user_id', self.client.session)

    def test_confirmar_rechaza_token_vencido_otra_empresa_o_correo_bloqueado(self):
        b = crear_empresa(nombre='Embol', slug='embol')
        token = reg.token_registro('ana@tekon.com', self.a)
        self.assertEqual(self.client.get(f'/embol/acceso/registro/{token}/').status_code, 404)  # sin dominios en B
        DominioPermitido.objects.create(empresa=b, dominio='tekon.com', rol=rol_por_base(b, RolBase.OBSERVADOR))
        self.assertEqual(self.client.get(f'/embol/acceso/registro/{token}/').status_code, 400)
        with mock.patch('cuentas.registro.TOKEN_VIDA', -1):
            self.assertEqual(self.client.get(f'/tekon/acceso/registro/{token}/').status_code, 400)
        CorreoBloqueado.objects.create(empresa=self.a, email='ana@tekon.com')
        self.assertEqual(self.client.get(f'/tekon/acceso/registro/{token}/').status_code, 400)
        self.assertFalse(User.objects.filter(email='ana@tekon.com').exists())

    def test_cuenta_bloqueada_no_puede_registrarse_ni_entrar(self):
        u = User.objects.create_user('b@tekon.com', 'clave-123x', is_active=False)
        self.assertIsNone(reg.dominio_permitido(self.a, u.email))
        self.client.post('/tekon/acceso/login/', {'username': 'b@tekon.com', 'password': 'clave-123x'})
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_registro_limita_intentos(self):
        for _ in range(5):
            self.client.post('/tekon/acceso/registro/', {'email': 'x@otro.com'})
        self.assertEqual(self.client.post('/tekon/acceso/registro/', {'email': 'x@otro.com'}).status_code, 429)

    # ── Panel ──
    def test_coordinador_gestiona_dominios_y_correos(self):
        self.client.force_login(self.coord)
        self.client.post('/tekon/config/acceso/', {'dominio': '@Nuevo.com', 'rol': self.rol_obs.pk})
        self.assertTrue(DominioPermitido.objects.filter(empresa=self.a, dominio='nuevo.com').exists())
        self.client.post('/tekon/config/acceso/', {'email': 'Mal@x.com', 'motivo': 'spam'})
        self.assertTrue(CorreoBloqueado.objects.filter(empresa=self.a, email='mal@x.com').exists())
        coord = rol_por_base(self.a, RolBase.COORDINADOR)
        self.client.post('/tekon/config/acceso/', {'dominio': 'otra.com', 'rol': coord.pk})
        self.assertFalse(DominioPermitido.objects.filter(dominio='otra.com').exists())

    def test_miembro_sin_capacidad_no_ve_acceso(self):
        u = User.objects.create_user('m@tekon.com', 'x')
        agregar_miembro(u, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        self.client.force_login(u)
        self.assertEqual(self.client.get('/tekon/config/acceso/').status_code, 403)

    # ── Bloqueo y eliminación (solo superusuario) ──
    def _miembro(self, email='v@tekon.com'):
        u = User.objects.create_user(email, 'x')
        return u, agregar_miembro(u, self.a, rol_por_base(self.a, RolBase.MIEMBRO))

    def test_eliminar_es_logico_solo_superusuario_y_se_restaura(self):
        u, m = self._miembro()
        t = Ticket.objects.create(empresa=self.a, titulo='T', solicitante='s', creador=u)
        self.client.force_login(self.coord)
        self.assertEqual(self.client.post(f'/tekon/config/miembros/{m.pk}/eliminar/').status_code, 403)
        u.refresh_from_db()
        self.assertFalse(u.is_deleted)
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(f'/tekon/config/miembros/{m.pk}/eliminar/').status_code, 200)
        self.client.post(f'/tekon/config/miembros/{m.pk}/eliminar/')
        u.refresh_from_db(); m.refresh_from_db(); t.refresh_from_db()
        self.assertTrue(u.is_deleted)
        self.assertFalse(u.is_active)
        self.assertFalse(m.activa)
        self.assertEqual(t.creador, u)   # el historial se conserva
        r = self.client.get('/tekon/config/miembros/')
        self.assertEqual([x.pk for x in r.context['eliminados']], [m.pk])
        self.assertNotIn(m, r.context['lista'])
        self.client.force_login(self.coord)
        self.assertEqual(self.client.post(f'/tekon/config/miembros/{m.pk}/restaurar/').status_code, 403)
        self.client.force_login(self.root)
        self.client.post(f'/tekon/config/miembros/{m.pk}/restaurar/')
        u.refresh_from_db(); m.refresh_from_db()
        self.assertFalse(u.is_deleted)
        self.assertTrue(u.is_active and m.activa)

    def test_no_se_elimina_a_otro_superusuario(self):
        otro = User.objects.create_superuser('r2@example.com', 'x')
        m = agregar_miembro(otro, self.a, rol_por_base(self.a, RolBase.MIEMBRO))
        self.client.force_login(self.root)
        self.client.post(f'/tekon/config/miembros/{m.pk}/eliminar/')
        otro.refresh_from_db()
        self.assertFalse(otro.is_deleted)

    def test_bloqueo_global_solo_superusuario_y_corta_el_acceso(self):
        u, m = self._miembro()
        self.client.force_login(self.coord)
        self.assertEqual(self.client.post(f'/tekon/config/miembros/{m.pk}/bloquear/').status_code, 403)
        self.client.force_login(self.root)
        self.client.post(f'/tekon/config/miembros/{m.pk}/bloquear/')
        u.refresh_from_db()
        self.assertFalse(u.is_active)
        self.client.post(f'/tekon/config/miembros/{m.pk}/bloquear/')
        u.refresh_from_db()
        self.assertTrue(u.is_active)

    def test_ayuda_raci_en_pantalla_de_usuarios(self):
        self.client.force_login(self.coord)
        self.assertContains(self.client.get('/tekon/config/miembros/'), '¿Qué es RACI?')

"""La migración 0003 traslada los avisos de la antigua bandeja a mensajes directos."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class MigracionChatTests(TransactionTestCase):
    migrar_desde = [('mje_mensajes', '0002_traer_de_jor_mensajes')]
    migrar_hasta = [('mje_mensajes', '0003_chat')]

    def migrar(self, destino):
        ex = MigrationExecutor(connection)
        ex.migrate(destino)
        return ex.loader.project_state(destino).apps

    def tearDown(self):
        # Deja la base de pruebas en la última migración para los demás tests.
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())

    def test_avisos_pasan_a_directos_y_los_de_skybot_se_descartan(self):
        viejo = self.migrar(self.migrar_desde)
        Empresa, Rol, User = viejo.get_model('empresas', 'Empresa'), viejo.get_model('cuentas', 'RolEmpresa'), viejo.get_model('cuentas', 'User')
        Membresia, Mensaje = viejo.get_model('cuentas', 'Membresia'), viejo.get_model('mje_mensajes', 'Mensaje')
        e = Empresa.objects.create(nombre='E', slug='emp-mig')
        rol = Rol.objects.create(empresa=e, nombre='R', rol_base='MIEMBRO')
        ana, beto = (User.objects.create(email=f'{n}@x.cl', password='x') for n in ('ana', 'beto'))
        m_ana, m_beto = (Membresia.objects.create(user=u, empresa=e, rol=rol) for u in (ana, beto))
        from django.utils import timezone
        pendiente = Mensaje.objects.create(empresa=e, destinatario=m_beto, remitente=ana, cuerpo='pendiente')
        leido = Mensaje.objects.create(empresa=e, destinatario=m_beto, remitente=ana, cuerpo='leído', confirmado=timezone.now())
        Mensaje.objects.create(empresa=e, destinatario=m_beto, remitente=None, cuerpo='aviso de skyBot')
        Mensaje.objects.create(empresa=e, destinatario=m_ana, remitente=ana, cuerpo='a mí mismo')

        nuevo = self.migrar(self.migrar_hasta)
        Mensaje, Conv, Part = (nuevo.get_model('mje_mensajes', n) for n in ('Mensaje', 'Conversacion', 'Participacion'))
        self.assertEqual(sorted(Mensaje.objects.values_list('texto', flat=True)), ['leído', 'pendiente'])
        conv = Conv.objects.get()
        self.assertEqual((conv.tipo, conv.directo_a_id, conv.directo_b_id), ('directo', *sorted((ana.pk, beto.pk))))
        # Lo que beto no había confirmado sigue sin leer; ana (la remitente) lo tiene todo leído.
        beto_p, ana_p = Part.objects.get(user_id=beto.pk), Part.objects.get(user_id=ana.pk)
        self.assertEqual(beto_p.ultimo_leido, pendiente.pk - 1)
        self.assertEqual(ana_p.ultimo_leido, max(pendiente.pk, leido.pk))


class MigracionModuloTests(TransactionTestCase):
    """0003 de empresas activa `msj` en las empresas existentes; 0004 de mensajes renombra la capacidad."""

    def migrar(self, destino):
        ex = MigrationExecutor(connection)
        ex.migrate(destino)
        return ex.loader.project_state(destino).apps

    def tearDown(self):
        ex = MigrationExecutor(connection)
        ex.migrate(ex.loader.graph.leaf_nodes())

    def test_empresas_existentes_reciben_el_modulo_y_la_capacidad_se_renombra(self):
        viejo = self.migrar([('empresas', '0002_contratista'), ('mje_mensajes', '0003_chat')])
        Empresa, Rol, RolPermiso = (viejo.get_model('empresas', 'Empresa'), viejo.get_model('cuentas', 'RolEmpresa'),
                                    viejo.get_model('cuentas', 'RolPermiso'))
        e = Empresa.objects.create(nombre='E', slug='emp-mod', modulos=['reg', 'jor'])
        rol = Rol.objects.create(empresa=e, nombre='R', rol_base='COORDINADOR')
        RolPermiso.objects.create(rol_empresa=rol, capacidad='mensajes.ver_todos_proyectos', habilitado=False)

        nuevo = self.migrar([('empresas', '0003_modulo_mensajeria'), ('mje_mensajes', '0004_capacidades_msj')])
        self.assertEqual(nuevo.get_model('empresas', 'Empresa').objects.get(slug='emp-mod').modulos, ['reg', 'jor', 'msj'])
        self.assertEqual(list(nuevo.get_model('cuentas', 'RolPermiso').objects.values_list('capacidad', flat=True)),
                         ['msj.ver_todos_proyectos'])

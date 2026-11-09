import json

from django.test import TestCase, override_settings
from django.utils import timezone

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
from jor_diario.models import Jornada, ReporteDiario
from jor_empleados.models import Perfil

from .models import ItemActividad

H = {'HTTP_X_INTERNAL_TOKEN': 'secreto'}
AJUSTES = dict(
    SECURE_SSL_REDIRECT=False, INTERNAL_API_TOKEN='secreto',
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


@override_settings(**AJUSTES)
class ApiInternaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.e = crear_empresa(nombre='Tekon', slug='tekon', modulos=['jor'])
        cls.otra = crear_empresa(nombre='Otra', slug='otra', modulos=['jor'])
        u = User.objects.create_user('a@x.cl', 'x')
        m = agregar_miembro(u, cls.e, rol_por_base(cls.e, RolBase.MIEMBRO))
        perfil = Perfil.de(m)
        j = Jornada.objects.create(empresa=cls.e, perfil=perfil, inicio=timezone.now(),
                                   estado=Jornada.Estado.COMPLETADA)
        r = ReporteDiario.objects.create(jornada=j, realizado='x', planificado='')
        cls.item = ItemActividad.objects.create(empresa=cls.e, reporte=r, tipo='hecho', texto='Algo raro')
        cls.manual = ItemActividad.objects.create(empresa=cls.e, reporte=r, tipo='hecho', posicion=1,
                                                  texto='Manual', manual=True)

    def post(self, url, datos, **h):
        return self.client.post(url, json.dumps(datos), content_type='application/json', **h)

    def test_sin_token_o_incorrecto(self):
        url = '/api/jor/interno/cerrar-vencidas/'
        self.assertEqual(self.post(url, {}).status_code, 401)
        self.assertEqual(self.post(url, {}, HTTP_X_INTERNAL_TOKEN='mal').status_code, 401)

    @override_settings(INTERNAL_API_TOKEN='')
    def test_deshabilitado_sin_token_configurado(self):
        self.assertEqual(self.post('/api/jor/interno/cerrar-vencidas/', {}, **H).status_code, 404)

    def test_cerrar_vencidas(self):
        r = self.post('/api/jor/interno/cerrar-vencidas/', {'empresa': 'tekon'}, **H)
        self.assertEqual(r.json(), {'ok': True, 'cerradas': 0})
        self.assertEqual(self.post('/api/jor/interno/cerrar-vencidas/', {'empresa': 'no'}, **H).status_code, 404)

    def test_pendientes_y_clasificar(self):
        r = self.client.get('/api/jor/interno/actividades/pendientes/?empresa=tekon', **H).json()
        self.assertEqual([i['id'] for i in r['items']], [self.item.pk])
        self.assertIn('riesgos', [c['codigo'] for c in r['categorias']])
        r = self.post('/api/jor/interno/actividades/clasificar/', {'empresa': 'tekon', 'asignaciones': [
            {'id': self.item.pk, 'categoria': 'riesgos'}, {'id': self.manual.pk, 'categoria': 'riesgos'},
            {'id': self.item.pk, 'categoria': 'inventada'}]}, **H).json()
        self.assertEqual((r['actualizados'], r['omitidos']), (1, 2))
        self.item.refresh_from_db()
        self.assertEqual((self.item.categoria, self.item.fuente), ('riesgos', 'llm'))
        self.manual.refresh_from_db()
        self.assertEqual(self.manual.categoria, 'otros')

    def test_clasificar_no_cruza_empresas(self):
        r = self.post('/api/jor/interno/actividades/clasificar/', {'empresa': 'otra', 'asignaciones': [
            {'id': self.item.pk, 'categoria': 'riesgos'}]}, **H).json()
        self.assertEqual(r['actualizados'], 0)

"""Importador de reg.tekon-rl.cl: conversión plana → anidada, renombrado de pasos e idempotencia."""
import json
import os
import tempfile
from io import BytesIO

from django.test import SimpleTestCase, TestCase, override_settings
from PIL import Image

from cuentas.services import crear_empresa
from reg_actividades.models import DatoPaso, Paso, PasoAsignado, Plantilla
from reg_construccion.models import RegConstruccion
from reg_fotos.models import Foto
from reg_txtss.models import RegTxtss

from .importar import Importador, anidar, opcional_de_etapa
from .tests import AJUSTES


class OpcionalDeEtapaTests(SimpleTestCase):
    def test_libro_de_obras_y_paso_electrico_son_opcionales_en_construccion(self):
        self.assertTrue(opcional_de_etapa('construccion', 'obra_objetivos', 'camera_libro_widget', {})['opcional'])
        self.assertTrue(opcional_de_etapa('construccion', 'obra_objetivos', 'camera_widget', {'etapa': 'obra_libro'})['opcional'])
        self.assertTrue(opcional_de_etapa('construccion', 'obra_electrico', 'camera_widget', {'foto_min': 2})['opcional'])

    def test_el_resto_no_cambia(self):
        cfg = {'label': 'Actividades'}
        self.assertEqual(opcional_de_etapa('construccion', 'obra_objetivos', 'lista_widget', cfg), cfg)
        self.assertNotIn('opcional', opcional_de_etapa('txtss', 'obra_electrico', 'camera_libro_widget', {}))

    def test_no_modifica_el_original(self):
        cfg = {}
        opcional_de_etapa('construccion', 'obra_electrico', 'camera_widget', cfg)
        self.assertEqual(cfg, {})


class AnidarTests(SimpleTestCase):
    def test_reparte_claves_por_widget(self):
        widgets = [('ubicacion_widget', {}),
                   ('form_dinamico_widget', {'campos': 'dimensiones|text|Dimensiones\nluz|toggle|Luz'}),
                   ('comentario_widget', {})]
        anidado, huerfanas = anidar({'lat': '-33.4', 'lon': '-70.6', 'dimensiones': '10x20', 'luz': 'on',
                                     'comentario': 'ok', 'raro': 1}, widgets)
        self.assertEqual(anidado['ubicacion_widget'], {'lat': -33.4, 'lon': -70.6})
        self.assertEqual(anidado['form_dinamico_widget'], {'dimensiones': '10x20', 'luz': True})
        self.assertEqual(anidado['comentario_widget'], {'comentario': 'ok'})
        self.assertEqual(huerfanas, ['raro'])

    def test_partidas_como_texto_json(self):
        anidado, _ = anidar({'plantilla': 'T', 'partidas': '[{"id":1,"actual":10}]'}, [('tabla_avance_widget', {})])
        self.assertEqual(anidado['tabla_avance_widget']['partidas'], [{'id': 1, 'actual': 10}])


def _jsonl(carpeta, nombre, filas):
    with open(os.path.join(carpeta, f'{nombre}.jsonl'), 'w', encoding='utf-8') as f:
        for fila in filas:
            f.write(json.dumps(fila) + '\n')


def _jpg():
    b = BytesIO()
    Image.new('RGB', (40, 30), 'red').save(b, 'JPEG')
    return b.getvalue()


@override_settings(**AJUSTES)
class ImportarTests(TestCase):
    def setUp(self):
        self.empresa = crear_empresa(nombre='PTI', slug='pti', modulos=['reg'])
        # El importador se prueba sobre una empresa sin la plantilla estándar que reciben las empresas nuevas.
        Plantilla.objects.filter(empresa=self.empresa).delete()
        Paso.objects.filter(empresa=self.empresa).delete()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = os.path.join(self.tmp.name, 'jsonl')
        self.media = os.path.join(self.tmp.name, 'media')
        os.makedirs(self.dir)
        os.makedirs(os.path.join(self.media, 'photos'))
        with open(os.path.join(self.media, 'photos', 'a.jpg'), 'wb') as f:
            f.write(_jpg())
        _jsonl(self.dir, 'django_content_type', [{'id': 7, 'app_label': 'reg_txtss', 'model': 'regtxtss'}])
        _jsonl(self.dir, 'core_contractor', [{'id': 1, 'name': 'Redes', 'code': 'rd', 'is_active': True}])
        _jsonl(self.dir, 'users_user', [
            {'id': 1, 'email': 'Ito@x.cl', 'username': 'ito', 'user_type': 'ITO', 'contractor_id': 1, 'password': 'pbkdf2_sha256$1$a$b',
             'first_name': 'Ito', 'last_name': 'Uno', 'is_active': True, 'report_access': []},
            {'id': 2, 'email': '', 'username': 'sin', 'user_type': 'VISITA', 'contractor_id': None, 'is_active': True,
             'report_access': ['construccion']}])
        _jsonl(self.dir, 'core_site', [
            {'id': 5, 'name': 'Poste Uno', 'pti_cell_id': 'P-1', 'operator_id': 'O1', 'tipo_sitio': 'POSTE', 'region': 'RM',
             'comuna': 'Lo', 'lat_man': -33.1, 'lon_man': -70.1, 'lat_ing': None, 'lon_ing': None, 'lat_con': None, 'lon_con': None},
            {'id': 6, 'name': 'Torre Uno', 'pti_cell_id': 'T-1', 'tipo_sitio': 'TORRE', 'lat_con': -34.5, 'lon_con': -71.5}])
        _jsonl(self.dir, 'actividades_tipoactividad', [
            {'id': 1, 'app_namespace': 'reg_txtss_postes', 'nombre': 'TX/TSS Poste', 'tipo_sitio': 'POSTE', 'activo': True},
            {'id': 2, 'app_namespace': 'reg_txtss_torres', 'nombre': 'TX/TSS Torre', 'tipo_sitio': 'TORRE', 'activo': True}])
        _jsonl(self.dir, 'actividades_pasodefinicion', [
            {'id': 1, 'nombre': 'sitio', 'titulo': 'Sitio'}, {'id': 2, 'nombre': 'sitio', 'titulo': 'Sitio'}])
        _jsonl(self.dir, 'actividades_pasowidget', [
            {'id': 1, 'pasodef_id': 1, 'widget_slug': 'ubicacion_widget', 'orden': 0, 'config': {}},
            {'id': 2, 'pasodef_id': 2, 'widget_slug': 'ubicacion_widget', 'orden': 0, 'config': {'label': 'Torre'}},
            {'id': 3, 'pasodef_id': 2, 'widget_slug': 'widget_inexistente', 'orden': 1, 'config': {}}])
        _jsonl(self.dir, 'actividades_configpaso', [
            {'id': 1, 'tipo_id': 1, 'pasodef_id': 1, 'orden': 0}, {'id': 2, 'tipo_id': 2, 'pasodef_id': 2, 'orden': 0}])
        _jsonl(self.dir, 'reg_txtss_regtxtss', [
            {'id': 10, 'sitio_id': 5, 'user_id': 1, 'fecha': '2026-10-01', 'alternativa': 'A', 'concluido': False,
             'is_active': True, 'created_at': '2026-10-01T10:00:00+00:00'}])
        _jsonl(self.dir, 'reg_construccion_regconstruccion', [])
        _jsonl(self.dir, 'actividades_datopaso', [
            {'id': 1, 'content_type_id': 7, 'object_id': 10, 'paso_nombre': 'sitio', 'datos': {'lat': '-33.2', 'lon': '-70.2'}}])
        _jsonl(self.dir, 'photos_photos', [
            {'id': 1, 'content_type_id': 7, 'object_id': 10, 'etapa': 'sitio', 'imagen': 'photos/a.jpg', 'descripcion': 'x', 'orden': 1}])
        _jsonl(self.dir, 'core_googlemapsimage', [])

    def correr(self):
        return Importador(self.empresa, self.dir, media=self.media).ejecutar()

    def test_importa_todo(self):
        n, omitidos, avisos = self.correr()
        self.assertEqual(RegTxtss.objects.filter(empresa=self.empresa).count(), 1)
        reg = RegTxtss.objects.get()
        self.assertEqual(reg.proyecto.codigo, 'P-1')
        self.assertEqual(reg.user.email, 'ito@x.cl')
        self.assertEqual(reg.created_at.year, 2026)
        self.assertEqual(reg.user.membresias.get().contratista.codigo, 'RD')
        self.assertEqual(reg.user.membresias.get().rol.nombre, 'ITO')
        self.assertTrue(any('widget_inexistente' in a for a in avisos))
        self.assertTrue(any('reg.legacy' in a for a in avisos))
        # «sitio» tiene dos definiciones distintas: la segunda lleva sufijo de su tipo
        self.assertEqual(sorted(Paso.objects.values_list('nombre', flat=True)), ['sitio', 'sitio-torre'])
        self.assertEqual(Plantilla.objects.filter(empresa=self.empresa).count(), 2)
        self.assertEqual(PasoAsignado.objects.count(), 2)
        from . import tipos
        self.assertEqual({t.clave for t in tipos.habilitados(type(self.empresa).objects.get(pk=self.empresa.pk))},
                         {'construccion-base', 'txtss', 'construccion'})   # los datos importados quedan visibles
        dato = DatoPaso.objects.get()
        self.assertEqual(dato.paso_nombre, 'sitio')
        self.assertEqual(dato.datos, {'ubicacion_widget': {'lat': -33.2, 'lon': -70.2}})
        self.assertTrue(dato.tiene_datos)
        foto = Foto.objects.get()
        self.assertEqual(foto.etapa, 'sitio')
        self.assertTrue(foto.miniatura)
        self.addCleanup(foto.imagen.delete, save=False)
        self.addCleanup(foto.miniatura.delete, save=False)

    def test_ubicaciones_del_proyecto(self):
        self.correr()
        from proyectos.models import Proyecto
        torre = Proyecto.objects.get(codigo='T-1')
        self.assertEqual(list(torre.ubicaciones.values_list('etiqueta', flat=True)), ['Construcción'])
        self.assertEqual(Proyecto.objects.get(codigo='P-1').tipo.nombre, 'Poste')

    def test_idempotente(self):
        self.correr()
        for f in Foto.objects.all():
            self.addCleanup(f.imagen.delete, save=False)
            self.addCleanup(f.miniatura.delete, save=False)
        antes = (RegTxtss.objects.count(), DatoPaso.objects.count(), Foto.objects.count(), Paso.objects.count(),
                 Plantilla.objects.count(), PasoAsignado.objects.count())
        n, omitidos, avisos = self.correr()
        despues = (RegTxtss.objects.count(), DatoPaso.objects.count(), Foto.objects.count(), Paso.objects.count(),
                   Plantilla.objects.count(), PasoAsignado.objects.count())
        self.assertEqual(antes, despues)
        self.assertEqual(sum(n.values()), 0)
        self.assertEqual(RegConstruccion.objects.count(), 0)


class LimpiarTests(TestCase):
    def test_limpiar_no_borra_proyectos_que_usan_otros_modulos(self):
        from django.utils import timezone

        from cuentas.models import User
        from cuentas.roles import RolBase
        from cuentas.services import agregar_miembro, rol_por_base
        from jor_diario.models import Jornada
        from jor_empleados.models import Perfil
        from proyectos.models import Proyecto
        e = crear_empresa(nombre='PTL', slug='ptl', modulos=['reg', 'jor'])
        ejemplo = Proyecto.objects.create(empresa=e, nombre='Ejemplo', codigo='E1')
        usado = Proyecto.objects.create(empresa=e, nombre='De jornadas', codigo='J1')
        u = User.objects.create_user('j@x.cl', 'x')
        m = agregar_miembro(u, e, rol_por_base(e, RolBase.MIEMBRO))
        Jornada.objects.create(empresa=e, perfil=Perfil.de(m), inicio=timezone.now(), proyecto=usado)
        with tempfile.TemporaryDirectory() as tmp:
            Importador(e, tmp, media=None).limpiar()
        self.assertFalse(Proyecto.objects.filter(pk=ejemplo.pk).exists())
        self.assertTrue(Proyecto.objects.filter(pk=usado.pk).exists())


@override_settings(**AJUSTES)
class ImportarConstruccionTests(TestCase):
    def test_avance_acumulado_entre_visitas(self):
        empresa = crear_empresa(nombre='PTI', slug='pti', modulos=['reg'])
        with tempfile.TemporaryDirectory() as tmp:
            _jsonl(tmp, 'django_content_type', [{'id': 9, 'app_label': 'reg_construccion', 'model': 'regconstruccion'}])
            _jsonl(tmp, 'core_contractor', [])
            _jsonl(tmp, 'users_user', [{'id': 1, 'email': 'a@x.cl', 'username': 'a', 'user_type': 'ITO', 'is_active': True}])
            _jsonl(tmp, 'core_site', [{'id': 6, 'name': 'Torre', 'pti_cell_id': 'T-1', 'tipo_sitio': 'TORRE'}])
            _jsonl(tmp, 'actividades_tipoactividad', [
                {'id': 3, 'app_namespace': 'reg_construccion_torres', 'nombre': 'Construcción', 'tipo_sitio': 'TORRE', 'activo': True}])
            _jsonl(tmp, 'actividades_pasodefinicion', [{'id': 9, 'nombre': 'obra_avance', 'titulo': 'Avance'}])
            _jsonl(tmp, 'actividades_pasowidget', [{'id': 9, 'pasodef_id': 9, 'widget_slug': 'tabla_avance_widget', 'orden': 0, 'config': {
                'plantillas': [{'nombre': 'T', 'partidas': [{'nombre': 'a', 'incidencia': 60}, {'nombre': 'b', 'incidencia': 40}]}]}}])
            _jsonl(tmp, 'actividades_configpaso', [{'id': 9, 'tipo_id': 3, 'pasodef_id': 9, 'orden': 0}])
            _jsonl(tmp, 'reg_txtss_regtxtss', [])
            _jsonl(tmp, 'reg_construccion_regconstruccion', [
                {'id': 1, 'sitio_id': 6, 'user_id': 1, 'fecha': '2026-09-01', 'proyecto': 'Obra', 'estado_obra': 'construccion'},
                {'id': 2, 'sitio_id': 6, 'user_id': 1, 'fecha': '2026-10-01', 'proyecto': 'Obra', 'estado_obra': 'construccion'}])
            _jsonl(tmp, 'actividades_datopaso', [
                {'id': 1, 'content_type_id': 9, 'object_id': 1, 'paso_nombre': 'obra_avance',
                 'datos': {'plantilla': 'T', 'partidas': [{'id': 1, 'nombre': 'a', 'incidencia': 60, 'actual': 50},
                                                          {'id': 2, 'nombre': 'b', 'incidencia': 40, 'actual': 0}]}},
                {'id': 2, 'content_type_id': 9, 'object_id': 2, 'paso_nombre': 'obra_avance',
                 'datos': {'plantilla': 'T', 'partidas': [{'id': 1, 'nombre': 'a', 'incidencia': 60, 'actual': 50},
                                                          {'id': 2, 'nombre': 'b', 'incidencia': 40, 'actual': 50}]}}])
            _jsonl(tmp, 'photos_photos', [])
            _jsonl(tmp, 'core_googlemapsimage', [])
            Importador(empresa, tmp, media=None).ejecutar()
        v1, v2 = RegConstruccion.objects.order_by('fecha')
        self.assertEqual(float(v1.avance_pct), 30.0)      # 60 % × 50 %
        self.assertEqual(float(v2.avance_pct), 80.0)      # a 100 % (60) + b 50 % (20)

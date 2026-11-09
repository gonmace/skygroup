from django.http import QueryDict
from django.test import SimpleTestCase

from . import widgets
from .widgets.base import Contexto


class PosteWidgetTests(SimpleTestCase):
    def setUp(self):
        self.w = widgets.obtener('poste_form_widget')

    def post(self, **kw):
        q = QueryDict(mutable=True)
        for k, v in kw.items():
            q[self.w.nombre_campo(k)] = v
        return q

    def test_registrado_y_con_plantilla(self):
        self.assertIsNotNone(self.w)
        self.assertEqual(self.w.plantilla, 'reg_actividades/widgets/poste.html')

    def test_obligatorios(self):
        datos, errores = self.w.leer(self.post(), {}, {})
        self.assertEqual(len(errores), 3)
        self.assertTrue(all('obligatorio' in e for e in errores))

    def test_guarda_las_claves_del_original(self):
        datos, errores = self.w.leer(
            self.post(tipo_estructura=' Poste HA ', altura='13 m', tension='Baja', luminaria='on', placa_poste='P-1'), {}, {})
        self.assertEqual(errores, [])
        self.assertEqual(set(datos), {
            'tipo_estructura', 'altura', 'tension', 'placa_poste', 'obstaculos', 'empresa_energia', 'comentario',
            'luminaria', 'red_protegida', 'acceso_camion_grua', 'vegetacion', 'antena_microondas'})
        self.assertEqual(datos['tipo_estructura'], 'Poste HA')
        self.assertIs(datos['luminaria'], True)
        self.assertIs(datos['vegetacion'], False)   # un toggle desmarcado se guarda como «No»

    def test_nivel(self):
        n = lambda d: self.w.nivel(d, {}, None)
        self.assertEqual(n({}), 1)
        self.assertEqual(n({'tipo_estructura': 'x'}), 2)
        todos = {c: 'x' for c in ('tipo_estructura', 'altura', 'tension', 'placa_poste', 'obstaculos', 'empresa_energia', 'comentario')}
        self.assertEqual(n(todos), 3)

    def test_valores_por_defecto_solo_sin_datos_guardados(self):
        cfg = {'default_tipo_estructura': 'Poste HA', 'default_altura': '13 m', 'default_acceso_camion_grua': '1'}
        vacio = self.w.contexto({}, cfg, None)
        self.assertEqual(vacio['textos']['tipo_estructura']['valor'], 'Poste HA')
        self.assertTrue(next(t for t in vacio['toggles'] if t['campo'].endswith('acceso_camion_grua'))['marcado'])
        guardado = self.w.contexto({'tipo_estructura': '', 'acceso_camion_grua': False}, cfg, None)
        self.assertEqual(guardado['textos']['tipo_estructura']['valor'], '')   # lo borrado no se repone
        self.assertFalse(next(t for t in guardado['toggles'] if t['campo'].endswith('acceso_camion_grua'))['marcado'])

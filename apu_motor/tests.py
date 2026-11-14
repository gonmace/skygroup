"""Tests del motor: puro Python, sin base de datos (`python manage.py test apu_motor`)."""
import copy
import unittest
from decimal import Decimal as D

from apu_motor import PerfilInvalido, calcular, validar_perfil
from apu_motor.plantillas import BOLIVIA_ESTANDAR


class BoliviaTests(unittest.TestCase):
    def setUp(self):
        self.perfil = validar_perfil(BOLIVIA_ESTANDAR)

    def test_cascada_completa(self):
        # MAT 100, MO 50, EQ 20 calculado a mano (el plan: A…K de la tabla de Bolivia).
        r = calcular(self.perfil, {'MAT': 100, 'MO': 50, 'EQ': 20})
        self.assertEqual(r.lineas['BS'], D('27.5'))
        self.assertEqual(r.lineas['IVA_MO'], D('11.5785'))
        self.assertEqual(r.lineas['TOT_MO'], D('89.0785'))
        self.assertEqual(r.lineas['HERR'], D('4.453925'))
        self.assertEqual(r.lineas['TOT_EQ'], D('24.453925'))
        self.assertEqual(r.lineas['DIRECTO'], D('213.532425'))
        self.assertEqual(r.lineas['GG'], D('21.3532425'))
        self.assertEqual(r.lineas['UT'], D('23.48856675'))
        self.assertEqual(r.lineas['IT'], D('7.983763838325'))
        self.assertEqual(r.total, D('266.36'))

    def test_sin_grupos_da_cero(self):
        self.assertEqual(calcular(self.perfil, {}).total, D('0.00'))

    def test_acepta_strings_y_floats_sin_deriva(self):
        a = calcular(self.perfil, {'MAT': '0.1', 'MO': '0.2', 'EQ': 0})
        b = calcular(self.perfil, {'MAT': 0.1, 'MO': 0.2, 'EQ': 0})
        self.assertEqual(a.total, b.total)

    def test_no_modifica_el_perfil_original(self):
        original = copy.deepcopy(BOLIVIA_ESTANDAR)
        validar_perfil(BOLIVIA_ESTANDAR)
        self.assertEqual(BOLIVIA_ESTANDAR, original)


class OtrosModosTests(unittest.TestCase):
    def test_sobre_precio(self):
        p = validar_perfil({'lineas': [
            {'cod': 'MAT', 'tipo': 'suma', 'grupo': 'MAT'},
            {'cod': 'CA', 'tipo': 'porcentaje', 'pct': 0.2, 'modo': 'sobre_precio', 'base': ['MAT']},
            {'cod': 'PU', 'tipo': 'subtotal', 'base': ['MAT', 'CA'], 'total': True}]})
        self.assertEqual(calcular(p, {'MAT': 80}).total, D('100.00'))  # 80 / (1 - 0.2)

    def test_factor_sobre_la_suma(self):
        p = validar_perfil({'lineas': [
            {'cod': 'MO', 'tipo': 'suma', 'grupo': 'MO', 'factor': 1.5, 'total': True}]})
        self.assertEqual(calcular(p, {'MO': 10}).total, D('15.00'))

    def test_redondeo_por_linea(self):
        datos = {'redondeo': {'linea': 2, 'total': 2}, 'lineas': [
            {'cod': 'MAT', 'tipo': 'suma', 'grupo': 'MAT'},
            {'cod': 'A', 'tipo': 'porcentaje', 'pct': 0.333, 'base': ['MAT']},
            {'cod': 'B', 'tipo': 'porcentaje', 'pct': 0.333, 'base': ['MAT']},
            {'cod': 'PU', 'tipo': 'subtotal', 'base': ['MAT', 'A', 'B'], 'total': True}]}
        con = calcular(validar_perfil(datos), {'MAT': 1.01})   # cada recargo 0.33633 → 0.34
        self.assertEqual(con.lineas['A'], D('0.34'))
        self.assertEqual(con.total, D('1.69'))
        datos['redondeo']['linea'] = None
        sin = calcular(validar_perfil(datos), {'MAT': 1.01})   # 1.01 + 0.67266 = 1.68266 → 1.68
        self.assertEqual(sin.total, D('1.68'))

    def test_half_up_vs_half_even(self):
        base = {'lineas': [{'cod': 'MAT', 'tipo': 'suma', 'grupo': 'MAT', 'total': True}]}
        self.assertEqual(calcular(validar_perfil(base), {'MAT': '0.125'}).total, D('0.13'))
        base['redondeo'] = {'modo': 'HALF_EVEN'}
        self.assertEqual(calcular(validar_perfil(base), {'MAT': '0.125'}).total, D('0.12'))


class NivelPresupuestoTests(unittest.TestCase):
    """Estilo Chile/Perú: la hora ya incluye leyes sociales; GG, utilidad e IVA van al final del presupuesto."""
    PERFIL = {'moneda': 'CLP', 'redondeo': {'total': 0}, 'lineas': [
        {'cod': 'MAT', 'tipo': 'suma', 'grupo': 'MAT'},
        {'cod': 'MO', 'tipo': 'suma', 'grupo': 'MO'},
        {'cod': 'EQ', 'tipo': 'suma', 'grupo': 'EQ'},
        {'cod': 'DIRECTO', 'tipo': 'subtotal', 'base': ['MAT', 'MO', 'EQ'], 'total': True},
        {'cod': 'GG', 'tipo': 'porcentaje', 'pct': 0.12, 'base': ['DIRECTO'], 'nivel': 'presupuesto'},
        {'cod': 'UT', 'tipo': 'porcentaje', 'pct': 0.10, 'base': ['DIRECTO'], 'nivel': 'presupuesto'},
        {'cod': 'NETO', 'tipo': 'subtotal', 'base': ['DIRECTO', 'GG', 'UT'], 'nivel': 'presupuesto'},
        {'cod': 'IVA', 'tipo': 'porcentaje', 'pct': 0.19, 'base': ['NETO'], 'nivel': 'presupuesto'},
        {'cod': 'TOTAL', 'tipo': 'subtotal', 'base': ['NETO', 'IVA'], 'nivel': 'presupuesto', 'total': True}]}

    def setUp(self):
        self.perfil = validar_perfil(self.PERFIL)

    def test_apu_se_queda_en_costo_directo(self):
        r = calcular(self.perfil, {'MAT': 1000, 'MO': 500, 'EQ': 100})
        self.assertEqual(r.total, D('1600'))
        self.assertNotIn('IVA', r.lineas)

    def test_presupuesto_aplica_recargos_una_vez_sobre_el_agregado(self):
        r = calcular(self.perfil, {'MAT': 10000, 'MO': 5000, 'EQ': 1000}, nivel='presupuesto')
        self.assertEqual(r.lineas['DIRECTO'], D('16000'))
        self.assertEqual(r.lineas['NETO'], D('19520'))   # 16000 × 1.22
        self.assertEqual(r.total, D('23229'))            # 19520 × 1.19 = 23228.8


class ValidacionTests(unittest.TestCase):
    def linea(self, **kw):
        return {'cod': 'X', 'tipo': 'suma', 'grupo': 'MAT', 'total': True, **kw}

    def assertInvalido(self, datos, fragmento):
        with self.assertRaisesRegex(PerfilInvalido, fragmento):
            validar_perfil(datos)

    def test_sin_lineas(self):
        self.assertInvalido({'lineas': []}, 'al menos una línea')

    def test_codigo_repetido(self):
        self.assertInvalido({'lineas': [self.linea(), self.linea()]}, 'repetido')

    def test_base_posterior_o_inexistente(self):
        self.assertInvalido({'lineas': [
            {'cod': 'A', 'tipo': 'subtotal', 'base': ['B']}, self.linea(cod='B')]}, 'no existe o no está antes')

    def test_sin_total(self):
        self.assertInvalido({'lineas': [self.linea(total=False)]}, 'precio unitario')

    def test_dos_totales_del_mismo_nivel(self):
        self.assertInvalido({'lineas': [self.linea(), self.linea(cod='Y')]}, 'más de una línea total')

    def test_grupo_invalido(self):
        self.assertInvalido({'lineas': [self.linea(grupo='ZZ')]}, 'grupo inválido')

    def test_porcentaje_como_entero_porcentual(self):
        self.assertInvalido({'lineas': [
            self.linea(), {'cod': 'P', 'tipo': 'porcentaje', 'pct': 55, 'base': ['X']}]}, 'fuera de rango')

    def test_sobre_precio_exige_menos_de_uno(self):
        self.assertInvalido({'lineas': [
            self.linea(), {'cod': 'P', 'tipo': 'porcentaje', 'pct': 1, 'modo': 'sobre_precio', 'base': ['X']}]},
            'fuera de rango')

    def test_apu_despues_de_presupuesto(self):
        self.assertInvalido({'lineas': [
            self.linea(), {'cod': 'P', 'tipo': 'subtotal', 'base': ['X'], 'nivel': 'presupuesto'},
            {'cod': 'Q', 'tipo': 'subtotal', 'base': ['X']}]}, 'van antes')

    def test_pct_no_numerico(self):
        self.assertInvalido({'lineas': [
            self.linea(), {'cod': 'P', 'tipo': 'porcentaje', 'pct': 'abc', 'base': ['X']}]}, 'no es un número')

    def test_calcular_exige_perfil_validado(self):
        with self.assertRaises(PerfilInvalido):
            calcular(BOLIVIA_ESTANDAR, {})

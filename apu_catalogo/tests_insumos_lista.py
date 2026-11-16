"""Página de Insumos: pestañas por tipo con contadores, filtro «Sin precio», buscador y estados vacíos."""
from datetime import date
from decimal import Decimal as D

from apu_catalogo.models import Insumo, PrecioInsumo, Tipo
from apu_generador.tests import Base


class ListaInsumosTests(Base):
    URL = '/tekon/apu/insumos/'

    def setUp(self):
        super().setUp()
        self.cemento = self.insumo('MAT-001', 'Cemento', unidad='kg', precio='1.5000')
        self.arena = self.insumo('MAT-002', 'Arena fina', unidad='m3')                      # sin precio
        self.albanil = self.insumo('MO-001', 'Albañil', Tipo.MANO_OBRA, 'h', precio='20')
        self.mezcladora = self.insumo('EQ-001', 'Mezcladora', Tipo.EQUIPO, 'h')            # sin precio
        self.ajeno = self.insumo('MAT-009', 'Del otro', empresa=self.b)

    def get(self, params='', usuario=None):
        self.client.force_login(usuario or self.su)
        return self.client.get(self.URL + params)

    def test_pestañas_por_tipo_con_contadores_solo_de_la_empresa(self):
        r = self.get()
        self.assertEqual(r.context['tipos_conteo'], [('MAT', 'Material', 2), ('MO', 'Mano de obra', 1), ('EQ', 'Equipo', 1)])
        self.assertEqual((r.context['n_total'], r.context['n_sin_precio']), (4, 2))
        self.assertNotContains(r, 'Del otro')
        html = r.content.decode()
        for ruta in ('?tipo=MAT', '?tipo=MO', '?tipo=EQ', '?sin_precio=1'):
            self.assertIn(f'href="{ruta}"', html)

    def test_filtro_por_tipo(self):
        r = self.get('?tipo=MO')
        self.assertEqual([i.codigo for g in r.context['grupos'] for i in g['insumos']], ['MO-001'])
        self.assertEqual(r.context['n_total'], 4)                                            # los contadores no dependen del filtro

    def test_filtro_sin_precio_solo_muestra_los_que_no_tienen_ninguno(self):
        PrecioInsumo.objects.create(insumo=self.arena, region='Tarija', fecha=date(2026, 1, 1), precio=D('9'), moneda='BOB')
        r = self.get('?sin_precio=1')
        self.assertEqual([i.codigo for g in r.context['grupos'] for i in g['insumos']], ['EQ-001'])   # Arena ya tiene (regional)
        self.assertContains(r, 'aria-pressed="true"')
        self.assertContains(r, 'name="sin_precio" value="1"')                                 # el buscador conserva el filtro

    def test_los_filtros_se_combinan_y_se_conservan_en_los_enlaces(self):
        r = self.get('?tipo=MAT&q=are&sin_precio=1')
        self.assertEqual([i.codigo for g in r.context['grupos'] for i in g['insumos']], ['MAT-002'])
        html = r.content.decode()
        self.assertIn('href="?tipo=MO&q=are&sin_precio=1"', html)
        self.assertIn('Limpiar filtros', html)

    def test_estado_vacio_con_filtros_y_sin_insumos(self):
        r = self.get('?q=zzzz')
        self.assertContains(r, 'No hay insumos con esos filtros')
        Insumo.objects.filter(empresa=self.a).delete()
        r = self.get()
        self.assertContains(r, 'Todavía no hay insumos')
        self.assertContains(r, '/tekon/apu/generar/')

    def test_precio_sin_ceros_de_mas_y_marcas(self):
        PrecioInsumo.objects.filter(insumo=self.albanil).update(estimado=True)
        self.cemento.activo = False
        self.cemento.save()
        r = self.get()
        self.assertContains(r, '<span class="font-medium">1,5</span>', html=False)
        self.assertNotContains(r, '1,5000')
        self.assertContains(r, 'Estimado')
        self.assertContains(r, 'Inactivo')
        self.assertContains(r, 'Sin precio')

    def test_editar_y_eliminar_solo_para_quien_gestiona_el_catalogo(self):
        r = self.get(usuario=self.coord)
        self.assertContains(r, f'/tekon/apu/insumos/{self.cemento.pk}/editar/')
        self.assertContains(r, f'/tekon/apu/insumos/{self.cemento.pk}/eliminar/')
        r = self.get(usuario=self.obs)                                                         # el observador solo ve
        self.assertNotContains(r, '/editar/')
        self.assertNotContains(r, '/eliminar/')
        self.assertContains(r, 'Cemento')

from django.core.management import call_command
from django.test import SimpleTestCase

from jor_diario.models import ReporteDiario
from jor_diario.tests import JornadasBase

from . import clasificador, servicios
from .models import CategoriaActividad, Etiqueta, ItemActividad


class ClasificadorTests(SimpleTestCase):
    def test_dividir_texto_libre(self):
        texto = "1.- Reunión con el cliente\n2) Revisión de planos; Informe semanal | ok\n- Cotización de bombas\n• \n  3. x"
        self.assertEqual(clasificador.dividir(texto), ['Reunión con el cliente', 'Revisión de planos', 'Informe semanal',
                                                       'Cotización de bombas'])
        self.assertEqual(clasificador.dividir(''), [])
        self.assertEqual(clasificador.dividir(None), [])

    def test_categorias_por_palabra_clave_tolerantes_a_acentos_y_typos(self):
        casos = {
            'Reunión de coordinación con contratista': 'reuniones', 'Cordinacion de obra': 'reuniones',
            'Análisis de riesgos del proyecto': 'riesgos', 'Actualicé el cronograma': 'cronogramas',
            'Planos de piping': 'diseno', 'Visita a terreno': 'supervision', 'Cotización a proveedor': 'adquisiciones',
            'Seguimiento de compromisos': 'seguimiento', 'Ordené la carpeta del proyecto': 'gestion_doc',
            'Almorcé tarde': 'otros', '': 'otros',
        }
        for texto, esperado in casos.items():
            self.assertEqual(clasificador.clasificar(texto)[0], esperado, texto)

    def test_la_primera_coincidencia_gana_por_prioridad(self):
        self.assertEqual(clasificador.clasificar('Reunión para revisar riesgos')[0], 'riesgos')


class ReporteBase(JornadasBase):
    def reporte(self, user, hecho='', plan=''):
        p = self.perfil(user)
        p.exige_reporte = False       # estos tests clasifican reportes parciales (solo «realizado» o solo «plan»)
        p.save(update_fields=['exige_reporte'])
        j = self.ini(p)
        self.fin(j.pk, p, hecho, plan)
        return ReporteDiario.objects.filter(jornada=j).first()


class SincronizacionTests(ReporteBase):
    def test_finalizar_clasifica_el_reporte(self):
        r = self.reporte(self.emp, 'Reunión con cliente\nInforme semanal', 'Visita a obra')
        items = list(r.items.order_by('tipo', 'posicion'))
        self.assertEqual([(i.tipo, i.categoria) for i in items],
                         [('hecho', 'reuniones'), ('hecho', 'informes'), ('planificado', 'supervision')])
        self.assertTrue(all(i.empresa_id == self.a.pk for i in items))
        self.assertEqual(CategoriaActividad.objects.filter(empresa=self.a).count(), 13)       # se sembraron al primer uso

    def test_es_idempotente_y_respeta_lo_manual(self):
        r = self.reporte(self.emp, 'Reunión con cliente\nAlmuerzo con el equipo')
        otros = r.items.get(posicion=1)
        servicios.recategorizar(otros, 'cronogramas')
        servicios.sincronizar_items(r)
        servicios.sincronizar_items(r)
        self.assertEqual(r.items.filter(tipo='hecho').count(), 2)
        otros.refresh_from_db()
        self.assertEqual((otros.categoria, otros.manual, otros.fuente), ('cronogramas', True, 'manual'))
        # Cambiar el texto del reporte no duplica ni pisa el ítem manual.
        r.realizado = 'Reunión con cliente\nAlmuerzo con el equipo\nInforme final'
        r.save()
        servicios.sincronizar_items(r)
        self.assertEqual(sorted(r.items.filter(tipo='hecho').values_list('texto', flat=True)),
                         ['Almuerzo con el equipo', 'Informe final', 'Reunión con cliente'])

    def test_recategorizar_exige_categoria_existente(self):
        r = self.reporte(self.emp, 'Reunión con cliente')
        with self.assertRaises(ValueError):
            servicios.recategorizar(r.items.get(), 'inventada')

    def test_una_categoria_desactivada_cae_en_otros(self):
        servicios.sembrar_categorias(self.a)
        CategoriaActividad.objects.filter(empresa=self.a, codigo='reuniones').update(activa=False)
        r = self.reporte(self.emp, 'Reunión con cliente')
        self.assertEqual(r.items.get().categoria, 'otros')

    def test_un_fallo_del_clasificador_no_impide_finalizar(self):
        from unittest import mock
        with mock.patch('jor_actividades.servicios.sincronizar_items', side_effect=RuntimeError('boom')):
            j = self.ini(self.perfil(self.emp))
            self.fin(j.pk, self.perfil(self.emp), 'algo', 'otra cosa')
        self.assertEqual(ReporteDiario.objects.count(), 1)
        self.assertFalse(ItemActividad.objects.exists())

    def test_las_categorias_son_por_empresa(self):
        servicios.sembrar_categorias(self.a)
        self.assertFalse(CategoriaActividad.objects.filter(empresa=self.b).exists())
        servicios.sembrar_categorias(self.a)             # idempotente
        self.assertEqual(CategoriaActividad.objects.filter(empresa=self.a).count(), 13)

    def test_comando_reclasifica(self):
        r = self.reporte(self.emp, 'Reunión con cliente')
        ItemActividad.objects.all().delete()
        call_command('reclasificar_actividades', empresa='tekon')
        self.assertEqual(r.items.count(), 1)


class EtiquetaTests(ReporteBase):
    def test_resolver_deduplica_por_nombre_normalizado(self):
        a = servicios.resolver_etiqueta(self.a, 'proyecto', 'Torre Ñuñoa')
        b = servicios.resolver_etiqueta(self.a, 'proyecto', '  torre   nunoa ')
        self.assertEqual(a.pk, b.pk)
        self.assertIsNone(servicios.resolver_etiqueta(self.a, 'proyecto', '   '))
        self.assertNotEqual(servicios.resolver_etiqueta(self.b, 'proyecto', 'Torre Ñuñoa').pk, a.pk)

    def test_fusionar_separar_e_ignorar(self):
        e1, e2, e3 = (servicios.resolver_etiqueta(self.a, 'proyecto', n) for n in ('Torre A', 'Torre Alfa', 'Torre A.'))
        servicios.fusionar(e2, e1)
        servicios.fusionar(e1, e3)                         # fusionar una raíz con alias arrastra sus alias
        e1.refresh_from_db(); e2.refresh_from_db()
        self.assertEqual((e1.canonica_id, e2.canonica_id), (e3.pk, e3.pk))
        self.assertEqual(servicios.resolver_etiqueta(self.a, 'proyecto', 'Torre Alfa').pk, e3.pk)
        servicios.separar(e2)
        e2.refresh_from_db()
        self.assertIsNone(e2.canonica_id)
        e3.ignorada = True
        e3.save()
        self.assertIsNone(servicios.resolver_etiqueta(self.a, 'proyecto', 'Torre A.'))
        self.assertIsNone(servicios.resolver_etiqueta(self.a, 'proyecto', 'Torre A'))      # alias de una ignorada

    def test_validaciones_de_fusion_y_renombre(self):
        a = servicios.resolver_etiqueta(self.a, 'proyecto', 'A')
        b = servicios.resolver_etiqueta(self.a, 'ubicacion', 'B')
        c = servicios.resolver_etiqueta(self.b, 'proyecto', 'C')
        for destino in (a, b, c):
            with self.assertRaises(servicios.ErrorEtiqueta):
                servicios.fusionar(a, destino)
        d = servicios.resolver_etiqueta(self.a, 'proyecto', 'D')
        with self.assertRaises(servicios.ErrorEtiqueta):
            servicios.renombrar(d, 'a')
        with self.assertRaises(servicios.ErrorEtiqueta):
            servicios.renombrar(d, '  ')
        servicios.renombrar(d, 'Delta', 'D-1', '#ff0000')
        d.refresh_from_db()
        self.assertEqual((d.nombre, d.clave, d.codigo, d.color), ('Delta', 'delta', 'D-1', '#ff0000'))


class VistasTests(ReporteBase):
    def test_gestion_de_etiquetas(self):
        e = servicios.resolver_etiqueta(self.a, 'proyecto', 'Torre A')
        o = servicios.resolver_etiqueta(self.a, 'proyecto', 'Torre Alfa')
        self.assertEqual(self.ir(self.emp, 'etiquetas/').status_code, 403)
        self.assertContains(self.ir(self.dir, 'etiquetas/'), 'Torre Alfa')
        self.ir(self.dir, 'etiquetas/', {'tipo': 'entregable', 'nombre': 'Plano 1'})
        self.assertTrue(Etiqueta.objects.filter(tipo='entregable', nombre='Plano 1').exists())
        self.ir(self.dir, f'etiquetas/{o.pk}/', {'accion': 'fusionar', 'destino': e.pk})
        o.refresh_from_db()
        self.assertEqual(o.canonica_id, e.pk)
        self.ir(self.dir, f'etiquetas/{o.pk}/', {'accion': 'separar'})
        self.ir(self.dir, f'etiquetas/{e.pk}/', {'accion': 'ignorar'})
        e.refresh_from_db()
        self.assertTrue(e.ignorada)
        self.ir(self.dir, f'etiquetas/{e.pk}/', {'accion': 'renombrar', 'nombre': 'Torre Z', 'color': 'rojo'})
        e.refresh_from_db()
        self.assertEqual(e.nombre, 'Torre A')                  # color inválido: no se guardó nada

    def test_no_se_toca_la_etiqueta_de_otra_empresa(self):
        ajena = servicios.resolver_etiqueta(self.b, 'proyecto', 'Ajena')
        self.assertEqual(self.ir(self.dir, f'etiquetas/{ajena.pk}/', {'accion': 'ignorar'}).status_code, 404)
        propia = servicios.resolver_etiqueta(self.a, 'proyecto', 'Propia')
        self.ir(self.dir, f'etiquetas/{propia.pk}/', {'accion': 'fusionar', 'destino': ajena.pk})
        propia.refresh_from_db()
        self.assertIsNone(propia.canonica_id)
        self.assertEqual(self.ir(self.dir, f'etiquetas/{propia.pk}/', {'accion': 'fusionar', 'destino': 'abc'}).status_code, 404)

    def test_categorias_crud_solo_pmo(self):
        self.assertEqual(self.ir(self.dir, 'categorias/').status_code, 403)
        self.assertContains(self.ir(self.pmo, 'categorias/'), 'Análisis de riesgos')
        r = self.ir(self.pmo, 'categorias/', {'etiqueta': 'Calidad', 'codigo': 'calidad', 'color': '#00ff00', 'orden': '20', 'activa': 'on'})
        self.assertEqual(r.status_code, 302)
        c = CategoriaActividad.objects.get(empresa=self.a, codigo='calidad')
        self.assertEqual(self.ir(self.pmo, 'categorias/', {'etiqueta': 'X', 'codigo': 'calidad', 'color': '#00ff00', 'orden': '1'}).status_code, 200)
        self.assertEqual(self.ir(self.pmo, 'categorias/', {'etiqueta': 'X', 'codigo': 'z', 'color': 'verde', 'orden': '1'}).status_code, 200)
        self.assertFalse(CategoriaActividad.objects.filter(codigo='z').exists())
        self.ir(self.pmo, f'categorias/{c.pk}/', {f'c{c.pk}-etiqueta': 'Calidad 2', f'c{c.pk}-codigo': 'cambiado',
                                                   f'c{c.pk}-color': '#111111', f'c{c.pk}-orden': '3'})
        c.refresh_from_db()
        self.assertEqual((c.etiqueta, c.codigo, c.activa), ('Calidad 2', 'calidad', False))      # el código no cambia
        otros = CategoriaActividad.objects.get(empresa=self.a, codigo='otros')
        self.ir(self.pmo, f'categorias/{otros.pk}/', {f'c{otros.pk}-etiqueta': 'Otros', f'c{otros.pk}-color': '#111111', f'c{otros.pk}-orden': '1'})
        otros.refresh_from_db()
        self.assertTrue(otros.activa)                          # «otros» no se desactiva

    def test_no_se_edita_la_categoria_de_otra_empresa(self):
        servicios.sembrar_categorias(self.b)
        ajena = CategoriaActividad.objects.get(empresa=self.b, codigo='riesgos')
        self.assertEqual(self.ir(self.pmo, f'categorias/{ajena.pk}/', {}).status_code, 404)


class ConfigPestanasTests(JornadasBase):
    def test_coordinador_ve_las_tres_pestanas_en_cada_pagina(self):
        for ruta in ('config/', 'categorias/', 'etiquetas/'):
            r = self.ir(self.pmo, ruta)
            self.assertEqual(r.status_code, 200, ruta)
            self.assertEqual([p['nombre'] for p in r.context['pestanas']], ['General', 'Categorías', 'Etiquetas'])
        self.assertEqual([p['nombre'] for p in self.ir(self.pmo, 'categorias/').context['pestanas'] if p['activa']], ['Categorías'])

    def test_quien_solo_gestiona_etiquetas_va_directo_a_su_pestana(self):
        r = self.ir(self.dir, 'config/')                    # coordinador acotado: sin jor.config.manage, con etiquetas.manage
        self.assertRedirects(r, '/tekon/jornadas/etiquetas/', fetch_redirect_response=False)
        self.assertEqual([p['nombre'] for p in self.ir(self.dir, 'etiquetas/').context['pestanas']], ['Etiquetas'])

    def test_sin_capacidades_no_entra_a_configuracion(self):
        self.assertEqual(self.ir(self.emp, 'config/').status_code, 403)


class EtiquetasAProyectosTests(JornadasBase):
    def etiqueta(self, nombre, empresa=None, tipo='proyecto', **kw):
        from .servicios import resolver_etiqueta
        e = resolver_etiqueta(empresa or self.a, tipo, nombre)
        for k, v in kw.items():
            setattr(e, k, v)
        e.save()
        return e

    def test_crea_el_proyecto_y_lo_vincula(self):
        from proyectos.models import Proyecto
        e = self.etiqueta('Torre Norte', codigo='TN')
        self.assertEqual(servicios.agregar_a_proyectos(self.a, [e.pk]), (1, 0))
        e.refresh_from_db()
        p = Proyecto.objects.get(nombre='Torre Norte')
        self.assertEqual((e.proyecto, p.empresa, p.codigo), (p, self.a, 'TN'))
        self.assertNotIn(e, servicios.etiquetas_pendientes_de_proyecto(self.a))

    def test_reusa_un_proyecto_existente_con_el_mismo_nombre(self):
        from proyectos.models import Proyecto
        e = self.etiqueta('torre  1')                                    # «Torre 1» ya existe (normalizado)
        self.assertEqual(servicios.agregar_a_proyectos(self.a, [e.pk]), (0, 1))
        e.refresh_from_db()
        self.assertEqual((e.proyecto, Proyecto.objects.filter(empresa=self.a).count()), (self.proy, 1))

    def test_es_idempotente(self):
        from proyectos.models import Proyecto
        e = self.etiqueta('Planta Sur')
        servicios.agregar_a_proyectos(self.a, [e.pk])
        self.assertEqual(servicios.agregar_a_proyectos(self.a, [e.pk]), (0, 0))
        self.assertEqual(Proyecto.objects.filter(nombre='Planta Sur').count(), 1)

    def test_codigo_en_conflicto_queda_vacio(self):
        from proyectos.models import Proyecto
        e = self.etiqueta('Otra cosa', codigo='t1')                      # «T1» es el código de Torre 1
        servicios.agregar_a_proyectos(self.a, [e.pk])
        self.assertEqual(Proyecto.objects.get(nombre='Otra cosa').codigo, '')

    def test_solo_etiquetas_raiz_de_proyecto_no_ignoradas_y_de_la_empresa(self):
        from proyectos.models import Proyecto
        raiz = self.etiqueta('Raíz')
        alias = self.etiqueta('Raiz variante', canonica=raiz)
        ignorada = self.etiqueta('Ignorada', ignorada=True)
        sede = self.etiqueta('Una sede', tipo='ubicacion')
        ajena = self.etiqueta('Ajena', empresa=self.b)
        ids = [alias.pk, ignorada.pk, sede.pk, ajena.pk]
        self.assertEqual(servicios.agregar_a_proyectos(self.a, ids), (0, 0))
        self.assertFalse(Proyecto.objects.filter(nombre__in=['Raiz variante', 'Ignorada', 'Una sede', 'Ajena']).exists())
        self.assertEqual(servicios.agregar_a_proyectos(self.a, [raiz.pk]), (1, 0))

    def test_vista_solo_para_quien_gestiona_proyectos_y_etiquetas(self):
        from proyectos.models import Proyecto
        e = self.etiqueta('Nueva obra')
        url = '/tekon/jornadas/etiquetas/a-proyectos/'
        for u in (self.emp, self.dir):                                   # Ejecutor y Coordinador acotado
            self.client.force_login(u)
            self.assertEqual(self.client.post(url, {'etiqueta': e.pk}).status_code, 403, u.email)
        self.assertFalse(Proyecto.objects.filter(nombre='Nueva obra').exists())
        self.client.force_login(self.pmo)
        r = self.client.post(url, {'etiqueta': [e.pk, 'x']})
        self.assertRedirects(r, '/tekon/proyectos/', fetch_redirect_response=False)
        self.assertTrue(Proyecto.objects.filter(empresa=self.a, nombre='Nueva obra').exists())
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_sin_seleccion_no_hace_nada(self):
        from proyectos.models import Proyecto
        antes = Proyecto.objects.count()
        self.client.force_login(self.pmo)
        self.client.post('/tekon/jornadas/etiquetas/a-proyectos/', {})
        self.assertEqual(Proyecto.objects.count(), antes)

    def test_la_lista_de_proyectos_muestra_los_pendientes_solo_a_quien_puede(self):
        self.etiqueta('Mencionado en reportes')
        self.client.force_login(self.pmo)
        self.assertContains(self.client.get('/tekon/proyectos/'), 'Mencionado en reportes')
        self.client.force_login(self.emp)
        r = self.client.get('/tekon/proyectos/')
        self.assertNotContains(r, 'Mencionado en reportes')


class MenuProyectosTests(JornadasBase):
    def menu(self, user):
        self.client.force_login(user)
        r = self.client.get('/tekon/jornadas/equipo/')
        return [(i['seccion'], i['nombre']) for i in r.context['menu_lateral']]

    def test_proyectos_es_un_grupo_propio_despues_del_de_equipo_y_antes_de_ajustes(self):
        m = self.menu(self.pmo)
        secciones = list(dict.fromkeys(s for s, _ in m))
        self.assertEqual(secciones[secciones.index('Equipo') + 1:], ['Reportes', 'Proyectos', 'Ajustes'])
        self.assertIn(('Proyectos', 'Proyectos'), m)
        self.assertNotIn('Reporte de personal', [n for s, n in m if s == 'Equipo'])   # el reporte va en su propia sección
        self.assertEqual([n for s, n in m if s == 'Reportes'], ['Reporte de personal'])

    def test_usa_el_termino_de_la_empresa(self):
        self.a.termino_proyecto_plural = 'Sitios'
        self.a.save()
        m = self.menu(self.pmo)
        self.assertIn(('Sitios', 'Sitios'), m)
        self.assertFalse([x for x in m if '{proyectos}' in x[0] + x[1]])

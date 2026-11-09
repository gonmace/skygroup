import shutil
import tempfile
from datetime import date, timedelta
from importlib import import_module
from pathlib import Path
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.http import QueryDict
from django.test import override_settings

from cuentas.roles import RolBase
from cuentas.services import crear_empresa
from reg_actividades import servicios as pasos
from reg_actividades.models import DatoPaso, Paso, PasoAsignado, Plantilla
from reg_actividades.widgets import obtener
from reg_base import revisiones, tipos
from reg_base.tests import BaseRegistros, persona
from reg_fotos.models import Foto
from reg_fotos.tests import STORAGES_TEST, exif_con_gps_y_fecha, imagen, subida
from reg_txtss.models import RegTxtss

from . import servicios
from .estandar import PASOS, sembrar_estandar
from .models import CLAVE, Hallazgo, RegConstruccionBase, SeguimientoHallazgo


def post(**campos):
    q = QueryDict(mutable=True)
    for k, v in campos.items():
        q.setlist(k, v) if isinstance(v, list) else q.update({k: v})
    return q


class Base(BaseRegistros):
    def setUp(self):
        super().setUp()
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=str(tmp), STORAGES=STORAGES_TEST)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.v = self.visita_nueva(self.p1)

    def visita_nueva(self, proyecto, fecha=None, user=None):
        return RegConstruccionBase.objects.create(
            empresa=self.a, proyecto=proyecto, user=user or self.ito1, contratista=self.c1, fecha=fecha or date.today())

    def paso(self, nombre, empresa=None):
        return Paso.objects.get(empresa=empresa or self.a, nombre=nombre)

    def hallazgo(self, visita=None, **kw):
        visita = visita or self.v
        datos = dict(empresa=self.a, proyecto=visita.proyecto, visita=visita, descripcion='Fisura de 2 mm en viga V-3',
                     severidad='mayor', plazo=date.today() + timedelta(days=5), creado_por=self.ito1)
        datos.update(kw)
        return Hallazgo.objects.create(**datos)

    def url(self, ruta=''):
        return f'/tekon/registros/construccion-base/{ruta}'


class TiposHabilitadosTests(Base):
    def test_una_empresa_nueva_tiene_construccion_activa_con_su_plantilla(self):
        self.assertTrue(tipos.esta_habilitado(self.a, CLAVE))
        plantilla = Plantilla.objects.get(empresa=self.a, tipo_registro=CLAVE, activa=True)
        self.assertEqual(plantilla.asignados.count(), len(PASOS))

    def test_los_tipos_viejos_no_se_activan_solos(self):
        nueva = crear_empresa(nombre='Nueva', slug='nueva', modulos=['reg'])
        self.assertEqual([t.clave for t in tipos.habilitados(nueva)], [CLAVE])
        u = persona('n@x.cl', nueva, RolBase.COORDINADOR)
        self.client.force_login(u)
        self.assertEqual(self.client.get('/nueva/registros/txtss/').status_code, 404)
        self.assertEqual(self.client.get('/nueva/registros/construccion/').status_code, 404)
        self.assertEqual(self.client.get('/nueva/registros/construccion-base/').status_code, 200)

    def test_desactivar_oculta_pero_no_borra(self):
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        self.client.force_login(self.pmo)
        self.assertContains(self.client.get('/tekon/registros/'), 'TX/TSS')
        tipos.deshabilitar(self.a, 'txtss')
        self.assertEqual(self.client.get('/tekon/registros/txtss/').status_code, 404)
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{r.pk}/').status_code, 404)
        self.assertNotContains(self.client.get('/tekon/registros/'), 'TX/TSS Poste')
        self.assertTrue(RegTxtss.objects.filter(pk=r.pk).exists())
        tipos.habilitar(self.a, 'txtss')
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{r.pk}/').status_code, 200)

    def test_las_rutas_genericas_tambien_respetan_el_tipo(self):
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        tipos.deshabilitar(self.a, 'txtss')
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{r.pk}/pasos/').status_code, 404)
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{r.pk}/fotos/general/').status_code, 404)

    def test_pantalla_de_tipos_es_del_superusuario(self):
        url = '/tekon/registros/config/tipos-de-registro/'
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.root)
        self.assertContains(self.client.get(url), 'Supervisión Campo')
        fresca = lambda: type(self.a).objects.get(pk=self.a.pk)   # la petición usa su propia instancia de la empresa
        self.client.post(f'{url}txtss/alternar/')
        self.assertFalse(tipos.esta_habilitado(fresca(), 'txtss'))
        self.client.post(f'{url}txtss/alternar/')
        self.assertTrue(tipos.esta_habilitado(fresca(), 'txtss'))

    def test_las_plantillas_solo_ofrecen_tipos_activos(self):
        from reg_actividades.forms import PlantillaForm
        tipos.deshabilitar(self.a, 'txtss')
        claves = [c for c, _ in PlantillaForm(empresa=self.a).fields['tipo_registro'].choices]
        self.assertNotIn('txtss', claves)
        self.assertIn(CLAVE, claves)

    def test_la_migracion_activa_solo_donde_hay_uso(self):
        otra = crear_empresa(nombre='Uso', slug='uso', modulos=['reg'])
        sin_uso = crear_empresa(nombre='Sin', slug='sin', modulos=['reg'])
        persona('uso@x.cl', otra, RolBase.COORDINADOR)
        from proyectos.models import Proyecto
        p = Proyecto.objects.create(empresa=otra, nombre='Sitio de uso', codigo='USO-1')
        RegTxtss.objects.create(empresa=otra, proyecto=p, user=None)
        mig = import_module('reg_base.migrations.0005_activar_tipos_en_uso')
        mig.activar_en_uso(django_apps, None)
        self.assertTrue(tipos.esta_habilitado(type(otra).objects.get(pk=otra.pk), 'txtss'))
        self.assertFalse(tipos.esta_habilitado(type(sin_uso).objects.get(pk=sin_uso.pk), 'txtss'))
        self.assertFalse(tipos.esta_habilitado(type(otra).objects.get(pk=otra.pk), 'construccion'))


class EstandarTests(Base):
    def test_sembrar_es_idempotente(self):
        antes = (Paso.objects.count(), Plantilla.objects.count(), PasoAsignado.objects.count())
        self.assertEqual(sembrar_estandar(self.a), (0, False))
        self.assertEqual((Paso.objects.count(), Plantilla.objects.count(), PasoAsignado.objects.count()), antes)

    def test_restaurar_vuelve_al_estandar_sin_perder_pasos_propios(self):
        paso = self.paso('cb_datos')
        paso.widgets.all().delete()
        propio = Paso.objects.create(empresa=self.a, nombre='mio', titulo='Mío')
        PasoAsignado.objects.create(plantilla=Plantilla.objects.get(empresa=self.a, tipo_registro=CLAVE), paso=propio, orden=99)
        sembrar_estandar(self.a, restaurar=True)
        self.assertEqual(paso.widgets.count(), 2)
        self.assertTrue(Paso.objects.filter(pk=propio.pk).exists())
        self.assertTrue(PasoAsignado.objects.filter(paso=propio).exists())

    def test_cada_empresa_edita_su_copia(self):
        self.paso('cb_datos').widgets.all().delete()
        self.assertEqual(self.paso('cb_datos', self.b).widgets.count(), 2)

    def test_todas_las_configuraciones_son_validas_y_no_se_numera(self):
        for nombre, titulo, _desc, widgets in PASOS:
            self.assertFalse(titulo[0].isdigit(), titulo)
            for slug, config in widgets:
                self.assertEqual(obtener(slug).validar_config(config), [], f'{nombre}/{slug}')

    def test_los_pasos_opcionales_no_cuentan_para_el_color(self):
        self.assertEqual(set(RegConstruccionBase.ETAPAS_OPCIONALES), {'cb_instrucciones', 'cb_libro'})
        pasos.guardar_paso(self.v, self.paso('cb_instrucciones'), post(lista_widget__entradas='Corregir'), {})
        self.assertEqual(RegConstruccionBase.objects.with_estado().get(pk=self.v.pk).orden_estado, 3)   # sigue «vacía»


class WidgetsTests(Base):
    def test_tabla_lee_filas_y_descarta_las_vacias(self):
        w = obtener('tabla_widget')
        cfg = {'columnas': 'actividad | text | Actividad | | *\nestado | select | Estado | A,B | *\navance | number | Avance'}
        datos, errs = w.leer(post(tabla_widget__actividad=['Excavar', '', 'Armar'], tabla_widget__estado=['A', '', 'B'],
                                  tabla_widget__avance=['10,5', '', '']), {}, cfg)
        self.assertEqual(errs, [])
        self.assertEqual(datos['filas'], [{'actividad': 'Excavar', 'estado': 'A', 'avance': 10.5},
                                          {'actividad': 'Armar', 'estado': 'B'}])

    def test_tabla_valida_obligatorios_numeros_y_opciones(self):
        w = obtener('tabla_widget')
        cfg = {'columnas': 'actividad | text | Actividad | | *\nestado | select | Estado | A,B\navance | number | Avance'}
        _, errs = w.leer(post(tabla_widget__actividad=['', 'x'], tabla_widget__estado=['A', 'Z'],
                              tabla_widget__avance=['', 'mucho']), {}, cfg)
        self.assertEqual(len(errs), 3)
        self.assertTrue(any('obligatorio' in e for e in errs))

    def test_tabla_nivel_y_config(self):
        w = obtener('tabla_widget')
        cfg = {'columnas': 'a | text | A', 'min_filas': 2}
        self.assertEqual(w.nivel({}, cfg, None), 1)
        self.assertEqual(w.nivel({'filas': [{'a': 'x'}]}, cfg, None), 2)
        self.assertEqual(w.nivel({'filas': [{'a': 'x'}, {'a': 'y'}]}, cfg, None), 3)
        self.assertTrue(w.validar_config({'columnas': 'a | toggle | A'}))
        self.assertTrue(w.validar_config({}))

    def test_formulario_acepta_hora(self):
        w = obtener('form_dinamico_widget')
        cfg = {'campos': 'hora | time | Hora | | *'}
        self.assertEqual(w.leer(post(form_dinamico_widget__hora='08:30'), {}, cfg)[0], {'hora': '08:30'})
        self.assertTrue(w.leer(post(form_dinamico_widget__hora='25:99'), {}, cfg)[1])
        self.assertEqual(w.validar_config(cfg), [])

    def test_firma_guarda_conserva_y_valida(self):
        import base64
        w = obtener('firma_widget')
        png = 'data:image/png;base64,' + base64.b64encode(b'\x89PNG\r\n\x1a\n' + b'0' * 40).decode()
        datos, errs = w.leer(post(firma_widget__png=png, firma_widget__nombre='Ana'), {}, {})
        self.assertEqual((errs, datos['nombre']), ([], 'Ana'))
        conservada, _ = w.leer(post(firma_widget__nombre='Ana'), {}, {}, mock.Mock(extra={'previos': datos}))
        self.assertEqual(conservada['png'], png)
        self.assertTrue(w.leer(post(firma_widget__png='data:image/png;base64,xxx'), {}, {})[1])
        self.assertTrue(w.leer(post(firma_widget__png='javascript:alert(1)'), {}, {})[1])

    def test_hallazgos_widget_no_guarda_un_falso_en_la_base(self):
        pasos.guardar_paso(self.v, self.paso('cb_hallazgos'), post(), {})
        self.assertFalse(DatoPaso.objects.get(object_id=self.v.pk, paso_nombre='cb_hallazgos').tiene_datos)
        pasos.guardar_paso(self.v, self.paso('cb_hallazgos'), post(hallazgos_widget__sin_hallazgos='on'), {})
        self.assertTrue(DatoPaso.objects.get(object_id=self.v.pk, paso_nombre='cb_hallazgos').tiene_datos)


class VisitasVistasTests(Base):
    def test_el_correlativo_es_por_proyecto(self):
        v2 = self.visita_nueva(self.p1, date.today() + timedelta(days=1))
        v3 = self.visita_nueva(self.t1)
        self.assertEqual((self.v.numero, v2.numero, v3.numero), (1, 2, 1))

    def test_crear_visita_desde_la_vista(self):
        self.client.force_login(self.pmo)
        r = self.client.post(self.url('nueva/'), {'proyecto': self.p1.pk, 'fecha': date.today().isoformat(),
                                                  'user': self.ito1.pk, 'contratista': self.c1.pk})
        nueva = RegConstruccionBase.objects.exclude(pk=self.v.pk).get()
        self.assertRedirects(r, self.url(f'{nueva.pk}/'))
        self.assertEqual(nueva.numero, 2)

    def test_un_ito_no_puede_activar_pero_si_cargar(self):
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(self.url('nueva/')).status_code, 403)
        r = self.client.get(self.url(f'{self.v.pk}/'))
        self.assertContains(r, 'Visita 1')

    def test_alcance_un_ito_no_ve_visitas_ajenas(self):
        self.client.force_login(self.ito3)
        self.assertEqual(self.client.get(self.url(f'{self.v.pk}/')).status_code, 404)

    def test_otra_empresa_no_ve_la_visita(self):
        self.client.force_login(self.pmo_b)
        self.assertEqual(self.client.get(f'/otra/registros/construccion-base/{self.v.pk}/').status_code, 404)

    def test_lista_muestra_solo_la_revision_vigente(self):
        rev = revisiones.crear_revision(self.v, self.pmo, 'Cambia el frente')
        self.client.force_login(self.pmo)
        r = self.client.get(self.url())
        self.assertEqual([x.pk for x in r.context['pagina']], [rev.pk])

    def test_emitir_exige_pasos_obligatorios(self):
        self.client.force_login(self.pmo)
        r = self.client.post(self.url(f'{self.v.pk}/emitir/'), follow=True)
        self.v.refresh_from_db()
        self.assertFalse(self.v.concluido)
        self.assertContains(r, 'Datos de la visita')
        self.assertIn('Datos de la visita', servicios.faltan_para_emitir(self.v))
        self.assertNotIn('Instrucciones y acuerdos en sitio', servicios.faltan_para_emitir(self.v))

    def test_emitir_deja_la_visita_en_solo_lectura(self):
        self.client.force_login(self.pmo)
        with mock.patch.object(servicios, 'faltan_para_emitir', return_value=[]):
            self.client.post(self.url(f'{self.v.pk}/emitir/'))
        self.v.refresh_from_db()
        self.assertTrue(self.v.concluido)
        self.assertEqual((self.v.emitido_por, bool(self.v.emitido_en)), (self.pmo, True))
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.post(self.url(f'{self.v.pk}/hallazgos/nuevo/'), {}).status_code, 403)
        self.assertEqual(self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/paso/cb_recursos/guardar/', {}).status_code, 403)
        self.assertEqual(self.client.post(self.url(f'{self.v.pk}/emitir/')).status_code, 404)   # no se reabre: se revisa

    def test_pdf(self):
        h = self.hallazgo()
        pasos.guardar_paso(self.v, self.paso('cb_actividades'), post(lista_widget__entradas='Excavación\nArmado de fierro'), {})
        pasos.guardar_paso(self.v, self.paso('cb_datos'), post(
            form_dinamico_widget__motivo='Rutinaria', form_dinamico_widget__comentario='Todo en orden'), {})
        self.client.force_login(self.pmo)
        r = self.client.get(self.url(f'{self.v.pk}/pdf/'))
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertEqual(h.codigo, 'H-001')

    def test_panel_del_resumen(self):
        self.hallazgo(severidad='critica')
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/registros/')
        self.assertContains(r, 'Hallazgos abiertos')
        self.assertContains(r, 'Hallazgos críticos abiertos')
        self.assertIn(CLAVE, [p['tipo'].clave for p in r.context['paneles']])


class HallazgosTests(Base):
    def test_codigo_correlativo_por_proyecto_y_vencimiento(self):
        a, b = self.hallazgo(), self.hallazgo(plazo=date.today() - timedelta(days=1))
        self.assertEqual((a.codigo, b.codigo), ('H-001', 'H-002'))
        self.assertFalse(a.vencido)
        self.assertTrue(b.vencido)
        otro = self.hallazgo(visita=self.visita_nueva(self.t1))
        self.assertEqual(otro.codigo, 'H-001')

    def test_crear_hallazgo_desde_la_vista(self):
        self.client.force_login(self.ito1)
        r = self.client.post(self.url(f'{self.v.pk}/hallazgos/nuevo/'), {
            'descripcion': 'Fisura', 'tipo': 'calidad', 'severidad': 'critica',
            'responsable': 'Capataz', 'plazo': date.today().isoformat()})
        h = Hallazgo.objects.get()
        self.assertRedirects(r, f'/tekon/registros/hallazgos/{h.pk}/')
        self.assertEqual((h.visita, h.proyecto, h.creado_por), (self.v, self.p1, self.ito1))

    def test_seguimiento_cierra_cambia_y_se_deshace(self):
        h = self.hallazgo()
        v2 = self.visita_nueva(self.p1, date.today() + timedelta(days=7))
        campo = f'seguimiento_widget__estado_{h.pk}'
        paso = self.paso('cb_seguimiento')
        pasos.guardar_paso(v2, paso, post(**{campo: 'cerrado', f'seguimiento_widget__comentario_{h.pk}': 'Corregido'}), {})
        h.refresh_from_db()
        self.assertEqual((h.estado, h.cerrado_en, h.cerrado_fecha), ('cerrado', v2, v2.fecha))
        pasos.guardar_paso(v2, paso, post(**{campo: 'en_proceso'}), {})
        h.refresh_from_db()
        self.assertEqual((h.estado, h.cerrado_en), ('en_proceso', None))
        pasos.guardar_paso(v2, paso, post(), {})
        h.refresh_from_db()
        self.assertEqual(h.estado, 'abierto')
        self.assertFalse(SeguimientoHallazgo.objects.exists())

    def test_solo_se_verifican_hallazgos_de_visitas_anteriores(self):
        h = self.hallazgo()
        v2 = self.visita_nueva(self.p1, date.today() + timedelta(days=7))
        self.assertEqual(list(servicios.pendientes_de_seguimiento(v2)), [h])
        self.assertEqual(list(servicios.pendientes_de_seguimiento(self.v)), [])
        self.assertEqual(list(servicios.pendientes_de_seguimiento(self.visita_nueva(self.t1))), [])   # otro proyecto

    def test_un_cerrado_deja_de_aparecer_en_visitas_posteriores(self):
        h = self.hallazgo()
        v2 = self.visita_nueva(self.p1, date.today() + timedelta(days=7))
        servicios.registrar_seguimiento(v2, h, 'cerrado')
        v3 = self.visita_nueva(self.p1, date.today() + timedelta(days=14))
        self.assertEqual(list(servicios.pendientes_de_seguimiento(v3)), [])
        self.assertEqual(list(servicios.pendientes_de_seguimiento(v2)), [h])   # la que lo cerró aún puede corregirlo

    def test_widget_de_seguimiento_nivel(self):
        w = obtener('seguimiento_widget')
        ctx = mock.Mock(registro=self.v)
        self.assertEqual(w.nivel({}, {}, ctx), 3)   # nada pendiente: completo solo
        self.hallazgo()
        v2 = self.visita_nueva(self.p1, date.today() + timedelta(days=7))
        self.assertEqual(w.nivel({}, {}, mock.Mock(registro=v2)), 1)

    def test_la_lista_global_filtra_y_respeta_el_alcance(self):
        self.hallazgo(severidad='critica')
        cerrado = self.hallazgo(estado='cerrado')
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/registros/hallazgos/')
        self.assertEqual(len(r.context['pagina']), 1)   # por defecto, solo pendientes
        self.assertEqual(len(self.client.get('/tekon/registros/hallazgos/?estado=cerrado').context['pagina']), 1)
        self.assertEqual(len(self.client.get('/tekon/registros/hallazgos/?severidad=menor').context['pagina']), 0)
        self.client.force_login(self.ito3)
        self.assertEqual(len(self.client.get('/tekon/registros/hallazgos/').context['pagina']), 0)
        self.assertEqual(self.client.get(f'/tekon/registros/hallazgos/{cerrado.pk}/').status_code, 404)

    def test_no_se_elimina_un_hallazgo_con_seguimientos(self):
        h = self.hallazgo()
        servicios.registrar_seguimiento(self.visita_nueva(self.p1, date.today() + timedelta(days=7)), h, 'en_proceso')
        self.client.force_login(self.ito1)
        self.client.post(f'/tekon/registros/hallazgos/{h.pk}/eliminar/')
        h.refresh_from_db()
        self.assertFalse(h.is_deleted)


class RevisionesTests(Base):
    def cargar(self):
        """Datos en un paso de la visita."""
        pasos.guardar_paso(self.v, self.paso('cb_recursos'), post(
            form_dinamico_widget__trabajadores='12', form_dinamico_widget__equipo_pesado='1 retroexcavadora'), {})

    def foto(self, visita, etapa):
        from reg_fotos.servicios import guardar_foto
        return guardar_foto(subida(), autor=self.ito1, registro=visita, etapa=etapa, descripcion='d')

    def test_la_revision_exige_comentario(self):
        for texto in ('', '   ', None):
            with self.assertRaises(ValidationError):
                revisiones.crear_revision(self.v, self.pmo, texto)
        self.assertEqual(RegConstruccionBase.objects.count(), 1)

    def test_crear_revision_copia_todo_y_deja_intacta_la_anterior(self):
        self.cargar()
        h = self.hallazgo()
        self.foto(self.v, 'cb_libro')
        self.foto(self.v, h.etapa_fotos)
        previa = self.visita_nueva(self.t1)   # visita de otro proyecto, no interviene
        anterior = self.hallazgo(visita=self.visita_nueva(self.p1, date.today() - timedelta(days=9)))
        self.v.numero = 3
        RegConstruccionBase.objects.filter(pk=self.v.pk).update(numero=3)
        self.v.refresh_from_db()
        servicios.registrar_seguimiento(self.v, anterior, 'en_proceso', 'Avanza')
        self.v.concluido = True
        self.v.save()

        rev = revisiones.crear_revision(self.v, self.pmo, 'Corrige hallazgos')
        self.v.refresh_from_db()

        self.assertEqual((rev.rev_numero, rev.numero, rev.serie, rev.rev_comentario), (1, 3, self.v.serie, 'Corrige hallazgos'))
        self.assertEqual((rev.rev_vigente, rev.concluido, rev.rev_origen_id), (True, False, self.v.pk))
        self.assertFalse(self.v.rev_vigente)
        self.assertTrue(self.v.concluido)   # la anterior queda como estaba
        # datos de pasos
        self.assertEqual(DatoPaso.objects.get(object_id=rev.pk, paso_nombre='cb_recursos').datos,
                         DatoPaso.objects.get(object_id=self.v.pk, paso_nombre='cb_recursos').datos)
        # fotos: archivos propios
        fv, fr = Foto.objects.filter(object_id=self.v.pk, etapa='cb_libro').get(), Foto.objects.filter(object_id=rev.pk, etapa='cb_libro').get()
        self.assertNotEqual(fv.imagen.name, fr.imagen.name)
        self.assertEqual(fr.imagen.read(), fv.imagen.read())
        # hallazgo copiado con su foto reapuntada y el original intacto
        copia = rev.hallazgos.get()
        self.assertEqual((copia.codigo, copia.origen_id, copia.descripcion), (h.codigo, h.pk, h.descripcion))
        self.assertTrue(Foto.objects.filter(object_id=rev.pk, etapa=copia.etapa_fotos).exists())
        self.assertFalse(Foto.objects.filter(object_id=rev.pk, etapa=h.etapa_fotos).exists())
        self.assertTrue(self.v.hallazgos.filter(pk=h.pk).exists())
        # seguimiento copiado
        self.assertEqual(rev.seguimientos.get().hallazgo, anterior)
        self.assertEqual(previa.rev_numero, 0)

    def test_borrar_una_foto_de_una_revision_no_afecta_a_la_otra(self):
        self.foto(self.v, 'cb_libro')
        rev = revisiones.crear_revision(self.v, self.pmo, 'Otra')
        Foto.objects.get(object_id=rev.pk, etapa='cb_libro').delete()
        f = Foto.objects.get(object_id=self.v.pk, etapa='cb_libro')
        self.assertTrue(f.imagen.storage.exists(f.imagen.name))

    def test_numeros_de_revision_correlativos_y_una_sola_vigente(self):
        r1 = revisiones.crear_revision(self.v, self.pmo, 'Uno')
        r2 = revisiones.crear_revision(r1, self.pmo, 'Dos')
        self.assertEqual([r.rev_numero for r in self.v.revisiones()], [0, 1, 2])
        self.assertEqual(list(RegConstruccionBase.objects.filter(serie=self.v.serie, rev_vigente=True)), [r2])
        revisiones.elegir_vigente(self.v)
        self.assertEqual(list(RegConstruccionBase.objects.filter(serie=self.v.serie, rev_vigente=True)), [self.v])

    def test_crear_y_elegir_desde_las_vistas(self):
        self.client.force_login(self.ito1)
        r = self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/revisiones/nueva/', {'comentario': 'Ajuste de frente'})
        rev = RegConstruccionBase.objects.get(rev_numero=1)
        self.assertRedirects(r, self.url(f'{rev.pk}/'))
        self.assertContains(self.client.get(self.url(f'{rev.pk}/')), 'Ajuste de frente')
        # un ITO no elige la vigente; un coordinador sí
        self.assertEqual(self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/revisiones/vigente/').status_code, 403)
        self.client.force_login(self.pmo)
        self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/revisiones/vigente/')
        self.v.refresh_from_db()
        self.assertTrue(self.v.rev_vigente)

    def test_sin_comentario_la_vista_no_crea(self):
        self.client.force_login(self.pmo)
        self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/revisiones/nueva/', {'comentario': ' '})
        self.assertEqual(RegConstruccionBase.objects.count(), 1)

    def test_un_observador_no_crea_revisiones(self):
        self.client.force_login(self.patro)
        r = self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/revisiones/nueva/', {'comentario': 'x'})
        self.assertEqual(r.status_code, 403)

    def test_un_tipo_sin_revisiones_responde_404(self):
        r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.post(f'/tekon/registros/txtss/{r.pk}/revisiones/nueva/', {'comentario': 'x'}).status_code, 404)

    def test_eliminar_la_vigente_promueve_otra(self):
        rev = revisiones.crear_revision(self.v, self.pmo, 'Uno')
        self.client.force_login(self.root)
        self.client.post(self.url(f'{rev.pk}/eliminar/'))
        self.v.refresh_from_db()
        self.assertTrue(self.v.rev_vigente)

    def test_la_revision_mantiene_el_pdf_y_muestra_el_motivo(self):
        rev = revisiones.crear_revision(self.v, self.pmo, 'Motivo de prueba')
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.get(self.url(f'{rev.pk}/pdf/')).status_code, 200)
        self.assertIn(('Motivo de la revisión', 'Motivo de prueba'), rev.cabecera_pdf())

    def test_otra_empresa_no_ve_las_revisiones(self):
        self.client.force_login(self.pmo_b)
        r = self.client.post(f'/otra/registros/construccion-base/{self.v.pk}/revisiones/nueva/', {'comentario': 'x'})
        self.assertEqual(r.status_code, 404)


class ContenidoDelReporteTests(Base):
    """Un botón (widget) por viñeta del reporte, y sus reglas."""

    def botones(self, nombre):
        return [pw.widget_slug for pw in self.paso(nombre).widgets.order_by('orden')]

    def test_los_seis_pasos_y_sus_botones(self):
        plantilla = Plantilla.objects.get(empresa=self.a, tipo_registro=CLAVE)
        orden = [a.paso.nombre for a in plantilla.asignados.select_related('paso').order_by('orden')]
        self.assertEqual(orden, ['cb_datos', 'cb_actividades', 'cb_recursos', 'cb_hallazgos', 'cb_seguimiento',
                                 'cb_instrucciones'])
        self.assertEqual(self.botones('cb_datos'), ['form_dinamico_widget', 'ubicacion_widget'])
        self.assertEqual(self.botones('cb_actividades'), ['lista_widget', 'camera_widget'])
        self.assertEqual(self.botones('cb_recursos'), ['form_dinamico_widget'])
        self.assertEqual(self.botones('cb_hallazgos'), ['hallazgos_widget', 'camera_widget'])
        self.assertEqual(self.botones('cb_seguimiento'), ['seguimiento_widget', 'camera_widget'])
        self.assertEqual(self.botones('cb_instrucciones'), ['lista_widget', 'camera_libro_widget'])
        self.assertFalse(Paso.objects.filter(empresa=self.a, nombre__in=['cb_seguridad', 'cb_cierre', 'cb_fotos']).exists())

    def test_motivo_es_obligatorio_y_el_comentario_no(self):
        paso = self.paso('cb_datos')
        ok, errs = pasos.guardar_paso(self.v, paso, post(form_dinamico_widget__comentario='Solo comentario'), {})
        self.assertFalse(ok)
        self.assertTrue(any('Motivo' in e for es in errs.values() for e in es))
        ok, _ = pasos.guardar_paso(self.v, paso, post(form_dinamico_widget__motivo='Recepción'), {})
        self.assertTrue(ok)
        bloques, _ = pasos.construir_paso(self.v, CLAVE, paso, DatoPaso.objects.get(object_id=self.v.pk, paso_nombre='cb_datos'), None, False)
        self.assertEqual(bloques[0]['nivel'], 3)   # completo sin comentario
        pasos.guardar_paso(self.v, paso, post(form_dinamico_widget__motivo='Recepción', form_dinamico_widget__comentario='Entrega parcial'), {})
        self.assertEqual(DatoPaso.objects.get(object_id=self.v.pk, paso_nombre='cb_datos').datos['form_dinamico_widget'],
                         {'motivo': 'Recepción', 'comentario': 'Entrega parcial'})

    def test_las_opciones_del_motivo(self):
        campo = obtener('form_dinamico_widget').contexto({}, self.paso('cb_datos').widgets.first().config, mock.Mock(puede_escribir=True))['campos'][0]
        self.assertEqual(campo['opciones'], ['Rutinaria', 'Inspección de actividad', 'Recepción', 'Prueba o ensayo',
                                             'Verificación de observaciones', 'Otro'])

    def test_recursos_pide_trabajadores_y_equipo_pesado_es_texto(self):
        paso = self.paso('cb_recursos')
        self.assertFalse(pasos.guardar_paso(self.v, paso, post(form_dinamico_widget__equipo_pesado='Grúa'), {})[0])
        self.assertTrue(pasos.guardar_paso(self.v, paso, post(form_dinamico_widget__trabajadores='8,5'), {})[0])
        self.assertEqual(DatoPaso.objects.get(object_id=self.v.pk, paso_nombre='cb_recursos').datos['form_dinamico_widget']['trabajadores'], 8.5)

    def test_actividades_es_una_lista_y_pide_cuatro_imagenes_con_metadatos(self):
        configs = {pw.widget_slug: pw.config for pw in self.paso('cb_actividades').widgets.all()}
        self.assertEqual((configs['camera_widget']['foto_min'], configs['camera_widget']['exigir_metadatos']), (4, True))
        pasos.guardar_paso(self.v, self.paso('cb_actividades'), post(lista_widget__entradas='Excavación\nArmado'), {})
        self.assertEqual(DatoPaso.objects.get(object_id=self.v.pk, paso_nombre='cb_actividades').datos['lista_widget']['entradas'],
                         ['Excavación', 'Armado'])

    def test_las_imagenes_de_hallazgos_verificacion_y_libro_son_opcionales(self):
        for nombre in ('cb_hallazgos', 'cb_seguimiento', 'cb_instrucciones'):
            for pw in self.paso(nombre).widgets.filter(widget_slug__in=['camera_widget', 'camera_libro_widget']):
                self.assertTrue(pw.config['opcional'], nombre)
                self.assertEqual(pw.config['foto_min'], 0, nombre)
                self.assertNotIn('exigir_metadatos', pw.config, nombre)
        libro = self.paso('cb_instrucciones').widgets.get(widget_slug='camera_libro_widget')
        self.assertEqual(libro.config['etapa'], 'cb_libro')

    def test_el_hallazgo_ya_no_tiene_contratista(self):
        self.assertNotIn('contratista', [f.name for f in Hallazgo._meta.get_fields()])
        self.client.force_login(self.ito1)
        r = self.client.get(self.url(f'{self.v.pk}/hallazgos/nuevo/'))
        self.assertEqual(sorted(r.context['form'].fields),
                         ['descripcion', 'plazo', 'responsable', 'severidad', 'tipo'])
        self.assertContains(r, 'Plazo')

    def test_con_lo_obligatorio_completo_se_puede_emitir_aunque_falten_las_imagenes_opcionales(self):
        pasos.guardar_paso(self.v, self.paso('cb_datos'), post(form_dinamico_widget__motivo='Rutinaria'), {})
        pasos.guardar_paso(self.v, self.paso('cb_actividades'), post(lista_widget__entradas='Excavación'), {})
        for i in range(4):
            guardar_foto = __import__('reg_fotos.servicios', fromlist=['guardar_foto']).guardar_foto
            guardar_foto(subida(datos=imagen(exif=exif_con_gps_y_fecha())), autor=self.ito1, registro=self.v, etapa='cb_actividades')
        pasos.guardar_paso(self.v, self.paso('cb_recursos'), post(form_dinamico_widget__trabajadores='10'), {})
        pasos.guardar_paso(self.v, self.paso('cb_hallazgos'), post(hallazgos_widget__sin_hallazgos='on'), {})
        self.assertEqual(servicios.faltan_para_emitir(self.v), [])   # seguimiento: nada pendiente → completo solo
        self.client.force_login(self.pmo)
        self.client.post(self.url(f'{self.v.pk}/emitir/'))
        self.v.refresh_from_db()
        self.assertTrue(self.v.concluido)

    def test_faltando_imagenes_de_actividades_no_se_puede_emitir(self):
        pasos.guardar_paso(self.v, self.paso('cb_actividades'), post(lista_widget__entradas='Excavación'), {})
        self.assertIn('Actividades', servicios.faltan_para_emitir(self.v))


class MetadatosDeLasFotosTests(Base):
    ETAPA = 'cb_actividades'

    def subir(self, archivo, etapa=None, user=None):
        self.client.force_login(user or self.ito1)
        return self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/fotos/{etapa or self.ETAPA}/subir/',
                                {'fotos': archivo}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_la_regla_solo_rige_en_el_boton_que_la_activa(self):
        regla = pasos.exige_metadatos
        self.assertTrue(regla(self.v, CLAVE, 'cb_actividades'))
        for etapa in ('cb_hallazgos', 'cb_seguimiento', 'cb_libro', 'general', f'hallazgo-1', 'seguimiento-1', 'inventada'):
            self.assertFalse(regla(self.v, CLAVE, etapa), etapa)

    def test_la_regla_sigue_a_la_etapa_efectiva_del_widget(self):
        pw = self.paso('cb_hallazgos').widgets.get(widget_slug='camera_widget')
        pw.config = {**pw.config, 'exigir_metadatos': True, 'etapa': 'otra-etapa'}
        pw.save()
        self.assertTrue(pasos.exige_metadatos(self.v, CLAVE, 'otra-etapa'))
        self.assertFalse(pasos.exige_metadatos(self.v, CLAVE, 'cb_hallazgos'))   # el widget ya no usa el nombre del paso

    def test_foto_sin_metadatos_se_rechaza_y_no_se_guarda(self):
        r = self.subir(subida())   # sin EXIF, como una foto reenviada por WhatsApp
        self.assertEqual(r.status_code, 400)
        self.assertIn('WhatsApp', r.json()['message'])
        self.assertFalse(Foto.objects.exists())

    def test_foto_con_fecha_pero_sin_gps_se_rechaza(self):
        from PIL import Image
        ex = Image.Exif()
        ex.get_ifd(0x8769)[0x9003] = '2026:03:10 12:30:00'
        r = self.subir(subida(datos=imagen(exif=ex)))
        self.assertEqual(r.status_code, 400)
        self.assertFalse(Foto.objects.exists())

    def test_foto_con_fecha_y_gps_se_acepta(self):
        r = self.subir(subida(datos=imagen(exif=exif_con_gps_y_fecha())))
        self.assertEqual(r.status_code, 200)
        foto = Foto.objects.get()
        self.assertEqual((foto.etapa, foto.exif_lat is not None, foto.exif_fecha is not None), (self.ETAPA, True, True))

    def test_en_otras_etapas_se_acepta_sin_metadatos(self):
        for etapa in ('general', 'cb_libro', 'cb_hallazgos'):
            self.assertEqual(self.subir(subida(), etapa=etapa).status_code, 200, etapa)
        h = self.hallazgo()
        self.assertEqual(self.subir(subida(), etapa=h.etapa_fotos).status_code, 200)

    def test_en_una_subida_multiple_se_guardan_solo_las_validas(self):
        self.client.force_login(self.ito1)
        r = self.client.post(f'/tekon/registros/construccion-base/{self.v.pk}/fotos/{self.ETAPA}/subir/',
                             {'fotos': [subida('a.jpg'), subida('b.jpg', datos=imagen(exif=exif_con_gps_y_fecha()))]},
                             HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(r.status_code, 200)
        self.assertIn('a.jpg', r.json()['message'])
        self.assertEqual(Foto.objects.count(), 1)

    def test_la_galeria_ofrece_tomar_foto_y_solo_donde_no_se_exigen_metadatos_tambien_la_galeria(self):
        self.client.force_login(self.ito1)
        con = self.client.get(f'/tekon/registros/construccion-base/{self.v.pk}/fotos/{self.ETAPA}/')
        self.assertContains(con, 'capture="environment"')
        self.assertContains(con, 'Capturar Imágenes')
        self.assertNotContains(con, 'Elegir de la galería')   # donde se exigen metadatos solo vale la cámara
        self.assertNotContains(con, ' multiple ')
        sin = self.client.get(f'/tekon/registros/construccion-base/{self.v.pk}/fotos/cb_hallazgos/')
        self.assertContains(sin, 'capture="environment"')      # también hay botón de cámara
        self.assertContains(sin, 'Capturar Imágenes')
        self.assertContains(sin, 'Elegir de la galería')
        self.assertContains(sin, 'multiple')

    def test_exigir_metadatos_debe_ser_booleano(self):
        w = obtener('camera_widget')
        self.assertEqual(w.validar_config({'exigir_metadatos': True}), [])
        self.assertTrue(w.validar_config({'exigir_metadatos': 'si'}))

    def test_las_revisiones_copian_las_fotos_sin_exigir_metadatos(self):
        from reg_fotos.servicios import guardar_foto
        guardar_foto(subida(), autor=self.ito1, registro=self.v, etapa=self.ETAPA)   # una foto previa sin EXIF (p. ej. importada)
        rev = revisiones.crear_revision(self.v, self.pmo, 'Copia')
        self.assertEqual(Foto.objects.filter(object_id=rev.pk, etapa=self.ETAPA).count(), 1)


class ActualizarEstandarTests(Base):
    def antigua(self, empresa):
        """Deja la plantilla como la primera versión del estándar: con Seguridad y Cierre, y sin la regla de metadatos."""
        plantilla = Plantilla.objects.get(empresa=empresa, tipo_registro=CLAVE)
        for nombre in ('cb_seguridad', 'cb_cierre'):
            paso = Paso.objects.create(empresa=empresa, nombre=nombre, titulo=nombre)
            PasoAsignado.objects.create(plantilla=plantilla, paso=paso, orden=50)
        pw = Paso.objects.get(empresa=empresa, nombre='cb_actividades').widgets.get(widget_slug='camera_widget')
        pw.config = {'label': 'Fotos', 'foto_min': 1}
        pw.save()
        return plantilla

    def nombres(self, plantilla):
        return [a.paso.nombre for a in plantilla.asignados.select_related('paso').order_by('orden')]

    def test_restaurar_quita_los_pasos_obsoletos_sin_borrarlos_y_deja_el_orden(self):
        plantilla = self.antigua(self.a)
        propio = Paso.objects.create(empresa=self.a, nombre='mio', titulo='Mío')
        PasoAsignado.objects.create(plantilla=plantilla, paso=propio, orden=99)
        sembrar_estandar(self.a, restaurar=True)
        self.assertEqual(self.nombres(plantilla)[:-1], [n for n, *_ in PASOS])
        self.assertEqual(self.nombres(plantilla)[-1], 'mio')   # el paso propio se conserva, al final
        self.assertTrue(Paso.objects.filter(empresa=self.a, nombre='cb_seguridad').exists())   # el paso y sus datos siguen
        camara = self.paso('cb_actividades').widgets.get(widget_slug='camera_widget')
        self.assertEqual((camara.config['foto_min'], camara.config['exigir_metadatos']), (4, True))

    def test_la_migracion_solo_actualiza_las_copias_de_la_primera_version(self):
        antigua = self.antigua(self.a)
        personalizada = Plantilla.objects.get(empresa=self.b, tipo_registro=CLAVE)
        Paso.objects.get(empresa=self.b, nombre='cb_datos').widgets.all().delete()   # la empresa B editó la suya
        mig = import_module('reg_construccion_base.migrations.0004_actualizar_estandar')
        mig.actualizar(django_apps, None)
        self.assertEqual(self.nombres(antigua), [n for n, *_ in PASOS])
        self.assertEqual(Paso.objects.get(empresa=self.b, nombre='cb_datos').widgets.count(), 0)   # no se pisó
        self.assertEqual(len(self.nombres(personalizada)), len(PASOS))


class AjustesDeContenidoTests(Base):
    def test_la_migracion_desasigna_imagenes_generales_y_renombra_actividades(self):
        plantilla = Plantilla.objects.get(empresa=self.a, tipo_registro=CLAVE)
        paso = Paso.objects.create(empresa=self.a, nombre='cb_fotos', titulo='Imágenes generales')
        PasoAsignado.objects.create(plantilla=plantilla, paso=paso, orden=9)
        Paso.objects.filter(empresa=self.a, nombre='cb_actividades').update(titulo='Actividades ejecutadas')
        Paso.objects.filter(empresa=self.b, nombre='cb_actividades').update(titulo='Mis actividades')   # título editado por la empresa
        foto = __import__('reg_fotos.servicios', fromlist=['guardar_foto']).guardar_foto(
            subida(), autor=self.ito1, registro=self.v, etapa='cb_fotos')
        import_module('reg_construccion_base.migrations.0005_ajustes_de_contenido').ajustar(django_apps, None)
        self.assertFalse(PasoAsignado.objects.filter(plantilla=plantilla, paso=paso).exists())
        self.assertTrue(Paso.objects.filter(pk=paso.pk).exists())          # el paso no se borra
        self.assertTrue(Foto.objects.filter(pk=foto.pk).exists())          # ni sus fotos
        self.assertEqual(self.paso('cb_actividades').titulo, 'Actividades')
        self.assertEqual(self.paso('cb_actividades', self.b).titulo, 'Mis actividades')   # no se pisa lo editado

    def test_el_paso_se_llama_actividades(self):
        titulos = {n: t for n, t, *_ in PASOS}
        self.assertEqual(titulos['cb_actividades'], 'Actividades')
        self.assertNotIn('cb_fotos', titulos)


class InsigniaDelLibroTests(Base):
    def botones(self, paso):
        resumen = pasos.resumen(self.v, CLAVE, self.pmo, False)
        return next(p for p in resumen if p['paso'].nombre == paso)['botones']

    def test_el_libro_de_obras_lleva_su_nombre_en_la_esquina(self):
        libro = next(b for b in self.botones('cb_instrucciones') if b['slug'] == 'camera_libro_widget')
        self.assertEqual((libro['insignia'], libro['insignia_texto']), ('Libro de Obras', True))
        from reg_fotos.servicios import guardar_foto
        guardar_foto(subida(), autor=self.ito1, registro=self.v, etapa='cb_libro')
        libro = next(b for b in self.botones('cb_instrucciones') if b['slug'] == 'camera_libro_widget')
        self.assertEqual((libro['insignia'], libro['conteo']), ('Libro de Obras', '1'))   # el texto no pierde el conteo (va al aria-label)

    def test_las_demas_camaras_siguen_con_su_contador(self):
        camara = next(b for b in self.botones('cb_actividades') if b['slug'] == 'camera_widget')
        self.assertEqual((camara['insignia'], camara['insignia_texto']), ('0/4', False))

    def test_la_pantalla_pinta_el_texto_y_el_aria_label_lleva_el_conteo(self):
        self.client.force_login(self.pmo)
        r = self.client.get(f'/tekon/registros/construccion-base/{self.v.pk}/')
        self.assertContains(r, '>Libro de Obras</span>')
        self.assertContains(r, 'aria-label="Imágenes de las actividades (0/4)"')

    def test_la_configuracion_puede_poner_otro_texto(self):
        w = obtener('camera_widget')
        self.assertEqual(w.validar_config({'insignia': 'Planos'}), [])
        self.assertTrue(w.validar_config({'insignia': 5}))
        self.assertTrue(w.validar_config({'insignia': 'x' * 31}))
        pw = self.paso('cb_hallazgos').widgets.get(widget_slug='camera_widget')
        pw.config = {**pw.config, 'insignia': 'Evidencia'}
        pw.save()
        b = next(b for b in self.botones('cb_hallazgos') if b['slug'] == 'camera_widget')
        self.assertEqual((b['insignia'], b['insignia_texto']), ('Evidencia', True))


class MenuAgrupadoTests(Base):
    def items(self, user):
        self.client.force_login(user)
        return self.client.get('/tekon/registros/').context['menu_lateral']

    def test_supervision_campo_y_hallazgos_van_bajo_el_encabezado_supervision(self):
        items = self.items(self.pmo)
        agrupados = [(i['nombre'], i['seccion']) for i in items if i['seccion'] == 'Supervisión']
        self.assertEqual(agrupados, [('Supervisión Campo', 'Supervisión'), ('Hallazgos', 'Supervisión')])
        nombres = [i['nombre'] for i in items]
        # el grupo es contiguo y va después de las entradas sin sección
        self.assertEqual(nombres.index('Hallazgos'), nombres.index('Supervisión Campo') + 1)
        self.assertLess(nombres.index('Construcción'), nombres.index('Supervisión Campo'))

    def test_el_encabezado_se_pinta_una_sola_vez(self):
        self.client.force_login(self.pmo)
        html = self.client.get('/tekon/registros/').content.decode()
        self.assertEqual(html.count('>Supervisión</div>'), 1)

    def test_si_el_tipo_se_desactiva_desaparece_el_grupo(self):
        tipos.deshabilitar(self.a, CLAVE)
        self.assertEqual([i for i in self.items(self.pmo) if i['seccion'] == 'Supervisión'], [])


class HallazgoSinUbicacionTests(Base):
    def test_el_hallazgo_no_tiene_ubicacion_y_el_formulario_tampoco(self):
        self.assertNotIn('ubicacion', [f.name for f in Hallazgo._meta.get_fields()])
        self.client.force_login(self.ito1)
        r = self.client.get(self.url(f'{self.v.pk}/hallazgos/nuevo/'))
        self.assertNotContains(r, 'Ubicación exacta')
        self.assertNotIn('ubicacion', r.context['form'].fields)

    def test_las_pantallas_con_hallazgos_se_ven_sin_la_ubicacion(self):
        h = self.hallazgo(severidad='critica')
        self.client.force_login(self.pmo)
        for url in (f'/tekon/registros/hallazgos/{h.pk}/', '/tekon/registros/hallazgos/', self.url(f'{self.v.pk}/'),
                    '/tekon/registros/', f'/tekon/registros/construccion-base/{self.v.pk}/paso/cb_hallazgos/'):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotContains(r, 'Ubicación exacta', msg_prefix=url)
        self.assertContains(self.client.get('/tekon/registros/hallazgos/'), 'Fisura de 2 mm')   # la lista muestra la descripción

    def test_el_pdf_lista_los_hallazgos_sin_columna_de_ubicacion(self):
        self.hallazgo()
        from reg_base.pdf import generar_pdf
        pdf = generar_pdf(self.v, CLAVE, self.pmo, 'Reporte')
        self.assertTrue(pdf.startswith(b'%PDF'))
        w = obtener('hallazgos_widget')
        pw = self.paso('cb_hallazgos').widgets.get(widget_slug='hallazgos_widget')
        html = w.html_pdf(pw, {}, mock.Mock(registro=self.v), None)
        self.assertIn('H-001', html)
        self.assertNotIn('Ubicación', html)

    def test_la_migracion_actualiza_el_texto_del_paso_solo_si_es_el_estandar(self):
        mig = import_module('reg_construccion_base.migrations.0006_quitar_ubicacion_del_hallazgo')
        Paso.objects.filter(empresa=self.a, nombre='cb_hallazgos').update(descripcion=mig.ANTES)
        Paso.objects.filter(empresa=self.b, nombre='cb_hallazgos').update(descripcion='Texto propio')
        mig.actualizar_texto(django_apps, None)
        self.assertEqual(self.paso('cb_hallazgos').descripcion, mig.AHORA)
        self.assertEqual(self.paso('cb_hallazgos', self.b).descripcion, 'Texto propio')

from datetime import date

from django.test import TestCase
from django.core.exceptions import ValidationError

from cuentas.models import User
from proyectos.models import Proyecto
from reg_base.tests import BaseRegistros

from .models import RegTxtss


class TxtssBase(BaseRegistros):
    def registro(self, proyecto=None, user=None, **kw):
        return RegTxtss.objects.create(empresa=self.a, proyecto=proyecto or self.p1, user=user or self.ito1, **kw)

    def login(self, user):
        self.client.force_login(user)


class ModeloTests(TxtssBase):
    def test_unico_por_proyecto_responsable_fecha_y_alternativa_entre_activos(self):
        r = self.registro()
        with self.assertRaises(ValidationError):
            self.registro()
        self.registro(alternativa='B')           # otra alternativa: ok
        r.soft_delete()
        self.registro()                          # tras borrar se puede recrear

    def test_proyecto_y_responsable_deben_ser_de_la_empresa(self):
        with self.assertRaises(ValidationError):
            self.registro(proyecto=self.pb)
        with self.assertRaises(ValidationError):
            self.registro(user=self.pmo_b)

    def test_siguiente_alternativa(self):
        self.assertEqual([self.registro(alternativa=a).siguiente_alternativa for a in 'ABE'], ['B', 'C', None])


class ListaTests(TxtssBase):
    def test_cada_rol_ve_su_alcance_y_solo_de_su_empresa(self):
        self.registro(self.p1, self.ito1)
        self.registro(self.t1, self.ito2)
        self.registro(self.t2, self.ito3)
        otra = RegTxtss.objects.create(empresa=self.b, proyecto=self.pb, user=self.pmo_b)
        cuenta = lambda u: len((self.client.force_login(u) or self.client.get('/tekon/registros/txtss/')).context['pagina'])
        self.assertEqual([cuenta(u) for u in (self.ito1, self.dir1, self.dir2, self.pmo, self.visita)], [1, 2, 1, 3, 3])
        self.client.force_login(self.pmo)
        self.assertNotContains(self.client.get('/tekon/registros/txtss/'), otra.proyecto.nombre)

    def test_pestanas_por_tipo_y_busqueda(self):
        self.registro(self.p1, self.ito1)
        self.registro(self.t1, self.ito1)
        self.login(self.pmo)
        r = self.client.get('/tekon/registros/txtss/')
        self.assertEqual([t.nombre for t in r.context['tabs']], ['Poste', 'Torre'])
        titulos = lambda q: sorted(x.proyecto.nombre for x in self.client.get('/tekon/registros/txtss/', q).context['pagina'])
        self.assertEqual(titulos({'tipo': self.poste.pk}), ['Poste Norte'])
        self.assertEqual(titulos({'tipo': self.torre.pk}), ['Torre Sur'])
        self.assertEqual(titulos({'q': 'sur'}), ['Torre Sur'])
        self.assertEqual(titulos({'q': 'T1'}), ['Torre Sur'])

    def test_filtro_y_orden_por_estado(self):
        a = self.registro(self.p1, self.ito1)
        b = self.registro(self.t1, self.ito1, concluido=True)
        self.login(self.pmo)
        orden = [x.pk for x in self.client.get('/tekon/registros/txtss/').context['pagina']]
        self.assertEqual(orden, [b.pk, a.pk])   # el orden lo fija orden_estado: concluido (2) antes que vacío (3)
        verdes = [x.pk for x in self.client.get('/tekon/registros/txtss/', {'estado': 'verde'}).context['pagina']]
        self.assertEqual(verdes, [b.pk])
        rojos = [x.pk for x in self.client.get('/tekon/registros/txtss/', {'estado': 'rojo'}).context['pagina']]
        self.assertEqual(rojos, [a.pk])

    def test_una_pestana_por_tipo_de_la_empresa_y_ninguna_si_no_hay(self):
        self.login(self.pmo)
        tabs = self.client.get('/tekon/registros/txtss/').context['tabs']
        self.assertEqual([t.nombre for t in tabs], sorted(t.nombre for t in self.a.tipos_proyecto.all()))
        from proyectos.models import Proyecto
        Proyecto.objects.filter(empresa=self.a).update(tipo=None)
        self.a.tipos_proyecto.all().delete()
        self.assertEqual(self.client.get('/tekon/registros/txtss/').context['tabs'], [])

    def test_paginacion(self):
        for i in range(30):
            RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1, fecha=date(2026, 1, 1 + i % 28), alternativa='ABCDE'[i // 28 % 5] if i >= 28 else 'A')
        self.login(self.pmo)
        self.assertEqual(len(self.client.get('/tekon/registros/txtss/').context['pagina']), 25)

    def test_el_select_de_proyectos_lista_los_de_la_empresa(self):
        self.login(self.pmo)
        html = self.client.get('/tekon/registros/txtss/activar/').content.decode()
        self.assertIn(f'name="proyectos" value="{self.p1.pk}"', html)
        self.assertNotIn(f'name="proyectos" value="{self.pb.pk}"', html)      # de otra empresa

    def test_visibilidad_del_boton_activar(self):
        for u, espera in ((self.pmo, True), (self.dir1, True), (self.ito1, False), (self.visita, False)):
            self.login(u)
            self.assertEqual(self.client.get('/tekon/registros/txtss/').context['puede_activar'], espera, u.email)


class ActivarTests(TxtssBase):
    def datos(self, **extra):
        d = {'proyectos': [self.p1.pk, self.t1.pk], 'fecha': '2026-03-10', 'alternativa': 'A', 'user': self.ito1.pk}
        d.update(extra)
        return d

    def test_activa_varios_proyectos_de_una_vez(self):
        self.login(self.dir1)
        r = self.client.post('/tekon/registros/txtss/activar/', self.datos())
        self.assertRedirects(r, '/tekon/registros/txtss/', fetch_redirect_response=False)
        self.assertEqual(RegTxtss.objects.filter(user=self.ito1, fecha=date(2026, 3, 10)).count(), 2)

    def test_uno_solo_lleva_directo_al_detalle(self):
        self.login(self.dir1)
        r = self.client.post('/tekon/registros/txtss/activar/', self.datos(proyectos=[self.p1.pk]))
        self.assertRedirects(r, f'/tekon/registros/txtss/{RegTxtss.objects.get().pk}/', fetch_redirect_response=False)

    def test_omite_los_que_ya_existen_y_no_reactiva_los_borrados(self):
        self.registro(self.p1, self.ito1, fecha=date(2026, 3, 10))
        borrado = self.registro(self.t1, self.ito1, fecha=date(2026, 3, 10))
        borrado.soft_delete()
        self.login(self.dir1)
        r = self.client.post('/tekon/registros/txtss/activar/', self.datos(), follow=True)
        self.assertContains(r, 'ya existía')
        # el borrado sigue en la papelera (solo el superusuario restaura) y se creó uno nuevo
        borrado.refresh_from_db()
        self.assertTrue(borrado.is_deleted)
        self.assertEqual(RegTxtss.objects.filter(is_deleted=False).count(), 2)
        self.assertEqual(RegTxtss.objects.filter(is_deleted=False, proyecto=self.t1).count(), 1)

    def test_el_director_solo_puede_asignar_a_gente_de_su_contratista(self):
        self.login(self.dir1)
        r = self.client.post('/tekon/registros/txtss/activar/', self.datos(user=self.ito3.pk))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(RegTxtss.objects.exists())

    def test_no_acepta_proyectos_de_otra_empresa(self):
        self.login(self.pmo)
        r = self.client.post('/tekon/registros/txtss/activar/', self.datos(proyectos=[self.pb.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(RegTxtss.objects.exists())

    def test_sin_permiso_no_activa(self):
        for u in (self.ito1, self.visita, self.patro):
            self.login(u)
            self.assertEqual(self.client.get('/tekon/registros/txtss/activar/').status_code, 403, u.email)
            self.assertEqual(self.client.post('/tekon/registros/txtss/activar/', self.datos()).status_code, 403)
        self.assertFalse(RegTxtss.objects.exists())

    def test_responsable_obligatorio_cuando_puede_elegir(self):
        self.login(self.pmo)
        self.assertEqual(self.client.post('/tekon/registros/txtss/activar/', self.datos(user='')).status_code, 200)
        self.assertFalse(RegTxtss.objects.exists())


class AccionesTests(TxtssBase):
    def setUp(self):
        super().setUp()
        self.r = self.registro()

    def url(self, accion):
        return f'/tekon/registros/txtss/{self.r.pk}/{accion}/'

    def test_detalle_respeta_el_alcance(self):
        self.login(self.ito1)
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').status_code, 200)
        self.login(self.ito2)                      # misma contratista, pero Miembro: solo ve lo propio
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').status_code, 404)
        self.login(self.dir1)
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').status_code, 200)
        self.login(self.dir2)                      # otra contratista
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').status_code, 404)
        self.login(self.pmo_b)                     # otra empresa
        self.assertEqual(self.client.get(f'/otra/registros/txtss/{self.r.pk}/').status_code, 404)

    def test_concluir_y_reabrir_segun_permiso(self):
        self.login(self.ito1)
        self.client.post(self.url('concluir'))
        self.r.refresh_from_db()
        self.assertTrue(self.r.concluido)
        self.client.post(self.url('concluir'))            # el ITO no puede reabrir
        self.assertEqual(self.client.post(self.url('concluir')).status_code, 403)
        self.r.refresh_from_db()
        self.assertTrue(self.r.concluido)
        self.login(self.dir1)
        self.client.post(self.url('concluir'))
        self.r.refresh_from_db()
        self.assertFalse(self.r.concluido)

    def test_la_visita_no_concluye_ni_cambia_nada(self):
        self.login(self.visita)
        for accion in ('concluir', 'copiar', 'fecha', 'responsable', 'eliminar'):
            self.assertEqual(self.client.post(self.url(accion), {'fecha': '2026-01-01'}).status_code, 403, accion)

    def test_copiar_usa_la_siguiente_alternativa_y_no_duplica(self):
        self.login(self.ito1)
        r = self.client.post(self.url('copiar'))
        nuevo = RegTxtss.objects.get(alternativa='B')
        self.assertRedirects(r, f'/tekon/registros/txtss/{nuevo.pk}/', fetch_redirect_response=False)
        self.assertEqual((nuevo.proyecto, nuevo.user, nuevo.fecha), (self.r.proyecto, self.r.user, self.r.fecha))
        self.client.post(self.url('copiar'))               # B ya existe
        self.assertEqual(RegTxtss.objects.filter(alternativa='B').count(), 1)
        e = self.registro(self.t1, self.ito1, alternativa='E')
        self.client.post(f'/tekon/registros/txtss/{e.pk}/copiar/')    # no hay después de E
        self.assertFalse(RegTxtss.objects.filter(proyecto=self.t1).exclude(pk=e.pk).exists())

    def test_cambiar_fecha_solo_si_se_puede_escribir(self):
        self.login(self.ito1)
        self.client.post(self.url('fecha'), {'fecha': '2026-05-01'})
        self.r.refresh_from_db()
        self.assertEqual(self.r.fecha, date(2026, 5, 1))
        self.client.post(self.url('fecha'), {'fecha': 'no-es-fecha'})      # inválida: no cambia
        self.r.refresh_from_db()
        self.assertEqual(self.r.fecha, date(2026, 5, 1))
        RegTxtss.objects.filter(pk=self.r.pk).update(concluido=True)
        self.assertEqual(self.client.post(self.url('fecha'), {'fecha': '2026-06-01'}).status_code, 403)   # concluido
        self.login(self.ito2)
        self.assertEqual(self.client.post(self.url('fecha'), {'fecha': '2026-06-01'}).status_code, 404)   # no es suyo

    def test_cambiar_fecha_a_una_ocupada_da_aviso_sin_romper(self):
        self.registro(self.p1, self.ito1, fecha=date(2026, 7, 7))
        self.login(self.ito1)
        r = self.client.post(self.url('fecha'), {'fecha': '2026-07-07'}, follow=True)
        self.assertEqual(r.status_code, 200)
        self.r.refresh_from_db()
        self.assertNotEqual(self.r.fecha, date(2026, 7, 7))

    def test_cambiar_responsable_y_alternativa(self):
        self.login(self.dir1)
        self.client.post(self.url('responsable'), {'user': self.ito2.pk, 'alternativa': 'C'})
        self.r.refresh_from_db()
        self.assertEqual((self.r.user, self.r.alternativa), (self.ito2, 'C'))
        self.client.post(self.url('responsable'), {'user': self.ito3.pk, 'alternativa': 'C'})   # de otra contratista
        self.r.refresh_from_db()
        self.assertEqual(self.r.user, self.ito2)
        self.login(self.ito2)
        self.assertEqual(self.client.post(self.url('responsable'), {'user': self.ito1.pk}).status_code, 403)

    def test_concluido_bloquea_el_cambio_de_responsable(self):
        RegTxtss.objects.filter(pk=self.r.pk).update(concluido=True)
        self.login(self.dir1)
        self.client.post(self.url('responsable'), {'user': self.ito2.pk})
        self.r.refresh_from_db()
        self.assertEqual(self.r.user, self.ito1)

    def test_eliminar_es_solo_del_superusuario_y_logico(self):
        self.login(self.pmo)
        self.assertEqual(self.client.post(self.url('eliminar')).status_code, 403)
        root = User.objects.create_superuser('root@x.cl', 'x')
        self.login(root)
        self.client.post(self.url('eliminar'))
        self.r.refresh_from_db()
        self.assertTrue(self.r.is_deleted)
        self.assertEqual(self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').status_code, 404)

    def test_el_detalle_ofrece_las_acciones_segun_rol(self):
        self.login(self.ito1)
        html = self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').content.decode()
        self.assertIn('Concluir', html)
        self.assertIn('Cambiar fecha', html)
        self.assertNotIn('Responsable y alternativa', html)
        self.login(self.dir1)
        self.assertIn('Responsable y alternativa', self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').content.decode())
        self.login(self.visita)
        html = self.client.get(f'/tekon/registros/txtss/{self.r.pk}/').content.decode()
        self.assertNotIn('Cambiar fecha', html)
        self.assertNotIn('>Concluir<', html)

    # --- columna de acciones y papelera ---
    def lista(self, user, extra=''):
        self.login(user)
        return self.client.get('/tekon/registros/txtss/' + extra).content.decode()

    def test_la_columna_de_acciones_depende_del_rol(self):
        raiz = User.objects.create_superuser('root@x.cl', 'x')
        casos = {  # usuario: (copiar, editar, eliminar)
            self.visita: (False, False, False), self.ito1: (True, False, False),
            self.dir1: (True, True, False), raiz: (True, True, True),
        }
        for u, (copiar, editar, eliminar) in casos.items():
            html = self.lista(u)
            self.assertIn('Generar PDF', html)
            self.assertEqual('Copiar con la siguiente alternativa' in html, copiar, u)
            self.assertEqual('aria-label="Editar registro"' in html, editar, u)
            self.assertEqual('aria-label="Eliminar"' in html, eliminar, u)

    def test_editar_no_aparece_en_concluidos(self):
        self.r.concluido = True
        self.r.save()
        self.assertNotIn('aria-label="Editar registro"', self.lista(self.dir1))

    def test_la_papelera_es_solo_del_superusuario_y_de_su_empresa(self):
        raiz = User.objects.create_superuser('root@x.cl', 'x')
        self.r.soft_delete()
        ajeno = RegTxtss.objects.create(empresa=self.b, proyecto=self.pb, user=self.pmo_b)
        ajeno.soft_delete()
        html = self.lista(raiz)
        self.assertIn('<h2 class="mb-1 text-lg font-semibold">Borrados</h2>', html)
        self.assertIn(f'/tekon/registros/txtss/{self.r.pk}/restaurar/', html)
        self.assertNotIn(f'/{ajeno.pk}/restaurar/', html)
        for u in (self.pmo, self.dir1, self.ito1):
            self.assertNotIn('Borrados</h2>', self.lista(u))

    def test_restaurar_solo_el_superusuario(self):
        self.r.soft_delete()
        url = self.url('restaurar')
        self.login(self.pmo)
        self.assertEqual(self.client.post(url).status_code, 403)
        raiz = User.objects.create_superuser('root@x.cl', 'x')
        self.login(raiz)
        self.client.post(url)
        self.r.refresh_from_db()
        self.assertFalse(self.r.is_deleted)
        self.assertEqual(self.client.post(url).status_code, 404)   # ya no está borrado

    def test_restaurar_con_clave_ocupada_avisa_sin_romper(self):
        self.r.soft_delete()
        self.registro(self.p1, self.ito1, fecha=self.r.fecha, alternativa=self.r.alternativa)
        raiz = User.objects.create_superuser('root@x.cl', 'x')
        self.login(raiz)
        r = self.client.post(self.url('restaurar'), follow=True)
        self.assertContains(r, 'No se pudo restaurar')
        self.r.refresh_from_db()
        self.assertTrue(self.r.is_deleted)

    def test_restaurar_no_alcanza_otra_empresa(self):
        ajeno = RegTxtss.objects.create(empresa=self.b, proyecto=self.pb, user=self.pmo_b)
        ajeno.soft_delete()
        self.login(User.objects.create_superuser('root@x.cl', 'x'))
        self.assertEqual(self.client.post(f'/tekon/registros/txtss/{ajeno.pk}/restaurar/').status_code, 404)

    def test_formatear_borra_los_datos_y_es_del_superusuario(self):
        from django.contrib.contenttypes.models import ContentType
        from reg_actividades.models import DatoPaso
        DatoPaso.objects.create(empresa=self.a, content_type=ContentType.objects.get_for_model(RegTxtss),
                                object_id=self.r.pk, paso_nombre='x', datos={'a': 1}, tiene_datos=True)
        url = self.url('formatear')
        self.login(self.pmo)
        self.assertEqual(self.client.post(url).status_code, 403)
        self.assertEqual(DatoPaso.objects.count(), 1)
        self.login(User.objects.create_superuser('root@x.cl', 'x'))
        self.client.post(url)
        self.assertEqual(DatoPaso.objects.count(), 0)

    def test_formatear_rechaza_los_concluidos(self):
        self.r.concluido = True
        self.r.save()
        self.login(User.objects.create_superuser('root@x.cl', 'x'))
        r = self.client.post(self.url('formatear'), follow=True)
        self.assertContains(r, 'está concluido')

    def test_next_externo_se_ignora(self):
        self.login(self.dir1)
        r = self.client.post(self.url('responsable'), {'user': self.ito1.pk, 'alternativa': 'B', 'next': 'https://evil.example/'})
        self.assertRedirects(r, f'/tekon/registros/txtss/{self.r.pk}/', fetch_redirect_response=False)
        r = self.client.post(self.url('responsable'), {'user': self.ito1.pk, 'alternativa': 'C', 'next': '/tekon/registros/txtss/?q=a'})
        self.assertRedirects(r, '/tekon/registros/txtss/?q=a', fetch_redirect_response=False)


class PdfTxtssTests(TestCase):
    """El PDF de TX/TSS se genera con su propia cabecera (sin campos de construcción)."""

    def test_pdf_txtss_borrador(self):
        from cuentas.models import User
        from cuentas.roles import RolBase
        from cuentas.services import agregar_miembro, crear_empresa, rol_por_base
        from proyectos.models import Proyecto
        from reg_txtss.models import RegTxtss
        from reg_base import tipos
        empresa = crear_empresa(nombre='Tekon', slug='tekon', modulos=['reg'])
        tipos.habilitar(empresa, 'txtss')
        u = User.objects.create_user('ito@x.cl', 'x')
        agregar_miembro(u, empresa, rol_por_base(empresa, RolBase.MIEMBRO))
        p = Proyecto.objects.create(empresa=empresa, nombre='Sitio 1', codigo='S1')
        r = RegTxtss.objects.create(empresa=empresa, proyecto=p, user=u)
        self.client.force_login(u)
        resp = self.client.get(f'/tekon/registros/txtss/{r.pk}/pdf/')
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b'%PDF'))
        self.assertIn('BORRADOR', resp['Content-Disposition'])

    def test_pdf_de_construccion_sin_proyecto_no_falla(self):
        from reg_base.pdf import generar_pdf
        from reg_construccion.models import RegConstruccion
        from cuentas.services import crear_empresa
        empresa = crear_empresa(nombre='Tekon', slug='tekon', modulos=['reg'])
        r = RegConstruccion.objects.create(empresa=empresa)
        self.assertTrue(generar_pdf(r, 'construccion', None, 'Construcción').startswith(b'%PDF'))


class MapaEnPdfTests(TestCase):
    def test_el_mapa_guardado_entra_al_pdf(self):
        from types import SimpleNamespace

        import pymupdf
        from django.contrib.contenttypes.models import ContentType
        from django.core.files.base import ContentFile

        from cuentas.services import crear_empresa
        from reg_actividades.models import ImagenMapa
        from reg_base.pdf import _mapa_html
        from reg_construccion.models import RegConstruccion
        empresa = crear_empresa(nombre='Tekon', slug='tekon', modulos=['reg'])
        r = RegConstruccion.objects.create(empresa=empresa)
        png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20)).tobytes('png')
        m = ImagenMapa(empresa=empresa, content_type=ContentType.objects.get_for_model(RegConstruccion),
                       object_id=r.pk, etapa='ubicacion', zoom=15, distancia_total_metros=1500)
        m.imagen.save('m.png', ContentFile(png), save=True)
        ctx = SimpleNamespace(registro=r, paso=SimpleNamespace(nombre='ubicacion'))
        pw = SimpleNamespace(widget_slug='mapa_1p', config={})
        archivo = pymupdf.Archive()
        html = _mapa_html(pw, None, ctx, 'Mapa', archivo)
        self.assertIn(f'mapa_{m.pk}.png', html)
        self.assertIn('Distancia', html)
        self.assertTrue(archivo.has_entry(f'mapa_{m.pk}.png'))
        ctx.paso.nombre = 'otro'   # sin imagen guardada: la sección no aparece
        self.assertEqual(_mapa_html(pw, None, ctx, 'Mapa', archivo), '')


class PdfTxtssPlantillaTests(TxtssBase):
    """El PDF recorre los pasos de la plantilla: datos del poste, coordenadas y desfase respecto a la referencia."""

    def test_contexto_con_poste_y_desfase(self):
        from django.contrib.contenttypes.models import ContentType
        from reg_actividades.models import DatoPaso, Paso, PasoAsignado, PasoWidget, Plantilla
        from .pdf import reporte
        a = self.a
        pl = Plantilla.objects.create(empresa=a, nombre='Poste', tipo_registro='txtss', tipo_proyecto=self.poste)
        paso = Paso.objects.create(empresa=a, nombre='poste', titulo='Poste')
        for i, slug in enumerate(('ubicacion_widget', 'poste_form_widget')):
            PasoWidget.objects.create(paso=paso, widget_slug=slug, orden=i)
        PasoAsignado.objects.create(plantilla=pl, paso=paso)
        from proyectos.models import ProyectoUbicacion
        ProyectoUbicacion.objects.create(proyecto=self.p1, etiqueta='Referencia', lat='-33.450000', lon='-70.660000')
        r = RegTxtss.objects.create(empresa=a, proyecto=self.p1, user=self.ito1, fecha=date(2026, 5, 1))
        DatoPaso.objects.create(empresa=a, content_type=ContentType.objects.get_for_model(RegTxtss), object_id=r.pk,
                                paso_nombre='poste', tiene_datos=True, datos={
            'ubicacion_widget': {'lat': -33.451, 'lon': -70.661},
            'poste_form_widget': {'tipo_estructura': 'HA', 'altura': '11,5 m', 'tension': 'Baja', 'luminaria': True}})
        ctx = reporte.contexto(r, {})
        self.assertEqual([s['nombre'] for s in ctx['despues']], ['poste'])
        self.assertEqual([f[0] for f in ctx['geo_filas']], ['Referencia', 'Inspección'])
        self.assertIn('Dentro de tolerancia', ctx['desfase']['estado'])
        self.assertIn(('Luminaria', 'Sí'), ctx['despues'][0]['bloques'][1]['filas'])
        self.assertTrue(reporte.generar(r, {}).startswith(b'%PDF'))


class PdfTxtssMapasComoElOriginalTests(TxtssBase):
    """Las dos imágenes de Google Maps del informe: mismos títulos, leyendas y notas que reg.tekon-rl.cl."""

    def test_titulos_leyendas_y_coordenadas_del_original(self):
        import pymupdf
        from django.contrib.contenttypes.models import ContentType
        from django.core.files.base import ContentFile
        from reg_actividades.models import ImagenMapa, Paso, PasoAsignado, PasoWidget, Plantilla
        from .pdf import reporte
        a = self.a
        pl = Plantilla.objects.create(empresa=a, nombre='Mapas', tipo_registro='txtss', tipo_proyecto=self.poste)
        for nombre, titulo, slug, cfg in (
                ('mandato', 'Referencia', 'mapa_1p', {}),
                ('desfase', 'Desfase', 'mapa_2_puntos', {'paso1': 'Mandato', 'paso2': 'Poste', 'label1': 'M', 'label2': 'P',
                                                         'color1': '#3b82f6', 'color2': '#e74c3c'})):
            paso = Paso.objects.create(empresa=a, nombre=nombre, titulo=titulo)
            PasoWidget.objects.create(paso=paso, widget_slug=slug, config=cfg, orden=0)
            PasoAsignado.objects.create(plantilla=pl, paso=paso)
        r = RegTxtss.objects.create(empresa=a, proyecto=self.p1, user=self.ito1, fecha=date(2026, 5, 1))
        png = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 20, 20)).tobytes('png')
        ct = ContentType.objects.get_for_model(RegTxtss)
        for etapa, pts in (('mandato', [{'lat': -17.868223, 'lon': -63.277012, 'label': 'M', 'color': '#3b82f6', 'size': 'mid'}]),
                           ('desfase', [])):
            m = ImagenMapa(empresa=a, content_type=ct, object_id=r.pk, etapa=etapa, zoom=20, coordenadas=pts)
            m.imagen.save('m.png', ContentFile(png), save=True)
        ctx = reporte.contexto(r, {})
        secciones = {s['nombre']: s for s in ctx['antes'] + ctx['despues']}
        self.assertEqual(secciones['mandato']['titulo'], 'Punto de Referencia')
        self.assertEqual(secciones['desfase']['titulo'], 'Desfase Referencia — Inspección (Poste)')
        mapa1 = secciones['mandato']['bloques'][0]
        self.assertEqual([l['nombre'] for l in mapa1['leyenda']], ['Referencia'])
        self.assertEqual(mapa1['nota'], ['Lat: -17,868223', 'Lon: -63,277012'])
        mapa2 = secciones['desfase']['bloques'][0]
        self.assertEqual([(l['nombre'], l['color']) for l in mapa2['leyenda']],
                         [('Referencia', '#3b82f6'), ('Poste (Inspección)', '#e74c3c')])


class PdfTxtssFormatosDelOriginalTests(TestCase):
    """Coordenadas como las imprimía reg.tekon-rl.cl: decimal con punto y DMS «S 36° 51' 56.32''»."""

    def test_dms_y_fila_geografica(self):
        from .pdf import reporte
        self.assertEqual(reporte._dms_orig(-36.865644, 'N', 'S'), "S 36° 51' 56.32''")
        self.assertEqual(reporte._dms_orig(-73.041111, 'E', 'W'), "W 73° 2' 28.0''")
        self.assertEqual(reporte._fila_geo('Referencia', -36.865556, -73.041111),
                         ['Referencia', '-36.865556', "S 36° 51' 56.0''", '-73.041111', "W 73° 2' 28.0''"])
        self.assertEqual(reporte._dms_orig(None, 'N', 'S'), 'N/A')

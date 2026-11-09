from datetime import date

from django.core.exceptions import ValidationError

from empresas.models import Contratista
from proyectos.models import Proyecto, ProyectoUbicacion
from reg_base.tests import BaseRegistros

from .models import RegConstruccion


class ConstruccionBase(BaseRegistros):
    def crear_visita(self, proyecto=None, user=None, **kw):
        kw.setdefault('fecha', date(2026, 3, 1))
        return RegConstruccion.objects.create(empresa=self.a, proyecto=proyecto or self.t1, user=user or self.ito1, **kw)

    def login(self, user):
        self.client.force_login(user)


class ModeloTests(ConstruccionBase):
    def test_aplica_a_proyectos_de_cualquier_tipo(self):
        self.crear_visita(self.p1)                       # Poste
        self.crear_visita(self.t1)                       # Torre

    def test_una_visita_por_proyecto_y_fecha(self):
        v = self.crear_visita()
        with self.assertRaises(ValidationError):
            self.crear_visita()
        v.soft_delete()
        self.crear_visita()

    def test_numero_de_visita_sigue_el_orden_por_fecha(self):
        v2 = self.crear_visita(fecha=date(2026, 3, 20))
        v1 = self.crear_visita(fecha=date(2026, 3, 5))
        v3 = self.crear_visita(fecha=date(2026, 4, 1))
        self.assertEqual([v.numero_visita for v in (v1, v2, v3)], [1, 2, 3])
        otro = self.crear_visita(self.t2, fecha=date(2026, 3, 25))
        self.assertEqual(otro.numero_visita, 1)           # cuenta por proyecto

    def test_contratista_de_otra_empresa_rechazado(self):
        ajeno = Contratista.objects.create(empresa=self.b, nombre='X', codigo='X')
        with self.assertRaises(ValidationError):
            self.crear_visita(contratista=ajeno)

    def test_coordenadas_prefieren_la_ubicacion_de_construccion(self):
        ProyectoUbicacion.objects.create(proyecto=self.t1, etiqueta='Principal', lat='-33.1', lon='-70.1')
        self.assertEqual(self.crear_visita().coordenadas, (-33.1, -70.1))
        ProyectoUbicacion.objects.create(proyecto=self.t1, etiqueta='Ingeniería', lat='-34.0', lon='-71.0')
        self.assertEqual(RegConstruccion.objects.get().coordenadas, (-34.0, -71.0))
        ProyectoUbicacion.objects.create(proyecto=self.t1, etiqueta='Construcción', lat='-35.0', lon='-72.0')
        self.assertEqual(RegConstruccion.objects.get().coordenadas, (-35.0, -72.0))
        self.assertEqual(self.crear_visita(self.t2).coordenadas, (None, None))


class ActivarYListaTests(ConstruccionBase):
    def datos(self, **extra):
        d = {'proyecto': self.t1.pk, 'fecha': '2026-03-10', 'user': self.ito1.pk, 'contratista': self.c1.pk}
        d.update(extra)
        return d

    def test_activar_crea_la_visita_y_va_al_detalle(self):
        self.login(self.dir1)
        r = self.client.post('/tekon/registros/construccion/activar/', self.datos())
        v = RegConstruccion.objects.get()
        self.assertRedirects(r, f'/tekon/registros/construccion/{v.pk}/', fetch_redirect_response=False)
        self.assertEqual((v.user, v.contratista, v.nombre_obra, v.fecha), (self.ito1, self.c1, 'Torre Sur', date(2026, 3, 10)))

    def test_ofrece_todos_los_proyectos_de_la_empresa(self):
        self.login(self.pmo)
        form = self.client.get('/tekon/registros/construccion/activar/').context['form']
        self.assertEqual(sorted(p.codigo for p in form.fields['proyecto'].queryset), ['P1', 'T1', 'T2'])

    def test_fecha_duplicada_se_rechaza_y_borrada_se_reactiva(self):
        v = self.crear_visita(fecha=date(2026, 3, 10))
        self.login(self.dir1)
        r = self.client.post('/tekon/registros/construccion/activar/', self.datos())
        self.assertContains(r, 'Ya existe una visita')
        v.soft_delete()
        self.client.post('/tekon/registros/construccion/activar/', self.datos(user=self.ito2.pk))
        v.refresh_from_db()
        self.assertEqual((v.is_deleted, v.user), (False, self.ito2))

    def test_sin_permiso_no_activa(self):
        for u in (self.ito1, self.visita, self.patro):
            self.login(u)
            self.assertEqual(self.client.post('/tekon/registros/construccion/activar/', self.datos()).status_code, 403)

    def test_lista_filtra_por_alcance_obra_y_estado(self):
        self.crear_visita(self.t1, self.ito1)
        Proyecto.objects.filter(pk=self.t2.pk).update(estado='PARALIZADO')
        self.crear_visita(self.t2, self.ito3, concluido=True)
        self.login(self.ito1)
        ctx = self.client.get('/tekon/registros/construccion/').context
        self.assertEqual(len(ctx['sitios']), 1)
        self.assertEqual(len(ctx['pagina']), 1)   # un solo sitio visible: queda seleccionado
        self.login(self.pmo)
        url = '/tekon/registros/construccion/'
        sitios = lambda q: sorted(s['proyecto__codigo'] for s in self.client.get(url, q).context['sitios'])
        self.assertEqual(sitios({}), ['T1', 'T2'])
        self.assertEqual(sitios({'q': 'sur'}), ['T1'])
        self.assertIsNone(self.client.get(url).context['pagina'])
        get = lambda q: [v.proyecto.codigo for v in self.client.get(url, q).context['pagina']]
        self.assertEqual(get({'proyecto': self.t2.pk}), ['T2'])
        self.assertEqual(get({'proyecto': self.t2.pk, 'obra': 'paralizado'}), ['T2'])
        self.assertEqual(get({'proyecto': self.t2.pk, 'estado': 'verde'}), ['T2'])
        self.assertEqual(get({'proyecto': self.t1.pk, 'estado': 'verde'}), [])


class DetalleYDatosTests(ConstruccionBase):
    def setUp(self):
        super().setUp()
        self.v = self.crear_visita()

    def url(self, accion=''):
        return f'/tekon/registros/construccion/{self.v.pk}/{accion + "/" if accion else ""}'

    def test_pdf_borrador_y_concluido(self):
        self.login(self.ito1)
        r = self.client.get(self.url('pdf'))
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/pdf'))
        self.assertTrue(r.content.startswith(b'%PDF'))
        self.assertIn('borrador', r['Content-Disposition'])
        self.v.concluido = True
        self.v.save()
        self.assertNotIn('borrador', self.client.get(self.url('pdf'))['Content-Disposition'])

    def test_lista_dibuja_filas_con_sitio_seleccionado(self):
        self.login(self.ito1)
        r = self.client.get(f'/tekon/registros/construccion/?proyecto={self.t1.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '<progress')

    def test_el_responsable_edita_los_datos_de_la_obra(self):
        self.login(self.ito1)
        r = self.client.post(self.url('datos'), {
            'fecha': '2026-03-05', 'nombre_obra': 'Torre Sur v2', 'descripcion': 'Nueva', 'revision': 2,
            'estado_obra': 'PARALIZADO', 'contratista': self.c1.pk,
        })
        self.assertRedirects(r, self.url(), fetch_redirect_response=False)
        self.v.refresh_from_db()
        # el nombre de la obra ya no se edita aquí (es el título de la página): se ignora aunque llegue en el POST
        self.assertEqual((self.v.nombre_obra, self.v.revision, self.v.estado_obra, self.v.contratista, self.v.fecha),
                         ('', 2, 'PARALIZADO', self.c1, date(2026, 3, 5)))

    def test_no_acepta_contratista_de_otra_empresa_ni_estado_invalido(self):
        ajeno = Contratista.objects.create(empresa=self.b, nombre='X', codigo='X')
        self.login(self.ito1)
        base = {'fecha': '2026-03-05', 'nombre_obra': 'x', 'revision': 0, 'estado_obra': 'CONSTRUCCION'}
        self.client.post(self.url('datos'), {**base, 'contratista': ajeno.pk})
        self.client.post(self.url('datos'), {**base, 'estado_obra': 'inventado'})
        self.v.refresh_from_db()
        self.assertEqual((self.v.contratista, self.v.nombre_obra), (None, ''))

    def test_concluida_o_ajena_o_de_solo_lectura_no_se_edita(self):
        datos = {'fecha': '2026-03-05', 'nombre_obra': 'hack', 'revision': 0, 'estado_obra': 'CONSTRUCCION'}
        self.login(self.visita)
        self.assertEqual(self.client.post(self.url('datos'), datos).status_code, 403)
        self.login(self.ito2)
        self.assertEqual(self.client.post(self.url('datos'), datos).status_code, 404)
        RegConstruccion.objects.filter(pk=self.v.pk).update(concluido=True)
        self.login(self.ito1)
        self.assertEqual(self.client.post(self.url('datos'), datos).status_code, 403)
        self.v.refresh_from_db()
        self.assertNotEqual(self.v.nombre_obra, 'hack')

    def test_concluir_reabrir_y_eliminar(self):
        self.login(self.ito1)
        self.client.post(self.url('concluir'))
        self.v.refresh_from_db()
        self.assertTrue(self.v.concluido)
        self.assertEqual(self.client.post(self.url('concluir')).status_code, 403)    # el ITO no reabre
        self.login(self.pmo)
        self.client.post(self.url('concluir'))
        self.v.refresh_from_db()
        self.assertFalse(self.v.concluido)
        self.assertEqual(self.client.post(self.url('eliminar')).status_code, 403)    # eliminar es de superusuario
        from cuentas.models import User
        root = User.objects.create_superuser('root@x.cl', 'x')
        self.login(root)
        self.client.post(self.url('eliminar'))
        self.v.refresh_from_db()
        self.assertTrue(self.v.is_deleted)

    def test_el_detalle_lista_las_visitas_del_proyecto_dentro_del_alcance(self):
        v2 = self.crear_visita(fecha=date(2026, 4, 2))
        ajena = self.crear_visita(fecha=date(2026, 5, 2), user=self.ito3)        # de otra contratista
        self.login(self.dir1)
        visitas = list(self.client.get(self.url()).context['visitas'])
        self.assertEqual([v.pk for v in visitas], [self.v.pk, v2.pk])
        self.login(self.pmo)
        self.assertIn(ajena.pk, [v.pk for v in self.client.get(self.url()).context['visitas']])

    def test_otra_empresa_no_ve_la_visita(self):
        self.login(self.pmo_b)
        self.assertEqual(self.client.get(f'/otra/registros/construccion/{self.v.pk}/').status_code, 404)



class EliminarContratistaDefinitivoTests(ConstruccionBase):
    """Solo el superusuario borra un contratista de la papelera; avisa de los registros ligados."""

    def papelera(self, c):
        c.is_deleted = True
        c.activo = False
        c.save()
        return f'/tekon/config/contratistas/{c.pk}/eliminar-definitivo/'

    def test_avisa_de_los_registros_ligados_y_los_deja_sin_contratista(self):
        libre = Contratista.objects.create(empresa=self.a, nombre='Libre', codigo='C9')  # sin miembros
        visita = self.crear_visita(contratista=libre)
        url = self.papelera(libre)
        self.login(self.root)
        self.assertContains(self.client.get(url), 'sin contratista')
        self.client.post(url)
        self.assertFalse(Contratista.objects.filter(pk=libre.pk).exists())
        visita.refresh_from_db()
        self.assertIsNone(visita.contratista)

    def test_con_miembros_ligados_no_se_elimina(self):
        url = self.papelera(self.c1)  # dir1, ito1, ito2 pertenecen a c1
        self.login(self.root)
        self.client.post(url)
        self.assertTrue(Contratista.objects.filter(pk=self.c1.pk).exists())

    def test_solo_superusuario_y_solo_desde_la_papelera(self):
        url = self.papelera(self.c2)
        self.login(self.pmo)
        self.client.post(url)
        self.assertTrue(Contratista.objects.filter(pk=self.c2.pk).exists())
        self.login(self.root)
        self.assertEqual(self.client.post(f'/tekon/config/contratistas/{self.c1.pk}/eliminar-definitivo/').status_code, 404)

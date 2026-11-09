"""Integridad de Construcción: visita posterior concluida, nueva visita, reasignar ITO, eliminar."""
from datetime import date

from reg_construccion.bloqueo import MENSAJE_POSTERIOR_CONCLUIDA, hay_posterior_concluida
from reg_construccion.models import RegConstruccion

from .tests_avance import SLUG, AvanceBase


class IntegridadTests(AvanceBase):
    def setUp(self):
        super().setUp()
        self.v1 = self.crear_visita(date(2026, 3, 1))
        self.v2 = self.crear_visita(date(2026, 4, 1))
        self.ids = self.definir(self.v1)

    def concluir_v2(self):
        RegConstruccion.objects.filter(pk=self.v2.pk).update(concluido=True)

    def url(self, v, accion):
        return f'/tekon/registros/construccion/{v.pk}/{accion}/'

    # ── regla base ─────────────────────────────────────────────────────────────
    def test_posterior_concluida_solo_cuenta_visitas_de_fechas_posteriores_del_mismo_proyecto(self):
        self.assertFalse(hay_posterior_concluida(self.v1))
        self.concluir_v2()
        self.assertTrue(hay_posterior_concluida(self.v1))
        self.assertFalse(hay_posterior_concluida(self.v2))                    # la propia no cuenta
        otro = self.crear_visita(date(2026, 3, 1), proyecto=self.t2)
        self.assertFalse(hay_posterior_concluida(otro))                       # otro proyecto
        self.assertFalse(hay_posterior_concluida(self.v1, date(2026, 5, 1)))  # fecha posterior a la concluida

    # ── guardar el avance ──────────────────────────────────────────────────────
    def test_no_se_puede_guardar_el_avance_si_hay_una_posterior_concluida(self):
        self.post(self.ito1, self.v1, self.filas(self.ids, ['', ''], ['', ''], ['50', '0']))
        self.assertEqual(RegConstruccion.objects.get(pk=self.v1.pk).avance_pct, 20)
        self.concluir_v2()
        r = self.post(self.ito1, self.v1, self.filas(self.ids, ['', ''], ['', ''], ['80', '80']))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(RegConstruccion.objects.get(pk=self.v1.pk).avance_pct, 20)      # sin cambios
        self.assertEqual(self.tabla(self.v1)['partidas'][0]['actual'], 50.0)
        self.assertContains(self.client.get(self.url(self.v1, 'paso/obra_avance')),
                            MENSAJE_POSTERIOR_CONCLUIDA[:40])

    def test_reabriendo_la_posterior_se_puede_editar_de_nuevo(self):
        self.concluir_v2()
        RegConstruccion.objects.filter(pk=self.v2.pk).update(concluido=False)
        self.post(self.ito1, self.v1, self.filas(self.ids, ['', ''], ['', ''], ['50', '0']))
        self.assertEqual(RegConstruccion.objects.get(pk=self.v1.pk).avance_pct, 20)

    def test_otros_pasos_no_se_bloquean(self):
        self.concluir_v2()
        self.post(self.ito1, self.v1, {'comentario_widget__comentario': 'x'}, paso='obra_libro')
        self.assertEqual(self.client.get(self.url(self.v1, 'paso/obra_libro')).status_code, 200)

    # ── cabecera: fecha ────────────────────────────────────────────────────────
    def test_cambiar_la_fecha_se_bloquea_con_una_posterior_concluida(self):
        self.concluir_v2()
        self.client.force_login(self.pmo)
        self.client.post(self.url(self.v1, 'datos'), {'fecha': '2026-03-10', 'estado_obra': 'CONSTRUCCION', 'revision': 0,
                                                       'nombre_obra': 'X', 'descripcion': '', 'user': self.ito1.pk})
        self.assertEqual(RegConstruccion.objects.get(pk=self.v1.pk).fecha, date(2026, 3, 1))
        # Mover la fecha DESPUÉS de la concluida también cambia el orden: tampoco se permite.
        self.client.post(self.url(self.v1, 'datos'), {'fecha': '2026-05-10', 'estado_obra': 'CONSTRUCCION', 'revision': 0,
                                                       'nombre_obra': 'X', 'descripcion': '', 'user': self.ito1.pk})
        self.assertEqual(RegConstruccion.objects.get(pk=self.v1.pk).fecha, date(2026, 3, 1))

    def test_otros_datos_de_la_cabecera_si_se_pueden_cambiar(self):
        self.concluir_v2()
        self.client.force_login(self.pmo)
        self.client.post(self.url(self.v1, 'datos'), {'fecha': '2026-03-01', 'estado_obra': 'PARALIZADO', 'revision': 3,
                                                       'nombre_obra': 'Nueva', 'descripcion': '', 'user': self.ito1.pk})
        v = RegConstruccion.objects.get(pk=self.v1.pk)
        self.assertEqual((v.estado_obra, v.revision), ('PARALIZADO', 3))

    # ── reasignar ITO ──────────────────────────────────────────────────────────
    def test_el_coordinador_reasigna_el_ito_y_un_ito_no_ve_el_campo(self):
        self.client.force_login(self.pmo)
        r = self.client.get(self.url(self.v1, '').rstrip('/') + '/')
        self.assertIn('user', r.context['form'].fields)
        self.client.post(self.url(self.v1, 'datos'), {'fecha': '2026-03-01', 'estado_obra': 'CONSTRUCCION', 'revision': 0,
                                                       'nombre_obra': 'X', 'descripcion': '', 'user': self.ito2.pk})
        self.assertEqual(RegConstruccion.objects.get(pk=self.v1.pk).user_id, self.ito2.pk)
        self.client.force_login(self.ito2)
        self.assertNotIn('user', self.client.get(self.url(self.v1, '').rstrip('/') + '/').context['form'].fields)
        # Un ITO no puede reasignar aunque forje el campo.
        self.client.post(self.url(self.v1, 'datos'), {'fecha': '2026-03-01', 'estado_obra': 'CONSTRUCCION', 'revision': 0,
                                                       'nombre_obra': 'X', 'descripcion': '', 'user': self.ito1.pk})
        self.assertEqual(RegConstruccion.objects.get(pk=self.v1.pk).user_id, self.ito2.pk)

    # ── eliminar ───────────────────────────────────────────────────────────────
    def test_eliminar_exige_visita_abierta_y_sin_posterior_concluida(self):
        from cuentas.models import User
        root = User.objects.create_superuser('root@x.cl', 'x')
        self.client.force_login(root)
        self.concluir_v2()
        self.client.post(self.url(self.v1, 'eliminar'))
        self.assertFalse(RegConstruccion.objects.get(pk=self.v1.pk).is_deleted)         # posterior concluida
        self.client.post(self.url(self.v2, 'eliminar'))
        self.assertFalse(RegConstruccion.objects.get(pk=self.v2.pk).is_deleted)         # ella misma concluida
        RegConstruccion.objects.filter(pk=self.v2.pk).update(concluido=False)
        self.client.post(self.url(self.v1, 'eliminar'))
        self.assertTrue(RegConstruccion.objects.get(pk=self.v1.pk).is_deleted)

    # ── nueva visita ───────────────────────────────────────────────────────────
    def test_nueva_visita_copia_la_cabecera_de_la_ultima(self):
        RegConstruccion.objects.filter(pk=self.v2.pk).update(
            revision=2, nombre_obra='Torre Sur II', descripcion='Ampliación', contratista=self.c1)
        self.client.force_login(self.pmo)
        r = self.client.post(self.url(self.v1, 'nueva-visita'), {'fecha': '2026-05-01'})
        nueva = RegConstruccion.objects.get(fecha=date(2026, 5, 1))
        self.assertRedirects(r, f'/tekon/registros/construccion/{nueva.pk}/')
        self.assertEqual((nueva.revision, nueva.estado_obra, nueva.nombre_obra, nueva.descripcion, nueva.contratista_id),
                         (2, 'CONSTRUCCION', 'Torre Sur II', 'Ampliación', self.c1.pk))
        self.assertEqual(nueva.user_id, self.v1.user_id)                  # el coordinador no se vuelve responsable
        self.assertEqual(nueva.numero_visita, 3)

    def test_un_ito_que_crea_la_visita_queda_como_responsable(self):
        self.client.force_login(self.ito1)
        self.client.post(self.url(self.v1, 'nueva-visita'), {'fecha': '2026-05-01'})
        self.assertEqual(RegConstruccion.objects.get(fecha=date(2026, 5, 1)).user_id, self.ito1.pk)

    def test_nueva_visita_rechaza_fecha_repetida_o_anterior_a_una_concluida(self):
        self.client.force_login(self.pmo)
        self.client.post(self.url(self.v1, 'nueva-visita'), {'fecha': '2026-04-01'})            # ya existe
        self.assertEqual(RegConstruccion.objects.filter(fecha=date(2026, 4, 1)).count(), 1)
        self.concluir_v2()
        self.client.post(self.url(self.v1, 'nueva-visita'), {'fecha': '2026-03-15'})            # antes de una concluida
        self.assertFalse(RegConstruccion.objects.filter(fecha=date(2026, 3, 15)).exists())

    def test_nueva_visita_exige_permiso_y_alcance(self):
        self.client.force_login(self.visita)                                # Observador: no carga datos
        self.assertEqual(self.client.post(self.url(self.v1, 'nueva-visita'), {'fecha': '2026-05-01'}).status_code, 403)
        self.client.force_login(self.ito3)                                  # ITO de otro contratista: no ve la visita
        self.assertEqual(self.client.post(self.url(self.v1, 'nueva-visita'), {'fecha': '2026-05-01'}).status_code, 404)
        self.assertFalse(RegConstruccion.objects.filter(fecha=date(2026, 5, 1)).exists())

    def test_activar_una_visita_anterior_a_una_concluida_se_rechaza(self):
        self.concluir_v2()
        self.client.force_login(self.pmo)
        self.client.post('/tekon/registros/construccion/activar/',
                         {'proyecto': self.t1.pk, 'fecha': '2026-03-20', 'user': self.ito1.pk})
        self.assertFalse(RegConstruccion.objects.filter(fecha=date(2026, 3, 20)).exists())

    def test_la_siembra_trae_los_14_items_del_original(self):
        from . import servicios
        from .models import Paso, PasoWidget
        servicios.sembrar_ejemplo(self.b)
        pw = PasoWidget.objects.get(paso__empresa=self.b, paso__nombre='obra_avance', widget_slug=SLUG)
        partidas = pw.config['plantillas'][0]['partidas']
        self.assertEqual((len(partidas), sum(p['incidencia'] for p in partidas)), (14, 100))
        self.assertEqual(sorted(Paso.objects.filter(empresa=self.b, nombre__startswith='obra_').values_list('nombre', flat=True)),
                         ['obra_avance', 'obra_comentarios', 'obra_electrico', 'obra_objetivos'])

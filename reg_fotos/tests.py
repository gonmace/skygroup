import io
import shutil
import tempfile
from datetime import date
from pathlib import Path

from django.contrib.contenttypes.models import ContentType
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from reg_base import estado
from reg_base.tests import BaseRegistros
from reg_construccion.models import RegConstruccion
from reg_txtss.models import RegTxtss

from .models import Foto

STORAGES_TEST = {
    'default': {'BACKEND': 'archivos.storage.HybridMediaStorage'},
    'privado': {'BACKEND': 'archivos.storage.HybridPrivateStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def imagen(color=(30, 120, 200), tam=(600, 300), exif=None, formato='JPEG'):
    from PIL import Image
    buf = io.BytesIO()
    img = Image.new('RGB', tam, color)
    kwargs = {'exif': exif} if exif is not None else {}
    img.save(buf, formato, **kwargs)
    return buf.getvalue()


def exif_con_gps_y_fecha():
    from PIL import Image
    ex = Image.Exif()
    ex.get_ifd(0x8769)[0x9003] = '2026:03:10 12:30:00'
    ex.get_ifd(0x8825).update({1: 'S', 2: (33.0, 27.0, 0.0), 3: 'W', 4: (70.0, 39.0, 36.0)})
    return ex


def subida(nombre='foto.jpg', datos=None, tipo='image/jpeg'):
    return SimpleUploadedFile(nombre, datos if datos is not None else imagen(), content_type=tipo)


class FotosBase(BaseRegistros):
    def setUp(self):
        super().setUp()
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        ctx = override_settings(MEDIA_ROOT=str(self.tmp), STORAGES=STORAGES_TEST)
        ctx.enable()
        self.addCleanup(ctx.disable)
        self.r = RegTxtss.objects.create(empresa=self.a, proyecto=self.p1, user=self.ito1)

    def url(self, accion='', clave='txtss', registro=None, etapa='general'):
        return f'/tekon/registros/{clave}/{(registro or self.r).pk}/fotos/{etapa}/{accion + "/" if accion else ""}'

    def subir(self, user, *archivos, ajax=False, **kw):
        self.client.force_login(user)
        extra = {'HTTP_X_REQUESTED_WITH': 'XMLHttpRequest'} if ajax else {}
        return self.client.post(self.url('subir', **kw), {'fotos': list(archivos)}, **extra)

    def en_disco(self):
        base = self.tmp / 'privado'
        return sorted(p for p in base.rglob('*') if p.is_file()) if base.exists() else []


class SubidaTests(FotosBase):
    def test_guarda_original_y_miniatura_en_el_almacenamiento_privado(self):
        r = self.subir(self.ito1, subida(), ajax=True)
        self.assertTrue(r.json()['success'])
        f = Foto.objects.get()
        self.assertEqual((f.empresa, f.etapa, f.object_id, f.subida_por, f.orden), (self.a, 'general', self.r.pk, self.ito1, 1))
        self.assertTrue(f.imagen.name.startswith(f'{self.a.pk}/reg/'))
        self.assertIn('/miniaturas/', f.miniatura.name)
        self.assertEqual(len(self.en_disco()), 2)
        from PIL import Image
        with Image.open(f.miniatura.path) as m:
            self.assertEqual(m.format, 'JPEG')
            self.assertLessEqual(max(m.size), 400)
        self.assertEqual(f.tamano, len(imagen()))

    def test_lee_gps_y_fecha_del_exif(self):
        self.subir(self.ito1, subida(datos=imagen(exif=exif_con_gps_y_fecha())))
        f = Foto.objects.get()
        self.assertAlmostEqual(f.exif_lat, -(33 + 27 / 60), places=5)
        self.assertAlmostEqual(f.exif_lon, -(70 + 39 / 60 + 36 / 3600), places=5)
        local = timezone.localtime(f.exif_fecha)    # el EXIF trae hora local sin zona: se interpreta en la del proyecto
        self.assertEqual((local.year, local.month, local.day, local.hour, local.minute), (2026, 3, 10, 12, 30))

    def test_sin_exif_no_falla(self):
        self.subir(self.ito1, subida())
        f = Foto.objects.get()
        self.assertEqual((f.exif_lat, f.exif_lon, f.exif_fecha), (None, None, None))

    def test_varias_fotos_toman_orden_correlativo(self):
        self.subir(self.ito1, subida('a.jpg'), subida('b.jpg', imagen((9, 9, 9))))
        self.assertEqual(list(Foto.objects.order_by('id').values_list('orden', flat=True)), [1, 2])

    def test_rechaza_lo_que_no_es_una_imagen_real(self):
        casos = [('x.jpg', b'esto no es una imagen'), ('x.exe', imagen()), ('x.svg', b'<svg onload=alert(1)/>'),
                 ('x.html', b'<script>1</script>')]
        for nombre, datos in casos:
            r = self.subir(self.ito1, subida(nombre, datos, 'image/jpeg'), ajax=True)
            self.assertEqual(r.status_code, 400, nombre)
            self.assertFalse(r.json()['success'])
        self.assertEqual((Foto.objects.count(), self.en_disco()), (0, []))

    def test_una_mala_no_impide_subir_las_buenas(self):
        r = self.subir(self.ito1, subida(), subida('mala.jpg', b'nada'), ajax=True)
        d = r.json()
        self.assertTrue(d['success'])
        self.assertEqual((len(d['photos']), Foto.objects.count()), (1, 1))
        self.assertIn('mala.jpg', d['message'])

    def test_respeta_el_tamano_maximo(self):
        with override_settings(FOTO_MAX_SIZE=100):
            r = self.subir(self.ito1, subida(), ajax=True)
        self.assertEqual(r.status_code, 400)
        self.assertIn('máximo', r.json()['message'])

    def test_sin_archivos(self):
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.post(self.url('subir'), {}, HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code, 400)

    def test_formulario_normal_redirige_con_mensaje(self):
        r = self.subir(self.ito1, subida())
        self.assertRedirects(r, self.url(), fetch_redirect_response=False)

    def test_permisos_de_escritura(self):
        self.assertEqual(self.subir(self.visita, subida()).status_code, 403)          # ve pero no escribe
        self.assertEqual(self.subir(self.patro, subida()).status_code, 403)
        self.assertEqual(self.subir(self.ito2, subida()).status_code, 404)            # no es su registro
        self.assertEqual(self.subir(self.dir2, subida()).status_code, 404)            # otra contratista
        self.assertEqual(Foto.objects.count(), 0)
        self.assertEqual(self.subir(self.dir1, subida()).status_code, 302)            # Director de su contratista: ok

    def test_registro_concluido_es_de_solo_lectura(self):
        RegTxtss.objects.filter(pk=self.r.pk).update(concluido=True)
        self.assertEqual(self.subir(self.ito1, subida()).status_code, 403)

    def test_otra_empresa_y_tipo_desconocido(self):
        self.client.force_login(self.pmo_b)
        self.assertEqual(self.client.post(f'/otra/registros/txtss/{self.r.pk}/fotos/general/subir/', {}).status_code, 404)
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.get('/tekon/registros/inventado/1/fotos/general/').status_code, 404)

    def test_funciona_con_construccion(self):
        v = RegConstruccion.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1, fecha=date(2026, 3, 1))
        self.assertEqual(self.subir(self.ito1, subida(), clave='construccion', registro=v).status_code, 302)
        self.assertEqual(Foto.objects.get().content_type, ContentType.objects.get_for_model(RegConstruccion))

    def test_modulo_no_habilitado(self):
        self.a.modulos = ['tar']
        self.a.save()
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(self.url()).status_code, 404)


class GestionTests(FotosBase):
    def setUp(self):
        super().setUp()
        self.subir(self.ito1, subida('a.jpg'), subida('b.jpg', imagen((1, 2, 3))), subida('c.jpg', imagen((4, 5, 6))))
        self.f1, self.f2, self.f3 = Foto.objects.order_by('id')

    def test_editar_descripcion(self):
        self.client.force_login(self.ito1)
        self.client.post(self.url(f'{self.f1.pk}/descripcion'), {'descripcion': '  Vista norte  '})
        self.f1.refresh_from_db()
        self.assertEqual(self.f1.descripcion, 'Vista norte')

    def test_eliminar_borra_los_archivos(self):
        self.client.force_login(self.ito1)
        n = len(self.en_disco())
        self.client.post(self.url(f'{self.f1.pk}/eliminar'))
        self.assertFalse(Foto.objects.filter(pk=self.f1.pk).exists())
        self.assertEqual(len(self.en_disco()), n - 2)     # original + miniatura

    def test_reordenar_y_los_ids_ajenos_se_ignoran(self):
        self.client.force_login(self.ito1)
        otro = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.subir(self.ito1, subida('z.jpg', imagen((7, 7, 7))), registro=otro)
        ajena = Foto.objects.get(object_id=otro.pk)
        r = self.client.post(self.url('orden'), '{"order": [%d, %d, %d, %d]}' % (self.f3.pk, ajena.pk, self.f1.pk, self.f2.pk),
                             content_type='application/json')
        self.assertTrue(r.json()['success'])
        orden = {f.pk: f.orden for f in Foto.objects.filter(object_id=self.r.pk)}
        self.assertEqual((orden[self.f3.pk], orden[self.f1.pk], orden[self.f2.pk]), (1, 2, 3))
        ajena.refresh_from_db()
        self.assertEqual(ajena.orden, 1)      # no se tocó la foto de otro registro

    def test_payload_de_orden_invalido(self):
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.post(self.url('orden'), 'nada', content_type='application/json').status_code, 400)

    def test_no_se_toca_una_foto_de_otro_registro_o_etapa(self):
        otro = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.post(self.url(f'{self.f1.pk}/eliminar', registro=otro)).status_code, 404)
        self.assertEqual(self.client.post(self.url(f'{self.f1.pk}/eliminar', etapa='otra')).status_code, 404)
        self.assertTrue(Foto.objects.filter(pk=self.f1.pk).exists())

    def test_solo_quien_puede_escribir_modifica(self):
        for u in (self.visita, self.patro):
            self.client.force_login(u)
            for accion in (f'{self.f1.pk}/eliminar', f'{self.f1.pk}/descripcion', 'orden'):
                self.assertEqual(self.client.post(self.url(accion), {}).status_code, 403, (u.email, accion))
        self.assertEqual(Foto.objects.count(), 3)

    def test_concluido_bloquea_eliminar(self):
        RegTxtss.objects.filter(pk=self.r.pk).update(concluido=True)
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.post(self.url(f'{self.f1.pk}/eliminar')).status_code, 403)

    def test_galeria_muestra_acciones_solo_a_quien_escribe(self):
        self.client.force_login(self.ito1)
        html = self.client.get(self.url()).content.decode()
        self.assertIn('Subir', html)
        self.assertIn('Eliminar', html)
        self.client.force_login(self.visita)
        html = self.client.get(self.url()).content.decode()
        self.assertNotIn('Eliminar', html)
        self.assertNotIn('name="fotos"', html)
        self.assertEqual(len(self.client.get(self.url()).context['fotos']), 3)

    def test_borrar_fisicamente_el_registro_elimina_sus_fotos_y_archivos(self):
        otro = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.subir(self.ito1, subida('o.jpg', imagen((9, 8, 7))), registro=otro)
        self.assertEqual((Foto.objects.count(), len(self.en_disco())), (4, 8))
        self.r.delete()      # borrado físico (el lógico conserva las fotos)
        self.assertEqual(list(Foto.objects.values_list('object_id', flat=True)), [otro.pk])
        self.assertEqual(len(self.en_disco()), 2)     # solo quedan los archivos de la foto del otro registro

    def test_el_borrado_logico_conserva_las_fotos(self):
        self.r.soft_delete()
        self.assertEqual(Foto.objects.count(), 3)


class ServirTests(FotosBase):
    def setUp(self):
        super().setUp()
        self.subir(self.ito1, subida())
        self.f = Foto.objects.get()

    def get(self, user, ruta, empresa='tekon'):
        self.client.force_login(user)
        return self.client.get(f'/{empresa}/registros/fotos/{self.f.pk}/{ruta}/')

    def test_sirve_imagen_y_miniatura_con_cabeceras_seguras(self):
        r = self.get(self.ito1, 'imagen')
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/jpeg'))
        self.assertEqual(b''.join(r.streaming_content), imagen())
        self.assertEqual(r['Content-Security-Policy'], 'sandbox')
        self.assertEqual(r['X-Content-Type-Options'], 'nosniff')
        self.assertIn('private', r['Cache-Control'])
        m = self.get(self.ito1, 'miniatura')
        self.assertLess(len(b''.join(m.streaming_content)), len(imagen()) + 1)

    def test_el_alcance_del_registro_manda(self):
        self.assertEqual(self.get(self.dir1, 'imagen').status_code, 200)       # director de su contratista
        self.assertEqual(self.get(self.pmo, 'imagen').status_code, 200)
        self.assertEqual(self.get(self.visita, 'imagen').status_code, 200)     # ve todo, solo lectura
        self.assertEqual(self.get(self.ito2, 'imagen').status_code, 404)       # miembro de otro registro
        self.assertEqual(self.get(self.dir2, 'miniatura').status_code, 404)    # otra contratista
        self.assertEqual(self.get(self.pmo_b, 'imagen', 'otra').status_code, 404)   # otra empresa

    def test_sin_acceso_al_reporte_no_ve_las_fotos(self):
        from cuentas.models import RolPermiso
        RolPermiso.objects.create(rol_empresa=self.ito1.membresias.get().rol, capacidad='reg.txtss.ver', habilitado=False)
        self.assertEqual(self.get(self.ito1, 'imagen').status_code, 403)

    def test_etag_permite_304(self):
        etag = self.get(self.ito1, 'miniatura')['ETag']
        self.client.force_login(self.ito1)
        r = self.client.get(f'/tekon/registros/fotos/{self.f.pk}/miniatura/', HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(r.status_code, 304)

    def test_la_ruta_generica_de_privados_no_sirve_fotos_de_registros(self):
        self.client.force_login(self.ito1)
        self.assertEqual(self.client.get(f'/archivos/privado/{self.f.imagen.name}').status_code, 404)
        self.client.force_login(self.pmo)
        self.assertEqual(self.client.get(f'/archivos/privado/{self.f.imagen.name}').status_code, 404)

    def test_registro_eliminado_oculta_sus_fotos(self):
        self.r.soft_delete()
        self.assertEqual(self.get(self.pmo, 'imagen').status_code, 404)

    def test_anonimo_va_al_login(self):
        self.client.logout()
        self.assertEqual(self.client.get(f'/tekon/registros/fotos/{self.f.pk}/imagen/').status_code, 302)


class EstadoYDetalleTests(FotosBase):
    def test_tener_fotos_vuelve_amarillo_el_registro(self):
        vacio = RegTxtss.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        self.subir(self.ito1, subida())
        colores = {r.pk: estado.color_estado(r) for r in RegTxtss.objects.with_estado()}
        self.assertEqual((colores[self.r.pk], colores[vacio.pk]), ('amarillo', 'rojo'))
        RegTxtss.objects.filter(pk=self.r.pk).update(concluido=True)
        self.assertEqual(estado.color_estado(RegTxtss.objects.with_estado().get(pk=self.r.pk)), 'verde')

    def test_etapas_opcionales_de_construccion_no_cuentan(self):
        v = RegConstruccion.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1, fecha=date(2026, 3, 1))
        self.subir(self.ito1, subida(), clave='construccion', registro=v, etapa='obra_libro')
        self.assertEqual(estado.color_estado(RegConstruccion.objects.with_estado().get(pk=v.pk)), 'rojo')
        self.subir(self.ito1, subida('b.jpg', imagen((8, 8, 8))), clave='construccion', registro=v, etapa='obra_avance')
        self.assertEqual(estado.color_estado(RegConstruccion.objects.with_estado().get(pk=v.pk)), 'amarillo')

    def test_el_detalle_muestra_las_fotos_y_el_enlace(self):
        self.subir(self.ito1, subida())
        r = self.client.get(f'/tekon/registros/txtss/{self.r.pk}/')
        self.assertEqual(r.context['fotos_total'], 1)
        self.assertContains(r, 'Subir / ver')
        self.assertContains(r, '/fotos/general/')
        self.client.force_login(self.visita)
        self.assertNotContains(self.client.get(f'/tekon/registros/txtss/{self.r.pk}/'), 'Subir / ver')

    def test_la_lista_refleja_el_color(self):
        self.subir(self.ito1, subida())
        pagina = self.client.get('/tekon/registros/txtss/').context['pagina']
        self.assertEqual([r.color for r in pagina], ['amarillo'])

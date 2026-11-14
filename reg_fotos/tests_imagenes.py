"""Registros → Imágenes: solo superusuario y administradores; descargar ZIP, comprimir y eliminar."""
import io
import json
import zipfile

from django.test import override_settings

from cuentas.models import User
from reg_construccion.models import RegConstruccion
from reg_txtss.models import RegTxtss

from . import imagenes, servicios
from .models import Foto
from .tests import FotosBase, imagen, subida


def _grande():
    """JPEG con ruido (no se comprime a casi nada) para que bajar la calidad sí reduzca el tamaño."""
    import random
    from PIL import Image
    random.seed(7)
    img = Image.new('RGB', (400, 300))
    img.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(400 * 300)])
    b = io.BytesIO()
    img.save(b, 'JPEG', quality=95)
    return b.getvalue()


class ImagenesBase(FotosBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_user('admin@x.cl', 'x')
        self.admin.empresas_administradas.add(self.a)       # administrador de sistema, no miembro
        self.f1 = self.foto(self.r, 'general', _grande())
        self.f2 = self.foto(self.r, 'sitio', imagen((10, 200, 10)))

    def foto(self, registro, etapa, datos, nombre='f.jpg'):
        return servicios.guardar_foto(subida(nombre, datos), autor=self.ito1, registro=registro, etapa=etapa)

    def post(self, user, accion, ids, **extra):
        self.client.force_login(user)
        return self.client.post(f'/tekon/registros/imagenes/{accion}/', json.dumps({'ids': ids, **extra}),
                                content_type='application/json')


class AccesoTests(ImagenesBase):
    def test_superusuario_y_administrador_entran(self):
        for u in (self.root, self.admin):
            self.client.force_login(u)
            r = self.client.get('/tekon/registros/imagenes/')
            self.assertEqual(r.status_code, 200, u.email)
            self.assertContains(r, 'Descargar ZIP')

    def test_los_demas_no_entran_ni_siquiera_el_coordinador(self):
        for u in (self.pmo, self.dir_solo, self.ito1, self.patro, self.visita):
            self.client.force_login(u)
            self.assertEqual(self.client.get('/tekon/registros/imagenes/').status_code, 403, u.email)
            for accion in ('descargar', 'comprimir', 'eliminar'):
                self.assertEqual(self.post(u, accion, [self.f1.pk]).status_code, 403, (u.email, accion))
            self.assertEqual(self.client.get(f'/tekon/registros/imagenes/{self.f1.pk}/archivo/').status_code, 403)
        self.assertEqual(Foto.objects.count(), 2)

    def test_administrador_de_otra_empresa_no_entra(self):
        otro = User.objects.create_user('otro@x.cl', 'x')
        otro.empresas_administradas.add(self.b)
        self.client.force_login(otro)
        self.assertEqual(self.client.get('/tekon/registros/imagenes/').status_code, 403)

    def test_el_menu_solo_lo_muestra_a_administradores(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get('/tekon/registros/imagenes/'), 'href="/tekon/registros/imagenes/"')
        self.client.force_login(self.pmo)
        self.assertNotContains(self.client.get('/tekon/registros/'), 'href="/tekon/registros/imagenes/"')

    def test_anonimo_va_al_login(self):
        self.assertEqual(self.client.get('/tekon/registros/imagenes/').status_code, 302)

    def test_no_sirve_fotos_de_otra_empresa(self):
        from reg_txtss.models import RegTxtss as T
        rb = T.objects.create(empresa=self.b, proyecto=self.pb, user=self.pmo_b)
        ajena = servicios.guardar_foto(subida(), autor=self.pmo_b, registro=rb, etapa='general')
        self.client.force_login(self.root)
        self.assertEqual(self.client.get(f'/tekon/registros/imagenes/{ajena.pk}/archivo/').status_code, 404)
        self.assertEqual(self.post(self.root, 'eliminar', [ajena.pk]).json()['eliminadas'], 0)
        self.assertTrue(Foto.objects.filter(pk=ajena.pk).exists())


class ListaTests(ImagenesBase):
    def test_filtros_y_orden(self):
        self.client.force_login(self.admin)
        get = lambda q='': self.client.get('/tekon/registros/imagenes/' + q)   # noqa: E731
        self.assertEqual(get().context['total'], 2)
        self.assertEqual(get('?etapa=sitio').context['total'], 1)
        self.assertEqual(get('?proyecto=%d' % self.p1.pk).context['total'], 2)
        self.assertEqual(get('?proyecto=%d' % self.t1.pk).context['total'], 0)
        self.assertEqual(get('?tipo=construccion').context['total'], 0)
        self.assertEqual(get('?tipo=txtss').context['total'], 2)
        self.assertEqual(get('?kb_min=%d' % (self.f1.tamano // 1024)).context['total'], 1)
        mayor = [f.pk for f in get('?orden=mayor').context['pagina']]
        self.assertEqual(mayor[0], self.f1.pk)

    def test_sirve_original_y_miniatura(self):
        self.client.force_login(self.admin)
        r = self.client.get(f'/tekon/registros/imagenes/{self.f1.pk}/archivo/')
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'image/jpeg'))
        self.assertEqual(self.client.get(f'/tekon/registros/imagenes/{self.f1.pk}/miniatura/').status_code, 200)


class DescargarTests(ImagenesBase):
    def test_zip_con_las_fotos_ordenadas_por_proyecto(self):
        r = self.post(self.admin, 'descargar', [self.f1.pk, self.f2.pk])
        self.assertEqual((r.status_code, r['Content-Type']), (200, 'application/zip'))
        self.assertIn('attachment', r['Content-Disposition'])
        with zipfile.ZipFile(io.BytesIO(b''.join(r.streaming_content))) as z:
            nombres = z.namelist()
            self.assertEqual(len(nombres), 2)
            self.assertTrue(all(n.startswith('p1/') and n.endswith('.jpg') for n in nombres), nombres)
            self.assertIsNone(z.testzip())

    def test_rechaza_lotes_demasiado_grandes_y_vacios(self):
        self.assertEqual(self.post(self.admin, 'descargar', []).status_code, 400)
        with override_settings():
            antes = imagenes.MAX_ZIP
            imagenes.MAX_ZIP = 1
            self.addCleanup(setattr, imagenes, 'MAX_ZIP', antes)
            self.assertEqual(self.post(self.admin, 'descargar', [self.f1.pk, self.f2.pk]).status_code, 400)


class ComprimirTests(ImagenesBase):
    def test_reduce_el_tamano_conserva_exif_y_resolucion_y_borra_la_version_anterior(self):
        from PIL import Image
        antes = self.f1.imagen.name
        tam = self.f1.tamano
        r = self.post(self.admin, 'comprimir', [self.f1.pk], quality=40)
        d = r.json()
        self.assertEqual((r.status_code, d['success'], d['comprimidas']), (200, True, 1))
        self.assertGreater(d['ahorro'], 0)
        self.f1.refresh_from_db()
        self.assertLess(self.f1.tamano, tam)
        self.assertNotEqual(self.f1.imagen.name, antes)
        self.assertFalse(self.f1.imagen.storage.exists(antes))        # no queda la versión vieja huérfana
        with self.f1.imagen.open('rb') as f, Image.open(f) as im:
            self.assertEqual(im.size, (400, 300))
        self.assertEqual(self.f1.imagen.size, self.f1.tamano)

    def test_conserva_el_exif(self):
        from PIL import Image

        from reg_fotos.tests import exif_con_gps_y_fecha
        f = self.foto(self.r, 'general', imagen(exif=exif_con_gps_y_fecha(), tam=(800, 600)))
        self.post(self.admin, 'comprimir', [f.pk], quality=10)
        f.refresh_from_db()
        with f.imagen.open('rb') as fh, Image.open(fh) as im:
            self.assertTrue(im.info.get('exif'))

    def test_la_calidad_se_acota_y_no_agranda(self):
        d = self.post(self.admin, 'comprimir', [self.f2.pk], quality=999).json()   # 95 como máximo
        self.assertTrue(d['success'])
        self.f2.refresh_from_db()
        self.assertEqual(self.f2.imagen.size, self.f2.tamano)

    def test_si_comprime_fotos_de_un_registro_concluido(self):
        """Comprimir no cambia el contenido (misma resolución y EXIF): es donde está casi todo el peso."""
        self.r.concluido = True
        self.r.save()
        d = self.post(self.admin, 'comprimir', [self.f1.pk], quality=40).json()
        self.assertEqual((d['comprimidas'], d['omitidas']), (1, 0))

    def test_explica_por_que_no_comprimio(self):
        """Una foto ya comprimida a esa calidad no se reduce más: se informa «ya optimizadas», no solo «0»."""
        self.post(self.admin, 'comprimir', [self.f1.pk], quality=40)
        d = self.post(self.admin, 'comprimir', [self.f1.pk], quality=95).json()   # más calidad que la de origen: no baja
        self.assertEqual((d['comprimidas'], d['sin_ahorro'], d['no_jpeg']), (0, 1, 0))
        self.assertIn('ya estaban optimizadas', d['message'])

    def test_lote_maximo(self):
        self.assertEqual(self.post(self.admin, 'comprimir', list(range(1, imagenes.MAX_COMPRIMIR + 2))).status_code, 400)


class EliminarTests(ImagenesBase):
    def test_borra_filas_y_archivos(self):
        self.assertEqual(len(self.en_disco()), 4)
        d = self.post(self.admin, 'eliminar', [self.f1.pk, self.f2.pk]).json()
        self.assertEqual((d['success'], d['eliminadas'], d['omitidas']), (True, 2, 0))
        self.assertFalse(Foto.objects.exists())
        self.assertEqual(self.en_disco(), [])

    def test_no_elimina_fotos_de_registros_concluidos(self):
        self.r.concluido = True
        self.r.save()
        d = self.post(self.root, 'eliminar', [self.f1.pk, self.f2.pk]).json()
        self.assertEqual((d['eliminadas'], d['omitidas']), (0, 2))
        self.assertEqual(Foto.objects.count(), 2)

    def test_solo_post(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get('/tekon/registros/imagenes/eliminar/').status_code, 405)

    def test_json_invalido(self):
        self.client.force_login(self.admin)
        r = self.client.post('/tekon/registros/imagenes/eliminar/', 'no es json', content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_recalcula_lo_completo_de_construccion(self):
        """Borrar fotos dispara las señales del registro (p. ej. «completo» de Construcción)."""
        v = RegConstruccion.objects.create(empresa=self.a, proyecto=self.t1, user=self.ito1)
        f = self.foto(v, 'obra_objetivos', imagen())
        self.post(self.admin, 'eliminar', [f.pk])
        self.assertFalse(Foto.objects.filter(pk=f.pk).exists())
        self.assertFalse(RegTxtss.objects.get(pk=self.r.pk).concluido)

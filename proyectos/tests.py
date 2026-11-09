from django.test import TestCase, override_settings

from cuentas.models import User
from cuentas.roles import RolBase
from cuentas.services import agregar_miembro, crear_empresa, rol_por_base

from .models import Proyecto, TipoProyecto

AJUSTES = dict(
    SECURE_SSL_REDIRECT=False,
    CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}},
    STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    },
)


def datos(**extra):
    base = {'nombre': 'Torre Norte', 'codigo': 'TX-001', 'estado': 'CONSTRUCCION',
            'ubicaciones-TOTAL_FORMS': 0, 'ubicaciones-INITIAL_FORMS': 0,
            'ubicaciones-MIN_NUM_FORMS': 0, 'ubicaciones-MAX_NUM_FORMS': 1000}
    base.update(extra)
    return base


@override_settings(**AJUSTES)
class ProyectosTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.a = crear_empresa(nombre='Tekon', slug='tekon', termino_proyecto_singular='Sitio',
                              termino_proyecto_plural='Sitios')
        cls.b = crear_empresa(nombre='Embol', slug='embol')
        cls.pmo = User.objects.create_user('pmo@example.com', 'x')
        agregar_miembro(cls.pmo, cls.a, rol_por_base(cls.a, RolBase.COORDINADOR))
        cls.lector = User.objects.create_user('lector@example.com', 'x')
        agregar_miembro(cls.lector, cls.a, rol_por_base(cls.a, RolBase.OBSERVADOR))
        cls.pmo_b = User.objects.create_user('pmob@example.com', 'x')
        agregar_miembro(cls.pmo_b, cls.b, rol_por_base(cls.b, RolBase.COORDINADOR))
        cls.torre = TipoProyecto.objects.create(empresa=cls.a, nombre='Torre')
        cls.p = Proyecto.objects.create(empresa=cls.a, nombre='Sitio Uno', codigo='A-1', tipo=cls.torre, ciudad='Santiago')
        cls.pb = Proyecto.objects.create(empresa=cls.b, nombre='Otra empresa', codigo='A-1')


    def test_proyecto_sin_tipo_muestra_el_tipo_por_defecto(self):
        sin = Proyecto.objects.create(empresa=self.a, nombre='Sin tipo', codigo='A-2')
        self.client.force_login(self.pmo)
        html = self.client.get('/tekon/proyectos/').content.decode()
        self.assertIn('badge-outline">Sitio<', html)                                  # término de la empresa, sin tono
        self.assertIn(f'badge-outline badge-tipo-{self.torre.color_idx}">Torre<', html)   # tipo real, con su tono
        self.assertContains(self.client.get(f'/tekon/proyectos/{sin.pk}/'), 'badge-outline">Sitio<')

    def test_titulo_y_menu_usan_el_termino_de_la_empresa(self):
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/proyectos/')
        self.assertContains(r, 'Sitios')
        self.assertIn('Sitios', [i['nombre'] for i in r.context['menu_lateral']])

    def test_vista_mapa_solo_con_proyectos_ubicados_y_con_tipo(self):
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/proyectos/?vista=mapa')
        self.assertEqual(r.context['puntos'], [])
        self.assertNotContains(r, 'data-proyectos-mapa')
        self.p.ubicaciones.create(etiqueta='Principal', lat='-33.45', lon='-70.66')
        sin = Proyecto.objects.create(empresa=self.a, nombre='Sin tipo', codigo='A-9')
        sin.ubicaciones.create(etiqueta='Principal', lat='-33.5', lon='-70.7')
        r = self.client.get('/tekon/proyectos/?vista=mapa')
        self.assertEqual({p['tipo'] for p in r.context['puntos']}, {'Torre', 'Sitio'})   # sin tipo → término de la empresa
        self.assertContains(r, 'data-proyectos-mapa')
        self.assertContains(r, 'data-mapa-tipos')
        self.assertNotContains(r, '<table')   # la vista mapa no repite la tabla

    def test_boton_ubicar_solo_con_ubicacion_y_el_mapa_recibe_el_destino(self):
        self.client.force_login(self.pmo)
        self.assertNotContains(self.client.get('/tekon/proyectos/'), 'Ubicar en el mapa')
        self.p.ubicaciones.create(etiqueta='Principal', lat='-33.45', lon='-70.66')
        r = self.client.get('/tekon/proyectos/?q=sitio')
        self.assertContains(r, f'q=sitio&amp;vista=mapa&amp;ubicar={self.p.pk}')
        self.assertContains(r, 'title="Ubicar en el mapa"', count=2)   # un proyecto: tarjeta (móvil) + fila (escritorio)
        r = self.client.get(f'/tekon/proyectos/?vista=mapa&ubicar={self.p.pk}')
        self.assertContains(r, f'data-ubicar="{self.p.pk}"')
        self.assertEqual(r.context['puntos'][0]['id'], self.p.pk)
        self.assertNotContains(self.client.get('/tekon/proyectos/?vista=mapa&ubicar=x'), 'data-ubicar')   # valor inválido

    def test_vista_lista_no_carga_el_mapa(self):
        self.client.force_login(self.pmo)
        self.p.ubicaciones.create(etiqueta='Principal', lat='-33.45', lon='-70.66')
        r = self.client.get('/tekon/proyectos/')
        self.assertEqual(r.context['puntos'], [])
        self.assertNotContains(r, 'data-proyectos-mapa')
        self.assertContains(r, '<table')

    def test_botones_de_tipo_filtran_la_tabla(self):
        poste = TipoProyecto.objects.create(empresa=self.a, nombre='Poste')
        Proyecto.objects.create(empresa=self.a, nombre='Poste Sur', codigo='P-9', tipo=poste)
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/proyectos/')
        self.assertEqual([(b['nombre'], b['n']) for b in r.context['botones_tipo']],
                         [('Todos', 2), ('Poste', 1), ('Torre', 1)])
        r = self.client.get(f'/tekon/proyectos/?tipo={poste.pk}')
        self.assertContains(r, 'Poste Sur')
        self.assertNotContains(r, 'Sitio Uno')
        self.assertContains(r, f'fila-tipo badge-tipo-{poste.color_idx}')
        self.assertContains(r, 'class="segmentado')
        self.assertContains(r, 'aria-current="true"')   # chip activo
        self.assertNotContains(r, '>Filtrar<')
        self.assertContains(r, 'data-autobuscar="3"')

    def test_la_lista_solo_muestra_la_empresa_activa(self):
        self.client.force_login(self.pmo)
        html = self.client.get('/tekon/proyectos/').content.decode()
        self.assertIn('Sitio Uno', html)
        self.assertNotIn('Otra empresa', html)

    def test_no_se_ve_ni_edita_un_proyecto_de_otra_empresa(self):
        self.client.force_login(self.pmo)
        for url in (f'/tekon/proyectos/{self.pb.pk}/', f'/tekon/proyectos/{self.pb.pk}/editar/'):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        self.assertEqual(self.client.post(f'/tekon/proyectos/{self.pb.pk}/eliminar/').status_code, 404)
        self.pb.refresh_from_db()
        self.assertFalse(self.pb.is_deleted)

    def test_interesado_ve_pero_no_modifica(self):
        self.client.force_login(self.lector)
        self.assertEqual(self.client.get('/tekon/proyectos/').status_code, 200)
        self.assertEqual(self.client.get(f'/tekon/proyectos/{self.p.pk}/').status_code, 200)
        self.assertEqual(self.client.get('/tekon/proyectos/nuevo/').status_code, 403)
        self.assertEqual(self.client.post(f'/tekon/proyectos/{self.p.pk}/eliminar/').status_code, 403)

    def test_crear_con_ubicacion_adicional(self):
        self.client.force_login(self.pmo)
        r = self.client.post('/tekon/proyectos/nuevo/', datos(
            tipo=self.torre.pk,
            **{'ubicaciones-TOTAL_FORMS': 1, 'ubicaciones-0-etiqueta': 'Ingeniería',
               'ubicaciones-0-lat': '-33.5', 'ubicaciones-0-lon': '-70.7'},
        ))
        p = Proyecto.objects.get(codigo='TX-001')
        self.assertRedirects(r, f'/tekon/proyectos/{p.pk}/', fetch_redirect_response=False)
        self.assertEqual((p.empresa, p.ubicaciones.get().etiqueta), (self.a, 'Ingeniería'))

    def test_codigo_duplicado_en_la_empresa_rechazado_pero_no_entre_empresas(self):
        self.client.force_login(self.pmo)
        r = self.client.post('/tekon/proyectos/nuevo/', datos(codigo='a-1'))  # ya existe «A-1» (sin distinguir mayúsculas)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Proyecto.objects.filter(empresa=self.a, codigo__iexact='a-1').count(), 1)
        # En otra empresa el mismo código es válido (Otra empresa ya tiene A-1).
        self.client.force_login(self.pmo_b)
        r = self.client.post('/embol/proyectos/nuevo/', datos(codigo='B-9'))
        self.assertEqual(r.status_code, 302)

    def test_no_se_puede_usar_un_tipo_de_otra_empresa(self):
        tipo_b = TipoProyecto.objects.create(empresa=self.b, nombre='Ajeno')
        self.client.force_login(self.pmo)
        r = self.client.post('/tekon/proyectos/nuevo/', datos(tipo=tipo_b.pk))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Proyecto.objects.filter(codigo='TX-001').exists())

    def test_codigo_opcional_y_repetible_vacio(self):
        self.client.force_login(self.pmo)
        for nombre in ('Sin código 1', 'Sin código 2'):
            r = self.client.post('/tekon/proyectos/nuevo/', datos(nombre=nombre, codigo=''))
            self.assertEqual(r.status_code, 302, r.content.decode()[:500] if r.status_code == 200 else '')
        self.assertEqual(Proyecto.objects.filter(empresa=self.a, codigo='').count(), 2)

    def test_eliminar_es_logico_y_libera_el_codigo(self):
        self.client.force_login(self.pmo)
        self.client.post(f'/tekon/proyectos/{self.p.pk}/eliminar/')
        self.p.refresh_from_db()
        self.assertTrue(self.p.is_deleted)
        self.assertEqual(self.client.get(f'/tekon/proyectos/{self.p.pk}/').status_code, 404)
        r = self.client.post('/tekon/proyectos/nuevo/', datos(codigo='A-1'))
        self.assertEqual(r.status_code, 302)

    def test_filtros_y_busqueda(self):
        Proyecto.objects.create(empresa=self.a, nombre='Poste Sur', codigo='P-2', estado='CONCLUIDO')
        self.client.force_login(self.pmo)
        html = self.client.get('/tekon/proyectos/?q=poste').content.decode()
        self.assertIn('Poste Sur', html)
        self.assertNotIn('Sitio Uno', html)
        self.assertIn('Poste Sur', self.client.get('/tekon/proyectos/?estado=CONCLUIDO').content.decode())

    def test_orden_de_la_tabla_por_columna(self):
        Proyecto.objects.create(empresa=self.a, nombre='Zeta', codigo='Z-1', estado='CONCLUIDO')
        Proyecto.objects.create(empresa=self.a, nombre='alfa', codigo='B-1', estado='INGENIERIA')
        self.client.force_login(self.pmo)

        def nombres(qs=''):
            r = self.client.get('/tekon/proyectos/' + qs)
            return [p.nombre for p in r.context['pagina']]

        self.assertEqual(nombres('?orden=nombre'), ['alfa', 'Sitio Uno', 'Zeta'])               # sin distinguir mayúsculas
        self.assertEqual(nombres('?orden=nombre&dir=desc'), ['Zeta', 'Sitio Uno', 'alfa'])
        self.assertEqual(nombres('?orden=estado'), ['alfa', 'Sitio Uno', 'Zeta'])               # ciclo de vida: Ing., Constr., Concl.
        self.assertEqual(nombres('?orden=estado&dir=desc'), ['Zeta', 'Sitio Uno', 'alfa'])
        self.assertEqual(len(nombres('?orden=inventado;drop')), 3)                              # columna inválida: se ignora
        r = self.client.get('/tekon/proyectos/?orden=nombre&q=a')
        self.assertTrue(next(c for c in r.context['columnas'] if c['titulo'] == 'Nombre')['activa'])
        self.assertContains(r, 'q=a&amp;orden=nombre&amp;dir=desc')                            # reclic invierte y conserva filtros

    def test_tipos_crud_y_proteccion(self):
        self.client.force_login(self.pmo)
        self.client.post('/tekon/proyectos/tipos/', {'nombre': 'Poste'})
        self.assertTrue(TipoProyecto.objects.filter(empresa=self.a, nombre='Poste').exists())
        self.client.post('/tekon/proyectos/tipos/', {'nombre': 'poste'})  # duplicado
        self.assertEqual(TipoProyecto.objects.filter(empresa=self.a, nombre__iexact='poste').count(), 1)
        self.client.post(f'/tekon/proyectos/tipos/{self.torre.pk}/eliminar/')  # en uso
        self.assertTrue(TipoProyecto.objects.filter(pk=self.torre.pk).exists())
        tipo_b = TipoProyecto.objects.create(empresa=self.b, nombre='Ajeno')
        self.assertEqual(self.client.post(f'/tekon/proyectos/tipos/{tipo_b.pk}/eliminar/').status_code, 404)

    def test_tipo_con_solo_proyectos_eliminados_se_puede_borrar(self):
        self.client.force_login(self.pmo)
        tipo = TipoProyecto.objects.create(empresa=self.a, nombre='Rooftop')
        borrado = Proyecto.objects.create(empresa=self.a, nombre='Viejo', codigo='A-77', tipo=tipo, is_deleted=True)
        self.client.post(f'/tekon/proyectos/tipos/{tipo.pk}/eliminar/')
        self.assertFalse(TipoProyecto.objects.filter(pk=tipo.pk).exists())
        borrado.refresh_from_db()
        self.assertIsNone(borrado.tipo_id)                                 # el proyecto eliminado se conserva, sin tipo
        activo = Proyecto.objects.create(empresa=self.a, nombre='Nuevo', codigo='A-78', tipo=self.torre)
        self.client.post(f'/tekon/proyectos/tipos/{self.torre.pk}/eliminar/')
        self.assertTrue(TipoProyecto.objects.filter(pk=self.torre.pk).exists() and activo.pk)   # con activos sigue protegido

    def test_slugs_de_rutas_de_la_app_estan_reservados(self):
        from django.core.exceptions import ValidationError
        for slug in ('config', 'proyectos', 'registros', 'tareas', 'jornadas'):
            with self.assertRaises(ValidationError, msg=slug):
                crear_empresa(nombre='X', slug=slug)

    def test_paginacion(self):
        Proyecto.objects.bulk_create([Proyecto(empresa=self.a, nombre=f'P{i}', codigo=f'Z-{i:03d}') for i in range(30)])
        self.client.force_login(self.pmo)
        r = self.client.get('/tekon/proyectos/')
        self.assertEqual(len(r.context['pagina']), 25)
        self.assertEqual(len(self.client.get('/tekon/proyectos/?page=2').context['pagina']), 6)

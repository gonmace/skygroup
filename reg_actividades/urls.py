from django.urls import path

from . import views, views_mapas

app_name = 'reg_actividades'

urlpatterns = [
    # Configuración (antes que las rutas con <clave>)
    path('registros/config/pasos/', views.pasos_config, name='pasos_config'),
    path('registros/config/pasos/<int:pk>/', views.paso_editar, name='paso_editar'),
    path('registros/config/pasos/<int:pk>/eliminar/', views.paso_eliminar, name='paso_eliminar'),
    path('registros/config/pasos/<int:pk>/widgets/agregar/', views.widget_agregar, name='widget_agregar'),
    path('registros/config/pasos/<int:pk>/widgets/<int:widget_id>/', views.widget_editar, name='widget_editar'),
    path('registros/config/pasos/<int:pk>/widgets/<int:widget_id>/eliminar/', views.widget_eliminar, name='widget_eliminar'),
    path('registros/config/plantillas/', views.plantillas, name='plantillas'),
    path('registros/config/plantillas/<int:pk>/', views.plantilla_editar, name='plantilla_editar'),
    path('registros/config/plantillas/<int:pk>/eliminar/', views.plantilla_eliminar, name='plantilla_eliminar'),
    path('registros/config/plantillas/<int:pk>/pasos/agregar/', views.plantilla_paso_agregar, name='plantilla_paso_agregar'),
    path('registros/config/plantillas/<int:pk>/pasos/<int:asignado_id>/orden/', views.plantilla_paso_orden, name='plantilla_paso_orden'),
    path('registros/config/plantillas/<int:pk>/pasos/<int:asignado_id>/quitar/', views.plantilla_paso_quitar, name='plantilla_paso_quitar'),
    path('registros/config/ejemplo/', views.sembrar, name='sembrar'),

    path('registros/<slug:clave>/<int:pk>/pasos/', views.pasos, name='pasos'),
    path('registros/<slug:clave>/<int:pk>/paso/<slug:nombre>/', views.paso, name='paso'),
    path('registros/<slug:clave>/<int:pk>/paso/<slug:nombre>/guardar/', views.guardar, name='guardar'),
    path('registros/<slug:clave>/<int:pk>/paso/<slug:nombre>/mapa/guardar/', views_mapas.guardar, name='mapa_guardar'),
    path('registros/<slug:clave>/<int:pk>/paso/<slug:nombre>/mapa/imagen/', views_mapas.imagen, name='mapa_imagen'),
]

from django.urls import path

from . import views, views_admin, views_plantillas

app_name = 'apu_generador'

urlpatterns = [
    path('apu/generar/', views.nuevo, name='nuevo'),
    path('apu/pendientes/', views.pendientes, name='pendientes'),
    path('apu/borrador/<int:pk>/continuar/', views.continuar, name='continuar'),
    path('apu/borrador/<int:pk>/actividad/', views.actividad, name='actividad'),
    path('apu/borrador/<int:pk>/resultado/', views.resultado, name='resultado'),
    path('apu/borrador/<int:pk>/precio/', views.precio, name='precio'),
    path('apu/borrador/<int:pk>/fila/', views.fila, name='fila'),
    path('apu/borrador/<int:pk>/sugerir-precios/', views.sugerir_precios, name='sugerir_precios'),
    path('apu/borrador/<int:pk>/guardar-apu/', views.guardar_apu, name='guardar_apu'),
    path('apu/borrador/<int:pk>/modificar/', views.modificar, name='modificar'),
    path('apu/borrador/<int:pk>/revision/', views.revision, name='revision'),
    path('apu/borrador/<int:pk>/eliminar/', views.eliminar, name='eliminar'),
    path('apu/borrador/<int:pk>/<slug:slug>/', views.paso, name='paso'),
    path('apu/borrador/<int:pk>/<slug:slug>/proponer/', views.proponer, name='proponer'),
    path('apu/borrador/<int:pk>/<slug:slug>/guardar/', views.guardar, name='guardar'),
    path('apu/lista/<int:pk>/reutilizar/', views.reutilizar, name='reutilizar'),
    path('apu/lista/<int:pk>/modificar/', views.modificar_apu, name='modificar_apu'),
    path('apu/usuarios/', views_admin.usuarios, name='usuarios'),
    path('apu/usuarios/empresa/', views_admin.limite_empresa, name='limite_empresa'),
    path('apu/usuarios/<int:pk>/limite/', views_admin.limite_persona, name='limite_persona'),
    path('apu/plantillas/', views_plantillas.plantillas, name='plantillas'),
    path('apu/plantillas/nueva/', views_plantillas.plantilla_nueva, name='plantilla_nueva'),
    path('apu/plantillas/<int:pk>/', views_plantillas.plantilla, name='plantilla'),
    path('apu/plantillas/<int:pk>/datos/', views_plantillas.plantilla_datos, name='plantilla_datos'),
    path('apu/plantillas/<int:pk>/<slug:paso>/guardar/', views_plantillas.prompt_guardar, name='prompt_guardar'),
    path('apu/plantillas/<int:pk>/<slug:paso>/probar/', views_plantillas.prompt_probar, name='prompt_probar'),
    path('apu/plantillas/<int:pk>/restaurar/<int:version_pk>/', views_plantillas.prompt_restaurar, name='prompt_restaurar'),
    path('apu/consumo-ia/', views_admin.consumo_ia, name='consumo_ia'),
    path('apu/consumo-ia/reiniciar/', views_admin.consumo_ia_reiniciar, name='consumo_ia_reiniciar'),
    path('apu/consumo-ia/tarifas/verificar/', views_admin.tarifas_verificar, name='tarifas_verificar'),
    path('apu/consumo-ia/tarifas/aplicar/', views_admin.tarifas_aplicar, name='tarifas_aplicar'),
    path('apu/consumo-ia/tarifas/<int:pk>/', views_admin.tarifa_editar, name='tarifa_editar'),
]

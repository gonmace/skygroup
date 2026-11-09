from django.urls import path

from . import views

app_name = 'jor_reportes'

urlpatterns = [
    path('jornadas/asistencia/', views.asistencia, name='asistencia'),
    path('jornadas/asistencia/excel/', views.asistencia_excel, name='asistencia_excel'),
    path('jornadas/estadisticas/', views.estadisticas, name='estadisticas'),
    path('jornadas/estadisticas/excel/', views.estadisticas_excel, name='estadisticas_excel'),
    path('jornadas/certificado/', views.certificado_pago, name='certificado'),
    path('jornadas/certificado/plantilla-base/', views.descargar_plantilla_base, name='plantilla_base'),
    path('jornadas/certificado/plantilla-modelo/', views.descargar_plantilla_modelo, name='plantilla_modelo'),
    path('jornadas/certificado/plantilla-actual/', views.descargar_plantilla_actual, name='plantilla_actual'),
]

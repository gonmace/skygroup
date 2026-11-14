from django.urls import path

from . import views

app_name = 'panel'

urlpatterns = [
    # Plataforma (superusuario)
    path('panel/', views.empresas, name='empresas'),
    path('panel/empresas/nueva/', views.empresa_editar, name='empresa_nueva'),
    path('panel/empresas/<int:pk>/', views.empresa_editar, name='empresa_editar'),
    path('panel/administradores/', views.administradores, name='administradores'),
    path('panel/administradores/nuevo/', views.administrador_editar, name='administrador_nuevo'),
    path('panel/administradores/<int:pk>/', views.administrador_editar, name='administrador_editar'),
    path('panel/administradores/<int:pk>/quitar/', views.administrador_quitar, name='administrador_quitar'),
    path('panel/correo/', views.correo, name='correo'),
    path('panel/credenciales/', views.credenciales, name='credenciales'),
    path('panel/correo/probar/', views.correo_probar, name='correo_probar'),
    path('panel/almacenamiento/', views.almacenamiento, name='almacenamiento'),
    path('panel/almacenamiento/migrar/', views.almacenamiento_migrar, name='almacenamiento_migrar'),
    # Empresa (prefijo /<slug>/ lo agrega el middleware)
    path('config/marca/', views.marca, name='marca'),
    path('config/miembros/', views.miembros, name='miembros'),
    path('config/miembros/nuevo/', views.miembro_nuevo, name='miembro_nuevo'),
    path('config/miembros/<int:pk>/', views.miembro_editar, name='miembro_editar'),
    path('config/miembros/<int:pk>/rapido/', views.miembro_rapido, name='miembro_rapido'),
    path('config/miembros/<int:pk>/reinvitar/', views.miembro_reinvitar, name='miembro_reinvitar'),
    path('config/miembros/<int:pk>/bloquear/', views.miembro_bloquear, name='miembro_bloquear'),
    path('config/miembros/<int:pk>/eliminar/', views.miembro_eliminar, name='miembro_eliminar'),
    path('config/miembros/<int:pk>/restaurar/', views.miembro_restaurar, name='miembro_restaurar'),
    path('config/acceso/', views.acceso, name='acceso'),
    path('config/nextcloud/', views.nextcloud, name='nextcloud'),
    path('config/nextcloud/probar/', views.nextcloud_probar, name='nextcloud_probar'),
    path('config/acceso/dominios/<int:pk>/alternar/', views.acceso_dominio_alternar, name='acceso_dominio_alternar'),
    path('config/acceso/dominios/<int:pk>/eliminar/', views.acceso_dominio_eliminar, name='acceso_dominio_eliminar'),
    path('config/acceso/correos/<int:pk>/eliminar/', views.acceso_correo_eliminar, name='acceso_correo_eliminar'),
    path('config/sedes/', views.sedes, name='sedes'),
    path('config/sedes/nueva/', views.sede_editar, name='sede_nueva'),
    path('config/sedes/<int:pk>/', views.sede_editar, name='sede_editar'),
    path('config/sedes/<int:pk>/eliminar/', views.sede_eliminar, name='sede_eliminar'),
    path('config/sedes/<int:pk>/alternar/', views.sede_alternar, name='sede_alternar'),
    path('config/contratistas/', views.contratistas, name='contratistas'),
    path('config/contratistas/nuevo/', views.contratista_editar, name='contratista_nuevo'),
    path('config/contratistas/<int:pk>/', views.contratista_editar, name='contratista_editar'),
    path('config/contratistas/<int:pk>/eliminar/', views.contratista_eliminar, name='contratista_eliminar'),
    path('config/contratistas/<int:pk>/alternar/', views.contratista_alternar, name='contratista_alternar'),
    path('config/contratistas/<int:pk>/restaurar/', views.contratista_restaurar, name='contratista_restaurar'),
    path('config/contratistas/<int:pk>/eliminar-definitivo/', views.contratista_eliminar_definitivo, name='contratista_eliminar_definitivo'),
    path('config/roles/', views.roles, name='roles'),
    path('config/roles/nuevo/', views.rol_editar, name='rol_nuevo'),
    path('config/roles/<int:pk>/', views.rol_editar, name='rol_editar'),
    path('config/roles/<int:pk>/eliminar/', views.rol_eliminar, name='rol_eliminar'),
    path('config/roles/<int:pk>/permisos/', views.rol_matriz, name='rol_matriz'),
]

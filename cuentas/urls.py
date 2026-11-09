from django.urls import path

from . import views

app_name = 'cuentas'

urlpatterns = [
    path('acceso/login/', views.LoginView.as_view(), name='login'),
    path('acceso/nextcloud/', views.nextcloud_iniciar, name='nextcloud_iniciar'),
    path('acceso/nextcloud/vincular/', views.nextcloud_vincular, name='nextcloud_vincular'),
    path('acceso/nextcloud/desvincular/', views.nextcloud_desvincular, name='nextcloud_desvincular'),
    path('acceso/nextcloud/callback/', views.nextcloud_callback, name='nextcloud_callback'),
    path('acceso/logout/', views.LogoutView.as_view(), name='logout'),
    path('acceso/impersonar/detener/', views.impersonar_detener, name='impersonar_detener'),
    path('acceso/impersonar/<int:pk>/', views.impersonar, name='impersonar'),
    path('acceso/registro/', views.registro, name='registro'),
    path('acceso/registro/<str:token>/', views.registro_confirmar, name='registro_confirmar'),
    path('acceso/recuperar/', views.PasswordResetView.as_view(), name='password_reset'),
    path('acceso/recuperar/enviado/', views.PasswordResetDoneView.as_view(), name='password_reset_hecho'),
    path('acceso/recuperar/<uidb64>/<token>/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirmar'),
    path('acceso/recuperar/completo/', views.PasswordResetCompleteView.as_view(), name='password_reset_completo'),
]

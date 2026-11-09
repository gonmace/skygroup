from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import TemplateView
from django.contrib.sitemaps.views import sitemap
from home.sitemaps import StaticViewSitemap

sitemaps = {
    'static': StaticViewSitemap,
}

urlpatterns = [
    path(settings.ADMIN_URL, admin.site.urls),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', TemplateView.as_view(
        template_name='robots.txt',
        content_type='text/plain',
    )),
    path('', include('cuentas.urls')),
    path('', include('empresas.urls')),
    path('', include('archivos.urls')),
    path('', include('panel.urls')),
    path('', include('notificaciones.urls')),
    path('', include('proyectos.urls')),
    path('', include('tar_tickets.urls')),
    path('', include('reg_base.urls')),
    path('', include('reg_txtss.urls')),
    path('', include('reg_construccion.urls')),
    path('', include('reg_construccion_base.urls')),
    path('', include('reg_fotos.urls')),
    path('', include('reg_actividades.urls')),
    path('', include('jor_empleados.urls')),
    path('', include('jor_diario.urls')),
    path('', include('jor_actividades.urls')),
    path('', include('jor_reportes.urls')),
    path('', include('mje_mensajes.urls')),
    path('', include('home.urls')),
]

if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [path('__reload__/', include('django_browser_reload.urls'))]

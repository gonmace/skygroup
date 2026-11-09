from django import forms
from django.contrib import admin, messages

from .models import MediaStorageConfig
from .storage import build_backend


class MediaStorageConfigForm(forms.ModelForm):
    class Meta:
        model = MediaStorageConfig
        fields = '__all__'
        widgets = {'s3_secret_key': forms.PasswordInput(render_value=True)}


@admin.register(MediaStorageConfig)
class MediaStorageConfigAdmin(admin.ModelAdmin):
    form = MediaStorageConfigForm
    fieldsets = (
        (None, {
            'fields': ('mode', 'cdn_url'),
            'description': 'Por defecto los archivos se guardan en este servidor. Los cambios aplican de inmediato; '
                           'los archivos ya subidos NO se mueven solos: usa "make sync-media".',
        }),
        ('Almacenamiento S3-compatible (solo modo S3)', {
            'fields': ('s3_endpoint_url', 's3_bucket', 's3_private_bucket', 's3_region', 's3_access_key', 's3_secret_key',
                       's3_location', 's3_path_style'),
        }),
    )

    def has_add_permission(self, request):
        return not MediaStorageConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        # Singleton: ir directo al formulario de edición
        from django.shortcuts import redirect
        from django.urls import reverse

        obj = MediaStorageConfig.objects.first()
        if obj:
            return redirect(reverse('admin:archivos_mediastorageconfig_change', args=[obj.pk]))
        return super().changelist_view(request, extra_context)

    def response_add(self, request, obj, post_url_continue=None):
        from django.shortcuts import redirect
        from django.urls import reverse
        super().response_add(request, obj, post_url_continue)
        return redirect(reverse('admin:archivos_mediastorageconfig_change', args=[obj.pk]))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.mode != MediaStorageConfig.Mode.S3:
            return
        try:  # prueba de conexión: avisa, no bloquea el guardado
            storage = build_backend(obj.as_dict())
            storage.bucket.meta.client.head_bucket(Bucket=obj.s3_bucket)
            if obj.s3_private_bucket:
                build_backend(obj.as_dict(), privado=True).bucket.meta.client.head_bucket(Bucket=obj.s3_private_bucket)
            messages.success(request, 'Conexión con el bucket verificada.')
            if not obj.s3_private_bucket:
                messages.warning(
                    request,
                    'Sin bucket privado: los archivos privados irán a «privado/» del bucket público. Asegúrate de que '
                    'la política del bucket y de la CDN deniegue la lectura anónima de «privado/*», o define un bucket privado.',
                )
        except Exception as exc:
            messages.warning(request, f'Guardado, pero no se pudo conectar con el bucket: {exc}')

from django.http import Http404, HttpResponse, HttpResponseNotModified

from .paleta import a_css, generar_tema, texto_contraste  # noqa: F401  (texto_contraste: reexportado)


def tema_css(request):
    """Hoja CSS con los colores de marca de la empresa. El CSP (`style-src 'self'`) no
    permite `<style>` inline, así que se sirve como stylesheet del mismo origen, cargada
    DESPUÉS de tailwind_css; sobrescribe las custom properties de DaisyUI. La paleta completa (texto seguro, acento
    derivado, tema oscuro) la calcula `empresas.paleta.generar_tema`."""
    empresa = getattr(request, 'empresa', None)
    if empresa is None:
        raise Http404
    etag = f'"{empresa.pk}-{empresa.version_tema()}"'
    if request.headers.get('If-None-Match') == etag:
        return HttpResponseNotModified()
    css = '\n'.join(filter(None, [
        '/* Colores de marca — generado por empresas.paleta */',
        a_css(generar_tema(empresa.color_primario, empresa.color_primario_oscuro,
                           empresa.color_acento, empresa.color_acento_oscuro)),
    ])) + '\n'
    response = HttpResponse(css, content_type='text/css; charset=utf-8')
    response['ETag'] = etag
    response['Cache-Control'] = 'public, max-age=300'
    return response

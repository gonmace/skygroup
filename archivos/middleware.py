from .models import get_media_config
from .storage import bucket_origin, media_origin


class MediaCspMiddleware:
    """Añade al CSP el origen de la CDN/bucket configurado en el admin (img-src y media-src).
    Debe ir DESPUÉS de CSPMiddleware en MIDDLEWARE (su respuesta se procesa antes)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        cfg = get_media_config()
        origin = media_origin(cfg)
        if origin:
            # Las URLs firmadas de archivos privados salen del bucket, no de la CDN pública.
            origins = list(dict.fromkeys(o for o in (
                origin, bucket_origin(cfg), bucket_origin(cfg, cfg.get('s3_private_bucket')) if cfg.get('s3_private_bucket') else None,
            ) if o))
            update = dict(getattr(response, '_csp_update', None) or {})
            update['img-src'] = origins
            update['media-src'] = ["'self'", *origins]
            response._csp_update = update
        return response

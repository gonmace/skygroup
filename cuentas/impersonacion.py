"""Impersonación: un superusuario navega como otro usuario sin conocer su contraseña.

La sesión sigue siendo la del superusuario (no se hace `login()` del otro, así que no se dispara
`user_logged_in` ni se registran visitas falsas). Solo se guarda en sesión a quién se imita y el
middleware sustituye `request.user` en cada petición, revalidando que el real siga siendo superusuario.
"""
import logging

from django.contrib.auth import get_user_model

SESSION_KEY = 'impersonar_id'
audit = logging.getLogger('cuentas.impersonacion')


class ImpersonacionMiddleware:
    """Debe ir DESPUÉS de AuthenticationMiddleware y ANTES de EmpresaMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.impersonador = None
        pk = request.session.get(SESSION_KEY)
        if pk:
            real = request.user
            objetivo = None
            if real.is_authenticated and real.is_superuser:
                objetivo = (get_user_model().objects
                            .filter(pk=pk, is_active=True, is_superuser=False).first())
            if objetivo is None:
                request.session.pop(SESSION_KEY, None)  # estado inválido: se descarta
            else:
                request.impersonador = real
                request.user = objetivo
        return self.get_response(request)

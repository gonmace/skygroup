from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from . import correos, impersonacion, registro as reg

from .forms import LoginForm, RegistroConfirmarForm, RegistroForm
from .models import Membresia


class LoginView(auth_views.LoginView):
    template_name = 'cuentas/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        empresa = getattr(self.request, 'empresa', None)
        ctx['registro_abierto'] = empresa is not None and reg.hay_dominios(empresa)
        return ctx


class LogoutView(auth_views.LogoutView):
    """Solo POST (Django 5+)."""


class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'cuentas/password_reset.html'
    email_template_name = 'cuentas/email/password_reset.txt'
    subject_template_name = 'cuentas/email/password_reset_asunto.txt'
    success_url = reverse_lazy('cuentas:password_reset_hecho')


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'cuentas/password_reset_hecho.html'


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'cuentas/password_reset_confirmar.html'
    success_url = reverse_lazy('cuentas:password_reset_completo')


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'cuentas/password_reset_completo.html'


def _destino(request):
    nxt = request.POST.get('next', '')
    ok = url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return nxt if ok and nxt else '/'


@login_required
@require_POST
def impersonar(request, pk):
    """Solo un superusuario real (no uno ya impersonando) puede iniciar."""
    if request.impersonador or not request.user.is_superuser:
        raise Http404
    objetivo = get_object_or_404(get_user_model(), pk=pk, is_active=True, is_superuser=False)
    request.session[impersonacion.SESSION_KEY] = objetivo.pk
    impersonacion.audit.warning('IMPERSONAR inicio: %s (id=%s) -> %s (id=%s)',
                                request.user.email, request.user.pk, objetivo.email, objetivo.pk)
    messages.info(request, f'Ahora ves la aplicación como {objetivo.get_full_name() or objetivo.email}.')
    return redirect('/')


@login_required
@require_POST
def impersonar_detener(request):
    real = request.impersonador
    if real is None:
        raise Http404
    impersonacion.audit.warning('IMPERSONAR fin: %s (id=%s) <- %s (id=%s)',
                                real.email, real.pk, request.user.email, request.user.pk)
    request.session.pop(impersonacion.SESSION_KEY, None)
    return redirect(_destino(request))


# ── Alta automática por dominio ───────────────────────────────────────────────

REGISTRO_INTENTOS = 5  # solicitudes por IP y hora


def _empresa_o_404(request):
    empresa = getattr(request, 'empresa', None)
    if empresa is None or not reg.hay_dominios(empresa):
        raise Http404
    return empresa


def _ip(request):
    return request.META.get('REMOTE_ADDR', '')


def registro(request):
    """Pide el correo. La respuesta es SIEMPRE la misma, exista o no la cuenta y esté o no permitido el dominio:
    no se puede usar para averiguar qué correos tienen acceso."""
    empresa = _empresa_o_404(request)
    form = RegistroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        clave = f'registro:{empresa.pk}:{_ip(request)}'
        cache.add(clave, 0, 3600)
        try:
            intentos = cache.incr(clave)
        except ValueError:
            intentos = 1
        if intentos > REGISTRO_INTENTOS:
            messages.error(request, 'Demasiados intentos. Vuelve a probar en una hora.')
            return render(request, 'cuentas/registro.html', {'form': form}, status=429)
        d = form.cleaned_data
        email = d['email'].strip().lower()
        if (reg.dominio_permitido(empresa, email)
                and not Membresia.objects.filter(user__email__iexact=email, empresa=empresa).exists()):
            token = reg.token_registro(email, empresa, d['first_name'], d['last_name'])
            correos.preparar_confirmacion_registro(request, email, empresa, token)()
        return render(request, 'cuentas/registro_enviado.html')
    return render(request, 'cuentas/registro.html', {'form': form})


def registro_confirmar(request, token):
    empresa = _empresa_o_404(request)
    datos = reg.leer_token(token, empresa)
    if datos is None:
        return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
    email = datos['e']
    if reg.dominio_permitido(empresa, email) is None:  # pudo bloquearse o quitarse el dominio tras enviar el enlace
        return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
    User = get_user_model()
    existente = User.objects.filter(email__iexact=email).first()
    if existente is not None:
        # Abrir el enlace demuestra que controla el correo, pero NO inicia sesión: entra con su contraseña.
        resultado = reg.registrar(empresa, email)
        if resultado is None:
            return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
        messages.success(request, 'Listo: ya tienes acceso. Inicia sesión con tu cuenta.')
        return redirect('cuentas:login')
    form = RegistroConfirmarForm(None, request.POST or None,
                                 initial={'first_name': datos.get('n', ''), 'last_name': datos.get('a', '')})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            resultado = reg.registrar(empresa, email, form.cleaned_data['first_name'],
                                      form.cleaned_data['last_name'], form.cleaned_data['new_password1'])
        if resultado is None:
            return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
        user = resultado[0]
        login(request, user, backend='cuentas.backends.EmailBackend')
        return redirect('home')
    return render(request, 'cuentas/registro_confirmar.html', {'form': form, 'email': email})

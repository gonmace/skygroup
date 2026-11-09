"""Módulos cuyos archivos privados se autorizan en sus PROPIAS vistas.

La ruta genérica `/archivos/privado/<empresa_id>/<módulo>/…` solo valida que el usuario pertenezca a
la empresa. Un módulo cuyos archivos requieren una autorización más fina (p. ej. acceso al ticket)
lo registra aquí, y la ruta genérica deja de servirlos.
"""
_PROTEGIDOS = set()


def proteger_modulo(codigo):
    _PROTEGIDOS.add(codigo)


def esta_protegido(codigo):
    return codigo in _PROTEGIDOS

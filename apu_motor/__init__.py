"""Motor de cálculo de APU (Análisis de Precios Unitarios).

Python puro: no importa Django ni toca la base de datos. No conoce ningún país: las reglas viven en un
*perfil* (dict/JSON), ver `perfil.py`. Uso:

    from apu_motor import calcular, validar_perfil
    perfil = validar_perfil(datos)
    resultado = calcular(perfil, {'MAT': 100, 'MO': 50, 'EQ': 20})
    resultado.total      # precio unitario
    resultado.lineas     # {codigo: Decimal}
"""
from .motor import Resultado, calcular
from .perfil import PerfilInvalido, validar_perfil

__all__ = ['calcular', 'validar_perfil', 'Resultado', 'PerfilInvalido']

"""Perfiles de ejemplo (datos, no código). Los porcentajes son valores típicos y se ajustan en cada perfil.

Por ahora solo Bolivia, tomado del plan. Chile se agrega cuando se tengan presupuestos reales para validarlo."""

BOLIVIA_ESTANDAR = {
    'perfil': 'Bolivia - estándar',
    'moneda': 'BOB',
    'redondeo': {'linea': None, 'total': 2, 'modo': 'HALF_UP'},
    'lineas': [
        {'cod': 'MAT', 'nombre': 'Materiales', 'tipo': 'suma', 'grupo': 'MAT'},
        {'cod': 'MO', 'nombre': 'Mano de obra', 'tipo': 'suma', 'grupo': 'MO'},
        {'cod': 'BS', 'nombre': 'Beneficios sociales', 'tipo': 'porcentaje', 'pct': 0.55, 'base': ['MO']},
        {'cod': 'IVA_MO', 'nombre': 'IVA s/ mano de obra', 'tipo': 'porcentaje', 'pct': 0.1494,
         'base': ['MO', 'BS']},
        {'cod': 'TOT_MO', 'nombre': 'Total mano de obra', 'tipo': 'subtotal', 'base': ['MO', 'BS', 'IVA_MO']},
        {'cod': 'HERR', 'nombre': 'Herramientas menores', 'tipo': 'porcentaje', 'pct': 0.05, 'base': ['TOT_MO']},
        {'cod': 'EQ', 'nombre': 'Equipo', 'tipo': 'suma', 'grupo': 'EQ'},
        {'cod': 'TOT_EQ', 'nombre': 'Equipo y maquinaria', 'tipo': 'subtotal', 'base': ['EQ', 'HERR']},
        {'cod': 'DIRECTO', 'nombre': 'Costo directo', 'tipo': 'subtotal', 'base': ['MAT', 'TOT_MO', 'TOT_EQ']},
        {'cod': 'GG', 'nombre': 'Gastos generales', 'tipo': 'porcentaje', 'pct': 0.10, 'base': ['DIRECTO']},
        {'cod': 'UT', 'nombre': 'Utilidad', 'tipo': 'porcentaje', 'pct': 0.10, 'base': ['DIRECTO', 'GG']},
        {'cod': 'IT', 'nombre': 'Impuesto a las Transacciones', 'tipo': 'porcentaje', 'pct': 0.0309,
         'base': ['DIRECTO', 'GG', 'UT']},
        {'cod': 'PU', 'nombre': 'Precio unitario', 'tipo': 'subtotal', 'base': ['DIRECTO', 'GG', 'UT', 'IT'],
         'total': True},
    ],
}

# Valores típicos SIN validar contra presupuestos reales: GG y utilidad varían por obra y mandante. Chile aplica
# el IVA y los recargos al final del presupuesto (nivel «presupuesto»); la hora de MO ya incluye leyes sociales.
CHILE_ESTANDAR = {
    'perfil': 'Chile - estándar (por validar)',
    'moneda': 'CLP',
    'redondeo': {'linea': None, 'total': 0, 'modo': 'HALF_UP'},
    'lineas': [
        {'cod': 'MAT', 'nombre': 'Materiales', 'tipo': 'suma', 'grupo': 'MAT'},
        {'cod': 'MO', 'nombre': 'Mano de obra', 'tipo': 'suma', 'grupo': 'MO'},
        {'cod': 'EQ', 'nombre': 'Equipos y herramientas', 'tipo': 'suma', 'grupo': 'EQ'},
        {'cod': 'DIRECTO', 'nombre': 'Costo directo', 'tipo': 'subtotal', 'base': ['MAT', 'MO', 'EQ'],
         'total': True},
        {'cod': 'GG', 'nombre': 'Gastos generales', 'tipo': 'porcentaje', 'pct': 0.12, 'base': ['DIRECTO'],
         'nivel': 'presupuesto'},
        {'cod': 'UT', 'nombre': 'Utilidad', 'tipo': 'porcentaje', 'pct': 0.10, 'base': ['DIRECTO'],
         'nivel': 'presupuesto'},
        {'cod': 'NETO', 'nombre': 'Total neto', 'tipo': 'subtotal', 'base': ['DIRECTO', 'GG', 'UT'],
         'nivel': 'presupuesto'},
        {'cod': 'IVA', 'nombre': 'IVA', 'tipo': 'porcentaje', 'pct': 0.19, 'base': ['NETO'],
         'nivel': 'presupuesto'},
        {'cod': 'TOTAL', 'nombre': 'Total', 'tipo': 'subtotal', 'base': ['NETO', 'IVA'], 'nivel': 'presupuesto',
         'total': True},
    ],
}

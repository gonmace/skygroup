"""Iconos que se pueden elegir para el botón de un componente del paso (clave `icono` de la configuración del widget).
Los nombres son los de `templates/components/icon.html`."""
ICONOS_ELEGIBLES = (
    ('camera', 'Cámara'), ('drone', 'Dron'), ('map-pin', 'Ubicación'), ('map', 'Mapa'), ('desfase', 'Desfase'),
    ('ruler', 'Distancia'), ('list', 'Lista'), ('chat', 'Comentarios'), ('clipboard', 'Formulario'),
    ('book', 'Libro de obras'), ('hardhat', 'Obra'), ('file-text', 'Documento'), ('chart', 'Avance'),
    ('paperclip', 'Adjunto'), ('eye', 'Inspección'), ('layers', 'Capas'),
)
NOMBRES_ICONO = {n for n, _ in ICONOS_ELEGIBLES}

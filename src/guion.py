"""Guion del reel: cada escena tiene su locución y el texto que aparece en pantalla.

La duración de cada escena la marca su locución (más una pausa), así que
voz y vídeo siempre van sincronizados.
"""
import os

ESCENAS_LARGO = [
    {
        "id": "intro",
        "voz": "Aragón también se respira.",
        "pausa": 0.5,
    },
    {
        "id": "presentacion",
        "voz": "Te presentamos el Ambientador del Cachirulo: una pieza artesanal, "
               "cuidada al detalle y con todo el carácter de nuestra tierra.",
        "pausa": 0.45,
    },
    {
        "id": "pulverizador",
        "voz": "Incluye un pulverizador de diez mililitros, elaborado con esencias naturales.",
        "pausa": 0.45,
    },
    {
        "id": "aromas",
        "voz": "Elige tu aroma favorito: coco y vainilla, mango y limón, o sol y mar.",
        "pausa": 0.5,
    },
    {
        "id": "paso1",
        "voz": "Usarlo es muy sencillo. Primero, pulveriza el ambientador sobre el yeso cerámico, "
               "a unos quince o veinte centímetros.",
        "pausa": 0.35,
    },
    {
        "id": "paso2",
        "voz": "Después, disfruta del aroma: el yeso absorbe la fragancia "
               "y la libera de forma suave y duradera.",
        "pausa": 0.35,
    },
    {
        "id": "paso3",
        "voz": "Y cuando notes que el aroma disminuye, vuelve a pulverizar. ¡Y sigue disfrutando!",
        "pausa": 0.5,
    },
    {
        "id": "tiendas",
        "voz": "Lo encontrarás exclusivamente en tiendas físicas colaboradoras: "
               "en Mercería El Siglo, calle Cortes de Aragón, cuarenta y seis; "
               "y en Papelería Casablanca, calle La Vía, dieciséis.",
        "pausa": 0.5,
    },
    {
        "id": "colabora",
        "voz": "¿Tienes una tienda y quieres colaborar con nosotros? "
               "Escríbenos por mensaje privado, por correo electrónico o llámanos por teléfono: "
               "te enviaremos toda la información.",
        "pausa": 1.2,
    },
    {
        "id": "cierre",
        "voz": "Ambientador del Cachirulo. Porque Aragón no solo se lleva en el pañuelo: "
               "también se lleva en casa.",
        "pausa": 2.6,
    },
]

# Versión corta (20-30 s) para Reels
ESCENAS_CORTO = [
    {"id": "intro", "voz": "Aragón también se respira.", "pausa": 0.3},
    {"id": "presentacion", "voz": "Ambientador del Cachirulo: artesanal y muy aragonés.", "pausa": 0.3},
    {"id": "aromas", "voz": "Esencias naturales: coco y vainilla, mango y limón, o sol y mar.", "pausa": 0.3},
    {"id": "pasos", "voz": "Pulveriza, disfruta y repite.", "pausa": 0.3},
    {"id": "tiendas", "voz": "Solo en tiendas físicas: Mercería El Siglo y Papelería Casablanca.", "pausa": 0.3},
    {"id": "colabora", "voz": "¿Tienes una tienda? Colabora con nosotros.", "pausa": 0.7},
    {"id": "cierre", "voz": "Porque Aragón también se lleva en casa.", "pausa": 1.5},
]

# Anuncio de producto (15-20 s) sobre el vídeo del ambientador girando
ESCENAS_ANUNCIO = [
    {"id": "intro", "voz": "Estos son nuestros Ambientadores del Cachirulo.", "pausa": 0.45},
    {"id": "artesanal", "voz": "Creados de forma artesanal, con pulverizador de diez mililitros.", "pausa": 0.45},
    {"id": "tiendas", "voz": "Encuéntralos exclusivamente en nuestras tiendas colaboradoras: "
                             "Mercería El Siglo, en Cortes de Aragón, cuarenta y seis; "
                             "y Papelería Casablanca, en La Vía, dieciséis.", "pausa": 0.5},
    {"id": "cierre", "voz": "Descúbrelos. ¡Te esperamos!", "pausa": 1.4},
]

VERSION = os.environ.get("VERSION", "largo")
ESCENAS = {"corto": ESCENAS_CORTO, "anuncio": ESCENAS_ANUNCIO}.get(VERSION, ESCENAS_LARGO)
SUFIJO = f"_{VERSION}" if VERSION in ("corto", "anuncio") else ""

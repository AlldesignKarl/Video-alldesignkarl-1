"""Renderiza el reel vertical (1080x1920, 30 fps) sincronizado con la locución.

Requiere haber ejecutado antes src/locucion.py (build/locucion.wav y build/tiempos.json).
Salida: output/ambientador_cachirulo_reel.mp4
"""
import json
import math
import os
import subprocess
import sys
from functools import lru_cache

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from guion import ESCENAS  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(RAIZ, "assets")
W, H, FPS = 1080, 1920, 30
FUNDIDO = 0.4  # segundos de fundido entre escenas

CREMA = (247, 240, 230)
KRAFT = (196, 160, 118)
ROJO = (170, 28, 38)
ROJO_OSCURO = (98, 16, 22)
NEGRO = (30, 26, 24)
BLANCO = (255, 252, 247)
TINTA = (58, 44, 38)

FUENTES = {
    "script": os.path.join(ASSETS, "fonts", "GreatVibes-Regular.ttf"),
    "serif": os.path.join(ASSETS, "fonts", "CormorantGaramond.ttf"),
    "sans": os.path.join(ASSETS, "fonts", "Montserrat.ttf"),
}

TEXTO_VOZ = {e["id"]: e["voz"] for e in ESCENAS}


# ---------------------------------------------------------------- utilidades
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 3 * x * x - 2 * x * x * x


def aparece(t, t0, dur=0.6):
    """Progreso 0..1 de una animación de entrada que empieza en t0."""
    return ease_out((t - t0) / dur)


@lru_cache(maxsize=None)
def fuente(nombre, tam, peso=None):
    f = ImageFont.truetype(FUENTES[nombre], tam)
    if peso is not None:
        f.set_variation_by_axes([peso])
    return f


@lru_cache(maxsize=None)
def texto(txt, nombre, tam, color, peso=None, tracking=0, sombra=0):
    """Capa RGBA recortada con el texto (con espaciado entre letras opcional)."""
    f = fuente(nombre, tam, peso)
    if tracking:
        anchos = [f.getlength(c) + tracking for c in txt]
        ancho = int(sum(anchos) - tracking)
    else:
        ancho = int(f.getlength(txt))
    asc, desc = f.getmetrics()
    pad = int(tam * 0.6) + sombra * 3
    capa = Image.new("RGBA", (ancho + 2 * pad, asc + desc + 2 * pad), (0, 0, 0, 0))

    def pinta(d, desplaz, col):
        x = pad + desplaz
        if tracking:
            for c, a in zip(txt, anchos):
                d.text((x, pad + desplaz), c, font=f, fill=col)
                x += a
        else:
            d.text((x, pad + desplaz), txt, font=f, fill=col)

    if sombra:
        s = Image.new("RGBA", capa.size, (0, 0, 0, 0))
        pinta(ImageDraw.Draw(s), sombra // 2, (0, 0, 0, 150))
        s = s.filter(ImageFilter.GaussianBlur(sombra))
        capa = Image.alpha_composite(capa, s)
    pinta(ImageDraw.Draw(capa), 0, color + (255,))
    bbox = capa.getbbox() or (0, 0, 1, 1)
    return capa.crop(bbox)


@lru_cache(maxsize=None)
def parrafo(txt, nombre, tam, color, ancho_max, peso=None, interlinea=1.35):
    """Texto centrado en varias líneas."""
    f = fuente(nombre, tam, peso)
    lineas, actual = [], ""
    for palabra in txt.split():
        prueba = (actual + " " + palabra).strip()
        if f.getlength(prueba) <= ancho_max:
            actual = prueba
        else:
            lineas.append(actual)
            actual = palabra
    lineas.append(actual)
    alto_linea = int(tam * interlinea)
    capa = Image.new("RGBA", (ancho_max, alto_linea * len(lineas) + tam), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    for i, linea in enumerate(lineas):
        d.text((ancho_max / 2, i * alto_linea + tam * 0.1), linea, font=f, fill=color + (255,), anchor="mt")
    return capa.crop(capa.getbbox())


def pegar(lienzo, capa, cx, cy, alpha=1.0, escala=1.0):
    """Pega una capa RGBA centrada en (cx, cy) con opacidad y escala."""
    if alpha <= 0.003:
        return
    if escala != 1.0:
        capa = capa.resize((max(1, int(capa.width * escala)), max(1, int(capa.height * escala))), Image.LANCZOS)
    mascara = capa.getchannel("A")
    if alpha < 0.999:
        mascara = mascara.point(lambda a: int(a * alpha))
    lienzo.paste(capa.convert("RGB"), (int(cx - capa.width / 2), int(cy - capa.height / 2)), mascara)


def momento(escena, fragmento, tiempos):
    """Instante aproximado en que la locución dice `fragmento` (reparto por caracteres)."""
    txt = TEXTO_VOZ[escena]
    e = tiempos[escena]
    idx = txt.find(fragmento)
    return e["voz_inicio"] + (e["voz_fin"] - e["voz_inicio"]) * idx / len(txt)


# ---------------------------------------------------------------- recursos
FOTO = Image.open(os.path.join(ASSETS, "producto.jpg")).convert("RGB")


def camara(cx, cy, s):
    """Encuadre de la foto: centro (cx, cy) en coordenadas de la foto y escala s."""
    s = max(s, H / FOTO.height, W / FOTO.width)
    cx = clamp(cx, W / 2 / s, FOTO.width - W / 2 / s)
    cy = clamp(cy, H / 2 / s, FOTO.height - H / 2 / s)
    a = 1 / s
    return FOTO.transform((W, H), Image.AFFINE, (a, 0, cx - W / 2 * a, 0, a, cy - H / 2 * a), Image.BICUBIC)


def _fondo_foto():
    lado = H
    grande = FOTO.resize((lado, lado), Image.LANCZOS)
    x0 = (lado - W) // 2
    fondo = grande.crop((x0, 0, x0 + W, H)).filter(ImageFilter.GaussianBlur(38))
    return Image.blend(fondo, Image.new("RGB", (W, H), (20, 14, 12)), 0.45)


def _tarjeta_foto(lado=1000, radio=40):
    foto = FOTO.resize((lado, lado), Image.LANCZOS).convert("RGBA")
    mascara = Image.new("L", (lado, lado), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, lado - 1, lado - 1), radio, fill=255)
    foto.putalpha(mascara)
    return foto


FONDO_FOTO = _fondo_foto()
TARJETA_FOTO = _tarjeta_foto()
LADO_FOTO = 940
SOMBRA_FOTO = Image.new("RGBA", (LADO_FOTO + 160, LADO_FOTO + 160), (0, 0, 0, 0))
ImageDraw.Draw(SOMBRA_FOTO).rounded_rectangle((80, 95, 80 + LADO_FOTO, 95 + LADO_FOTO), 40, fill=(0, 0, 0, 150))
SOMBRA_FOTO = SOMBRA_FOTO.filter(ImageFilter.GaussianBlur(28))


def foto_centrada(zoom=1.0, cy=H / 2):
    """La foto completa, centrada y con esquinas redondeadas; `zoom` hace un ligero acercamiento."""
    img = FONDO_FOTO.copy()
    lado = int(LADO_FOTO * zoom)
    img.paste(SOMBRA_FOTO.convert("RGB"), (int(W / 2 - SOMBRA_FOTO.width / 2), int(cy - SOMBRA_FOTO.height / 2)),
              SOMBRA_FOTO.getchannel("A"))
    tarjeta = TARJETA_FOTO.resize((lado, lado), Image.BICUBIC)
    img.paste(tarjeta.convert("RGB"), (int(W / 2 - lado / 2), int(cy - lado / 2)), tarjeta.getchannel("A"))
    return img


def gradiente(alto, desde, hasta, color=(0, 0, 0)):
    """Capa RGBA vertical que va de opacidad `desde` a `hasta`."""
    g = np.linspace(desde, hasta, alto)[:, None] * 255
    a = np.repeat(g, W, axis=1).astype(np.uint8)
    capa = Image.new("RGBA", (W, alto), color + (0,))
    capa.putalpha(Image.fromarray(a))
    return capa


def papel():
    rng = np.random.default_rng(7)
    base = np.array(CREMA, dtype=np.float32)[None, None, :] * np.ones((H, W, 1), np.float32)
    ruido = rng.normal(0, 3.2, (H, W, 1))
    yy, xx = np.mgrid[0:H, 0:W]
    vi = ((xx - W / 2) / W) ** 2 + ((yy - H / 2) / H) ** 2
    base = base * (1 - 0.16 * vi[..., None]) + ruido
    return Image.fromarray(np.clip(base, 0, 255).astype(np.uint8))


def vichy(ancho, alto, q=22):
    """Cuadro vichy rojo y negro (como el lazo del cachirulo)."""
    yy, xx = np.mgrid[0:alto, 0:ancho]
    a = (xx // q) % 2
    b = (yy // q) % 2
    img = np.zeros((alto, ancho, 3), np.float32)
    img[:] = ROJO
    img[(a == 1) ^ (b == 1)] = ROJO_OSCURO
    img[(a == 1) & (b == 1)] = NEGRO
    trama = ((xx % 3 == 0) | (yy % 3 == 0)) * -10.0
    img += trama[..., None]
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def tinta(caja, color=TINTA):
    """Extrae un icono de la tarjeta de instrucciones como capa RGBA del color dado."""
    recorte = Image.open(os.path.join(ASSETS, "instrucciones.jpg")).convert("L").crop(caja)
    a = np.clip((170 - np.array(recorte, np.float32)) / 90, 0, 1) * 255
    capa = Image.new("RGBA", recorte.size, color + (0,))
    capa.putalpha(Image.fromarray(a.astype(np.uint8)))
    return capa.crop(capa.getbbox())


def corazon(tam, color, grosor=4, relleno=False):
    esc = 4
    t = np.linspace(0, 2 * math.pi, 400)
    x = 16 * np.sin(t) ** 3
    y = -(13 * np.cos(t) - 5 * np.cos(2 * t) - 2 * np.cos(3 * t) - np.cos(4 * t))
    k = tam * esc / 36
    pts = [(tam * esc / 2 + xi * k, tam * esc / 2 + yi * k) for xi, yi in zip(x, y)]
    capa = Image.new("RGBA", (tam * esc, tam * esc), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    if relleno:
        d.polygon(pts, fill=color + (255,))
    else:
        d.line(pts + [pts[0]], fill=color + (255,), width=grosor * esc, joint="curve")
    return capa.resize((tam, tam), Image.LANCZOS)


def separador(ancho, color=TINTA):
    """Línea — corazón — línea, como en la tarjeta de instrucciones."""
    capa = Image.new("RGBA", (ancho, 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    d.line((0, 20, ancho / 2 - 34, 20), fill=color + (255,), width=2)
    d.line((ancho / 2 + 34, 20, ancho, 20), fill=color + (255,), width=2)
    capa.alpha_composite(corazon(34, color, 2), (ancho // 2 - 17, 3))
    return capa


def chincheta(tam, color=ROJO):
    esc = 4
    s = tam * esc
    capa = Image.new("RGBA", (s, int(s * 1.35)), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    r = s / 2
    d.ellipse((0, 0, s, s), fill=color + (255,))
    d.polygon([(r * 0.18, r * 1.45), (s - r * 0.18, r * 1.45), (r, s * 1.35)], fill=color + (255,))
    d.ellipse((r * 0.55, r * 0.55, s - r * 0.55, s - r * 0.55), fill=(0, 0, 0, 0))
    return capa.resize((tam, int(tam * 1.35)), Image.LANCZOS)


def bocadillo(tam, color):
    esc = 4
    s = tam * esc
    capa = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    g = int(s * 0.055)
    d.rounded_rectangle((g, g, s - g, s * 0.72), radius=s * 0.2, outline=color + (255,), width=g)
    d.line([(s * 0.28, s * 0.70), (s * 0.22, s * 0.92), (s * 0.48, s * 0.72)], fill=color + (255,), width=g,
           joint="curve")
    for i in range(3):
        cx = s * (0.32 + 0.18 * i)
        d.ellipse((cx - g * 1.1, s * 0.37 - g * 1.1, cx + g * 1.1, s * 0.37 + g * 1.1), fill=color + (255,))
    return capa.resize((tam, tam), Image.LANCZOS)


def tarjeta(ancho, alto, color=BLANCO, alpha=235, radio=34, sombra=True):
    pad = 40
    capa = Image.new("RGBA", (ancho + 2 * pad, alto + 2 * pad), (0, 0, 0, 0))
    if sombra:
        s = Image.new("RGBA", capa.size, (0, 0, 0, 0))
        ImageDraw.Draw(s).rounded_rectangle((pad, pad + 10, pad + ancho, pad + alto + 10), radio, fill=(60, 40, 30, 70))
        capa = s.filter(ImageFilter.GaussianBlur(16))
    ImageDraw.Draw(capa).rounded_rectangle((pad, pad, pad + ancho, pad + alto), radio, fill=color + (alpha,))
    return capa


PAPEL = papel()
VICHY = vichy(W, 60)
ICONOS = {
    "paso1": tinta((70, 395, 240, 648)),
    "paso2": tinta((40, 708, 236, 903)),
    "paso3": tinta((52, 986, 238, 1165)),
}
GRAD_ARRIBA = gradiente(900, 0.62, 0.0)
GRAD_ABAJO = gradiente(900, 0.0, 0.72)


def fondo_papel(t):
    lienzo = PAPEL.copy()
    lienzo.paste(VICHY.crop((0, 0, W, 26)), (0, 0))
    lienzo.paste(VICHY.crop((0, 0, W, 26)), (0, H - 26))
    return lienzo


# ---------------------------------------------------------------- escenas
def esc_intro(t, T):
    e = T["intro"]
    p = (t - e["inicio"]) / (T["presentacion"]["fin"] - e["inicio"])
    img = foto_centrada(0.97 + 0.04 * p, 1010)
    a1 = aparece(t, 0.35, 0.9)
    pegar(img, texto("Aragón", "script", 190, BLANCO, sombra=8), W / 2, 250 - 30 * a1, a1)
    a2 = aparece(t, 0.95, 0.8)
    pegar(img, texto("TAMBIÉN SE RESPIRA", "sans", 40, BLANCO, 500, tracking=9, sombra=6), W / 2, 415 - 20 * a2, a2)
    return img


def esc_presentacion(t, T):
    e = T["presentacion"]
    p = (t - T["intro"]["inicio"]) / (e["fin"] - T["intro"]["inicio"])
    img = foto_centrada(0.97 + 0.04 * p, 1010 - 180 * ease_in_out((t - e["inicio"]) / 0.9))
    a = aparece(t, e["inicio"] + 0.2, 0.8)
    y = 1580 + 60 * (1 - a)
    pegar(img, tarjeta(900, 400, alpha=245), W / 2, y, a)
    pegar(img, texto("TE PRESENTAMOS", "sans", 30, ROJO, 600, tracking=8), W / 2, y - 130, a)
    a2 = aparece(t, momento("presentacion", "Ambientador", T) - 0.1, 0.8)
    pegar(img, texto("Ambientador", "script", 118, NEGRO), W / 2, y - 40, a2)
    pegar(img, texto("del Cachirulo", "script", 118, ROJO), W / 2, y + 70, a2)
    a3 = aparece(t, momento("presentacion", "una pieza", T), 0.8)
    pegar(img, texto("ARTESANAL  ·  CUIDADO AL DETALLE", "sans", 25, TINTA, 500, tracking=4), W / 2, y + 160, a3)
    return img


def esc_pulverizador(t, T):
    e = T["pulverizador"]
    p = (t - e["inicio"]) / (e["fin"] - e["inicio"])
    img = foto_centrada(1.0 + 0.03 * p, 830)
    items = [
        ("10 ml", "diez", "script", 120),
        ("PULVERIZADOR INCLUIDO", "pulverizador", "sans", 36),
        ("ESENCIAS NATURALES", "esencias", "sans", 36),
    ]
    ys = [1435, 1600, 1725]
    for (txt, frag, f, tam), y in zip(items, ys):
        a = aparece(t, momento("pulverizador", frag, T) - 0.25, 0.6)
        if f == "script":
            pegar(img, texto(txt, f, tam, BLANCO, sombra=6), W / 2, y + 30 * (1 - a), a)
        else:
            pastilla = tarjeta(640, 92, color=CREMA, alpha=240, radio=46, sombra=False)
            pegar(img, pastilla, W / 2, y + 30 * (1 - a), a)
            pegar(img, texto(txt, f, tam, ROJO, 600, tracking=5), W / 2, y + 30 * (1 - a), a)
    return img


AROMAS = [
    ("Coco y vainilla", "coco", ((250, 244, 230), (214, 178, 120))),
    ("Mango y limón", "mango", ((246, 163, 60), (236, 214, 70))),
    ("Sol y mar", "sol", ((244, 190, 70), (80, 150, 190))),
]


@lru_cache(maxsize=None)
def medallon(c1, c2, tam=120):
    esc = 4
    s = tam * esc
    capa = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    d.pieslice((0, 0, s, s), 90, 270, fill=c1 + (255,))
    d.pieslice((0, 0, s, s), 270, 90, fill=c2 + (255,))
    d.ellipse((0, 0, s, s), outline=TINTA + (255,), width=6 * esc // 2)
    return capa.resize((tam, tam), Image.LANCZOS)


def esc_aromas(t, T):
    e = T["aromas"]
    img = fondo_papel(t)
    a = aparece(t, e["inicio"] + 0.1, 0.7)
    pegar(img, texto("ESENCIAS NATURALES", "sans", 32, ROJO, 600, tracking=8), W / 2, 330, a)
    pegar(img, texto("Elige tu aroma", "script", 150, NEGRO), W / 2, 480 - 20 * (1 - a), a)
    pegar(img, separador(560), W / 2, 610, a)
    for i, (nombre, frag, (c1, c2)) in enumerate(AROMAS):
        ai = aparece(t, momento("aromas", frag, T) - 0.2, 0.6)
        y = 830 + i * 290
        dx = 80 * (1 - ai)
        pegar(img, tarjeta(860, 220, alpha=250), W / 2 + dx, y, ai)
        franja = VICHY.crop((0, 0, 24, 220))
        capa = Image.new("RGBA", (24, 220))
        capa.paste(franja)
        pegar(img, capa, W / 2 - 430 + 12 + dx, y, ai)
        pegar(img, medallon(c1, c2), W / 2 - 290 + dx, y, ai)
        pegar(img, texto(nombre, "serif", 78, NEGRO, 600), W / 2 + 90 + dx, y - 4, ai)
    a4 = aparece(t, e["voz_fin"] - 0.2, 0.6)
    pegar(img, texto("FORMATO 10 ML  ·  PULVERIZADOR INCLUIDO", "sans", 26, TINTA, 500, tracking=4), W / 2, 1720, a4)
    return img


PASOS = [
    ("paso1", "Aplica el perfume",
     "Pulveriza el ambientador sobre el yeso cerámico desde una distancia de 15-20 cm."),
    ("paso2", "Disfruta del aroma",
     "El yeso cerámico absorbe la fragancia y la libera de forma suave y duradera."),
    ("paso3", "Vuelve a pulverizar",
     "Cuando notes que el aroma disminuye, vuelve a aplicar el perfume. ¡Y sigue disfrutando!"),
]


def esc_paso(n):
    ident, titulo, desc = PASOS[n]

    def dibuja(t, T):
        e = T[ident]
        img = fondo_papel(t)
        cab = aparece(t, T["paso1"]["inicio"] + 0.1, 0.7) if n == 0 else 1.0
        pegar(img, texto("Instrucciones de uso", "script", 124, NEGRO), W / 2, 270, cab)
        pegar(img, separador(560), W / 2, 380, cab)
        # indicador de pasos
        for i in range(3):
            activo = i == n
            col = ROJO if activo else KRAFT
            circulo = Image.new("RGBA", (84, 84), (0, 0, 0, 0))
            d = ImageDraw.Draw(circulo)
            if activo:
                d.ellipse((2, 2, 82, 82), fill=col + (255,))
                num = texto(str(i + 1), "serif", 54, BLANCO, 600)
            else:
                d.ellipse((2, 2, 82, 82), outline=col + (255,), width=3)
                num = texto(str(i + 1), "serif", 54, col, 600)
            circulo.alpha_composite(num, (42 - num.width // 2, 42 - num.height // 2))
            pegar(img, circulo, W / 2 + (i - 1) * 150, 500, cab)
        # inicio del contenido: en el paso 1, tras «Usarlo es muy sencillo»
        t0 = momento("paso1", "Primero", T) - 0.3 if n == 0 else e["inicio"]
        a = aparece(t, t0, 0.7)
        pop = 0.85 + 0.15 * ease_out((t - t0) / 0.5)
        circ = Image.new("RGBA", (520, 520), (0, 0, 0, 0))
        ImageDraw.Draw(circ).ellipse((0, 0, 519, 519), fill=BLANCO + (255,), outline=KRAFT + (255,), width=4)
        pegar(img, circ, W / 2, 900, a, pop)
        icono = ICONOS[ident]
        esc = 330 / max(icono.width, icono.height)
        # pequeño movimiento en el icono para darle vida
        vaiven = math.sin((t - t0) * 2.2) * 6
        pegar(img, icono, W / 2, 900 + vaiven, a, esc * pop)
        a2 = aparece(t, t0 + 0.3, 0.7)
        pegar(img, texto(titulo, "serif", 96, ROJO, 600), W / 2, 1300 - 20 * (1 - a2), a2)
        pegar(img, parrafo(desc, "serif", 60, TINTA, 860, 500), W / 2, 1480 - 20 * (1 - a2), a2)
        return img

    return dibuja


def esc_tiendas(t, T):
    e = T["tiendas"]
    img = fondo_papel(t)
    a = aparece(t, e["inicio"] + 0.1, 0.7)
    pegar(img, texto("DISPONIBLE EXCLUSIVAMENTE EN", "sans", 32, TINTA, 500, tracking=6), W / 2, 280, a)
    pegar(img, texto("tiendas físicas", "script", 150, ROJO), W / 2, 410 - 20 * (1 - a), a)
    pegar(img, texto("COLABORADORAS", "sans", 32, TINTA, 500, tracking=6), W / 2, 530, a)
    a0 = aparece(t, momento("tiendas", "en Mercería", T) - 0.6, 0.7)
    pegar(img, separador(560), W / 2, 640, a0)
    pegar(img, texto("¿Dónde encontrarlo?", "serif", 76, NEGRO, 600), W / 2, 750, a0)
    tiendas = [("Mercería El Siglo", "Calle Cortes de Aragón, 46", "Mercería"),
               ("Papelería Casablanca", "Calle La Vía, 16", "Papelería")]
    for i, (nombre, dir_, frag) in enumerate(tiendas):
        ai = aparece(t, momento("tiendas", frag, T) - 0.25, 0.6)
        y = 1010 + i * 330
        dy = 40 * (1 - ai)
        pegar(img, tarjeta(880, 260, alpha=250), W / 2, y + dy, ai)
        pegar(img, chincheta(64), W / 2 - 340, y + dy, ai)
        pegar(img, texto(nombre, "serif", 76, NEGRO, 700), W / 2 + 50, y - 38 + dy, ai)
        pegar(img, texto(dir_, "sans", 38, TINTA, 400), W / 2 + 50, y + 52 + dy, ai)
    a3 = aparece(t, e["voz_fin"] - 0.5, 0.7)
    pegar(img, texto("¡Te esperamos!", "script", 100, ROJO), W / 2, 1700, a3)
    return img


FONDO_VICHY = (vichy(W + 200, H + 200, q=64).filter(ImageFilter.GaussianBlur(6)))


def esc_colabora(t, T):
    e = T["colabora"]
    p = (t - e["inicio"]) / (e["fin"] - e["inicio"])
    off = int(100 * p)
    img = FONDO_VICHY.crop((off, off, off + W, off + H))
    img = Image.blend(img, Image.new("RGB", (W, H), NEGRO), 0.7)
    a = aparece(t, e["inicio"] + 0.1, 0.7)
    pegar(img, texto("¿Tienes una tienda?", "script", 140, BLANCO, sombra=4), W / 2, 330 - 20 * (1 - a), a)
    a2 = aparece(t, momento("colabora", "quieres", T) - 0.2, 0.7)
    pegar(img, texto("COLABORA CON NOSOTROS", "sans", 46, CREMA, 600, tracking=8), W / 2, 500, a2)
    pegar(img, separador(560, CREMA), W / 2, 590, a2)
    pegar(img, parrafo("Estamos abiertos a nuevas tiendas colaboradoras.", "serif", 58, CREMA, 860, 500),
          W / 2, 700, a2)
    a3 = aparece(t, momento("colabora", "Escríbenos", T) - 0.2, 0.7)
    pegar(img, tarjeta(860, 100, color=CREMA, alpha=250, radio=50, sombra=False), W / 2, 880, a3)
    pegar(img, texto("ESCRÍBENOS POR MENSAJE PRIVADO", "sans", 32, ROJO, 700, tracking=3), W / 2, 880, a3)
    contactos = [("CORREO", "alldesignkarl@gmail.com", "correo", 1110),
                 ("TELÉFONO", "614 65 37 36", "llámanos", 1340)]
    for etiqueta, dato, frag, y in contactos:
        ai = aparece(t, momento("colabora", frag, T) - 0.3, 0.6)
        dy = 30 * (1 - ai)
        pegar(img, tarjeta(860, 190, alpha=248), W / 2, y + dy, ai)
        pegar(img, texto(etiqueta, "sans", 28, ROJO, 600, tracking=6), W / 2, y - 45 + dy, ai)
        pegar(img, texto(dato, "serif", 68, NEGRO, 700), W / 2, y + 30 + dy, ai)
    a4 = aparece(t, momento("colabora", "te enviaremos", T), 0.7)
    pegar(img, texto("y te enviaremos toda la información", "serif", 50, CREMA, 500), W / 2, 1580, a4)
    return img


def esc_cierre(t, T):
    e = T["cierre"]
    p = (t - e["inicio"]) / (e["fin"] - e["inicio"])
    img = foto_centrada(1.02 - 0.05 * ease_in_out(p), 1100)
    a = aparece(t, e["inicio"] + 0.1, 0.8)
    pegar(img, texto("Ambientador del Cachirulo", "script", 104, BLANCO, sombra=6), W / 2, 200, a)
    a2 = aparece(t, momento("cierre", "Porque", T) - 0.1, 0.8)
    pegar(img, texto("Aragón no solo se lleva en el pañuelo,", "serif", 56, BLANCO, 600, sombra=6), W / 2, 340, a2)
    a3 = aparece(t, momento("cierre", "también", T) - 0.1, 0.8)
    pegar(img, texto("también se lleva en casa.", "serif", 56, BLANCO, 600, sombra=6), W / 2, 420, a3)

    # tarjeta final
    fin = ease_in_out((t - (e["voz_fin"] + 0.3)) / 0.8)
    if fin > 0:
        final = fondo_papel(t)
        pegar(final, corazon(70, ROJO, relleno=True), W / 2, 640)
        pegar(final, texto("Ambientador", "script", 170, NEGRO), W / 2, 820)
        pegar(final, texto("del Cachirulo", "script", 170, ROJO), W / 2, 990)
        pegar(final, separador(600), W / 2, 1150)
        pegar(final, texto("GRACIAS POR APOYAR LA ARTESANÍA LOCAL", "sans", 30, TINTA, 500, tracking=5),
              W / 2, 1250)
        img = Image.blend(img, final, fin)
    return img


ESCENA_FN = {
    "intro": esc_intro,
    "presentacion": esc_presentacion,
    "pulverizador": esc_pulverizador,
    "aromas": esc_aromas,
    "paso1": esc_paso(0),
    "paso2": esc_paso(1),
    "paso3": esc_paso(2),
    "tiendas": esc_tiendas,
    "colabora": esc_colabora,
    "cierre": esc_cierre,
}

# transiciones: la intro y la presentación comparten plano (sin fundido)
SIN_FUNDIDO = {"presentacion"}


def fotograma(t, T, orden):
    idx = 0
    for i, ident in enumerate(orden):
        if t >= T[ident]["inicio"]:
            idx = i
    ident = orden[idx]
    img = ESCENA_FN[ident](t, T)
    dt = t - T[ident]["inicio"]
    if idx > 0 and dt < FUNDIDO and ident not in SIN_FUNDIDO:
        previa = ESCENA_FN[orden[idx - 1]](t, T)
        img = Image.blend(previa, img, ease_in_out(dt / FUNDIDO))
    return img


def main():
    with open(os.path.join(RAIZ, "build", "tiempos.json")) as f:
        datos = json.load(f)
    T = {e["id"]: e for e in datos["escenas"]}
    orden = [e["id"] for e in datos["escenas"]]
    duracion = datos["duracion"]
    n = int(math.ceil(duracion * FPS))

    solo = os.environ.get("PREVIEW")  # PREVIEW=12.5,30 -> guarda PNGs de esos instantes
    if solo:
        os.makedirs(os.path.join(RAIZ, "build", "preview"), exist_ok=True)
        for s in solo.split(","):
            fotograma(float(s), T, orden).save(os.path.join(RAIZ, "build", "preview", f"t{float(s):05.1f}.jpg"),
                                               quality=85)
        return

    salida = os.path.join(RAIZ, "output", "ambientador_cachirulo_reel.mp4")
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [ffmpeg, "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", os.path.join(RAIZ, "build", "locucion.wav"),
           "-af", "loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", salida]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        proc.stdin.write(fotograma(i / FPS, T, orden).tobytes())
        if i % (FPS * 5) == 0:
            print(f"{i / FPS:5.1f}s / {duracion:.1f}s", flush=True)
    proc.stdin.close()
    proc.wait()
    print("Vídeo:", salida)


if __name__ == "__main__":
    main()

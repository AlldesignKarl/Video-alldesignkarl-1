"""Genera la locución y los subtítulos.

Motores de voz (variable MOTOR):
  google      Google Cloud Text-to-Speech, voces Chirp 3 HD de España (GOOGLE_API_KEY)
  gemini      Gemini TTS (GEMINI_API_KEY)
  elevenlabs  ElevenLabs multilingual (ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID)
  kokoro      Kokoro local, sin clave (por defecto)

Salida:
  build/locucion.wav   pista de voz completa
  build/tiempos.json   inicio y duración de cada escena
  output/subtitulos.srt
"""
import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.dirname(__file__))
from guion import ESCENAS  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELOS = os.environ.get("KOKORO_DIR", os.path.join(RAIZ, "models"))
MOTOR = os.environ.get("MOTOR", "kokoro")
VOZ = os.environ.get("VOZ")
VELOCIDAD = float(os.environ.get("VELOCIDAD", "0.92"))
# Indicación de tono para Gemini (vacía por defecto: algunos modelos la leen en voz alta)
ESTILO = os.environ.get("ESTILO", "")
INICIO = 0.6  # silencio antes de la primera frase


def recortar_silencio(audio, sr=24000, antes=0.12, despues=0.3):
    """Quita el silencio de los extremos con margen amplio y suaviza los bordes (sin clics ni cortes)."""
    if len(audio) == 0:
        return audio
    umbral = max(0.002, 0.02 * float(np.abs(audio).max()))
    # envolvente suavizada (10 ms) para no cortar consonantes suaves ni finales de palabra
    ventana = max(1, int(0.01 * sr))
    envolvente = np.convolve(np.abs(audio), np.ones(ventana) / ventana, mode="same")
    activo = np.where(envolvente > umbral)[0]
    if len(activo) == 0:
        return audio
    audio = audio[max(0, activo[0] - int(antes * sr)): activo[-1] + int(despues * sr)].copy()
    entrada, salida = min(len(audio), int(0.015 * sr)), min(len(audio), int(0.08 * sr))
    audio[:entrada] *= np.linspace(0, 1, entrada)
    audio[len(audio) - salida:] *= np.linspace(1, 0, salida)
    return audio


def _post(url, cuerpo, cabeceras=None):
    peticion = urllib.request.Request(url, data=json.dumps(cuerpo).encode(),
                                      headers={"Content-Type": "application/json", **(cabeceras or {})})
    try:
        with urllib.request.urlopen(peticion, timeout=120) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"Error {e.code} de {url.split('?')[0]}:\n{e.read().decode(errors='replace')}")


def _pcm16(datos):
    return np.frombuffer(datos, dtype="<i2").astype(np.float32) / 32768


def motor_google():
    clave = os.environ["GOOGLE_API_KEY"]
    voz = VOZ or "es-ES-Chirp3-HD-Aoede"

    def sintetiza(txt):
        r = json.loads(_post(
            f"https://texttospeech.googleapis.com/v1/text:synthesize?key={clave}",
            {"input": {"text": txt},
             "voice": {"languageCode": "es-ES", "name": voz},
             "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": 24000,
                             "speakingRate": VELOCIDAD}}))
        audio, sr = sf.read(io.BytesIO(base64.b64decode(r["audioContent"])), dtype="float32")
        return audio, sr
    return sintetiza


def _modelos_gemini(clave):
    """Modelos de voz disponibles para la clave, del mejor al más básico (primero los «pro»)."""
    peticion = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000",
                                      headers={"x-goog-api-key": clave})
    try:
        with urllib.request.urlopen(peticion, timeout=60) as r:
            modelos = [m["name"].split("/")[-1] for m in json.load(r).get("models", [])]
    except urllib.error.HTTPError as e:
        sys.exit(f"Error {e.code} al listar modelos de Gemini:\n{e.read().decode(errors='replace')}")
    tts = [m for m in modelos if "tts" in m]
    if not tts:
        sys.exit("La clave no tiene acceso a ningún modelo de voz de Gemini.")
    def version(m):
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", m)
        return float(v.group(1)) if v else 0.0
    return sorted(tts, key=lambda m: ("pro" not in m, "lite" in m, -version(m), "preview" in m))


def motor_gemini():
    clave = os.environ["GEMINI_API_KEY"]
    modelos = [os.environ["GEMINI_MODELO"]] if os.environ.get("GEMINI_MODELO") else _modelos_gemini(clave)
    voz = VOZ or "Kore"
    print(f"Gemini: modelos disponibles {modelos}, voz {voz}")

    def pide(modelo, txt, con_estilo):
        prompt = f"{ESTILO}: {txt}" if con_estilo and ESTILO else txt
        peticion = urllib.request.Request(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            data=json.dumps({
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                                     "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}},
            }).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": clave})
        with urllib.request.urlopen(peticion, timeout=100) as r:
            return json.load(r)

    def siguiente_modelo(motivo):
        if len(modelos) == 1:
            sys.exit(f"Ningún modelo de voz de Gemini tiene cupo disponible ({motivo}). Prueba mañana.")
        print(f"  {modelos[0]}: {motivo}, paso a {modelos[1]}")
        modelos.pop(0)

    def sintetiza(txt):
        con_estilo = bool(ESTILO)
        limitados = 0
        # duración máxima razonable: si se pasa, ha leído también la indicación de estilo
        maximo = 0.095 * len(txt) + 2.0
        for intento in range(20):
            modelo = modelos[0]
            try:
                r = pide(modelo, txt, con_estilo)
                datos = r["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                audio = _pcm16(base64.b64decode(datos))
                if con_estilo and len(audio) / 24000 > maximo:
                    print(f"  audio demasiado largo ({len(audio) / 24000:.1f}s > {maximo:.1f}s), "
                          "repito sin indicación de estilo")
                    con_estilo = False
                    continue
                # el plan gratuito admite pocas peticiones por minuto: espacia las llamadas
                time.sleep(float(os.environ.get("GEMINI_PAUSA", "21")))
                return audio, 24000
            except urllib.error.HTTPError as e:
                cuerpo = e.read().decode(errors="replace")
                if e.code == 429 and "limit: 0" in cuerpo:
                    siguiente_modelo("no incluido en el plan")
                    continue
                if e.code == 429:
                    limitados += 1
                    if limitados >= 3:
                        siguiente_modelo("sin cupo")
                        limitados = 0
                        continue
                if e.code in (429, 500, 503):
                    espera = re.search(r'"retryDelay":\s*"(\d+)', cuerpo)
                    espera = int(espera.group(1)) + 2 if espera else 20 * (intento + 1)
                    print(f"  {modelo}: error {e.code}, espero {espera}s")
                    time.sleep(espera)
                    continue
                sys.exit(f"Error {e.code} de Gemini ({modelo}):\n{cuerpo}")
            except (KeyError, IndexError):
                print(f"  {modelo}: respuesta sin audio, reintento")
                time.sleep(5)
            except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
                print(f"  {modelo}: sin respuesta ({e}), reintento")
                time.sleep(10)
        sys.exit("Gemini no ha devuelto audio tras varios intentos.")
    return sintetiza


def motor_elevenlabs():
    clave = os.environ["ELEVENLABS_API_KEY"]
    voz = VOZ or os.environ["ELEVENLABS_VOICE_ID"]

    def sintetiza(txt):
        datos = _post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voz}?output_format=pcm_24000",
            {"text": txt, "model_id": os.environ.get("ELEVENLABS_MODELO", "eleven_multilingual_v2"),
             "language_code": "es",
             "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25,
                                "use_speaker_boost": True, "speed": VELOCIDAD}},
            {"xi-api-key": clave})
        return _pcm16(datos), 24000
    return sintetiza


def motor_kokoro():
    from kokoro_onnx import Kokoro
    kokoro = Kokoro(os.path.join(MODELOS, "kokoro-v1.0.onnx"), os.path.join(MODELOS, "voices-v1.0.bin"))
    return lambda txt: kokoro.create(txt, voice=VOZ or "ef_dora", speed=VELOCIDAD, lang="es")


MOTORES = {"google": motor_google, "gemini": motor_gemini, "elevenlabs": motor_elevenlabs, "kokoro": motor_kokoro}


def srt_tiempo(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def main():
    sintetiza = MOTORES[MOTOR]()
    os.makedirs(os.path.join(RAIZ, "build"), exist_ok=True)
    os.makedirs(os.path.join(RAIZ, "output"), exist_ok=True)

    sr = 24000  # todos los motores devuelven 24 kHz
    pista = [np.zeros(int(INICIO * sr), dtype=np.float32)]
    t = INICIO
    tiempos, srt = [], []
    for i, escena in enumerate(ESCENAS, 1):
        audio, sr = sintetiza(escena["voz"])
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        audio = recortar_silencio(audio.astype(np.float32), sr)
        dur_voz = len(audio) / sr
        pausa = escena["pausa"]
        pista += [audio, np.zeros(int(pausa * sr), dtype=np.float32)]
        inicio_escena = 0.0 if i == 1 else t
        tiempos.append({"id": escena["id"], "voz_inicio": t, "voz_fin": t + dur_voz,
                        "inicio": inicio_escena, "fin": t + dur_voz + pausa})
        srt.append(f"{i}\n{srt_tiempo(t)} --> {srt_tiempo(t + dur_voz)}\n{escena['voz']}\n")
        t += dur_voz + pausa
        print(f"{escena['id']:<14} {dur_voz:5.2f}s")

    voz = np.concatenate(pista)
    voz = voz / max(1e-6, np.abs(voz).max()) * 0.89  # normaliza a ~-1 dBFS
    sf.write(os.path.join(RAIZ, "build", "locucion.wav"), voz, sr)
    with open(os.path.join(RAIZ, "build", "tiempos.json"), "w") as f:
        json.dump({"duracion": len(voz) / sr, "escenas": tiempos}, f, indent=2, ensure_ascii=False)
    with open(os.path.join(RAIZ, "output", "subtitulos.srt"), "w") as f:
        f.write("\n".join(srt))
    print(f"Total ({MOTOR}): {len(voz) / sr:.2f}s")


if __name__ == "__main__":
    main()

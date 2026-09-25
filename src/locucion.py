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
import sys
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
ESTILO = os.environ.get(
    "ESTILO",
    "Lee este texto como una locutora profesional de España, con acento castellano, "
    "tono cálido, cercano y elegante, a ritmo pausado:")
INICIO = 0.6  # silencio antes de la primera frase


def recortar_silencio(audio, umbral=0.004, margen=int(0.05 * 24000)):
    activo = np.where(np.abs(audio) > umbral)[0]
    if len(activo) == 0:
        return audio
    return audio[max(0, activo[0] - margen): activo[-1] + margen]


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


def motor_gemini():
    clave = os.environ["GEMINI_API_KEY"]
    modelo = os.environ.get("GEMINI_MODELO", "gemini-2.5-pro-preview-tts")
    voz = VOZ or "Kore"

    def sintetiza(txt):
        r = json.loads(_post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
            {"contents": [{"parts": [{"text": f"{ESTILO}\n\n{txt}"}]}],
             "generationConfig": {"responseModalities": ["AUDIO"],
                                  "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voz}}}}},
            {"x-goog-api-key": clave}))
        datos = r["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
        return _pcm16(base64.b64decode(datos)), 24000
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
        audio = recortar_silencio(audio.astype(np.float32), margen=int(0.05 * sr))
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

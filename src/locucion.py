"""Genera la locución con Kokoro (voz neuronal, español de España) y los subtítulos.

Salida:
  build/locucion.wav   pista de voz completa
  build/tiempos.json   inicio y duración de cada escena
  output/subtitulos.srt
"""
import json
import os
import sys

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

sys.path.insert(0, os.path.dirname(__file__))
from guion import ESCENAS  # noqa: E402

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELOS = os.environ.get("KOKORO_DIR", os.path.join(RAIZ, "models"))
VOZ = os.environ.get("VOZ", "ef_dora")
VELOCIDAD = float(os.environ.get("VELOCIDAD", "0.92"))
INICIO = 0.6  # silencio antes de la primera frase


def recortar_silencio(audio, umbral=0.004, margen=int(0.05 * 24000)):
    activo = np.where(np.abs(audio) > umbral)[0]
    if len(activo) == 0:
        return audio
    return audio[max(0, activo[0] - margen): activo[-1] + margen]


def srt_tiempo(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def main():
    kokoro = Kokoro(os.path.join(MODELOS, "kokoro-v1.0.onnx"), os.path.join(MODELOS, "voices-v1.0.bin"))
    os.makedirs(os.path.join(RAIZ, "build"), exist_ok=True)
    os.makedirs(os.path.join(RAIZ, "output"), exist_ok=True)

    sr = 24000
    pista = [np.zeros(int(INICIO * sr), dtype=np.float32)]
    t = INICIO
    tiempos, srt = [], []
    for i, escena in enumerate(ESCENAS, 1):
        audio, sr = kokoro.create(escena["voz"], voice=VOZ, speed=VELOCIDAD, lang="es")
        audio = recortar_silencio(audio.astype(np.float32))
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
    print(f"Total: {len(voz) / sr:.2f}s")


if __name__ == "__main__":
    main()

# Reel · Ambientador del Cachirulo

Reel vertical para Instagram (1080×1920, 30 fps, unos 67 s) con locución en español de España.

- `output/ambientador_cachirulo_reel.mp4`: vídeo final con audio.
- `output/subtitulos.srt`: subtítulos de la locución.
- `instagram/copy.txt`: texto de la publicación.
- `src/guion.py`: texto de la locución de cada escena.

## Regenerar el vídeo

```bash
pip install -r requirements.txt
mkdir -p models
curl -L -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o models/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
python3 src/locucion.py   # locución, tiempos y subtítulos
python3 src/render.py     # vídeo
```

### Voz realista (recomendado)

```bash
MOTOR=google GOOGLE_API_KEY=... python3 src/locucion.py        # Chirp 3 HD, es-ES (voz: es-ES-Chirp3-HD-Aoede)
MOTOR=gemini GEMINI_API_KEY=... python3 src/locucion.py        # Gemini TTS (voz: Kore)
MOTOR=elevenlabs ELEVENLABS_API_KEY=... ELEVENLABS_VOICE_ID=... python3 src/locucion.py
python3 src/render.py
```

`VOZ=...` elige otra voz del motor, `VELOCIDAD=1.0` cambia el ritmo y `ESTILO="..."` cambia la indicación de tono en Gemini.

### Voz local (sin clave)

Por defecto se usa Kokoro `ef_dora` (femenina). `VOZ=em_alex` usa una voz masculina y `VELOCIDAD=0.9` cambia el ritmo.
Para ver fotogramas sueltos sin renderizar todo: `PREVIEW=5,20,45 python3 src/render.py` (se guardan en `build/preview/`).

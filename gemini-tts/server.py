from flask import Flask, request, jsonify, Response
from google.cloud import texttospeech_v1beta1 as texttospeech
from google.oauth2 import service_account
import hashlib
import re
import os
import pickle

app = Flask(__name__)

# Autenticación
credentials = service_account.Credentials.from_service_account_file(
    './gemini-tts.json'
)
client = texttospeech.TextToSpeechClient(credentials=credentials)

# Cache de audio en memoria Y en disco
audio_cache = {}
CACHE_FILE = '/tmp/tts_cache.pkl'

# Cargar cache persistente si existe
if os.path.exists(CACHE_FILE):
    try:
        with open(CACHE_FILE, 'rb') as f:
            audio_cache = pickle.load(f)
        print(f"✅ Cache cargado: {len(audio_cache)} audios", flush=True)
    except:
        print("⚠️ No se pudo cargar cache persistente", flush=True)

print("✅ Servidor de Gemini TTS iniciado", flush=True)


def sanitizar_texto(text):
    """
    Limpia el texto para evitar errores y MEJORA LA PRONUNCIACIÓN.
    """
    # ✅ FIX CRÍTICO: SALESLAND debe pronunciarse correctamente
    # Gemini entiende mejor la fonética española si separamos las palabras
    text = re.sub(r'SALESLAND', 'Seils Land', text, flags=re.IGNORECASE)
    text = re.sub(r'salesland', 'Seils Land', text, flags=re.IGNORECASE)
    
    # También manejar variantes
    text = re.sub(r'seils\s*land', 'Seils Land', text, flags=re.IGNORECASE)
    text = re.sub(r'SEILS\s*LAND', 'Seils Land', text, flags=re.IGNORECASE)
    
    # Convertir URLs a texto legible
    text = re.sub(r'https?://[^\s]+', 'ver portal del empleado', text)
    
    # Limpiar siglas problemáticas
    text = text.replace('RRHH', 'recursos humanos')
    text = text.replace('R.R.H.H.', 'recursos humanos')
    
    # DNI se pronuncia mejor así
    text = re.sub(r'DNI', 'de ene i', text)
    
    # Eliminar saltos de línea múltiples
    text = re.sub(r'\n+', ' ', text)
    
    # Eliminar espacios extras
    text = re.sub(r'\s+', ' ', text).strip()
    
    return text


def generar_audio(text):
    """
    Genera audio usando Gemini TTS con configuración optimizada.
    """
    # Sanitizar texto primero
    text = sanitizar_texto(text)
    
    # Hash para cache
    text_hash = hashlib.md5(text.encode()).hexdigest()
    
    # Verificar cache
    if text_hash in audio_cache:
        print(f"📦 Cache hit para: '{text[:50]}...'", flush=True)
        return audio_cache[text_hash]
    
    print(f"🎤 Generando audio nuevo: '{text[:50]}...'", flush=True)
    
    # Síntesis de voz
    synthesis_input = texttospeech.SynthesisInput(text=text)
    
    # Configurar voz (Achernar es la mejor voz masculina en español)
    voice = texttospeech.VoiceSelectionParams(
        language_code="es-ES",
        name="Achernar",
        model_name="gemini-2.5-flash-tts"
    )
    
    # Audio config optimizado para telefonía
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3,
        sample_rate_hertz=24000,
        speaking_rate=1.1,  # Ligeramente más rápido para conversación natural
        pitch=0.0,
        effects_profile_id=["telephony-class-application"]  # Optimizado para llamadas
    )
    
    # Sintetizar
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice,
        audio_config=audio_config
    )
    
    audio_data = response.audio_content
    
    # Guardar en cache (memoria y disco)
    audio_cache[text_hash] = audio_data
    
    # Persistir cache cada 5 audios nuevos
    if len(audio_cache) % 5 == 0:
        try:
            with open(CACHE_FILE, 'wb') as f:
                pickle.dump(audio_cache, f)
            print(f"💾 Cache guardado: {len(audio_cache)} audios", flush=True)
        except Exception as e:
            print(f"⚠️ Error guardando cache: {e}", flush=True)
    
    print(f"✅ Audio generado: {len(audio_data)} bytes", flush=True)
    
    return audio_data


@app.route('/synthesize', methods=['POST'])
def synthesize():
    """
    Genera audio usando Gemini TTS.
    """
    try:
        data = request.get_json()
        text = data.get('text', '')
        
        if not text:
            return jsonify({"error": "No text provided"}), 400
        
        audio_data = generar_audio(text)
        
        return Response(
            audio_data,
            mimetype='audio/mpeg',
            headers={'Content-Type': 'audio/mpeg'}
        )
        
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

# // STREAMING

@app.route('/stream', methods=['POST'])
def stream_audio():
    """
    Genera audio con Chirp3-HD y streaming.
    Retorna chunks de audio mientras se generan.
    """
    try:
        data = request.get_json()
        text = data.get('text', '')
        
        if not text:
            return jsonify({"error": "No text provided"}), 400
        
        text = sanitizar_texto(text)
        
        print(f"🎤 [STREAM] Generando: '{text[:50]}...'", flush=True)
        
        streaming_config = texttospeech.StreamingSynthesizeConfig(
            voice=texttospeech.VoiceSelectionParams(
                language_code='es-US',
                name='es-US-Chirp3-HD-Fenrir',
            )
        )
        
        config_request = texttospeech.StreamingSynthesizeRequest(
            streaming_config=streaming_config
        )
        
        def request_generator():
            yield config_request
            yield texttospeech.StreamingSynthesizeRequest(
                input=texttospeech.StreamingSynthesisInput(text=text)
            )
        
        def generate():
            for response in client.streaming_synthesize(request_generator()):
                yield response.audio_content
        
        return Response(
            generate(),
            mimetype='audio/L16',
            headers={'Content-Type': 'audio/L16'}
        )
        
    except Exception as e:
        print(f"❌ Error streaming: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route('/pregenerar', methods=['POST'])
def pregenerar():
    """
    Pre-genera audios comunes para reducir latencia.
    """
    try:
        data = request.get_json()
        textos = data.get('textos', [])
        
        if not textos:
            return jsonify({"error": "No texts provided"}), 400
        
        generados = 0
        for texto in textos:
            try:
                generar_audio(texto)
                generados += 1
            except Exception as e:
                print(f"⚠️ Error pre-generando '{texto[:30]}...': {e}", flush=True)
        
        return jsonify({
            "success": True,
            "generados": generados,
            "total_cache": len(audio_cache)
        })
        
    except Exception as e:
        print(f"❌ Error en pre-generación: {e}", flush=True)
        return jsonify({"error": str(e)}), 500


@app.route('/cache/stats', methods=['GET'])
def cache_stats():
    """Estadísticas del cache"""
    return jsonify({
        "audios_en_cache": len(audio_cache),
        "cache_file_exists": os.path.exists(CACHE_FILE)
    })


@app.route('/cache/clear', methods=['POST'])
def cache_clear():
    """Limpiar cache"""
    global audio_cache
    audio_cache = {}
    if os.path.exists(CACHE_FILE):
        os.remove(CACHE_FILE)
    return jsonify({"success": True, "message": "Cache limpiado"})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "ok",
        "service": "gemini-tts",
        "model": "gemini-2.5-flash-tts",
        "voice": "Achernar",
        "cache_size": len(audio_cache)
    })


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5003, debug=False)
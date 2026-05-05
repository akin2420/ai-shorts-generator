import textwrap
import os
import requests
import whisper
import gradio as gr
from PIL import Image, ImageDraw, ImageFont 
from google import genai
from elevenlabs.client import ElevenLabs
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips, CompositeVideoClip
from dotenv import load_dotenv


load_dotenv()

os.environ["IMAGEMAGICK_BINARY"] = "/opt/homebrew/bin/convert" 


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
HF_TOKEN = os.getenv("HF_TOKEN")

gemini_client = genai.Client(api_key=GEMINI_API_KEY)
eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
WHISPER_MODEL = whisper.load_model("base")

def kusursuz_yazi_olustur(metin, sure, index, v_yukseklik):
    font_size = 90
    try:
        font = ImageFont.truetype("/Library/Fonts/Arial.ttf", font_size)
    except:
        font = ImageFont.load_default()
        
    dummy_img = Image.new('RGBA', (1, 1))
    draw = ImageDraw.Draw(dummy_img)
    bbox = draw.textbbox((0, 0), metin, font=font)
    
    genislik = bbox[2] - bbox[0]
    yukseklik = bbox[3] - bbox[1]
    
    padding = 40 
    img = Image.new('RGBA', (genislik + padding*2, yukseklik + padding*2), (0, 0, 0, 0)) 
    draw = ImageDraw.Draw(img)
    
    draw.text(
        (padding - bbox[0], padding - bbox[1]), 
        metin, 
        font=font, 
        fill="yellow", 
        stroke_width=6, 
        stroke_fill="black"
    )
    
    dosya_adi = f"temp_kelime_{index}.png"
    img.save(dosya_adi)
    
    clip = ImageClip(dosya_adi).with_duration(sure)
    clip = clip.with_position(('center', int(v_yukseklik * 0.70)))
    
    return clip, dosya_adi

def video_fabrikasi(konu, progress=gr.Progress()):
    video_adi = "shorts_final.mp4"
    print(f" '{konu}' için Shorts üretimi başlıyor...")
    
    V_GENISLIK = 1080
    V_YUKSEKLIK = 1920
    olusturulan_yazi_dosyalari = [] 

    try:

        progress(0.05, desc="Senaryo Ve Görsel Planı Hazırlanıyor... ")
        print("📝 Senaryo ve görsel planı hazırlanıyor...")
        prompt = (f"Write a 30-second viral YouTube Shorts script about {konu}. "
                  "STRICT LIMIT: Maximum 65 words. English only. "
                  "CRITICAL INSTRUCTION: Start the script with a mind-blowing, highly engaging 3-second HOOK. "
                  "Also, provide 3 short image descriptions for the scenes. Make the first image prompt an intense, eye-catching visual that perfectly matches the hook. "
                  "Format: SCRIPT: [text] PROMPTS: [1. prompt, 2. prompt, 3. prompt]")
        
        response = gemini_client.models.generate_content(model="gemini-3.1-flash-lite-preview", contents=prompt)
        raw_text = response.text
        
        script_text = raw_text.split("PROMPTS:")[0].replace("SCRIPT:", "").strip()
        image_prompts = raw_text.split("PROMPTS:")[1].strip().split("\n")[:3]
        image_prompts = [p.strip("123. ") for p in image_prompts]

        progress(0.20, desc="Seslendiriliyor...")
        print("🗣 Seslendiriliyor...")
        voices = eleven_client.voices.get_all()
        target_voice_id = next((v.voice_id for v in voices.voices if "Adam" in v.name), voices.voices[0].voice_id)
        
        audio_generator = eleven_client.text_to_speech.convert(
            text=script_text, voice_id=target_voice_id, model_id="eleven_multilingual_v2"
        )
        with open("gecici_ses.mp3", "wb") as f:
            for chunk in audio_generator: f.write(chunk)

        progress(0.35,desc="Görseller çiziliyor...")
        print("🎨 Görseller çiziliyor...")
        resim_dosyalari = []
        api_url = "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell" 
        headers = {"Authorization": f"Bearer {HF_TOKEN}"}

        for i, p in enumerate(image_prompts):
            full_p = f"{p}, cinematic, documentary style, 8k, realistic, 9:16 ratio"
            resp = requests.post(api_url, headers=headers, json={"inputs": full_p})
            
            if resp.status_code == 200:
                img_path = f"sahne_{i}.png"
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                resim_dosyalari.append(img_path)
            else:
                print(f" Görsel {i} üretilemedi! Hata Kodu: {resp.status_code}")

        if not resim_dosyalari:
            return None, "HATA: Görsel üretilemedi."

        progress(0.60, desc="Analiz ediliyor...")
        
        audio_analysis = WHISPER_MODEL.transcribe("gecici_ses.mp3", word_timestamps=True)
        
        progress(0.70, desc="Arka plan montajı...")
        
        ana_ses = AudioFileClip("gecici_ses.mp3")
        sahne_suresi = ana_ses.duration / len(resim_dosyalari)
        
        klipler = []
        for m in resim_dosyalari:
            clip = ImageClip(m).with_duration(sahne_suresi)
            clip = clip.resized(height=V_YUKSEKLIK)
            if clip.w > V_GENISLIK:
                clip = clip.cropped(x_center=clip.w/2, width=V_GENISLIK)
            clip = clip.resized(lambda t: 1 + 0.03 * t) 
            klipler.append(clip)

        video_arkaplan = concatenate_videoclips(klipler, method="compose").with_audio(ana_ses)

        progress(0.80, desc="Altyazılar çiziliyor...")
        print("✍️ Altyazılar çiziliyor...")
        altyazi_klipleri = []
        kelime_index = 0
        
        for segment in audio_analysis['segments']:
            if 'words' in segment:
                for word_info in segment['words']:
                    metin = word_info['word'].strip().upper()
                    sure = word_info['end'] - word_info['start']
            
                    if sure <= 0 or not metin: 
                        continue

                    clip, dosya_adi = kusursuz_yazi_olustur(metin, sure, kelime_index, V_YUKSEKLIK)
                    clip = clip.with_start(word_info['start'])
                    
                    altyazi_klipleri.append(clip)
                    olusturulan_yazi_dosyalari.append(dosya_adi)
                    kelime_index += 1
        progress(0.90,desc="Render alınıyor...")
        print(" Render alınıyor...")
        final_video = CompositeVideoClip([video_arkaplan] + altyazi_klipleri, size=(V_GENISLIK, V_YUKSEKLIK))
        final_video.write_videofile(video_adi, fps=24, codec="libx264", audio_codec="aac")
        
        progress(1.0, desc="İŞLEM TAMAMLANDI.")
        print(f" İŞLEM TAMAM! Dosya: {video_adi}")
        return video_adi 
        
    except Exception as e:
        print(f" Hata: {e}")
        return None
        
    finally:
        for dosya in olusturulan_yazi_dosyalari:
            if os.path.exists(dosya):
                os.remove(dosya)


# --- GRADIO ARAYÜZÜ (GELİŞMİŞ TASARIM) ---

# Arayüz için özel CSS (Animasyonlar, renkler ve gölgeler)
custom_css = """
body {
    background-color: #0d1117;
}
#main-title {
    text-align: center;
    background: linear-gradient(90deg, #00C9FF 0%, #92FE9D 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    font-size: 3.5em;
    font-weight: 900;
    margin-bottom: 0px;
    padding-top: 20px;
}
#sub-title {
    text-align: center;
    color: #8b949e;
    font-size: 1.2em;
    margin-bottom: 40px;
}
#neon-btn {
    background: linear-gradient(45deg, #ff00cc, #3333ff) !important;
    border: none !important;
    color: white !important;
    font-weight: bold !important;
    font-size: 1.2em !important;
    padding: 15px !important;
    border-radius: 10px !important;
    transition: all 0.3s ease-in-out !important;
}
#neon-btn:hover {
    transform: scale(1.03) !important;
    box-shadow: 0 0 15px #ff00cc, 0 0 30px #3333ff !important;
}
.video-box {
    border-radius: 15px !important;
    box-shadow: 0 10px 30px rgba(0,0,0,0.4) !important;
}
"""

# Temayı Dark (Karanlık) yapıyoruz ve CSS'i ekliyoruz
with gr.Blocks(theme=gr.themes.Base(), css=custom_css) as demo:
    
    # Havalı Başlık
    gr.Markdown("<h1 id='main-title'> AI Shorts Studio</h1>")
    gr.Markdown("<p id='sub-title'>Sadece konuyu yazın, gerisini yapay zekaya bırakın. Senaryo, ses, görsel ve kurgu saniyeler içinde hazır!</p>")
    
    
    with gr.Row():
        
        
        with gr.Column(scale=1):
            gr.Markdown("###  İçerik Fikri")
            konu_input = gr.Textbox(
                label="", 
                placeholder="Örn: What if the Earth suddenly stopped spinning for just one second?",
                lines=8 
            )
            uret_btn = gr.Button(" VİDEOYU ÜRET", elem_id="neon-btn")
            gr.Markdown("<br><p style='color: gray; font-size: 0.9em;'>*Not: Render işlemi internet ve bilgisayar hızına bağlı olarak 1-2 dakika sürebilir. Lütfen bekleyin.*</p>")
        
        
        with gr.Column(scale=1):
            gr.Markdown("###  Sonuç (Hazır Video)")
            video_output = gr.Video(label="", elem_classes="video-box")

    
    uret_btn.click(fn=video_fabrikasi, inputs=konu_input, outputs=video_output)

if __name__ == "__main__":
    demo.launch()
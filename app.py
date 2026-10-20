import base64
import hashlib
import html
import json
import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ---------- 1. PERSIAPAN ----------
load_dotenv()
load_dotenv(Path(__file__).resolve().parent / ".env")
LOG_FILE = "data/log.csv"
HITS_FILE = "data/request_hits.txt"
SETTING_FILE = "data/pengaturan.json"
USAGE_FILE = "data/pemakaian.csv"
RIWAYAT_FILE = "data/riwayat_chat.json"
KOLOM_SEMBUNYI = ["temperature", "top_p", "top_k", "persona"]
MODE_CHAT, MODE_EKS = "💬 Chat", "🧪 Eksperimen"
os.makedirs("data", exist_ok=True)

CONFIG_TEMA = Path(".streamlit/config.toml")        # Streamlit hanya membaca config dari folder .streamlit
if not CONFIG_TEMA.exists():
    try:
        CONFIG_TEMA.parent.mkdir(exist_ok=True)
        CONFIG_TEMA.write_text("""[theme]
base = "light"
primaryColor = "#D97757"
backgroundColor = "#FFFFFF"
secondaryBackgroundColor = "#F8F7F5"
textColor = "#1A1A1A"
font = "sans serif"
baseRadius = "large"

[theme.sidebar]
backgroundColor = "#F8F7F5"
secondaryBackgroundColor = "#F0EFEA"

[client]
toolbarMode = "minimal"

[browser]
gatherUsageStats = false
""", encoding="utf-8")
    except Exception:
        pass

LOGO = "gambar/1.png"
ADA_LOGO = os.path.exists(LOGO)

def muat_gambar_b64(path):
    if os.path.exists(path):
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    return ""

logo_b64 = muat_gambar_b64(LOGO)

st.set_page_config(page_title="PANDU", page_icon=LOGO if ADA_LOGO else "🤖", layout="wide")
if ADA_LOGO:
    st.logo(LOGO, size="large")                  # logo di paling atas sidebar, di atas menu halaman (sama seperti Dashboard)

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@800;900&display=swap');

header[data-testid="stHeader"] {{background: transparent !important;}}   /* header tetap ada supaya menu titik tiga & tombol sidebar muncul */
[data-testid="stBottom"] > div {{background: #FFFFFF !important;}}
footer, [data-testid="stDecoration"], [data-testid="stAppDeployButton"], .stAppDeployButton {{display: none !important;}}

.stApp {{ background-color: #FFFFFF; }}

/* Sidebar ala Claude */
section[data-testid="stSidebar"] {{
    background-color: #F8F7F5 !important;
    border-right: 1px solid #EAE9E5;
}}

.grup {{font-size: .70rem; opacity: .6; font-weight: 700; text-transform: uppercase;
       letter-spacing: .07em; margin: .9rem 0 .15rem .4rem;}}

section[data-testid="stSidebar"] [data-testid="stButtonGroup"] {{width: 100%;}}
section[data-testid="stSidebar"] [data-testid="stButtonGroup"] button {{flex: 1;}}

section[data-testid="stSidebar"] .stButton button[kind="secondary"],
section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-secondary"] {{
       background: transparent; border: 0; box-shadow: none; color: inherit; min-height: 0;
       justify-content: flex-start; font-weight: 500; padding: .5rem .7rem; border-radius: 8px;}}
section[data-testid="stSidebar"] .stButton button[kind="secondary"]:hover,
section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-secondary"]:hover {{background: #EAE9E5;}}
section[data-testid="stSidebar"] .stButton button[kind="secondary"] > div,
section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-secondary"] > div {{width: 100%; justify-content: flex-start;}}
section[data-testid="stSidebar"] .stButton button[kind="secondary"] p,
section[data-testid="stSidebar"] .stButton button[data-testid="stBaseButton-secondary"] p {{
       margin: 0; width: 100%; text-align: left; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: #1A1A1A;}}

[class*="st-key-aktif_"] .stButton button {{background: #EAE9E5 !important; font-weight: 600;}}

section[data-testid="stSidebar"] [data-testid="stColumn"]:last-child .stButton button {{
       justify-content: center; opacity: .45; padding: .5rem .3rem;}}
section[data-testid="stSidebar"] [data-testid="stColumn"]:last-child .stButton button:hover {{opacity: 1;}}

[data-testid="stChatInput"] {{ 
    border-radius: 12px; border: 1px solid #EAE9E5; 
    background-color: #F8F7F5; box-shadow: none; 
}}
[data-testid="stChatInput"]:focus-within {{ border-color: #D4D3CF; }}

[data-testid="stChatMessage"] {{ background: transparent; padding: 1.5rem 0; gap: 1rem; border-bottom: 1px solid #F8F7F5; }}
[data-testid="stChatMessageAvatarUser"] {{display: none;}}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{
    background: transparent; padding: 1rem 0;
    width: 100%; max-width: 100%; margin: 0;}}
    
[data-testid="stChatMessageAvatarAssistant"] {{ background-color: #F8F7F5; color: #1A1A1A; border: 1px solid #EAE9E5; }}

.salam {{ text-align: center; margin: 20vh 0 3rem; }}
.salam h1 {{ 
    font-family: 'Newsreader', serif; font-size: 3.2rem; 
    font-weight: 500; color: #1A1A1A; margin-bottom: 0.5rem; 
    line-height: 1.2; letter-spacing: -0.5px;
}}
.salam p {{ color: #555555; font-size: 1.1rem; font-family: sans-serif; }}

.hero {{ background: #F8F7F5; border: 1px solid #EAE9E5; 
       border-radius: 16px; padding: 26px 32px; margin-bottom: 18px; color: #1A1A1A; }}
.hero-title {{ font-family: 'Newsreader', serif; font-size: 2.2rem; font-weight: 500; letter-spacing: -0.5px; }}
.hero-sub {{ color: #555555; margin-top: 6px; font-size: 1rem; }}

[data-testid="stMetric"] {{ background: #FFFFFF; border: 1px solid #EAE9E5; padding: 14px 18px; border-radius: 12px; border-left: none; }}
[data-testid="stMetricLabel"] {{ color: #555555; font-size: 0.9rem; }}
[data-testid="stMetricValue"] {{ color: #1A1A1A; font-weight: 600; font-family: 'Newsreader', serif; }}

.stButton button, .stDownloadButton > button {{
    border-radius: 8px; font-weight: 500; border: 1px solid #EAE9E5; 
    background-color: #FFFFFF; color: #1A1A1A; transition: all 0.2s;
    width: 100%; padding: .55rem 1rem;
}}
.stButton button:hover, .stDownloadButton > button:hover {{ 
    background-color: #F0EFEA; border-color: #D4D3CF; color: #1A1A1A; 
}}
.stButton button[kind="primary"] {{ background-color: #1A1A1A; color: #FFFFFF; border: none; }}
.stButton button[kind="primary"]:hover {{ background-color: #333333; color: #FFFFFF; }}

[data-testid="stVerticalBlockBorderWrapper"] {{border-radius: 12px; border: 1px solid #EAE9E5;}}
.kosong {{border: 2px dashed #EAE9E5; border-radius: 16px; padding: 56px 20px;
         text-align: center; color: #555555; line-height: 1.7;}}

/* ===== jaring pengaman: tetap terang walau tema Streamlit gelap atau config.toml belum terbaca ===== */
:root {{ color-scheme: light; }}
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNav"] a span, [data-testid="stSidebarNavLink"], [data-testid="stSidebarNavLink"] span {{ color: #1A1A1A !important; }}
.grup {{ color: #6B6B6B !important; opacity: 1 !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: #6B6B6B !important; }}
[data-testid="stWidgetLabel"] p, [data-testid="stExpander"] summary, [data-testid="stExpander"] summary p {{ color: #1A1A1A !important; }}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-segmented_control"] {{
    background: #FFFFFF !important; color: #1A1A1A !important; border: 1px solid #EAE9E5 !important; }}
section[data-testid="stSidebar"] button[data-testid="stBaseButton-segmented_controlActive"] {{
    background: #1A1A1A !important; color: #FFFFFF !important; border: 1px solid #1A1A1A !important; }}
button[data-testid^="stBaseButton-segmented"] p {{ color: inherit !important; }}
[data-testid="stChatInput"], [data-testid="stChatInput"] > div, [data-testid="stChatInputTextArea"] {{
    background: #FFFFFF !important; color: #1A1A1A !important; }}
[data-testid="stChatInput"] textarea::placeholder {{ color: #8A8A8A !important; }}
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea, [data-baseweb="select"] > div {{
    background-color: #FFFFFF !important; color: #1A1A1A !important; border-color: #EAE9E5 !important; }}

/* ===== tulisan PANDU di samping logo sidebar ===== */
/* pembungkus logo bisa berupa <a> (halaman selain utama) atau <div> (halaman utama), jadi dicari lewat gambar logonya */
div:has(> [data-testid="stSidebarLogo"]), a:has(> [data-testid="stSidebarLogo"]) {{ display: flex !important; align-items: center; gap: .65rem; text-decoration: none !important; }}
div:has(> [data-testid="stSidebarLogo"])::after, a:has(> [data-testid="stSidebarLogo"])::after {{
    content: "PANDU"; font-family: 'Orbitron', sans-serif; font-weight: 900; font-size: 1.45rem; letter-spacing: .16em; line-height: 1;
    background: linear-gradient(135deg, #1A1A1A 0%, #D97757 100%);
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }}
</style>
""", unsafe_allow_html=True)


# ---------- 2. FUNGSI JATAH REQUEST ----------
def baca_pengaturan():
    baku = {"rpd": 20, "rpm": 5, "tpm": 250000, "offset_kunci": {}}
    try:
        with open(SETTING_FILE) as f:
            baku.update(json.load(f))
    except Exception:
        pass
    return baku


try:
    from zoneinfo import ZoneInfo
    PASIFIK = ZoneInfo("America/Los_Angeles")
except Exception:
    PASIFIK = None


def hari_google(waktu=None):
    waktu = waktu or datetime.now()
    if PASIFIK is None:
        return waktu.strftime("%Y-%m-%d")
    return waktu.astimezone(PASIFIK).strftime("%Y-%m-%d")


def jam_reset():
    if PASIFIK is None:
        return None
    sekarang = datetime.now(PASIFIK)
    tengah = (sekarang + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tengah.astimezone().strftime("%H:%M")


def baca_waktu(teks):
    for bentuk in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(teks).strip(), bentuk)
        except ValueError:
            pass
    return None


def id_kunci(kunci):
    return hashlib.sha256(kunci.encode()).hexdigest()[:8] if kunci else ""


def catat_request(kunci):
    with open(HITS_FILE, "a") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "|" + id_kunci(kunci) + "\n")


def hitung_request(kunci):
    hari_ini = menit_ini = 0
    kid = id_kunci(kunci)
    if os.path.exists(HITS_FILE):
        sekarang = datetime.now()
        hari = hari_google(sekarang)
        with open(HITS_FILE) as f:
            for baris in f:
                teks, _, kode = baris.strip().partition("|")
                if kode != kid:
                    continue
                waktu = baca_waktu(teks)
                if waktu is None:
                    continue
                if hari_google(waktu) == hari:
                    hari_ini += 1
                if (sekarang - waktu).total_seconds() < 60:
                    menit_ini += 1
    o = baca_pengaturan().get("offset_kunci", {}).get(kid)
    if o and o.get("hari") == hari_google():
        hari_ini = max(hari_ini + int(o.get("rpd", 0)), 0)
    return hari_ini, menit_ini


def hitung_tpm(kunci):
    if not os.path.exists(USAGE_FILE):
        return 0
    d = pd.read_csv(USAGE_FILE)
    if "kunci" not in d.columns:
        return 0
    d = d[d["kunci"].fillna("") == id_kunci(kunci)]
    batas = datetime.now() - timedelta(seconds=60)
    ada = d["waktu"].apply(baca_waktu).apply(lambda w: w is not None and w >= batas)
    return int(pd.to_numeric(d.loc[ada, "input_tokens"], errors="coerce").fillna(0).sum())


def catat_pemakaian(usage):
    baru = pd.DataFrame([{"waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "model": model,
                          "anggota": anggota, "kunci": id_kunci(kunci_aktif), **usage}])
    if os.path.exists(USAGE_FILE):
        data = pd.concat([pd.read_csv(USAGE_FILE), baru], ignore_index=True)
    elif os.path.exists(LOG_FILE):
        lama = pd.read_csv(LOG_FILE)
        kolom = ["waktu", "model", "anggota", "input_tokens", "output_tokens", "thinking_tokens", "total_tokens"]
        data = pd.concat([lama.reindex(columns=kolom), baru], ignore_index=True)
    else:
        data = baru
    data.to_csv(USAGE_FILE, index=False)


def token_terpakai():
    if os.path.exists(USAGE_FILE):
        return int(pd.read_csv(USAGE_FILE)["total_tokens"].sum())
    if os.path.exists(LOG_FILE):
        return int(pd.read_csv(LOG_FILE)["total_tokens"].sum())
    return 0


# ---------- 3. RIWAYAT OBROLAN ----------
def muat_riwayat():
    try:
        with open(RIWAYAT_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def simpan_riwayat(data):
    with open(RIWAYAT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def kelompok_waktu(teks):
    w = baca_waktu(teks)
    if w is None:
        return "Lebih lama"
    selisih = (datetime.now().date() - w.date()).days
    if selisih <= 0:
        return "Hari ini"
    if selisih == 1:
        return "Kemarin"
    if selisih <= 7:
        return "7 hari terakhir"
    return "Lebih lama"


def obrolan_baru():
    st.session_state["chat_id"] = None
    st.session_state["pesan"] = []
    st.session_state["mode_pilih"] = MODE_CHAT


def buka_chat(cid):
    c = muat_riwayat().get(cid)
    if c:
        st.session_state["chat_id"] = cid
        st.session_state["pesan"] = c.get("pesan", [])
    st.session_state["mode_pilih"] = MODE_CHAT


def hapus_chat(cid):
    data = muat_riwayat()
    data.pop(cid, None)
    simpan_riwayat(data)
    if st.session_state.get("chat_id") == cid:
        obrolan_baru()


def simpan_chat(pesan):
    data = muat_riwayat()
    sekarang = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cid = st.session_state.get("chat_id")
    if cid is None or cid not in data:
        cid = uuid.uuid4().hex[:8]
        judul = pesan[0]["text"].strip().replace("\n", " ")
        data[cid] = {"judul": judul[:60] or "Obrolan baru", "dibuat": sekarang}
        st.session_state["chat_id"] = cid
    data[cid]["pesan"] = pesan
    data[cid]["diubah"] = sekarang
    simpan_riwayat(data)
    st.session_state["pesan"] = pesan


def pakai_saran(teks):
    st.session_state["_saran"] = teks


# ---------- 4. SIDEBAR ----------
def ingat(kunci, baku):
    return st.session_state.get("_ingat_" + kunci, baku)


def simpan_ingatan(kunci, nilai):
    st.session_state["_ingat_" + kunci] = nilai
    return nilai


PERSONA_TEKS = "Kamu adalah pemandu wisata Yogyakarta yang ramah dan penuh semangat. Jawab dalam bahasa Indonesia."   # persona tetap untuk mode Chat

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
zai_key = os.getenv("ZAI_API_KEY") or ""          # key Z.ai, dipakai kalau model GLM dipilih
anggota = "Steven Teody Budiono"

st.session_state.setdefault("chat_id", None)
st.session_state.setdefault("pesan", [])
if "mode_pilih" not in st.session_state:
    st.session_state["mode_pilih"] = ingat("mode", MODE_CHAT)

with st.sidebar:
    if not ADA_LOGO:
        st.markdown("### PANDU")
    
    mode = st.segmented_control("Mode", [MODE_CHAT, MODE_EKS], key="mode_pilih", label_visibility="collapsed")
    mode = simpan_ingatan("mode", mode or ingat("mode", MODE_CHAT))

    if mode == MODE_CHAT:
        st.button("✏️ Obrolan baru", type="primary", key="baru", on_click=obrolan_baru)
        riwayat = muat_riwayat()
        with st.container(key="riwayat", height=330, border=False):
            if not riwayat:
                st.caption("Belum ada riwayat obrolan.")
            terakhir = None
            for cid, c in sorted(riwayat.items(), key=lambda kv: kv[1].get("diubah", ""), reverse=True):
                grup = kelompok_waktu(c.get("diubah"))
                if grup != terakhir:
                    st.markdown(f'<div class="grup">{grup}</div>', unsafe_allow_html=True)
                    terakhir = grup
                judul = c.get("judul", "Obrolan").replace("`", "'")
                kiri_s, kanan_s = st.columns([6, 1], gap="small", vertical_alignment="center")
                aktif = cid == st.session_state["chat_id"]
                kiri_s.button(judul[:34] + ("…" if len(judul) > 34 else ""),
                              key=f"aktif_{cid}" if aktif else f"buka_{cid}",
                              on_click=buka_chat, args=(cid,), help=judul)
                kanan_s.button("🗑", key=f"hapus_{cid}", on_click=hapus_chat, args=(cid,), help="Hapus obrolan ini")

    st.divider()
    with st.expander("⚙️ Model"):
        opsi_model = ["gemini-3.8-flash", "glm-4.7-flash"]
        model_terpilih = ingat("model", "gemini-3.8-flash")
        idx_model = opsi_model.index(model_terpilih) if model_terpilih in opsi_model else 0
        model = simpan_ingatan("model", st.selectbox("Pilih model", opsi_model, index=idx_model, key="model"))

    cari_web = False
    if mode == MODE_CHAT:
        cari_web = simpan_ingatan("cari_web", st.toggle("🌐 Pencarian web", value=ingat("cari_web", False), key="cari_web",
                                                        help="Untuk pertanyaan yang butuh info terbaru (berita, harga, dll). Hanya berlaku di mode Chat."))
        if cari_web:
            st.caption("Hasil pencarian ikut dihitung sebagai token input, dan pencarian bisa punya kuota atau biaya "
                       "sendiri di penyedia. Mode Eksperimen tidak memakai pencarian.")

    persona_teks = PERSONA_TEKS if mode == MODE_CHAT else ""      # Chat selalu berpersona pemandu wisata; Eksperimen tanpa persona tambahan

    params = {}      # parameter sampling tidak diatur manual lagi: model memakai nilai bawaannya

    pengaturan = baca_pengaturan()
    if str(model).lower().startswith("glm"):
        batas = pengaturan                                   # batas GLM disimpan di rpd/rpm/tpm (diatur di Dashboard)
    else:                                                    # batas Gemini disimpan terpisah, supaya tidak ikut angka GLM
        batas = {"rpd": 20, "rpm": 5, "tpm": 250000, **pengaturan.get("batas_gemini", {})}
    rpd, rpm, tpm = int(batas["rpd"]), int(batas["rpm"]), int(batas["tpm"])

lebar = "820px" if mode == MODE_CHAT else "1280px"
bawah = "6rem" if mode == MODE_CHAT else "5rem"
st.markdown(f"<style>.block-container {{padding-top: 2rem; padding-bottom: {bawah}; max-width: {lebar};}}</style>",
            unsafe_allow_html=True)

pakai_glm = str(model).lower().startswith("glm")          # GLM dipanggil lewat Z.ai, selain itu Gemini
kunci_aktif = zai_key if pakai_glm else api_key
nama_ai = "GLM" if pakai_glm else "Gemini"                 # dipakai untuk teks tombol dan judul

if not kunci_aktif:
    if pakai_glm:
        st.error("API key Z.ai belum ditemukan. Tambahkan baris ini di file **`.env`**, lalu jalankan ulang Streamlit:")
        st.code("ZAI_API_KEY=isi_api_key_zai_di_sini", language="bash")
    else:
        st.error("API key belum ditemukan. Buat file **`.env`** di folder yang sama dengan `app.py`, isi seperti ini, "
                 "lalu jalankan ulang Streamlit:")
        st.code("GEMINI_API_KEY=isi_api_key_kamu_di_sini", language="bash")
    if mode == MODE_CHAT:
        st.chat_input("Isi API key di file .env dulu...", disabled=True)
    st.stop()

client = genai.Client(api_key=api_key) if api_key else None


# ---------- 5. FUNGSI BANTU ----------
ZAI_URL = "https://api.z.ai/api/paas/v4/chat/completions"      # API Z.ai (kompatibel dengan format OpenAI)


class HasilGLM:
    """Pembungkus jawaban GLM supaya bentuknya mirip jawaban Gemini (punya .text) dan membawa data token."""
    def __init__(self, text, usage, sumber=None):
        self.text, self.usage, self.sumber = text, usage, sumber or []


def ke_pesan_glm(contents, system=None):
    """Ubah isi percakapan (teks, atau daftar pesan gaya Gemini) menjadi daftar pesan gaya OpenAI."""
    pesan = []
    if system:
        pesan.append({"role": "system", "content": system})
    if isinstance(contents, str):
        pesan.append({"role": "user", "content": contents})
    else:
        for c in contents:
            teks = "".join(p.text or "" for p in c.parts)
            pesan.append({"role": "assistant" if c.role == "model" else "user", "content": teks})
    return pesan


@st.cache_resource
def _antrean_glm():
    """Satu kunci untuk seluruh aplikasi. Saat halaman dijalankan ulang (mis. tombol sidebar digeser) request lama
    ke Z.ai masih berjalan di server, jadi request baru menunggu giliran supaya tidak melewati batas konkurensi (kode 1302)."""
    return threading.Lock()


def panggil_glm(contents, system=None, cari=False):
    pesan = ke_pesan_glm(contents, system)
    isi = {"model": model, "messages": pesan}
    if cari:                                   # pencarian web bawaan Z.ai (tools -> web_search), sesuai docs.z.ai
        kueri = next((m["content"] for m in reversed(pesan) if m["role"] == "user"), "")
        isi["tools"] = [{"type": "web_search", "web_search": {"enable": "True", "search_engine": "search-prime",
                                                              "search_result": "True", "search_query": kueri.strip()[:70]}}]
    if "temperature" in params:
        isi["temperature"] = params["temperature"]
    if "top_p" in params:
        isi["top_p"] = params["top_p"]
    r = requests.post(ZAI_URL, json=isi, timeout=120,
                      headers={"Authorization": f"Bearer {kunci_aktif}", "Content-Type": "application/json"})
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code} {r.text[:300]}")
    data = r.json()
    teks = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    u = data.get("usage") or {}
    pikir = int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    keluar = int(u.get("completion_tokens") or 0)
    masuk = int(u.get("prompt_tokens") or 0)
    usage = {"input_tokens": masuk, "output_tokens": max(keluar - pikir, 0), "thinking_tokens": pikir,
             "total_tokens": int(u.get("total_tokens") or (masuk + keluar))}
    sumber = []
    for it in (data.get("web_search") or []):                       # daftar hasil pencarian (kalau dikembalikan server)
        if isinstance(it, dict) and (it.get("link") or it.get("url")):
            sumber.append({"judul": it.get("title") or it.get("media") or (it.get("link") or it.get("url")),
                           "url": it.get("link") or it.get("url"),
                           "situs": it.get("media") or "", "ref": str(it.get("refer") or "")})
    return HasilGLM(teks, usage, sumber)


def tanya_glm(contents, system=None, coba=3, cari=False):
    for i in range(coba):
        catat_request(kunci_aktif)
        try:
            with _antrean_glm():
                hasil = panggil_glm(contents, system, cari)
        except Exception as e:
            pesan = str(e)
            # 5xx = server error; 1305 = server Z.ai kelebihan beban; 1302 = terlalu banyak request bersamaan. Keduanya biasanya reda dalam hitungan detik
            sibuk = pesan.strip()[:3] in ("500", "502", "503", "504") or '"1305"' in pesan or '"1302"' in pesan or "overloaded" in pesan.lower()
            if sibuk and i < coba - 1:
                time.sleep(8 * (i + 1))          # tunggu 8 detik, lalu 16 detik
                continue
            raise
        catat_pemakaian(hasil.usage)
        return hasil


def stream_glm(contents, system, hasil, saat_mulai=None, coba=3, cari=False):
    """GLM dipanggil tanpa streaming (supaya data token pasti lengkap), lalu jawabannya ditampilkan sekaligus."""
    h = tanya_glm(contents, system, coba, cari)
    hasil["usage"] = h.usage
    hasil["sumber"] = h.sumber
    if saat_mulai:
        saat_mulai()
    if h.text:
        yield h.text


def tanya_gemini(contents, system=None, coba=2):
    if pakai_glm:
        return tanya_glm(contents, system, coba)
    isi = dict(params)
    if system:
        isi["system_instruction"] = system
    config = types.GenerateContentConfig(**isi) if isi else None
    for i in range(coba):
        catat_request(kunci_aktif)
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:
            sibuk = "503" in str(e) or "UNAVAILABLE" in str(e)
            if sibuk and i < coba - 1:
                time.sleep(10)
                continue
            raise
        catat_pemakaian(baca_usage(resp))
        return resp


def ambil_grounding(potongan):
    """Dari Grounding with Google Search: (daftar sumber, peta nomor chunk -> nomor sumber, daftar pendukung kalimat)."""
    try:
        meta = potongan.candidates[0].grounding_metadata
        sumber, peta = [], {}
        for idx, c in enumerate(meta.grounding_chunks or []):
            if c.web and c.web.uri:
                sumber.append({"judul": c.web.title or c.web.uri, "url": c.web.uri, "situs": "", "ref": ""})
                peta[idx] = len(sumber)
        return sumber, peta, list(meta.grounding_supports or [])
    except Exception:
        return [], {}, []


def sisipkan_rujukan_gemini(teks, supports, peta, sumber):
    """Sisipkan penanda [1] [2] (berupa tautan) di akhir kalimat yang didukung sumber. Indeks dari Google dalam byte UTF-8."""
    try:
        sisip = []
        for sp in (supports or []):
            akhir = sp.segment.end_index
            nomor = sorted({peta[i] for i in (sp.grounding_chunk_indices or []) if i in peta})
            if akhir is not None and nomor:
                sisip.append((akhir, "".join(f"[[{n}]]({sumber[n - 1]['url']})" for n in nomor)))
        data = teks.encode("utf-8")
        for akhir, tanda in sorted(sisip, key=lambda x: -x[0]):
            data = data[:akhir] + tanda.encode("utf-8") + data[akhir:]
        return data.decode("utf-8")
    except Exception:
        return teks                                    # kalau ada yang janggal, tampilkan jawaban apa adanya


def rujukan_glm(teks, sumber):
    """Ubah penanda [ref_1] dari Z.ai menjadi tautan bernomor [1]."""
    try:
        for n, x in enumerate(sumber, 1):
            ref = x.get("ref", "").strip("[]")
            if ref:
                tautan = f"[[{n}]]({x['url']})"
                teks = teks.replace(f"[{ref}]", tautan).replace(f"【{ref}】", tautan)
        return teks
    except Exception:
        return teks


def tampilkan_sumber(sumber):
    """Kotak daftar link sumber bernomor di bawah jawaban."""
    unik, terlihat = [], set()
    for x in sumber or []:
        if x.get("url") and x["url"] not in terlihat:
            terlihat.add(x["url"]); unik.append(x)
    if not unik:
        return
    with st.expander(f"🔗 Sumber ({len(unik)})", expanded=True):
        for n, x in enumerate(unik, 1):
            situs = x.get("situs") or ""
            judul = (x.get("judul") or x["url"]).replace("[", "(").replace("]", ")")[:90]
            st.markdown(f"{n}. [{judul}]({x['url']})" + (f" — {situs}" if situs and situs not in judul else ""))


def tanya_stream(contents, system, hasil, saat_mulai=None, coba=2, cari=False):
    if pakai_glm:
        yield from stream_glm(contents, system, hasil, saat_mulai, 3, cari)
        return
    isi = dict(params)
    if system:
        isi["system_instruction"] = system
    if cari:
        isi["tools"] = [types.Tool(google_search=types.GoogleSearch())]      # pencarian Google bawaan Gemini
    config = types.GenerateContentConfig(**isi) if isi else None
    for i in range(coba):
        catat_request(kunci_aktif)
        sudah_keluar = False
        try:
            for potongan in client.models.generate_content_stream(model=model, contents=contents, config=config):
                if potongan.usage_metadata:
                    hasil["usage"] = baca_usage(potongan)
                src, peta, supports = ambil_grounding(potongan)
                if src:
                    hasil["sumber"], hasil["peta"], hasil["supports"] = src, peta, supports
                if potongan.text:
                    if not sudah_keluar and saat_mulai:
                        saat_mulai()
                    sudah_keluar = True
                    yield potongan.text
        except Exception as e:
            sibuk = "503" in str(e) or "UNAVAILABLE" in str(e)
            if sibuk and i < coba - 1 and not sudah_keluar:
                time.sleep(10)
                continue
            raise
        if "usage" in hasil:
            catat_pemakaian(hasil["usage"])
        return


def peringatan_jatah():
    hari_ini, menit_ini = hitung_request(kunci_aktif)
    if hari_ini >= rpd:
        st.warning(f"Perkiraan jatah request hari ini sudah habis ({hari_ini}/{rpd}). Request bisa ditolak (error 429).")
    elif menit_ini >= rpm:
        st.warning(f"Sudah {menit_ini} request dalam 1 menit terakhir (batas {rpm}). Tunggu sebentar sebelum mengirim lagi.")


def tampilkan_error(e):
    pesan = str(e)
    kode = pesan.strip()[:3]
    penyedia = "Z.ai" if pakai_glm else "Gemini API"
    if "1305" in pesan or "overloaded" in pesan.lower():
        st.error(f"Server {penyedia} sedang kelebihan beban (kode 1305), padahal kuota kamu belum tentu habis. "
                 "Aplikasi sudah mencoba ulang otomatis beberapa kali. Tunggu 1-2 menit lalu klik Coba lagi, "
                 "atau pindah ke model lain lewat ⚙️ Model di sidebar.")
        with st.expander("Detail error dari server"):
            st.code(pesan[:1500])
    elif '"1302"' in pesan or "Rate limit reached for requests" in pesan:
        st.error(f"{penyedia} menolak karena terlalu banyak request diproses **bersamaan** (kode 1302: batas konkurensi model **{model}**), "
                 "bukan kuota harian. Tunggu sekitar 30 detik tanpa mengubah apa pun di sidebar, lalu klik Coba lagi. "
                 "Hindari menggeser tombol atau mengirim ulang saat jawaban masih diproses.")
        with st.expander("Detail error dari server"):
            st.code(pesan[:1500])
    elif "429" in pesan or "RESOURCE_EXHAUSTED" in pesan:
        rendah = pesan.lower()
        reset = jam_reset()
        if "limit: 0" in rendah:
            sebab = (f"Model **{model}** tidak punya kuota sama sekali di akun/paket API key ini (limit: 0). "
                     "Coba pilih model lain di sidebar (⚙️ Model).")
        elif "perday" in rendah or "per day" in rendah:
            sebab = ("Yang habis adalah kuota **harian** (RPD). Cek di dashboard penyedia, karena pemakaian dari "
                     "tempat lain dengan API key yang sama ikut dihitung. "
                     + (f"Reset berikutnya sekitar jam {reset} (waktu laptop)." if reset and not pakai_glm else ""))
        elif "perminute" in rendah or "per minute" in rendah:
            sebab = "Yang habis adalah kuota **per menit**. Tunggu sekitar 1 menit lalu klik Coba lagi."
        else:
            sebab = "Bisa kuota per menit atau per hari. Lihat detail di bawah untuk tahu yang mana."
        st.error(f"{penyedia} menolak request untuk model **{model}** (error 429: kuota habis, bukan salah modelnya). {sebab}")
        with st.expander("Detail error dari server"):
            st.code(pesan[:1500])
    elif kode == "404" or "NOT_FOUND" in pesan:
        st.error(f"Model **{model}** tidak dikenali oleh {penyedia}. Pilih model lain di sidebar (⚙️ Model).")
    elif kode in ("401", "403") or "API_KEY_INVALID" in pesan or "PERMISSION_DENIED" in pesan:
        st.error(f"API key {penyedia} ditolak. Cek isi file `.env`, lalu jalankan ulang Streamlit.")
    elif kode == "503" or "UNAVAILABLE" in pesan:
        st.error("Server model sedang sibuk (503). Tunggu beberapa menit lalu coba lagi.")
    else:
        st.error(f"Gagal: {e}")


def baca_usage(resp):
    if isinstance(resp, HasilGLM):
        return resp.usage
    u = resp.usage_metadata
    return {
        "input_tokens": u.prompt_token_count or 0,
        "output_tokens": u.candidates_token_count or 0,
        "thinking_tokens": getattr(u, "thoughts_token_count", 0) or 0,
        "total_tokens": u.total_token_count or 0,
    }


WIB = timezone(timedelta(hours=7))                     # WIB = UTC+7


def jam_wib():
    """Jam sekarang dalam WIB, misalnya '22.14 WIB' (tidak bergantung pada zona waktu laptop)."""
    return datetime.now(WIB).strftime("%H.%M") + " WIB"


def baris_dasar(jenis, nomor, prompt, jawaban, usage):
    return {
        "waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "anggota": anggota,
        "jenis": jenis, "model": model, "nomor_kombinasi": nomor,
        "prompt": prompt, "jawaban": jawaban, **usage,
    }


def simpan_log(baris):
    baris = pd.DataFrame([baris])
    if os.path.exists(LOG_FILE):
        lama = pd.read_csv(LOG_FILE, dtype={"nomor_kombinasi": str})
        data = pd.concat([lama, baris], ignore_index=True)
    else:
        data = baris
    data["total_kumulatif"] = data["total_tokens"].cumsum()
    data.to_csv(LOG_FILE, index=False)
    return int(data["total_kumulatif"].iloc[-1])


# ---------- 6. HALAMAN CHAT ----------
SARAN = ["Buatkan itinerari liburan 3 hari di Yogyakarta",
         "Rekomendasi kuliner khas Yogyakarta yang wajib dicoba",
         "Tempat wisata alam terbaik di sekitar Yogyakarta",
         "Tips berkunjung ke Candi Prambanan dan Keraton"]


def halaman_chat():
    pesan = st.session_state["pesan"]
    teks = st.chat_input("Tanya seputar wisata Yogyakarta...", key="chat_input")
    saran = st.session_state.pop("_saran", None)
    teks = teks or saran

    if not pesan and not teks:
        # Nama Steven dihapus, sekarang hanya menampilkan "Halo!" saja
        st.markdown(f'<div class="salam">'
                    f'<h1>Halo!</h1>'
                    f'<p>Ada yang bisa aku bantu hari ini?</p></div>', unsafe_allow_html=True)
        k1, k2 = st.columns(2)
        for i, s in enumerate(SARAN):
            (k1 if i % 2 == 0 else k2).button(s, key=f"saran_{i}", on_click=pakai_saran, args=(s,))

    for m in pesan:
        with st.chat_message("user" if m["role"] == "user" else "assistant"):
            st.markdown(m.get("tampil") or m["text"])
            if m.get("info"):
                st.caption((f"🤖 {m['model']} | " if m.get("model") else "") + m["info"])
            tampilkan_sumber(m.get("sumber"))

    if not teks:
        return

    jam_kirim = jam_wib()                               # jam saat pesan dikirim
    peringatan_jatah()
    riwayat_gemini = [types.Content(role=m["role"], parts=[types.Part(text=m["text"])]) for m in pesan]
    contents = riwayat_gemini + [types.Content(role="user", parts=[types.Part(text=teks)])]
    with st.chat_message("user"):
        st.markdown(teks)

    hasil, jawaban = {}, None
    with st.chat_message("assistant"):
        berpikir = st.empty()
        berpikir.markdown("_Sedang berpikir…_")
        try:
            jawaban = st.write_stream(tanya_stream(contents, persona_teks.strip() or None, hasil,
                                                   saat_mulai=berpikir.empty, cari=cari_web))
        except Exception as e:
            berpikir.empty()
            tampilkan_error(e)
            st.button("↻ Coba lagi", key="coba_lagi", on_click=pakai_saran, args=(teks,))

    if jawaban is None:
        return
    jawaban = jawaban or "(kosong)"
    usage = hasil.get("usage") or {"input_tokens": 0, "output_tokens": 0, "thinking_tokens": 0, "total_tokens": 0}
    info = (f"Input: {usage['input_tokens']} | Output: {usage['output_tokens']} | "
            f"Thinking: {usage['thinking_tokens']} | Total: {usage['total_tokens']} | "
            f"Waktu: {jam_kirim}")
    if cari_web:
        info = "🌐 Web | " + info
    simpan_log({**baris_dasar("chat", "chat", teks, jawaban, usage), "kualitas": "(chat + web)" if cari_web else "(chat)"})
    sumber = hasil.get("sumber") or []
    tampil = jawaban
    if sumber:
        tampil = (rujukan_glm(jawaban, sumber) if pakai_glm
                  else sisipkan_rujukan_gemini(jawaban, hasil.get("supports"), hasil.get("peta"), sumber))
    simpan_chat(pesan + [{"role": "user", "text": teks},
                         {"role": "model", "text": jawaban, "tampil": tampil if tampil != jawaban else None,
                          "info": info, "model": model, "sumber": sumber}])
    st.rerun()


# ---------- 7. HALAMAN EKSPERIMEN ----------
def halaman_eksperimen():
    st.write("")

    kiri, kanan = st.columns([5, 7], gap="large")
    with kiri:
        with st.container(border=True):
            st.markdown("#### ✍️ Prompt")
            st.caption("Prompt dikirim apa adanya, tanpa persona tambahan, supaya hasil tiap nomor kombinasi bisa dibandingkan.")
            nomor = simpan_ingatan("nomor", st.text_input("Nomor kombinasi", placeholder="mis. 3.2", key="nomor",
                                                          value=ingat("nomor", "")))
            prompt = simpan_ingatan("prompt", st.text_area("Prompt", height=220, key="prompt",
                                                           value=ingat("prompt", "")))
            kirim = st.button(f"🚀 Kirim ke {nama_ai}", type="primary", key="kirim")
        if kirim:
            if not prompt.strip():
                st.warning("Prompt masih kosong.")
            else:
                peringatan_jatah()
                resp = None
                jam_kirim = jam_wib()
                try:
                    with st.spinner(f"Menunggu {nama_ai} ({model})..."):
                        resp = tanya_gemini(prompt)
                except Exception as e:
                    tampilkan_error(e)
                if resp is not None:
                    st.session_state["hasil"] = baris_dasar(
                        "eksperimen", nomor, prompt, resp.text or "(kosong)", baca_usage(resp))
                    st.session_state["hasil_jam"] = jam_kirim

    with kanan:
        if "hasil" in st.session_state:
            h = st.session_state["hasil"]
            with st.container(border=True):
                st.markdown("#### 🤖 Jawaban " + nama_ai)
                st.caption(f"Nomor kombinasi: {h['nomor_kombinasi'] or '-'}  |  Model: {h['model']}")
                st.write(h["jawaban"])
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Token input", h["input_tokens"])
            c2.metric("Token output", h["output_tokens"])
            c3.metric("Token thinking", h["thinking_tokens"])
            c4.metric("Total terpakai", h["total_tokens"])
            c5.metric("Waktu kirim", st.session_state.get("hasil_jam", "-"))

            with st.container(border=True):
                st.markdown("#### 📝 Penilaian")
                kualitas = st.text_area("Deskripsi kualitas hasil (kamu yang menilai)", key="kualitas", height=110)
                if st.button("💾 Simpan ke log", key="simpan"):
                    if not kualitas.strip():
                        st.warning("Deskripsi kualitas masih kosong. Isi dulu sebelum menyimpan.")
                    else:
                        total = simpan_log({**h, "kualitas": kualitas})
                        st.success(f"Tersimpan! Total token terpakai sejauh ini: {total}")
        else:
            st.markdown(f'<div class="kosong">Hasil dari {nama_ai} akan muncul di sini.<br>'
                        f'Isi prompt di sebelah kiri, lalu klik <b>Kirim ke {nama_ai}</b>.</div>',
                        unsafe_allow_html=True)

    with st.expander("📄 Lihat log"):
        if os.path.exists(LOG_FILE):
            df = pd.read_csv(LOG_FILE, dtype={"nomor_kombinasi": str})
            df_tampil = df.drop(columns=KOLOM_SEMBUNYI, errors="ignore")
            st.dataframe(df_tampil.tail(10), hide_index=True)
            st.download_button("⬇️ Download CSV", df_tampil.to_csv(index=False), "log.csv", "text/csv")
        else:
            st.caption("Belum ada data.")


if mode == MODE_CHAT:
    halaman_chat()
else:
    halaman_eksperimen()
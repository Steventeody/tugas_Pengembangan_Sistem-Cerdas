import hashlib
import json
import os
import time
from datetime import datetime, timedelta

import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from google import genai
from google.genai import types

# ---------- 1. PERSIAPAN ----------
load_dotenv()                                  # baca file .env (tempat API key disimpan)
LOG_FILE = "data/log.csv"                      # buku catatan hasil eksperimen
HITS_FILE = "data/request_hits.txt"            # catatan setiap request yang dikirim ke Gemini
SETTING_FILE = "data/pengaturan.json"          # batas request (RPD / RPM / TPM), diatur di halaman Dashboard
USAGE_FILE = "data/pemakaian.csv"              # catatan token SEMUA request yang berhasil (disimpan atau tidak)
KOLOM_SEMBUNYI = ["temperature", "top_p", "top_k", "persona"]   # tidak ditampilkan lagi; data lama di log.csv tetap utuh
os.makedirs("data", exist_ok=True)

st.set_page_config(page_title="AI Token Lab", page_icon="🧪", layout="wide")
st.markdown("""
<style>
.block-container {padding-top: 1.5rem; max-width: 1280px;}
footer {visibility: hidden;}
.hero {background: linear-gradient(135deg, #4C9AFF 0%, #8E7CFF 55%, #B48CFF 100%);
       border-radius: 20px; padding: 26px 32px; margin-bottom: 18px; color: #fff;
       box-shadow: 0 8px 24px rgba(76,154,255,.25);}
.hero-title {font-size: 2rem; font-weight: 800; letter-spacing: -0.5px; line-height: 1.2;}
.hero-sub {opacity: .92; margin-top: 6px; font-size: .98rem;}
[data-testid="stMetric"] {background: rgba(128,128,128,0.08); border: 1px solid rgba(128,128,128,0.18);
                          border-left: 4px solid #4C9AFF; padding: 14px 18px; border-radius: 14px;}
[data-testid="stMetricLabel"] {opacity: .75;}
[data-testid="stMetricValue"] {font-weight: 700;}
.stTabs [data-baseweb="tab-list"] {gap: 6px;}
.stTabs [data-baseweb="tab"] {border-radius: 10px 10px 0 0; padding: 10px 18px; font-weight: 600;}
.stButton > button, .stDownloadButton > button {border-radius: 12px; font-weight: 600; width: 100%; padding: .55rem 1rem;}
.stButton > button[kind="primary"] {background: linear-gradient(135deg, #4C9AFF, #8E7CFF); border: 0; color: #fff;}
[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 16px;}
section[data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.2);}
[data-testid="stChatMessage"] {border-radius: 14px;}
.kosong {border: 2px dashed rgba(128,128,128,.35); border-radius: 16px; padding: 56px 20px;
         text-align: center; opacity: .7; line-height: 1.7;}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div class="hero">
  <div class="hero-title">🧪 AI Token Lab</div>
  <div class="hero-sub">Eksperimen prompt engineering dengan Gemini &middot; setiap percobaan mencatat token input, output, dan thinking</div>
</div>
""", unsafe_allow_html=True)
slot_status = st.empty()      # kartu status (sisa token, request, TPM, model), diisi di akhir halaman


# ---------- 2. FUNGSI JATAH REQUEST ----------
def baca_pengaturan():
    baku = {"rpd": 20, "rpm": 5, "tpm": 250000,    # batas dari Batasan Kecepatan AI Studio (diubah di Dashboard)
            "offset_kunci": {}}                   # penyesuaian "Samakan" di Dashboard, dicatat PER API key (berlaku 1 hari)
    try:
        with open(SETTING_FILE) as f:
            baku.update(json.load(f))
    except Exception:
        pass
    return baku


try:
    from zoneinfo import ZoneInfo
    PASIFIK = ZoneInfo("America/Los_Angeles")      # Google mereset kuota harian tengah malam waktu Pasifik
except Exception:
    PASIFIK = None                                 # tzdata belum terpasang: pakai tanggal laptop


def hari_google(waktu=None):
    """Tanggal 'hari' menurut Google. waktu = datetime lokal (tanpa zona); kosong = sekarang."""
    waktu = waktu or datetime.now()
    if PASIFIK is None:
        return waktu.strftime("%Y-%m-%d")
    return waktu.astimezone(PASIFIK).strftime("%Y-%m-%d")


def jam_reset():
    """Jam reset harian berikutnya dalam waktu laptop (HH:MM), atau None kalau zona waktu tidak tersedia."""
    if PASIFIK is None:
        return None
    sekarang = datetime.now(PASIFIK)
    tengah = (sekarang + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return tengah.astimezone().strftime("%H:%M")


def baca_waktu(teks):
    """Baca waktu dari teks. Menerima format dengan detik maupun tanpa detik (log lama)."""
    for bentuk in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(teks).strip(), bentuk)
        except ValueError:
            pass
    return None


def id_kunci(kunci):
    """Kode pendek dari API key (hash, bukan key aslinya). Tiap API key punya jatah RPD/RPM sendiri."""
    return hashlib.sha256(kunci.encode()).hexdigest()[:8] if kunci else ""


def catat_request(kunci):
    """Setiap kali program menghubungi Gemini, satu baris 'waktu|kode_key' dicatat."""
    with open(HITS_FILE, "a") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "|" + id_kunci(kunci) + "\n")


def hitung_request(kunci):
    """(jumlah request hari ini menurut Google, jumlah request 60 detik terakhir) KHUSUS untuk API key ini,
    dari catatan aplikasi ditambah penyesuaian 'Samakan dengan AI Studio' dari Dashboard (kalau ada untuk hari ini).
    Ganti API key = hitungan mulai dari 0 lagi (atau sesuai angka yang di-'Samakan' untuk key itu)."""
    hari_ini = menit_ini = 0
    kid = id_kunci(kunci)
    if os.path.exists(HITS_FILE):
        sekarang = datetime.now()
        hari = hari_google(sekarang)
        with open(HITS_FILE) as f:
            for baris in f:
                teks, _, kode = baris.strip().partition("|")
                if kode != kid:                 # catatan lama (tanpa kode) dan key lain tidak dihitung
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
    """Token INPUT dalam 60 detik terakhir untuk API key ini (itulah yang dihitung TPM Gemini)."""
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
    """Catat token satu request yang berhasil. Dipanggil untuk SETIAP request, jadi yang tidak disimpan pun terhitung."""
    baru = pd.DataFrame([{"waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "model": model,
                          "anggota": anggota or "(tanpa nama)", "kunci": id_kunci(api_key), **usage}])
    if os.path.exists(USAGE_FILE):
        data = pd.concat([pd.read_csv(USAGE_FILE), baru], ignore_index=True)
    elif os.path.exists(LOG_FILE):
        # pertama kali: masukkan dulu token dari log lama supaya angkanya tidak mulai dari nol
        lama = pd.read_csv(LOG_FILE)
        kolom = ["waktu", "model", "anggota", "input_tokens", "output_tokens", "thinking_tokens", "total_tokens"]
        data = pd.concat([lama.reindex(columns=kolom), baru], ignore_index=True)
    else:
        data = baru
    data.to_csv(USAGE_FILE, index=False)


def token_terpakai():
    """Total token yang sudah dipakai (semua request)."""
    if os.path.exists(USAGE_FILE):
        return int(pd.read_csv(USAGE_FILE)["total_tokens"].sum())
    if os.path.exists(LOG_FILE):
        return int(pd.read_csv(LOG_FILE)["total_tokens"].sum())
    return 0


# ---------- 3. SIDEBAR: pengaturan ----------
# Streamlit menghapus isi kolom input kalau pindah halaman (mis. ke Dashboard lalu kembali).
# Jadi nilainya disalin ke session_state biasa, yang tetap ada selama tab browser tidak ditutup/di-refresh.
def ingat(kunci, baku):
    """Ambil nilai terakhir yang diisi untuk kolom ini (atau nilai awal kalau belum pernah)."""
    return st.session_state.get("_ingat_" + kunci, baku)


def simpan_ingatan(kunci, nilai):
    st.session_state["_ingat_" + kunci] = nilai
    return nilai



st.sidebar.markdown("## ⚙️ Pengaturan")
with st.sidebar.expander("🔑 Akun & model", expanded=True):
    api_key = os.getenv("GEMINI_API_KEY")
    if api_key:
        st.success("API key terbaca dari file .env")
    else:
        api_key = simpan_ingatan("api_key", st.text_input("API key", type="password", key="api_key",
                                                          value=ingat("api_key", "")))
    model = simpan_ingatan("model", st.text_input("Nama model", value=ingat("model", "gemini-3.8-flash"), key="model",
                                                  help="Samakan dengan isi model= di tombol 'Dapatkan kode' AI Studio"))
    anggota = simpan_ingatan("anggota", st.text_input("Nama kamu", value=ingat("anggota", ""), key="anggota"))

# Parameter sampling: kalau tidak dicentang, model memakai nilai bawaannya
with st.sidebar.expander("🎛️ Parameter lanjutan (opsional)"):
    manual = simpan_ingatan("manual", st.checkbox("Atur manual", value=ingat("manual", False), key="manual"))
    temperature = simpan_ingatan("temperature", st.slider("Temperature", 0.0, 2.0, ingat("temperature", 1.0), 0.1,
                                                          disabled=not manual))
    top_p = simpan_ingatan("top_p", st.slider("Top-p", 0.0, 1.0, ingat("top_p", 0.95), 0.05, disabled=not manual))
    top_k = simpan_ingatan("top_k", st.slider("Top-k", 1, 100, ingat("top_k", 40), 1, disabled=not manual))
params = {"temperature": temperature, "top_p": top_p, "top_k": float(top_k)} if manual else {}

pengaturan = baca_pengaturan()                 # batas request diatur di halaman Dashboard
rpd, rpm, tpm = int(pengaturan["rpd"]), int(pengaturan["rpm"]), int(pengaturan["tpm"])
slot_sisa = st.sidebar.empty()      # diisi di akhir halaman supaya angkanya selalu terbaru

if not api_key:
    st.info("Isi API key di sidebar (bagian Akun & model), atau taruh di file .env")
    st.stop()

client = genai.Client(api_key=api_key)


# ---------- 4. FUNGSI BANTU ----------
def tanya_gemini(contents, system=None, coba=2):
    """Kirim ke Gemini. Kalau server sibuk (503), diulang 1 kali saja supaya jatah request hemat."""
    isi = dict(params)
    if system:
        isi["system_instruction"] = system      # persona dipasang di sini
    config = types.GenerateContentConfig(**isi) if isi else None
    for i in range(coba):
        catat_request(api_key)                  # setiap percobaan menghabiskan 1 request
        try:
            resp = client.models.generate_content(model=model, contents=contents, config=config)
        except Exception as e:
            sibuk = "503" in str(e) or "UNAVAILABLE" in str(e)
            if sibuk and i < coba - 1:
                time.sleep(10)
                continue
            raise
        catat_pemakaian(baca_usage(resp))       # token yang kebakar dicatat untuk setiap request berhasil
        return resp


def peringatan_jatah():
    """Tampilkan peringatan sebelum mengirim kalau jatah request hampir/sudah habis."""
    hari_ini, menit_ini = hitung_request(api_key)
    if hari_ini >= rpd:
        st.warning(f"Perkiraan jatah request hari ini sudah habis ({hari_ini}/{rpd}). Request bisa ditolak (error 429).")
    elif menit_ini >= rpm:
        st.warning(f"Sudah {menit_ini} request dalam 1 menit terakhir (batas {rpm}). Tunggu sebentar sebelum mengirim lagi.")


def tampilkan_error(e):
    pesan = str(e)
    if "429" in pesan or "RESOURCE_EXHAUSTED" in pesan:
        st.error("Jatah request habis (error 429). Tunggu 1 menit, atau coba lagi besok kalau batas hariannya yang habis.")
    else:
        st.error(f"Gagal: {e}")


def baca_usage(resp):
    """Ambil angka token dari balasan Gemini."""
    u = resp.usage_metadata
    return {
        "input_tokens": u.prompt_token_count or 0,
        "output_tokens": u.candidates_token_count or 0,
        "thinking_tokens": getattr(u, "thoughts_token_count", 0) or 0,
        "total_tokens": u.total_token_count or 0,
    }


def baris_dasar(jenis, nomor, prompt, jawaban, usage):
    return {
        "waktu": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "anggota": anggota or "(tanpa nama)",
        "jenis": jenis, "model": model, "nomor_kombinasi": nomor,
        "prompt": prompt, "jawaban": jawaban, **usage,
    }


def simpan_log(baris):
    """Tambah satu baris ke log, lalu hitung ulang total token yang menumpuk."""
    baris = pd.DataFrame([baris])
    if os.path.exists(LOG_FILE):
        lama = pd.read_csv(LOG_FILE, dtype={"nomor_kombinasi": str})
        data = pd.concat([lama, baris], ignore_index=True)
    else:
        data = baris
    data["total_kumulatif"] = data["total_tokens"].cumsum()
    data.to_csv(LOG_FILE, index=False)
    return int(data["total_kumulatif"].iloc[-1])


# ---------- 5. TAB ----------
tab_eks, tab_chat = st.tabs(["🧪 Eksperimen Prompt", "💬 Chat Persona"])

# ===== TAB EKSPERIMEN =====
with tab_eks:
    kiri, kanan = st.columns([5, 7], gap="large")

    with kiri:
        with st.container(border=True):
            st.markdown("#### ✍️ Prompt")
            st.caption("Prompt dikirim apa adanya, tanpa persona tambahan, supaya hasil tiap nomor kombinasi bisa dibandingkan.")
            nomor = simpan_ingatan("nomor", st.text_input("Nomor kombinasi", placeholder="mis. 3.2", key="nomor",
                                                          value=ingat("nomor", "")))
            prompt = simpan_ingatan("prompt", st.text_area("Prompt", height=220, key="prompt",
                                                           value=ingat("prompt", "")))
            kirim = st.button("🚀 Kirim ke Gemini", type="primary", key="kirim")
        if kirim:
            if not prompt.strip():
                st.warning("Prompt masih kosong.")
            else:
                peringatan_jatah()
                resp = None
                try:
                    with st.spinner("Menunggu Gemini..."):
                        resp = tanya_gemini(prompt)          # chat baru, tanpa riwayat
                except Exception as e:
                    tampilkan_error(e)
                if resp is not None:
                    # session_state = ingatan sementara (Streamlit menjalankan ulang file tiap klik)
                    st.session_state["hasil"] = baris_dasar(
                        "eksperimen", nomor, prompt, resp.text or "(kosong)", baca_usage(resp))

    with kanan:
        if "hasil" in st.session_state:
            h = st.session_state["hasil"]
            with st.container(border=True):
                st.markdown("#### 🤖 Jawaban Gemini")
                st.caption(f"Nomor kombinasi: {h['nomor_kombinasi'] or '-'}  |  Model: {h['model']}")
                st.write(h["jawaban"])
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Token input", h["input_tokens"])
            c2.metric("Token output", h["output_tokens"])
            c3.metric("Token thinking", h["thinking_tokens"])
            c4.metric("Total terpakai", h["total_tokens"])

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
            st.markdown('<div class="kosong">Hasil dari Gemini akan muncul di sini.<br>'
                        'Isi prompt di sebelah kiri, lalu klik <b>Kirim ke Gemini</b>.</div>',
                        unsafe_allow_html=True)

# ===== TAB CHAT PERSONA =====
PERSONA = {
    "Tanpa persona": "",
    "Dosen yang sabar": "Kamu adalah dosen yang sabar dan suka memberi analogi sederhana. Jawab dalam bahasa Indonesia yang mudah dipahami.",
    "Barista santai": "Kamu adalah barista yang santai dan ramah. Bicara dengan gaya gaul tapi sopan, dalam bahasa Indonesia.",
    "Pemandu wisata Yogyakarta": "Kamu adalah pemandu wisata Yogyakarta yang ramah dan penuh semangat. Jawab dalam bahasa Indonesia.",
    "Kustom (tulis sendiri)": "",
}
with tab_chat:
    kiri, kanan = st.columns([4, 8], gap="large")

    with kiri:
        with st.container(border=True):
            st.markdown("#### 🎭 Persona AI")
            pilih = st.selectbox("Persona", list(PERSONA), key="pilih_persona")
            persona_teks = st.text_area("Instruksi persona (system prompt)", value=PERSONA[pilih],
                                        height=150, key=f"persona_{pilih}")
            st.caption("Persona dan riwayat obrolan ikut dihitung sebagai token input di setiap pesan. "
                       "Semua pesan tercatat otomatis di log. Setiap pesan memakai 1 request dari jatah harian.")
            st.session_state.setdefault("chat", [])
            if st.button("🗑️ Hapus percakapan", key="hapus_chat"):
                st.session_state["chat"] = []

    with kanan:
        with st.container(border=True, height=440):
            if not st.session_state["chat"]:
                st.caption("Belum ada percakapan. Tulis pesan di kolom bawah untuk memulai.")
            for m in st.session_state["chat"]:
                with st.chat_message("user" if m["role"] == "user" else "assistant"):
                    st.write(m["text"])
                    if m.get("info"):
                        st.caption(m["info"])
        teks = st.chat_input("Tulis pesan...", key="chat_input")

    if teks:
        peringatan_jatah()
        riwayat = [types.Content(role=m["role"], parts=[types.Part(text=m["text"])])
                   for m in st.session_state["chat"]]
        contents = riwayat + [types.Content(role="user", parts=[types.Part(text=teks)])]
        resp = None
        try:
            with st.spinner("Menunggu Gemini..."):
                resp = tanya_gemini(contents, system=persona_teks.strip() or None)
        except Exception as e:
            tampilkan_error(e)
        if resp is not None:
            usage = baca_usage(resp)
            jawaban = resp.text or "(kosong)"
            info = (f"Input: {usage['input_tokens']} | Output: {usage['output_tokens']} | "
                    f"Thinking: {usage['thinking_tokens']} | Total: {usage['total_tokens']}")
            simpan_log({**baris_dasar("chat", "chat", teks, jawaban, usage),
                        "kualitas": "(chat)"})
            st.session_state["chat"] += [{"role": "user", "text": teks},
                                         {"role": "model", "text": jawaban, "info": info}]
            st.rerun()

# ---------- 6. LOG ----------
with st.expander("📄 Lihat log"):
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE, dtype={"nomor_kombinasi": str})
        df_tampil = df.drop(columns=KOLOM_SEMBUNYI, errors="ignore")   # hanya disembunyikan, file log tidak diubah
        st.dataframe(df_tampil.tail(10), hide_index=True)
        st.download_button("⬇️ Download CSV", df_tampil.to_csv(index=False), "log.csv", "text/csv")
    else:
        st.caption("Belum ada data.")

# ---------- 7. RINGKASAN (SIDEBAR + KARTU STATUS) ----------
hari_ini, menit_ini = hitung_request(api_key)
pakai = token_terpakai()
reset = jam_reset()

with slot_sisa.container():
    st.progress(min(hari_ini / rpd, 1.0))
    st.caption(f"Hari ini (RPD): {hari_ini}/{rpd} request (sisa {max(rpd - hari_ini, 0)})  \n"
               f"1 menit terakhir: {menit_ini}/{rpm} request (RPM)  \n"
               f"1 menit terakhir: {hitung_tpm(api_key):,}/{tpm:,} token masuk (TPM)  \n"
               + (f"Reset harian sekitar jam {reset} (waktu laptop)  \n" if reset else "")
               + f"Hitungan khusus API key ini (kode {id_kunci(api_key)}); ganti key = hitungan terpisah.  \n"
               + "Hanya menghitung request lewat aplikasi ini, kecuali sudah disamakan di halaman Dashboard.")

with slot_status.container():
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total token terpakai", f"{pakai:,}", help="Input + output + thinking dari semua request yang berhasil")
    s2.metric("Request hari ini", f"{hari_ini} / {rpd}", help=f"Sisa {max(rpd - hari_ini, 0)} request")
    s3.metric("Token masuk per menit", f"{hitung_tpm(api_key):,}", help=f"Batas {tpm:,} token masuk per menit (TPM)")
    s4.metric("Model", model)

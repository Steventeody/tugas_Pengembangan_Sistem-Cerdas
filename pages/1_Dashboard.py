import base64
import hashlib
import json
import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

load_dotenv(override=True)                     # baca API key dari file .env

LOG_FILE = "data/log.csv"                      # file yang sama dengan yang ditulis app.py
C_IN, C_OUT, C_THINK = "#6D8FD0", "#D98C5F", "#9C8CBF"       # palet lembut yang serasi dengan tema krem PANDU
WARNA = {"Input": C_IN, "Output": C_OUT, "Thinking": C_THINK}
HITS_FILE = "data/request_hits.txt"            # dicatat oleh app.py tiap request ke model
SETTING_FILE = "data/pengaturan.json"          # batas RPD / RPM / TPM (dibaca juga oleh app.py)
USAGE_FILE = "data/pemakaian.csv"              # token SEMUA request yang berhasil (dicatat app.py)


# Angka awal batas untuk GLM (Z.ai). Hanya perkiraan: cocokkan dengan halaman Rate Limits di dashboard Z.ai.
BATAS_GLM = {"rpd": 1000, "rpm": 60, "tpm": 1000000}
# Angka awal batas untuk Gemini (perkiraan): cocokkan dengan Batasan Kecepatan di Google AI Studio.
BATAS_GEMINI = {"rpd": 20, "rpm": 5, "tpm": 250000}

# Jatah request mengikuti filter "Penyedia": tiap penyedia punya API key, batas, dan teks sendiri.
CFG = {
    "Z.ai (GLM)": {"env": ["ZAI_API_KEY"], "batas": BATAS_GLM, "label": "GLM / Z.ai", "singkat": "GLM",
                   "dashboard": "dashboard Z.ai", "halaman_batas": "dashboard Z.ai > Rate Limits"},
    "Gemini": {"env": ["GEMINI_API_KEY", "GOOGLE_API_KEY"], "batas": BATAS_GEMINI, "label": "Gemini / AI Studio",
               "singkat": "Gemini", "dashboard": "AI Studio", "halaman_batas": "AI Studio > Batasan Kecepatan"},
}


def baca_pengaturan():
    baku = {"rpd": 20, "rpm": 5, "tpm": 250000,
            "offset_kunci": {}}                   # penyesuaian manual dari AI Studio, dicatat PER API key (berlaku 1 hari)
    try:
        with open(SETTING_FILE) as f:
            baku.update(json.load(f))
    except Exception:
        pass
    return baku


def simpan_pengaturan(**perubahan):
    data = baca_pengaturan()
    data.update({k: (v if isinstance(v, (str, dict)) else int(v)) for k, v in perubahan.items()})
    os.makedirs("data", exist_ok=True)
    with open(SETTING_FILE, "w") as f:
        json.dump(data, f)


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
    """Kode pendek dari API key (hash, bukan key aslinya). Harus sama dengan di app.py."""
    return hashlib.sha256(kunci.encode()).hexdigest()[:8] if kunci else ""


def kunci_aktif(penyedia="Z.ai (GLM)"):
    """API key penyedia yang dipilih, dibaca dari file .env."""
    for nama in CFG[penyedia]["env"]:
        if os.getenv(nama):
            return os.getenv(nama)
    return ""


KID = id_kunci(kunci_aktif())     # diganti sesuai filter Penyedia setelah filter dibaca


def hitung_tpm():
    """Token INPUT dalam 60 detik terakhir untuk API key aktif (itulah yang dihitung TPM)."""
    if not os.path.exists(USAGE_FILE):
        return 0
    d = pd.read_csv(USAGE_FILE)
    if "kunci" not in d.columns or not KID:
        return 0
    d = d[d["kunci"].fillna("") == KID]
    batas = datetime.now() - timedelta(seconds=60)
    ada = d["waktu"].apply(baca_waktu).apply(lambda w: w is not None and w >= batas)
    return int(pd.to_numeric(d.loc[ada, "input_tokens"], errors="coerce").fillna(0).sum())


def baca_hits():
    """Daftar waktu request yang dikirim dengan API key aktif (teks 'YYYY-MM-DD HH:MM:SS').
    Catatan lama (tanpa kode key) dan request dari key lain tidak ikut."""
    if not os.path.exists(HITS_FILE) or not KID:
        return []
    hasil = []
    with open(HITS_FILE) as f:
        for b in f:
            teks, _, kode = b.strip().partition("|")
            if teks and kode == KID:
                hasil.append(teks)
    return hasil


def offset_hari_ini():
    """Penyesuaian 'Samakan' untuk API key aktif, kalau dibuat hari ini."""
    o = baca_pengaturan().get("offset_kunci", {}).get(KID)
    return int(o.get("rpd", 0)) if o and o.get("hari") == hari_google() else 0


def hitung_mentah():
    """Jumlah request hari ini (menurut Google) murni dari catatan aplikasi, tanpa penyesuaian manual."""
    hari = hari_google()
    return sum(1 for w in (baca_waktu(h) for h in baca_hits()) if w is not None and hari_google(w) == hari)


def penyedia_dari_model(nama_model):
    m = str(nama_model).lower()
    return "Z.ai (GLM)" if "glm" in m else "Gemini" if "gemini" in m else "Lainnya"


def singkat(n):
    """1000000 -> '1M', 250000 -> '250k' (supaya muat di kartu angka)."""
    n = int(n)
    return f"{n / 1_000_000:g}M" if n >= 1_000_000 else f"{n / 1_000:g}k" if n >= 1_000 else str(n)


def token_hari_ini():
    """Total token (semua request berhasil) hari ini untuk API key aktif."""
    if not os.path.exists(USAGE_FILE) or not KID:
        return 0
    u = pd.read_csv(USAGE_FILE)
    if "kunci" not in u.columns:
        return 0
    u = u[u["kunci"].fillna("") == KID]
    hari = hari_google()
    waktu = [baca_waktu(t) for t in u["waktu"]]          # datetime biasa (bukan Timestamp pandas) supaya zona waktu benar
    ada = [w is not None and hari_google(w) == hari for w in waktu]
    return int(pd.to_numeric(u.loc[ada, "total_tokens"], errors="coerce").fillna(0).sum())


def rapikan(fig, judul, tinggi=340):
    fig.update_layout(title=judul, height=tinggi, margin=dict(l=10, r=10, t=50, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1))
    return fig


# jumlah (elemen struktur A, teknik B) tiap nomor kombinasi, dari tabel dosen
KOMBINASI = {'1': (1, 1), '1.2': (1, 2), '2': (1, 1), '2.2': (2, 1), '3': (2, 1), '3.2': (2, 2), '4': (3, 1),
             '4.2': (3, 2), '5': (4, 1), '5.2': (4, 2), '6': (5, 1), '6.2': (5, 2), '7': (1, 2), '7.2': (2, 2),
             '8': (1, 3), '8.2': (2, 3), '9': (1, 4), '9.2': (2, 4), '10': (1, 5), '10.2': (2, 5), '11': (1, 6),
             '11.2': (2, 6), '12': (1, 7), '12.2': (2, 7), '13': (1, 8), '13.2': (2, 8), '14': (6, 1), '14.2': (6, 2)}


def norm_nomor(n):
    """'1.0' -> '1', '3.2' -> '3.2'. Teks selain angka (misal 'chat') dibiarkan."""
    if pd.isna(n):
        return n
    try:
        f = float(n)
    except (TypeError, ValueError):
        return n
    return str(int(f)) if f.is_integer() else str(f)


# ---------- 1. TAMPILAN ----------
LOGO = next((p for p in ("gambar/1.png", "gambar/logo_pandu.jpg") if os.path.exists(p)), None)
st.set_page_config(page_title="Dashboard PANDU", page_icon=LOGO or "📊", layout="wide")
if LOGO:
    st.logo(LOGO, size="large")                  # logo di paling atas sidebar, di atas menu halaman

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@800;900&display=swap');

footer, [data-testid="stDecoration"], [data-testid="stAppDeployButton"], .stAppDeployButton {display: none !important;}
header[data-testid="stHeader"] {background: transparent;}
.stApp {background-color: #FFFFFF;}
.block-container {padding-top: 2rem; padding-bottom: 5rem; max-width: 1280px;}

section[data-testid="stSidebar"] {background-color: #F8F7F5 !important; border-right: 1px solid #EAE9E5;}
section[data-testid="stSidebar"] h2 {font-family: 'Newsreader', serif; font-weight: 500; font-size: 1.3rem; color: #1A1A1A;}

.hero {background: #F8F7F5; border: 1px solid #EAE9E5; border-radius: 16px; padding: 26px 32px; margin-bottom: 20px; color: #1A1A1A;}
.hero-title {font-family: 'Newsreader', serif; font-size: 2.2rem; font-weight: 500; letter-spacing: -0.5px; line-height: 1.2;}
.hero-sub {color: #555555; margin-top: 6px; font-size: 1rem;}

[data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #EAE9E5; padding: 14px 18px; border-radius: 12px;}
[data-testid="stMetricLabel"] {color: #555555; font-size: 0.9rem;}
[data-testid="stMetricValue"] {color: #1A1A1A; font-weight: 600; font-family: 'Newsreader', serif;}

.stTabs [data-baseweb="tab-list"] {gap: 4px; border-bottom: 1px solid #EAE9E5;}
.stTabs [data-baseweb="tab"] {border-radius: 8px 8px 0 0; padding: 10px 18px; font-weight: 500; color: #555555;}
.stTabs [aria-selected="true"] {color: #1A1A1A; font-weight: 600;}

.stButton > button, .stDownloadButton > button {
    border-radius: 8px; font-weight: 500; border: 1px solid #EAE9E5; background-color: #FFFFFF; color: #1A1A1A;
    transition: all 0.2s; width: 100%; padding: .55rem 1rem;}
.stButton > button:hover, .stDownloadButton > button:hover {background-color: #F0EFEA; border-color: #D4D3CF; color: #1A1A1A;}

[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 12px; border: 1px solid #EAE9E5;}
[data-testid="stExpander"] {border: 1px solid #EAE9E5; border-radius: 10px; background: #FFFFFF;}
[data-testid="stDataFrame"] {border: 1px solid #EAE9E5; border-radius: 10px;}

/* ===== tulisan PANDU di samping logo sidebar ===== */
[data-testid="stLogoLink"] { display: flex !important; align-items: center; gap: .65rem; text-decoration: none !important; }
[data-testid="stLogoLink"]::after { content: "PANDU"; font-family: 'Orbitron', sans-serif; font-weight: 900; font-size: 1.45rem;
    letter-spacing: .16em; line-height: 1;
    background: linear-gradient(135deg, #1A1A1A 0%, #D97757 100%);
    -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }
</style>
""", unsafe_allow_html=True)
st.markdown("""
<div class="hero">
  <div class="hero-title">Dashboard Token</div>
  <div class="hero-sub">Pemantauan token input, output, dan thinking dari semua percobaan, plus jatah request harian</div>
</div>
""", unsafe_allow_html=True)

# ---------- 2. PENYEDIA AWAL ----------
P_AWAL = "Gemini" if (kunci_aktif("Gemini") and not kunci_aktif("Z.ai (GLM)")) else "Z.ai (GLM)"


# ---------- 3. BACA DATA ----------
if not os.path.exists(LOG_FILE):
    st.info("Belum ada data. Jalankan eksperimen di halaman utama dan klik 'Simpan ke log' dulu.")
    KID = id_kunci(kunci_aktif(P_AWAL))
    st.stop()

df = pd.read_csv(LOG_FILE, dtype={"nomor_kombinasi": str})
if df.empty:
    st.info("Log masih kosong.")
    KID = id_kunci(kunci_aktif(P_AWAL))
    st.stop()

for kolom, default in [("anggota", "(tanpa nama)"), ("jenis", "eksperimen")]:
    if kolom not in df.columns:                  # data lama belum punya kolom ini
        df[kolom] = default
    df[kolom] = df[kolom].fillna(default)
if "model" not in df.columns:                    # log lama belum mencatat nama model
    df["model"] = "(tidak tercatat)"
df["model"] = df["model"].fillna("(tidak tercatat)")
df["penyedia"] = df["model"].map(penyedia_dari_model)
for kolom in ["input_tokens", "output_tokens", "thinking_tokens", "total_tokens"]:
    df[kolom] = pd.to_numeric(df[kolom], errors="coerce").fillna(0)
df["nomor_kombinasi"] = df["nomor_kombinasi"].map(norm_nomor)

df["percobaan_ke"] = range(1, len(df) + 1)
df["total_kumulatif"] = df.groupby("anggota")["total_tokens"].cumsum()   # dihitung sebelum difilter

# ---------- 4. SIDEBAR: filter ----------
st.sidebar.markdown("## 🔎 Filter")
semua_anggota = sorted(df["anggota"].unique())
semua_jenis = sorted(df["jenis"].unique())
pilih_anggota = semua_anggota          # filter Anggota dihapus: semua anggota ikut dihitung
pilih_jenis = st.sidebar.multiselect("Jenis", semua_jenis, default=semua_jenis)
semua_penyedia = sorted(df["penyedia"].unique())
pilih_penyedia = st.sidebar.multiselect("Penyedia", semua_penyedia,       # awalnya hanya GLM; tambahkan Gemini untuk membandingkan
                                        default=[p for p in semua_penyedia if p == "Z.ai (GLM)"] or semua_penyedia)
semua_model = sorted(df.loc[df["penyedia"].isin(pilih_penyedia), "model"].unique())
pilih_model = st.sidebar.multiselect("Model", semua_model, default=semua_model)

# Jatah request mengikuti filter Penyedia. Kalau lebih dari satu penyedia dipilih, pilih salah satu untuk kartu jatah.
kenal = [p for p in pilih_penyedia if p in CFG] or [P_AWAL]
if len(kenal) > 1:
    penyedia_jatah = st.sidebar.selectbox("Jatah request untuk", kenal, key="penyedia_jatah")
else:
    penyedia_jatah = kenal[0]
CP = CFG[penyedia_jatah]
KID = id_kunci(kunci_aktif(penyedia_jatah))      # semua hitungan jatah di bawah memakai API key penyedia ini

d = df[df["anggota"].isin(pilih_anggota) & df["jenis"].isin(pilih_jenis)
       & df["penyedia"].isin(pilih_penyedia) & df["model"].isin(pilih_model)]
if d.empty:
    st.warning("Tidak ada data untuk filter ini.")
    st.stop()
eks = d[(d["jenis"] == "eksperimen") & d["nomor_kombinasi"].notna()].copy()

tab_ringkas, tab_model, tab_kombinasi, tab_analisis, tab_data = st.tabs(
    ["📊 Ringkasan", "🤖 Per model", "🧩 Per kombinasi", "🔬 Analisis", "📄 Data"])

# ===== TAB RINGKASAN =====
with tab_ringkas:
    masuk = d["input_tokens"].sum()
    keluar = d["output_tokens"].sum() + d["thinking_tokens"].sum()
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Jumlah percobaan", len(d))
    k2.metric("Total token di log", f"{int(d['total_tokens'].sum()):,}")
    k3.metric("Rata-rata per percobaan", f"{int(d['total_tokens'].mean()):,}")
    k4.metric("Output+thinking per 1 input", f"{keluar / masuk:.1f}x" if masuk else "-",
              help="Berapa kali lipat token yang dihasilkan model dibanding token yang kamu kirim.")
    selisih = (d["input_tokens"] + d["output_tokens"] + d["thinking_tokens"] - d["total_tokens"]).abs().sum()
    if selisih > 0:
        st.caption("Catatan: total dari API berbeda dengan input + output + thinking "
                   "(kemungkinan ada token lain yang ikut dihitung).")

    # ---- Grafik baru: token per hari ----
    tgl = d["waktu"].apply(baca_waktu)
    harian = d.assign(tanggal=tgl.apply(lambda w: w.strftime("%Y-%m-%d") if w is not None else None)).dropna(subset=["tanggal"])
    if not harian.empty:
        per_tgl = (harian.groupby("tanggal")[["input_tokens", "output_tokens", "thinking_tokens"]].sum()
                   .rename(columns={"input_tokens": "Input", "output_tokens": "Output", "thinking_tokens": "Thinking"})
                   .reset_index().melt(id_vars="tanggal", var_name="Jenis token", value_name="Token"))
        grafik_hari = px.bar(per_tgl, x="tanggal", y="Token", color="Jenis token", color_discrete_map=WARNA,
                             labels={"tanggal": "Tanggal", "Token": "Token"})
        grafik_hari.update_xaxes(type="category")
        st.plotly_chart(rapikan(grafik_hari, "Token per hari (input, output, thinking)", 300))

    g1, g2 = st.columns([1, 2])
    with g1:
        donut = go.Figure(go.Pie(
            labels=["Input", "Output", "Thinking"],
            values=[d["input_tokens"].sum(), d["output_tokens"].sum(), d["thinking_tokens"].sum()],
            hole=0.55, marker=dict(colors=[C_IN, C_OUT, C_THINK]), sort=False))
        st.plotly_chart(rapikan(donut, "Proporsi token"))
    with g2:
        garis = px.line(d, x="percobaan_ke", y="total_kumulatif", color="anggota", markers=True,
                        labels={"percobaan_ke": "Percobaan ke-", "total_kumulatif": "Total token", "anggota": "Anggota"})
        garis.update_xaxes(dtick=1)
        st.plotly_chart(rapikan(garis, "Total token terpakai (menumpuk)"))

# ===== TAB PER MODEL =====
with tab_model:
    st.caption("Perbandingan pemakaian token antar model GLM (dan penyedia lain kalau dipilih di filter), dari semua percobaan "
               "di log sesuai filter sidebar. Nama model dicatat otomatis tiap jawaban disimpan.")
    ada_penyedia = sorted(d["penyedia"].unique())
    for p_nama, kolom_p in zip(ada_penyedia, st.columns(len(ada_penyedia))):
        dp = d[d["penyedia"] == p_nama]
        keluar_p = dp["output_tokens"].sum() + dp["thinking_tokens"].sum()
        with kolom_p.container(border=True):
            st.markdown(f"**{p_nama}**")
            m1, m2, m3 = st.columns(3)
            m1.metric("Percobaan", len(dp))
            m2.metric("Total token", f"{int(dp['total_tokens'].sum()):,}")
            m3.metric("Porsi thinking", f"{dp['thinking_tokens'].sum() / keluar_p:.0%}" if keluar_p else "-",
                      help="Porsi token berpikir dari seluruh token yang dihasilkan model.")
            if p_nama == "Z.ai (GLM)" and keluar_p and dp["thinking_tokens"].sum() == 0:
                st.caption("Thinking 0: API tidak melaporkan token berpikir terpisah, jadi semuanya tercatat sebagai output.")

    pm = d.groupby(["penyedia", "model"]).agg(
        percobaan=("total_tokens", "size"), Input=("input_tokens", "mean"), Output=("output_tokens", "mean"),
        Thinking=("thinking_tokens", "mean"), total_rata=("total_tokens", "mean"),
        total_token=("total_tokens", "sum")).reset_index()
    panjang = pm.melt(id_vars=["penyedia", "model"], value_vars=["Input", "Output", "Thinking"],
                      var_name="Jenis token", value_name="Token")
    batang_m = px.bar(panjang, x="model", y="Token", color="Jenis token", color_discrete_map=WARNA,
                      labels={"model": "Model"})
    batang_m.update_xaxes(type="category")
    st.plotly_chart(rapikan(batang_m, "Rata-rata token per jawaban, per model", 380))

    total_m = px.bar(pm, x="model", y="total_token", color="penyedia", text_auto=",.0f",
                     labels={"model": "Model", "total_token": "Total token", "penyedia": "Penyedia"})
    total_m.update_xaxes(type="category")
    st.plotly_chart(rapikan(total_m, "Total token terpakai per model", 340))

    tabel_m = pm.rename(columns={"percobaan": "Percobaan", "total_rata": "Rata-rata total", "total_token": "Total token"})
    for k in ["Input", "Output", "Thinking", "Rata-rata total"]:
        tabel_m[k] = tabel_m[k].round(0).astype(int)
    st.dataframe(tabel_m, hide_index=True)

# ===== TAB PER KOMBINASI =====
with tab_kombinasi:
    dikerjakan = sorted(set(eks["nomor_kombinasi"]) & set(KOMBINASI), key=float)
    belum = sorted(set(KOMBINASI) - set(dikerjakan), key=float)
    st.progress(len(dikerjakan) / len(KOMBINASI),
                text=f"{len(dikerjakan)} dari {len(KOMBINASI)} kombinasi sudah dijalankan")
    if belum:
        st.caption("Belum dijalankan: " + ", ".join(belum))
    else:
        st.success("Semua kombinasi sudah dijalankan.")

    if eks.empty:
        st.info("Belum ada data eksperimen untuk filter ini.")
    else:
        rata = eks.groupby("nomor_kombinasi").agg(
            percobaan=("total_tokens", "size"), input_tokens=("input_tokens", "mean"),
            output_tokens=("output_tokens", "mean"), thinking_tokens=("thinking_tokens", "mean"),
            total_tokens=("total_tokens", "mean")).reset_index()
        rata["urut"] = pd.to_numeric(rata["nomor_kombinasi"], errors="coerce")
        rata = rata.sort_values("urut")
        panjang = rata.rename(columns={"input_tokens": "Input", "output_tokens": "Output", "thinking_tokens": "Thinking"}) \
                      .melt(id_vars="nomor_kombinasi", value_vars=["Input", "Output", "Thinking"],
                            var_name="Jenis token", value_name="Token")
        batang = px.bar(panjang, x="nomor_kombinasi", y="Token", color="Jenis token", color_discrete_map=WARNA,
                        labels={"nomor_kombinasi": "Nomor kombinasi"})
        batang.update_xaxes(type="category", categoryorder="array", categoryarray=list(rata["nomor_kombinasi"]))
        st.plotly_chart(rapikan(batang, "Rata-rata token per nomor kombinasi", 400))
        st.caption("Kalau satu nomor dicoba lebih dari sekali, yang ditampilkan adalah rata-ratanya.")
        tabel_rata = rata.drop(columns="urut").round(0).astype({"input_tokens": int, "output_tokens": int,
                                                                  "thinking_tokens": int, "total_tokens": int})
        st.dataframe(tabel_rata, hide_index=True)

# ===== TAB ANALISIS =====
with tab_analisis:
    petakan = eks[eks["nomor_kombinasi"].isin(KOMBINASI)].copy()
    if len(petakan) < 2:
        st.info("Analisis muncul setelah ada minimal 2 percobaan dengan nomor kombinasi dari tabel dosen.")
    else:
        petakan["elemen_A"] = petakan["nomor_kombinasi"].map(lambda n: KOMBINASI[n][0])
        petakan["teknik_B"] = petakan["nomor_kombinasi"].map(lambda n: KOMBINASI[n][1])
        petakan["keluar"] = petakan["output_tokens"] + petakan["thinking_tokens"]
        st.caption("Tujuan: melihat apakah prompt yang makin kompleks (lebih banyak elemen struktur atau teknik) "
                   "memakai token lebih banyak. Jumlah elemen dan teknik diambil dari tabel kombinasi dosen.")

        a1, a2 = st.columns(2)
        with a1:
            per_a = petakan.groupby("elemen_A").agg(input_tokens=("input_tokens", "mean"), n=("input_tokens", "size")).reset_index()
            fig_a = px.bar(per_a, x="elemen_A", y="input_tokens", text_auto=".0f", color_discrete_sequence=[C_IN],
                           labels={"elemen_A": "Jumlah elemen struktur (A)", "input_tokens": "Rata-rata token input"})
            fig_a.update_xaxes(type="category")
            st.plotly_chart(rapikan(fig_a, "Token input vs jumlah elemen struktur"))
            st.caption("Banyak percobaan per kelompok: " + ", ".join(f"{int(r.elemen_A)} elemen = {int(r.n)}" for r in per_a.itertuples()))
        with a2:
            per_b = petakan.groupby("teknik_B").agg(Output=("output_tokens", "mean"), Thinking=("thinking_tokens", "mean"),
                                                    n=("output_tokens", "size")).reset_index()
            fig_b = px.bar(per_b, x="teknik_B", y=["Output", "Thinking"], color_discrete_map=WARNA,
                           labels={"teknik_B": "Jumlah teknik prompting (B)", "value": "Rata-rata token", "variable": "Jenis token"})
            fig_b.update_xaxes(type="category")
            st.plotly_chart(rapikan(fig_b, "Token output dan thinking vs jumlah teknik"))
            st.caption("Banyak percobaan per kelompok: " + ", ".join(f"{int(r.teknik_B)} teknik = {int(r.n)}" for r in per_b.itertuples()))

        sebar = px.scatter(petakan, x="input_tokens", y="keluar", color="anggota", hover_data=["nomor_kombinasi"],
                           labels={"input_tokens": "Token input", "keluar": "Token output + thinking", "anggota": "Anggota"})
        st.plotly_chart(rapikan(sebar, "Token input vs token output+thinking (tiap titik = satu percobaan)", 380))

        st.markdown("**Ringkasan otomatis**")
        hemat = petakan.loc[petakan["total_tokens"].idxmin()]
        boros = petakan.loc[petakan["total_tokens"].idxmax()]
        st.write(f"- Paling hemat: kombinasi **{hemat['nomor_kombinasi']}** ({int(hemat['total_tokens']):,} token).")
        st.write(f"- Paling boros: kombinasi **{boros['nomor_kombinasi']}** ({int(boros['total_tokens']):,} token).")
        if petakan["elemen_A"].nunique() >= 3 and len(petakan) >= 5:
            r = petakan["elemen_A"].corr(petakan["input_tokens"])
            if pd.notna(r):
                st.write(f"- Korelasi jumlah elemen struktur dengan token input: **{r:.2f}** (1 = naik searah, 0 = tidak ada pola).")
        st.caption("Ringkasan ini hanya indikasi. Jumlah percobaan masih sedikit dan satu kombinasi biasanya cuma dicoba sekali, "
                   "jadi jangan dijadikan kesimpulan tanpa pertimbangan lain.")

# ===== TAB DATA =====
with tab_data:
    kolom = ["percobaan_ke", "waktu", "anggota", "jenis", "model", "nomor_kombinasi", "input_tokens",
             "output_tokens", "thinking_tokens", "total_tokens", "total_kumulatif", "kualitas"]
    tabel = d[[k for k in kolom if k in d.columns]]
    st.dataframe(tabel, hide_index=True)
    st.download_button("⬇️ Download CSV", tabel.to_csv(index=False), "log_dashboard.csv", "text/csv")

    st.markdown("#### 🔍 Detail satu percobaan")
    label = {int(r.percobaan_ke): f"#{int(r.percobaan_ke)} | {r.model} | {r.nomor_kombinasi} | {int(r.total_tokens):,} token"
             for r in d.itertuples()}
    pilih = st.selectbox("Pilih percobaan", list(label), format_func=lambda i: label[i], key="detail")
    baris = d[d["percobaan_ke"] == pilih].iloc[0]
    with st.container(border=True):
        st.caption("Prompt")
        st.write(baris.get("prompt", "-"))
        st.caption(f"Jawaban model ({baris.get('model', '-')})")
        st.write(baris.get("jawaban", "-"))
        st.caption("Penilaian kualitas")
        st.write(baris.get("kualitas", "-"))

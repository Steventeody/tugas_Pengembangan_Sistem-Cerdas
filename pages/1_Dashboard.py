import hashlib
import json
import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

LOG_FILE = "data/log.csv"                      # file yang sama dengan yang ditulis app.py
C_IN, C_OUT, C_THINK = "#4C9AFF", "#FF8B3D", "#B48CFF"
WARNA = {"Input": C_IN, "Output": C_OUT, "Thinking": C_THINK}
HITS_FILE = "data/request_hits.txt"            # dicatat oleh app.py tiap request ke Gemini
SETTING_FILE = "data/pengaturan.json"          # batas RPD / RPM / TPM (dibaca juga oleh app.py)
USAGE_FILE = "data/pemakaian.csv"              # token SEMUA request yang berhasil (dicatat app.py)


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


def kunci_aktif():
    """API key yang sedang dipakai: dari .env, atau yang diisi di halaman utama (tersimpan di session_state)."""
    return os.getenv("GEMINI_API_KEY") or st.session_state.get("_ingat_api_key", "")


KID = id_kunci(kunci_aktif())


def hitung_tpm():
    """Token INPUT dalam 60 detik terakhir untuk API key aktif (itulah yang dihitung TPM Gemini)."""
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
st.set_page_config(page_title="Dashboard Token", page_icon="📊", layout="wide")
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
[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 16px;}
section[data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.2);}
</style>
""", unsafe_allow_html=True)
st.markdown("""
<div class="hero">
  <div class="hero-title">📊 Dashboard Token</div>
  <div class="hero-sub">Pemantauan token input, output, dan thinking dari semua percobaan, plus jatah request</div>
</div>
""", unsafe_allow_html=True)

# ---------- 2. SIDEBAR: batas request ----------
awal = baca_pengaturan()
st.sidebar.markdown("## ⚙️ Pengaturan")
with st.sidebar.expander("🪙 Anggaran & batas request"):
    rpd = st.number_input("Batas request per hari (RPD)", min_value=1, value=int(awal["rpd"]),
                          key="rpd_dash", help="Lihat di AI Studio > Batasan Kecepatan")
    rpm = st.number_input("Batas request per menit (RPM)", min_value=1, value=int(awal["rpm"]),
                          key="rpm_dash", help="Lihat di AI Studio > Batasan Kecepatan")
    tpm = st.number_input("Batas token masuk per menit (TPM)", min_value=1, value=int(awal["tpm"]),
                          step=10000, key="tpm_dash", help="Lihat di AI Studio > Batasan Kecepatan")
if (rpd, rpm, tpm) != (awal["rpd"], awal["rpm"], awal["tpm"]):
    simpan_pengaturan(rpd=rpd, rpm=rpm, tpm=tpm)

with st.sidebar.expander("🔄 Samakan dengan AI Studio"):
    st.caption("Buka AI Studio > Batasan Kecepatan, lihat angka RPD model kamu, lalu isi di bawah. "
               "Penyesuaian ini hanya berlaku untuk hari ini.")
    rpd_studio = st.number_input("RPD terpakai menurut AI Studio", min_value=0, value=0, key="rpd_studio_dash")
    if st.button("Samakan", key="sinkron_dash"):
        if not KID:
            st.warning("Belum ada API key aktif. Isi dulu di halaman utama (app), lalu kembali ke sini.")
        else:
            offset = baca_pengaturan().get("offset_kunci", {})
            offset[KID] = {"rpd": int(rpd_studio) - hitung_mentah(), "hari": hari_google()}
            simpan_pengaturan(offset_kunci=offset)
            st.success("Sudah disamakan untuk hari ini (khusus API key ini).")

# ---------- 3. BACA DATA ----------
if not os.path.exists(LOG_FILE):
    st.info("Belum ada data. Jalankan eksperimen di halaman utama dan klik 'Simpan ke log' dulu.")
    st.stop()

df = pd.read_csv(LOG_FILE, dtype={"nomor_kombinasi": str})
if df.empty:
    st.info("Log masih kosong.")
    st.stop()

for kolom, default in [("anggota", "(tanpa nama)"), ("jenis", "eksperimen")]:
    if kolom not in df.columns:                  # data lama belum punya kolom ini
        df[kolom] = default
    df[kolom] = df[kolom].fillna(default)
for kolom in ["input_tokens", "output_tokens", "thinking_tokens", "total_tokens"]:
    df[kolom] = pd.to_numeric(df[kolom], errors="coerce").fillna(0)
df["nomor_kombinasi"] = df["nomor_kombinasi"].map(norm_nomor)

df["percobaan_ke"] = range(1, len(df) + 1)
df["total_kumulatif"] = df.groupby("anggota")["total_tokens"].cumsum()   # dihitung sebelum difilter

# ---------- 4. SIDEBAR: filter ----------
st.sidebar.markdown("## 🔎 Filter")
semua_anggota = sorted(df["anggota"].unique())
semua_jenis = sorted(df["jenis"].unique())
pilih_anggota = st.sidebar.multiselect("Anggota", semua_anggota, default=semua_anggota)
pilih_jenis = st.sidebar.multiselect("Jenis", semua_jenis, default=semua_jenis)

d = df[df["anggota"].isin(pilih_anggota) & df["jenis"].isin(pilih_jenis)]
if d.empty:
    st.warning("Tidak ada data untuk filter ini.")
    st.stop()
eks = d[(d["jenis"] == "eksperimen") & d["nomor_kombinasi"].notna()].copy()

tab_ringkas, tab_kombinasi, tab_analisis, tab_data = st.tabs(
    ["📊 Ringkasan", "🧩 Per kombinasi", "🔬 Analisis", "📄 Data"])

# ===== TAB RINGKASAN =====
with tab_ringkas:
    hits = [w for w in (baca_waktu(h) for h in baca_hits()) if w is not None]
    hari = hari_google()
    hari_ini = sum(1 for w in hits if hari_google(w) == hari)
    hari_ini = max(hari_ini + offset_hari_ini(), 0)    # hasil "Samakan" langsung terpakai

    with st.container(border=True):
        st.markdown("#### ⏱️ Jatah request hari ini")
        j1, j2, j3, j4 = st.columns(4)
        j1.metric("Batas per hari (RPD)", rpd)
        j2.metric("Request terpakai hari ini", hari_ini)
        j3.metric("Sisa request hari ini", max(rpd - hari_ini, 0))
        j4.metric("Token masuk 1 menit (TPM)", f"{hitung_tpm():,} / {tpm:,}")
        persen = min(hari_ini / rpd, 1.0)
        st.progress(persen, text=f"{persen:.0%} dari batas harian ({hari_ini} dari {rpd} request)")
        if hari_ini >= rpd:
            st.error("Perkiraan jatah request hari ini sudah habis.")
        elif persen >= 0.8:
            st.warning("Jatah request hari ini hampir habis.")
        reset = jam_reset()
        st.caption((f"API key aktif: kode {KID}. " if KID else "Belum ada API key aktif (isi di halaman utama), jadi hitungan 0. ")
                   + "Hitungan dipisah per API key. Dihitung dari request yang dikirim lewat aplikasi ini (termasuk yang gagal atau diulang). "
                   "Pemakaian di tempat lain, misalnya langsung di AI Studio, hanya ikut terhitung kalau sudah disamakan lewat "
                   "'Samakan dengan AI Studio' di sidebar. "
                   + (f"Hari dihitung menurut Google (tengah malam waktu Pasifik), reset berikutnya sekitar jam {reset} waktu laptop."
                      if reset else "Zona waktu Pasifik tidak tersedia, jadi hari dihitung memakai tanggal laptop."))
        if hits:
            per_hari = pd.Series([hari_google(w) for w in hits]).value_counts().sort_index()
            grafik = px.bar(x=per_hari.index, y=per_hari.values, labels={"x": "Tanggal (waktu Pasifik)", "y": "Request"})
            grafik.add_hline(y=rpd, line_dash="dash", annotation_text="Batas harian")
            grafik.update_xaxes(type="category")
            st.plotly_chart(rapikan(grafik, "Request per hari", 260))

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
    kolom = ["percobaan_ke", "waktu", "anggota", "jenis", "nomor_kombinasi", "input_tokens",
             "output_tokens", "thinking_tokens", "total_tokens", "total_kumulatif", "kualitas"]
    tabel = d[[k for k in kolom if k in d.columns]]
    st.dataframe(tabel, hide_index=True)
    st.download_button("⬇️ Download CSV", tabel.to_csv(index=False), "log_dashboard.csv", "text/csv")

    st.markdown("#### 🔍 Detail satu percobaan")
    label = {int(r.percobaan_ke): f"#{int(r.percobaan_ke)} | {r.nomor_kombinasi} | {int(r.total_tokens):,} token"
             for r in d.itertuples()}
    pilih = st.selectbox("Pilih percobaan", list(label), format_func=lambda i: label[i], key="detail")
    baris = d[d["percobaan_ke"] == pilih].iloc[0]
    with st.container(border=True):
        st.caption("Prompt")
        st.write(baris.get("prompt", "-"))
        st.caption("Jawaban Gemini")
        st.write(baris.get("jawaban", "-"))
        st.caption("Penilaian kualitas")
        st.write(baris.get("kualitas", "-"))

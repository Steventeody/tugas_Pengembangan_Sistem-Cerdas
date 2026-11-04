import os
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

LOG_FILE = "data/log.csv"                      # file yang sama dengan yang ditulis app.py
C_IN, C_OUT, C_THINK = "#6D8FD0", "#D98C5F", "#9C8CBF"       # palet lembut yang serasi dengan tema krem PANDU
WARNA = {"Input": C_IN, "Output": C_OUT, "Thinking": C_THINK}


def baca_waktu(teks):
    """Baca waktu dari teks. Menerima format dengan detik maupun tanpa detik (log lama)."""
    for bentuk in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(str(teks).strip(), bentuk)
        except ValueError:
            pass
    return None


def penyedia_dari_model(nama_model):
    m = str(nama_model).lower()
    return "Z.ai (GLM)" if "glm" in m else "Gemini" if "gemini" in m else "Lainnya"


def rapikan(fig, judul, tinggi=340):
    fig.update_layout(title=judul, height=tinggi, margin=dict(l=10, r=10, t=50, b=10),
                      font=dict(family="Inter, -apple-system, Segoe UI, sans-serif", color="#1A1A1A"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title_text=""),
                      plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF", bargap=0.35, title_font=dict(size=15))
    if fig.data and fig.data[0].type != "pie":                 # donut tidak punya sumbu
        fig.update_xaxes(showgrid=False, linecolor="#D4D3CF", ticks="")
        fig.update_yaxes(gridcolor="#EFEEE9", zeroline=False, ticks="")
        if fig.data[0].type == "bar" and fig.layout.barmode == "group" and getattr(fig.data[0], "orientation", "v") != "h":
            fig.update_traces(texttemplate="%{y:,.0f}", textposition="outside", cliponaxis=False, textfont=dict(size=11, color="#555555"))
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
        f = float(str(n).replace(",", "."))
    except (TypeError, ValueError):
        return n
    return str(int(f)) if f.is_integer() else str(f)


JENIS_UJI = ("uji_tanpa_rag", "uji_rag")       # baris yang ditulis tombol "Set uji RAG" di halaman utama


def susun_pasangan_uji(uji):
    """Satukan baris uji_tanpa_rag dan uji_rag menjadi satu baris per (model, nomor U01, U02, ...).
    Kalau satu pertanyaan dijalankan berulang, dipakai rata-ratanya. Hanya pertanyaan yang punya kedua sisi yang ikut."""
    kolom = ["input_tokens", "output_tokens", "thinking_tokens", "total_tokens"]
    kunci = ["model", "nomor_kombinasi"]
    a = uji[uji["jenis"] == "uji_tanpa_rag"]
    b = uji[uji["jenis"] == "uji_rag"]
    if a.empty or b.empty:
        return pd.DataFrame()
    rata_a = a.groupby(kunci)[kolom].mean()
    rata_b = b.groupby(kunci)[kolom].mean()
    pas = rata_a.join(rata_b, how="inner", lsuffix="_tanpa", rsuffix="_rag")
    if pas.empty:
        return pd.DataFrame()
    pas["pertanyaan"] = a.groupby(kunci)["prompt"].last()
    pas["potongan"] = b.assign(n=b["sumber_wisata"].map(len)).groupby(kunci)["n"].last()      # potongan data wisata yang benar-benar terkirim
    pas = pas.reset_index()
    for k in ("input", "output", "thinking", "total"):
        pas["selisih_" + k] = pas[k + "_tokens_rag"] - pas[k + "_tokens_tanpa"]
    pas["rasio_total"] = pas["total_tokens_rag"] / pas["total_tokens_tanpa"].where(pas["total_tokens_tanpa"] > 0)
    pas["urut"] = pas["nomor_kombinasi"].astype(str).str.extract(r"(\d+)")[0].astype(float)
    return pas.sort_values(["urut", "model"]).drop(columns="urut").reset_index(drop=True)


def persen(rag, tanpa):
    return (rag - tanpa) / tanpa * 100 if tanpa else None


def ringkas_kelompok(pas):
    """Rata-rata per kelompok: pertanyaan yang konteks RAG-nya terkirim, dan yang tidak (di luar data wisata)."""
    if pas.empty:
        return pd.DataFrame()
    baris = []
    for nama, sub in (("Konteks RAG terkirim", pas[pas["potongan"] > 0]), ("Tidak ada konteks yang cocok", pas[pas["potongan"] == 0])):
        if sub.empty:
            continue
        i_t, i_r = sub["input_tokens_tanpa"].mean(), sub["input_tokens_rag"].mean()
        t_t, t_r = sub["total_tokens_tanpa"].mean(), sub["total_tokens_rag"].mean()
        baris.append({"Kelompok": nama, "Pertanyaan": len(sub), "Input tanpa RAG": round(i_t), "Input dengan RAG": round(i_r),
                      "Selisih input (%)": round(persen(i_r, i_t), 1) if i_t else None,
                      "Total tanpa RAG": round(t_t), "Total dengan RAG": round(t_r),
                      "Selisih total (%)": round(persen(t_r, t_t), 1) if t_t else None})
    return pd.DataFrame(baris)


# ---------- 1. TAMPILAN ----------
LOGO = next((p for p in ("gambar/1.png", "gambar/logo_pandu.jpg") if os.path.exists(p)), None)
st.set_page_config(page_title="Dashboard PANDU", page_icon=LOGO or "📊", layout="wide")
if LOGO:
    st.logo(LOGO, size="large")                  # logo di paling atas sidebar, di atas menu halaman

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@800;900&display=swap');
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

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

/* ===== sidebar ala Claude: datar, rapat, tanpa kotak-kotak (sama dengan halaman utama) ===== */
:root { color-scheme: light; }
section[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding: .5rem .75rem 1rem; }
section[data-testid="stSidebar"] hr { margin: .7rem 0 !important; border-color: #ECEBE6 !important; }
[data-testid="stSidebarNav"] a, [data-testid="stSidebarNavLink"] { border-radius: 8px !important; padding: .35rem .65rem !important; font-size: .9rem !important; color: #1A1A1A !important; }
[data-testid="stSidebarNav"] a:hover, [data-testid="stSidebarNavLink"]:hover { background: #EFEEE9 !important; }
[data-testid="stSidebarNav"] a[aria-current="page"], [data-testid="stSidebarNavLink"][aria-current="page"] { background: #EAE9E5 !important; font-weight: 600; }
section[data-testid="stSidebar"] h2 { font-family: 'Inter', sans-serif !important; font-weight: 600; font-size: 1rem; margin: .2rem 0 .4rem .2rem; padding: 0; }
section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { font-size: .8rem; color: #6B6B6B !important; font-weight: 500; }
section[data-testid="stSidebar"] [data-baseweb="select"] > div { background: #FFFFFF !important; border-color: #E3E1DB !important; border-radius: 8px !important; }
section[data-testid="stSidebar"] [data-testid="stExpander"] { border: 0 !important; background: transparent !important; }
section[data-testid="stSidebar"] [data-testid="stExpander"] summary { padding: .45rem .65rem !important; border-radius: 8px; font-size: .9rem; }
section[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover { background: #EFEEE9; }

/* ===== font: Inter untuk semua teks, Newsreader untuk judul besar, ikon dan kode tidak disentuh ===== */
html, body, .stApp, .stApp p, .stApp li, .stApp label, .stApp a, .stApp div, .stApp button, .stApp input, .stApp textarea, .stApp select,
.stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp h5, .stApp h6, .stApp summary, .stApp span:not([data-testid="stIconMaterial"]) {
    font-family: 'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif !important; letter-spacing: -0.005em; }
.stApp pre, .stApp code, .stApp pre *, .stApp pre span:not([data-testid="stIconMaterial"]) {
    font-family: 'Source Code Pro', Consolas, monospace !important; letter-spacing: 0; }
.stApp .hero-title, .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricValue"] * {
    font-family: 'Newsreader', Georgia, serif !important; letter-spacing: -0.02em; }
</style>
""", unsafe_allow_html=True)
st.markdown("""
<div class="hero">
  <div class="hero-title">Dashboard Token</div>
  <div class="hero-sub">Pemantauan token input, output, dan thinking dari semua percobaan dan obrolan, termasuk pemakaian RAG</div>
</div>
""", unsafe_allow_html=True)

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
if "model" not in df.columns:                    # log lama belum mencatat nama model
    df["model"] = "(tidak tercatat)"
df["model"] = df["model"].fillna("(tidak tercatat)")
df["penyedia"] = df["model"].map(penyedia_dari_model)
for kolom in ["input_tokens", "output_tokens", "thinking_tokens", "total_tokens"]:
    df[kolom] = pd.to_numeric(df[kolom], errors="coerce").fillna(0)
df["anggota"] = "Semua anggota"                  # nama anggota tidak ditampilkan di dashboard (tabel maupun grafik)
df["nomor_kombinasi"] = df["nomor_kombinasi"].map(norm_nomor)

kolom_asli = set(df.columns)                      # kolom yang benar-benar ada di log.csv
for kolom in ("rag", "rag_sumber", "dokumen", "dokumen_sumber", "gambar"):
    if kolom not in df.columns:                   # log lama belum punya kolom RAG
        df[kolom] = ""
    df[kolom] = df[kolom].fillna("").astype(str)


def pecah_sumber(teks):
    return [s.strip() for s in str(teks).split(";") if s.strip()]


_rs = df["rag_sumber"].map(pecah_sumber)
df["sumber_wisata"] = _rs.map(lambda daftar: [s for s in daftar if not s.startswith("[dok]")])       # potongan data/wisata yang terkirim
df["sumber_dok"] = [[s for s in a if s.startswith("[dok]")] + pecah_sumber(b) for a, b in zip(_rs, df["dokumen_sumber"])]   # potongan dokumen unggahan
df["pakai_rag"] = df["sumber_wisata"].map(len) > 0
df["pakai_dok"] = df["sumber_dok"].map(len) > 0

df["percobaan_ke"] = range(1, len(df) + 1)
df["total_kumulatif"] = df.groupby("anggota")["total_tokens"].cumsum()   # dihitung sebelum difilter

# ---------- 4. SIDEBAR: filter ----------
st.sidebar.markdown("## Filter")
semua_anggota = sorted(df["anggota"].unique())
semua_jenis = sorted(j for j in df["jenis"].unique() if j not in JENIS_UJI)      # baris set uji tidak ditawarkan di filter; datanya tetap dipakai bagian "Set uji RAG" di tab RAG
pilih_anggota = semua_anggota          # filter Anggota dihapus: semua anggota ikut dihitung
pilih_jenis = st.sidebar.multiselect("Jenis", semua_jenis, default=semua_jenis)
# filter sumber chat dan RAG: sama dengan filter di "Lihat log" pada halaman utama
_ya = lambda k: df[k].str.lower().eq("ya")
_chat = df["jenis"].eq("chat")
_kategori = {"Chat biasa": _chat & ~_ya("dokumen") & ~_ya("gambar"), "Dokumen": _ya("dokumen"), "Gambar": _ya("gambar"),
             "Eksperimen": ~_chat & ~df["jenis"].eq("saran_dokumen")}
pilih_sumber = st.sidebar.multiselect("Sumber", list(_kategori), default=list(_kategori))
pilih_rag = st.sidebar.multiselect("RAG", ["Tanpa RAG", "Dengan RAG"], default=["Tanpa RAG", "Dengan RAG"])
_ok_sumber = pd.Series(False, index=df.index)
for _n in pilih_sumber:
    _ok_sumber |= _kategori[_n]
_ok_rag = (_ya("rag") & ("Dengan RAG" in pilih_rag)) | (~_ya("rag") & ("Tanpa RAG" in pilih_rag))
semua_penyedia = sorted(df["penyedia"].unique())
pilih_penyedia = st.sidebar.multiselect("Penyedia", semua_penyedia,       # awalnya hanya GLM; tambahkan Gemini untuk membandingkan
                                        default=[p for p in semua_penyedia if p == "Z.ai (GLM)"] or semua_penyedia)
semua_model = sorted(df.loc[df["penyedia"].isin(pilih_penyedia), "model"].unique())
pilih_model = st.sidebar.multiselect("Model", semua_model, default=semua_model)

d = df[df["anggota"].isin(pilih_anggota) & df["jenis"].isin(pilih_jenis) & _ok_sumber & _ok_rag
       & df["penyedia"].isin(pilih_penyedia) & df["model"].isin(pilih_model)]
if d.empty:
    st.warning("Tidak ada data untuk filter ini.")
    st.stop()
eks = d[(d["jenis"] == "eksperimen") & d["nomor_kombinasi"].notna()].copy()

tab_ringkas, tab_model, tab_kombinasi, tab_analisis, tab_data, tab_rag = st.tabs(
    ["Ringkasan", "Per model", "Per kombinasi", "Analisis", "Data", "RAG"])

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
    kolom = ["percobaan_ke", "waktu", "jenis", "model", "nomor_kombinasi", "input_tokens",
             "output_tokens", "thinking_tokens", "total_tokens", "total_kumulatif", "kualitas"]
    kolom += [k for k in ("rag", "rag_sumber", "dokumen", "dokumen_sumber", "rag_metode") if k in kolom_asli]
    tabel = d[[k for k in kolom if k in d.columns]]
    st.dataframe(tabel, hide_index=True)
    st.download_button("Download CSV (sesuai filter)", tabel.to_csv(index=False).encode("utf-8-sig"), "log_dashboard.csv", "text/csv")

    st.markdown("#### Detail satu percobaan")
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


# ===== TAB RAG =====
with tab_rag:
    st.caption("Membandingkan token dengan dan tanpa konteks RAG. 'Dengan konteks' berarti potongan data wisata benar-benar ikut terkirim ke model, "
               "bukan sekadar RAG menyala. Tab ini mengikuti filter Penyedia dan Model, tetapi tidak filter Jenis.")
    semua = df[df["penyedia"].isin(pilih_penyedia) & df["model"].isin(pilih_model)]

    # ---- 0. Set uji RAG: tiap pertanyaan tanpa dan dengan RAG ----
    uji = semua[semua["jenis"].isin(JENIS_UJI)]
    pas = susun_pasangan_uji(uji)
    if not pas.empty:
        st.markdown("#### Set uji RAG: pertanyaan yang sama, tanpa dan dengan RAG")
        i_t, i_r = pas["input_tokens_tanpa"].mean(), pas["input_tokens_rag"].mean()
        t_t, t_r = pas["total_tokens_tanpa"].mean(), pas["total_tokens_rag"].mean()
        u1, u2, u3, u4 = st.columns(4)
        u1.metric("Pertanyaan yang dibandingkan", len(pas))
        u2.metric("Rata-rata input tanpa RAG", f"{int(i_t):,}")
        u3.metric("Rata-rata input dengan RAG", f"{int(i_r):,}",
                  delta=f"{persen(i_r, i_t):+.0f}% dibanding tanpa RAG" if i_t else None, delta_color="off")
        u4.metric("Rata-rata total dengan RAG", f"{int(t_r):,}",
                  delta=f"{persen(t_r, t_t):+.0f}% dibanding {int(t_t):,} tanpa RAG" if t_t else None, delta_color="off",
                  help="Total = input + output + thinking. Thinking bervariasi antar panggilan, jadi total lebih berisik daripada input.")

        ringkas = ringkas_kelompok(pas)
        if len(ringkas) > 1:
            st.caption("Dipisah menurut apakah RAG benar-benar menempelkan potongan. Pertanyaan di luar data wisata seharusnya hampir tidak berbeda.")
            st.dataframe(ringkas, hide_index=True)

        WARNA_UJI = {"Tanpa RAG": "#B8B5AD", "Dengan RAG": "#D97757"}
        banyak_model_u = pas["model"].nunique() > 1
        pas["Label"] = pas["nomor_kombinasi"].astype(str) + (" · " + pas["model"] if banyak_model_u else "")
        bentuk = pas.melt(id_vars="Label", value_vars=["input_tokens_tanpa", "input_tokens_rag"], var_name="Kondisi", value_name="Token input")
        bentuk["Kondisi"] = bentuk["Kondisi"].map({"input_tokens_tanpa": "Tanpa RAG", "input_tokens_rag": "Dengan RAG"})
        grafik_u = px.bar(bentuk, x="Label", y="Token input", color="Kondisi", barmode="group", color_discrete_map=WARNA_UJI,
                          labels={"Label": "Pertanyaan (U01, U02, ...)"})
        grafik_u.update_xaxes(type="category")
        st.plotly_chart(rapikan(grafik_u, "Token input per pertanyaan: tanpa dan dengan RAG", 340))

        tabel_u = pas.assign(Pertanyaan=pas["pertanyaan"].astype(str).str.slice(0, 70))[
            ["nomor_kombinasi", "Pertanyaan", "potongan", "input_tokens_tanpa", "input_tokens_rag", "selisih_input",
             "total_tokens_tanpa", "total_tokens_rag", "selisih_total", "rasio_total"]].rename(columns={
            "nomor_kombinasi": "No", "potongan": "Potongan terkirim", "input_tokens_tanpa": "Input tanpa RAG",
            "input_tokens_rag": "Input dengan RAG", "selisih_input": "Selisih input", "total_tokens_tanpa": "Total tanpa RAG",
            "total_tokens_rag": "Total dengan RAG", "selisih_total": "Selisih total", "rasio_total": "Rasio total (x)"})
        for k in ["Input tanpa RAG", "Input dengan RAG", "Selisih input", "Total tanpa RAG", "Total dengan RAG", "Selisih total"]:
            tabel_u[k] = tabel_u[k].round(0).astype(int)
        tabel_u["Rasio total (x)"] = tabel_u["Rasio total (x)"].round(2)
        st.dataframe(tabel_u, hide_index=True)
        st.download_button("Download CSV set uji", tabel_u.to_csv(index=False).encode("utf-8-sig"), "set_uji_rag.csv", "text/csv",
                           key="unduh_uji")           # utf-8-sig supaya langsung terbaca benar di Excel

        kunci_a = uji[uji["jenis"] == "uji_tanpa_rag"][["model", "nomor_kombinasi"]].drop_duplicates()
        kunci_b = uji[uji["jenis"] == "uji_rag"][["model", "nomor_kombinasi"]].drop_duplicates()
        if len(kunci_a) != len(pas) or len(kunci_b) != len(pas):
            st.caption("Ada pertanyaan yang baru punya satu sisi (belum selesai dijalankan), jadi tidak ikut dibandingkan.")
        st.caption("Selisih positif berarti dengan RAG memakai lebih banyak token. Angka ini dari satu kali jalan per pertanyaan; "
                   "token thinking bervariasi, jadi ulangi set uji beberapa kali untuk rata-rata yang lebih stabil.")

    ada_rag = semua["pakai_rag"] | semua["pakai_dok"] | (semua["jenis"] == "eksperimen_rag")
    if not ada_rag.any():
        st.info("Belum ada data RAG. Kirim pertanyaan di mode Chat (RAG data wisata atau dokumen unggahan) atau jalankan Eksperimen dengan RAG menyala, "
                "lalu muat ulang halaman ini.")
    else:
        kolom_token = ["input_tokens", "output_tokens", "thinking_tokens", "total_tokens"]
        nama_token = {"input_tokens": "Input", "output_tokens": "Output", "thinking_tokens": "Thinking", "total_tokens": "Total"}
        WARNA_KEL = {"Tanpa konteks RAG": "#B8B5AD", "Dengan konteks RAG": "#D97757"}

        # ---- 1. Chat: dengan vs tanpa konteks ----
        st.markdown("#### Chat: dengan dan tanpa konteks RAG")
        chat = semua[(semua["jenis"] == "chat") & ~semua["pakai_dok"]]
        kel = chat.assign(Kelompok=chat["pakai_rag"].map({True: "Dengan konteks RAG", False: "Tanpa konteks RAG"}))
        if kel["Kelompok"].nunique() < 2:
            st.info("Perbandingan butuh obrolan di kedua kelompok (dengan dan tanpa konteks RAG), dan belum ada. "
                    "Obrolan yang memakai dokumen unggahan sengaja tidak dihitung di sini.")
        else:
            rata = kel.groupby("Kelompok")[kolom_token].mean()
            jml = kel["Kelompok"].value_counts()
            m1, m2, m3 = st.columns(3)
            m1.metric("Obrolan dengan konteks", int(jml.get("Dengan konteks RAG", 0)))
            m2.metric("Obrolan tanpa konteks", int(jml.get("Tanpa konteks RAG", 0)))
            i_rag, i_tanpa = rata.loc["Dengan konteks RAG", "input_tokens"], rata.loc["Tanpa konteks RAG", "input_tokens"]
            m3.metric("Rata-rata token input dengan konteks", f"{int(i_rag):,}",
                      delta=f"{(i_rag - i_tanpa) / i_tanpa * 100:+.0f}% dibanding tanpa konteks" if i_tanpa else None, delta_color="off")
            panjang = (rata.rename(columns=nama_token).reset_index()
                       .melt(id_vars="Kelompok", value_vars=["Input", "Output", "Thinking"], var_name="Jenis token", value_name="Rata-rata token"))
            grafik = px.bar(panjang, x="Jenis token", y="Rata-rata token", color="Kelompok", barmode="group", color_discrete_map=WARNA_KEL)
            st.plotly_chart(rapikan(grafik, "Rata-rata token per jawaban (chat)", 320))
            st.caption("Pertanyaan di kedua kelompok berbeda, jadi ini perbandingan kasar.")

        # ---- 2. Pasangan eksperimen ----
        dasar, dengan = semua[semua["jenis"] == "eksperimen"], semua[semua["jenis"] == "eksperimen_rag"]
        a = dasar.groupby(["model", "nomor_kombinasi"])[kolom_token].mean()
        b = dengan.groupby(["model", "nomor_kombinasi"])[kolom_token].mean()
        pas = a.join(b, how="inner", lsuffix="_tanpa", rsuffix="_rag").reset_index()
        if not pas.empty:
            st.markdown("#### Pasangan eksperimen: nomor kombinasi dan model yang sama")
            for k in kolom_token:
                pas["Selisih " + nama_token[k].lower()] = pas[k + "_rag"] - pas[k + "_tanpa"]
            banyak_model = pas["model"].nunique() > 1
            pas["Kombinasi"] = pas["nomor_kombinasi"] + (" · " + pas["model"] if banyak_model else "")
            p1, p2 = st.columns(2)
            p1.metric("Pasangan yang bisa dibandingkan", len(pas))
            p2.metric("Rata-rata selisih token input", f"{pas['Selisih input'].mean():+,.0f}")
            lebar = (pas.melt(id_vars="Kombinasi", value_vars=["Selisih input", "Selisih output", "Selisih thinking"],
                              var_name="Jenis token", value_name="Selisih token")
                     .assign(**{"Jenis token": lambda x: x["Jenis token"].str.replace("Selisih ", "").str.capitalize()}))
            grafik = px.bar(lebar, x="Kombinasi", y="Selisih token", color="Jenis token", barmode="group", color_discrete_map=WARNA)
            grafik.update_xaxes(type="category")
            st.plotly_chart(rapikan(grafik, "Selisih token: dengan RAG dikurangi tanpa RAG", 340))
            tampil = pas[["Kombinasi", "input_tokens_tanpa", "input_tokens_rag", "Selisih input", "Selisih output", "Selisih thinking", "Selisih total"]]
            tampil = tampil.rename(columns={"input_tokens_tanpa": "Input tanpa RAG", "input_tokens_rag": "Input dengan RAG"})
            st.dataframe(tampil.round(0), hide_index=True)
            st.caption("Bernilai positif berarti dengan RAG memakai lebih banyak token. Kalau satu kombinasi dijalankan berkali-kali, yang dipakai rata-ratanya.")

            with st.expander("Bandingkan jawaban dan penilaian kualitas"):
                opsi = {f"{r.nomor_kombinasi} · {r.model}": (r.model, r.nomor_kombinasi) for r in pas.itertuples()}
                pilih_p = st.selectbox("Pilih pasangan", list(opsi), key="pasangan_rag")
                mdl, nmr = opsi[pilih_p]
                tanpa_b = dasar[(dasar["model"] == mdl) & (dasar["nomor_kombinasi"] == nmr)].iloc[-1]
                rag_b = dengan[(dengan["model"] == mdl) & (dengan["nomor_kombinasi"] == nmr)].iloc[-1]
                ka, kb = st.columns(2)
                for kolom_ui, judul, baris in ((ka, "Tanpa RAG", tanpa_b), (kb, "Dengan RAG", rag_b)):
                    with kolom_ui, st.container(border=True):
                        st.markdown(f"**{judul}**")
                        st.caption(f"{int(baris['input_tokens']):,} input | {int(baris['output_tokens']):,} output | {int(baris['thinking_tokens']):,} thinking")
                        if judul == "Dengan RAG":
                            st.caption("Sumber: " + (baris["rag_sumber"] or "(tidak ada konteks yang cocok)"))
                        st.caption("Jawaban")
                        st.write(baris.get("jawaban", "-"))
                        st.caption("Penilaian kualitas")
                        st.write(baris.get("kualitas", "-"))

        # ---- 3. Sumber paling sering terambil ----
        st.markdown("#### Sumber yang paling sering terambil")
        hitung = {}
        for daftar in semua["sumber_wisata"]:
            for s in daftar:
                hitung[s] = hitung.get(s, 0) + 1
        if not hitung:
            st.info("Belum ada potongan data wisata yang terambil.")
        else:
            top = pd.DataFrame(sorted(hitung.items(), key=lambda x: -x[1])[:10], columns=["Potongan", "Jumlah"]).iloc[::-1]
            grafik = px.bar(top, x="Jumlah", y="Potongan", orientation="h", color_discrete_sequence=[C_OUT])
            st.plotly_chart(rapikan(grafik, "10 potongan data wisata teratas", 60 + 34 * len(top)))

        # ---- 4. Dokumen unggahan ----
        st.markdown("#### Dokumen unggahan")
        dok = semua[semua["pakai_dok"]]
        if dok.empty:
            st.info("Belum ada obrolan yang memakai dokumen unggahan.")
        else:
            tanpa_dok = semua[(semua["jenis"] == "chat") & ~semua["pakai_dok"]]
            q1, q2 = st.columns(2)
            q1.metric("Request dengan dokumen", len(dok))
            i_dok = dok["input_tokens"].mean()
            q2.metric("Rata-rata token input dengan dokumen", f"{int(i_dok):,}",
                      delta=(f"{(i_dok - tanpa_dok['input_tokens'].mean()) / tanpa_dok['input_tokens'].mean() * 100:+.0f}% dibanding chat tanpa dokumen"
                             if len(tanpa_dok) and tanpa_dok["input_tokens"].mean() else None), delta_color="off")

        # ---- 5. Tabel baris RAG ----
        st.markdown("#### Semua baris yang memakai RAG atau dokumen")
        isi = semua[ada_rag][["waktu", "jenis", "model", "nomor_kombinasi", "input_tokens", "total_tokens", "rag_sumber", "dokumen_sumber"]]
        st.dataframe(isi.rename(columns={"input_tokens": "token_input", "total_tokens": "token_total"}), hide_index=True)

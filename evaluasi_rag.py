"""Evaluasi retrieval RAG PANDU: tanpa API, tanpa Streamlit, tanpa biaya token.

Jalankan dari folder proyek (yang berisi app.py dan data/wisata):
    python evaluasi_rag.py                # ringkasan metrik untuk k = 1, 3, 5 + daftar pertanyaan yang gagal
    python evaluasi_rag.py --csv          # tulis juga hasil per pertanyaan ke evaluasi_rag_hasil.csv
    python evaluasi_rag.py --lembar       # tulis lembar penilaian manual (kesetiaan jawaban) ke lembar_nilai_rag.csv
    python evaluasi_rag.py --app lama.py  # evaluasi file app lain (mis. versi sebelum perubahan) untuk dibandingkan
    python evaluasi_rag.py --semantik     # bandingkan BM25 dengan pencarian semantik (butuh GEMINI_API_KEY di .env; memakai kuota embedding:
                                          # sekitar 2 panggilan saja) dan tampilkan rentang kemiripan untuk mengkalibrasi RAG_SEM_MIN

Yang diukur adalah RAG yang SAMA dengan yang dipakai chatbot: fungsi cari_konteks dari app.py, lengkap dengan pengaman nama tempat
dan ambang skornya. Fungsinya dimuat dari bagian "3b. RAG" sampai sebelum "4. SIDEBAR" di app.py, jadi kalau kamu mengubah RAG di sana,
hasil evaluasi ikut berubah tanpa mengedit file ini (kalau kamu menggeser penanda bagian itu, sesuaikan MULAI dan AKHIR di bawah).

Set uji (SET_UJI) disusun dari judul "##" di file data/wisata. Jawaban acuan = judul potongan yang SEHARUSNYA terambil.
Jumlahnya masih kecil, jadi angkanya indikasi, bukan bukti. Tambahkan pertanyaanmu sendiri, dan cek ulang label acuannya kalau isi data berubah.
"""
import csv
import hashlib
import io
import math
import re
import sys
import time
import types
import uuid
from pathlib import Path

APP = Path(sys.argv[sys.argv.index("--app") + 1]).resolve() if "--app" in sys.argv else Path(__file__).resolve().parent / "app.py"
RAG_DIR = "data/wisata"
MULAI, AKHIR = "# ---------- 3b. RAG", "# ---------- 4. SIDEBAR"
K_DIUJI, K_UTAMA = (1, 3, 5), 3                      # K_UTAMA = jumlah potongan bawaan chatbot (RAG_K_BAWAAN)

# (pertanyaan, [judul potongan yang diharapkan], jenis). Jenis "positif" = jawabannya ada di data; "negatif" = tidak ada, RAG sebaiknya tidak menempelkan apa pun.
SET_UJI = [
    ("Apa itu gudeg dan disajikan dengan apa?", ["Gudeg"], "positif"),
    ("Di mana pusat bakpia di Yogyakarta?", ["Bakpia Pathok"], "positif"),
    ("Sate klatak itu sate apa?", ["Sate Klatak"], "positif"),
    ("Kenapa kopi joss disebut joss?", ["Kopi Joss dan angkringan"], "positif"),
    ("Relief Ramayana ada di candi mana?", ["Candi Prambanan"], "positif"),
    ("Kapan waktu yang bagus menikmati matahari terbenam di Ratu Boko?", ["Candi Ratu Boko"], "positif"),
    ("Apa itu Sumbu Filosofi Yogyakarta?", ["Malioboro dan Sumbu Filosofi"], "positif"),
    ("Berapa jauh Borobudur dari pusat kota Yogyakarta?", ["Candi Borobudur"], "positif"),
    ("Pantai mana di Gunungkidul yang punya gondola?", ["Pantai di Gunungkidul"], "positif"),
    ("Apa yang bisa dilakukan di Gumuk Pasir Parangkusumo?", ["Pantai Parangtritis dan Gumuk Pasir"], "positif"),
    ("Gua Jomblang itu masuknya bagaimana?", ["Gua Jomblang dan Gua Pindul"], "positif"),
    ("Bagaimana susunan itinerari 3 hari di Yogyakarta?", ["Contoh susunan itinerari 3 hari di Yogyakarta"], "positif"),
    ("Naik apa untuk berkeliling di dalam kota Yogyakarta?", ["Transportasi di dalam kota Yogyakarta"], "positif"),
    ("Apa saja yang menarik di Ubud?", ["Ubud"], "positif"),
    ("Pura mana di Bali yang ada tari Kecak saat matahari terbenam?", ["Pura-pura terkenal di Bali"], "positif"),
    ("Bagaimana cara ke Nusa Penida?", ["Nusa Penida"], "positif"),
    ("Apa yang terjadi di Bali saat Nyepi?", ["Budaya, upacara, dan Nyepi"], "positif"),
    ("Kawah Putih Ciwidey itu seperti apa?", ["Kawah Putih Ciwidey"], "positif"),
    ("Oleh-oleh apa yang populer dari Bandung?", ["Belanja di Bandung", "Kuliner khas Bandung"], "positif"),
    ("Bagaimana cara ke Bandung dari Jakarta?", ["Ke Bandung dari Jakarta"], "positif"),
    ("Apa itu Kampung Inggris Pare?", ["Kampung Inggris Pare"], "positif"),
    ("Tahu takwa itu apa?", ["Kuliner khas Kediri"], "positif"),
    ("Apa itu Terowongan Ampera di Gunung Kelud?", ["Gunung Kelud"], "positif"),
    ("Bagaimana melihat matahari terbit di Gunung Bromo?", ["Gunung Bromo"], "positif"),
    ("Apa itu coban di Malang?", ["Air terjun di Malang"], "positif"),
    ("Kenapa Pantai Tiga Warna perlu reservasi?", ["Pantai selatan Malang"], "positif"),
    ("Kampung Jodipan di Malang terkenal karena apa?", ["Kampung warna-warni dan kota Malang"], "positif"),
    ("Keripik tempe Sanan berasal dari mana?", ["Kuliner khas Malang"], "positif"),
    ("Apa saja wisata keluarga di Kota Batu?", ["Kota Batu"], "positif"),
    ("Jam buka Candi Prambanan jam berapa?", ["Harga tiket dan jam buka"], "positif"),      # jebakan: data sengaja tidak mencatat jam buka, hanya menyuruh pengguna mengecek
    ("Berapa harga tiket masuk Candi Borobudur?", ["Harga tiket dan jam buka"], "positif"),   # info umum harus ikut walau tempat disebut
    ("Berapa harga tiket di Lombok?", ["Harga tiket dan jam buka"], "positif"),               # tempat tidak ada di data, tetapi info umum tetap berlaku
    ("Berapa jam perjalanan dari Yogyakarta ke Borobudur?", ["Candi Borobudur"], "positif"),
    ("Apa itu Pantai Timang?", ["Pantai di Gunungkidul"], "positif"),                         # nama yang hanya ada di isi potongan, bukan judulnya
    ("Bagaimana ke Bandara Juanda dari Malang?", ["Ke Malang dan berkeliling"], "positif"),   # nama transit boleh dicari kalau pertanyaannya soal akses
    ("Berapa jam dari Surabaya ke Malang naik kereta?", ["Ke Malang dan berkeliling"], "positif"),
    # pertanyaan umum "tempat apa saja di kota X" (dulu BM25 mengambil potongan kuliner/akses; sekarang potongan tempat wisata menurut urutan file). Ditulis setelah masalahnya ditemukan.
    ("Wisata paling populer di Kediri", ["Monumen Simpang Lima Gumul", "Gunung Kelud", "Candi dan situs sejarah Kediri"], "positif"),
    ("Rekomendasi tempat wisata di Bandung", ["Kawah Putih Ciwidey", "Gunung Tangkuban Parahu dan Lembang", "Wisata keluarga di Lembang"], "positif"),
    ("Destinasi terkenal di Yogyakarta", ["Candi Prambanan", "Candi Ratu Boko", "Candi Borobudur"], "positif"),
    ("Wisata apa saja di Surabaya?", [], "negatif"),                                          # jebakan: kata 'Surabaya' muncul di data Kediri dan Malang, tetapi hanya sebagai asal perjalanan
    ("Wisata apa saja di Jakarta?", [], "negatif"),                                           # sama: 'Jakarta' hanya muncul di judul 'Ke Bandung dari Jakarta'
    ("Tempat wisata di Kulon Progo", [], "negatif"),                                          # hanya disebut sebagai lokasi bandara YIA
    ("Bagaimana wisata di Tokyo?", [], "negatif"),
    ("Rekomendasi tempat wisata di Lombok", [], "negatif"),
    ("Kuliner khas Medan apa saja?", [], "negatif"),
    ("Halo, apa kabar?", [], "negatif"),
    ("Apa itu fotosintesis?", [], "negatif"),
    # pertanyaan umum non-wisata (PANDU sekarang asisten serbaguna). Ditulis setelah ada laporan sumber wisata nyasar pada pertanyaan soal dokumen;
    # empat yang terakhir kebetulan memuat beberapa kata data wisata (nasi goreng, Inggris, kopi, sejarah) dan sulit ditolak lewat kecocokan kata.
    ("Apa metode yang dipakai penulis?", [], "negatif"),
    ("Data berasal dari mana?", [], "negatif"),
    ("Jelaskan isi dokumen tersebut", [], "negatif"),
    ("Berapa akurasi tertingginya?", [], "negatif"),
    ("Buatkan jadwal belajar seminggu", [], "negatif"),
    ("Tolong buatkan email izin tidak masuk kerja", [], "negatif"),
    ("Apa itu machine learning dan contohnya?", [], "negatif"),
    ("Bagaimana cara menjaga kesehatan jantung?", [], "negatif"),
    ("Tips hemat uang bulanan untuk mahasiswa", [], "negatif"),
    ("Rekomendasi film yang seru", [], "negatif"),
    ("Bagaimana cara membuat nasi goreng?", [], "negatif"),
    ("Terjemahkan kalimat ini ke bahasa Inggris", [], "negatif"),
    ("Cara membuat kopi yang enak di rumah", [], "negatif"),
    ("Jelaskan tentang sejarah kemerdekaan Indonesia", [], "negatif"),
]


def muat_rag():
    """Muat fungsi RAG dari app.py (tanpa menjalankan Streamlit). Mengembalikan namespace berisi cari_konteks dkk."""
    sumber = APP.read_text(encoding="utf-8")
    kode = sumber[sumber.index(MULAI):sumber.index(AKHIR)]
    st = types.SimpleNamespace(session_state={}, cache_resource=lambda f: f)        # st tiruan: hanya yang dipakai bagian RAG
    ns = dict(re=re, math=math, time=time, uuid=uuid, hashlib=hashlib, io=io, Path=Path, st=st, RAG_DIR=RAG_DIR)
    exec(compile(kode, str(APP), "exec"), ns)
    return types.SimpleNamespace(**ns)


def dasar(judul):
    return re.sub(r" \(bagian \d+\)$", "", judul)


def nilai(rag, k, vq=None, vek=None):
    """Jalankan seluruh set uji untuk satu nilai k. Mengembalikan daftar baris hasil per pertanyaan."""
    baris = []
    for q, harapan, jenis in SET_UJI:
        hasil = rag.cari_konteks(q, k) if vq is None else rag.cari_konteks(q, k, vektor=vq[q], vek_idx=vek)
        judul = [dasar(c["judul"]) for c in hasil]
        unik = list(dict.fromkeys(judul))
        cocok = [j for j in unik if j in harapan]
        peringkat = next((i for i, j in enumerate(judul, 1) if j in harapan), None)
        baris.append({
            "pertanyaan": q, "jenis": jenis, "harapan": harapan, "terambil": judul,
            "skor": [c["skor"] for c in hasil], "kata_dikirim": sum(len(c["teks"].split()) for c in hasil),
            "hit1": bool(judul and judul[0] in harapan), "hitk": peringkat is not None,
            "recall": len(cocok) / len(harapan) if harapan else None,
            "presisi": len(cocok) / len(unik) if unik else 0.0,
            "rr": 1 / peringkat if peringkat else 0.0,
            "kosong": not hasil,
        })
    return baris


def ringkas(baris):
    pos = [b for b in baris if b["jenis"] == "positif"]
    neg = [b for b in baris if b["jenis"] == "negatif"]
    rata = lambda xs: sum(xs) / len(xs) if xs else float("nan")
    return {
        "Hit@1": rata([b["hit1"] for b in pos]), "Hit@k": rata([b["hitk"] for b in pos]),
        "Recall@k": rata([b["recall"] for b in pos]), "Presisi@k": rata([b["presisi"] for b in pos]),
        "MRR": rata([b["rr"] for b in pos]), "Cakupan": rata([not b["kosong"] for b in pos]),
        "Penolakan benar": rata([b["kosong"] for b in neg]),
        "Kata/pertanyaan": rata([b["kata_dikirim"] for b in baris]),
    }


def cetak_ringkasan(semua):
    kunci = list(next(iter(semua.values())))
    print(f"\n{'Metrik':<18}" + "".join(f"k={k:<8}" for k in semua))
    for m in kunci:
        sel = [semua[k][m] for k in semua]
        print(f"{m:<18}" + "".join((f"{v:<10.0f}" if m == "Kata/pertanyaan" else f"{v:<10.2f}") for v in sel))
    n_pos = sum(1 for _, _, j in SET_UJI if j == "positif")
    print(f"\n{n_pos} pertanyaan positif, {len(SET_UJI) - n_pos} negatif. Hit@k = ada potongan yang benar di antara yang terambil; "
          "Cakupan = RAG menempelkan sesuatu;\nPenolakan benar = pertanyaan di luar data tidak mendapat konteks; Kata/pertanyaan = perkiraan beban token input dari RAG.")


def cetak_gagal(baris, k):
    gagal = [b for b in baris if (b["jenis"] == "positif" and not b["hitk"]) or (b["jenis"] == "negatif" and not b["kosong"])]
    print(f"\nPertanyaan yang gagal pada k={k} ({len(gagal)} dari {len(baris)}):")
    for b in gagal:
        print(f"  - [{b['jenis']}] {b['pertanyaan']}\n      diharapkan: {b['harapan'] or '(tidak ada konteks)'}\n      terambil  : {b['terambil'] or '(kosong)'}")
    salah_urut = [b for b in baris if b["jenis"] == "positif" and b["hitk"] and not b["hit1"]]
    if salah_urut:
        print(f"\nBenar terambil tetapi bukan peringkat 1 ({len(salah_urut)}):")
        for b in salah_urut:
            print(f"  - {b['pertanyaan']}  -> {b['terambil']}")


def tulis_csv(baris, nama="evaluasi_rag_hasil.csv"):
    with open(nama, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["pertanyaan", "jenis", "diharapkan", "terambil", "skor", "hit1", "hitk", "recall", "presisi", "rr", "kata_dikirim"])
        for b in baris:
            w.writerow([b["pertanyaan"], b["jenis"], "; ".join(b["harapan"]), "; ".join(b["terambil"]), "; ".join(map(str, b["skor"])),
                        int(b["hit1"]), int(b["hitk"]), "" if b["recall"] is None else round(b["recall"], 2), round(b["presisi"], 2),
                        round(b["rr"], 2), b["kata_dikirim"]])
    print(f"\nHasil per pertanyaan ditulis ke {nama}")


def tulis_lembar(baris, nama="lembar_nilai_rag.csv"):
    """Lembar untuk menilai jawaban chatbot secara manual (kamu yang menilai): tempel jawaban dari chat, lalu isi skornya."""
    with open(nama, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["no", "pertanyaan", "konteks_terkirim", "jawaban_chatbot (tempel)", "setia_konteks (0-2)", "menjawab_pertanyaan (0-2)", "ada_hal_dikarang (ya/tidak)", "catatan"])
        for i, b in enumerate(baris, 1):
            w.writerow([i, b["pertanyaan"], "; ".join(b["terambil"]) or "(tidak ada)", "", "", "", "", ""])
    print(f"\nLembar penilaian manual ditulis ke {nama}. Rubrik: setia_konteks 2 = semua klaim ada di konteks, 1 = sebagian, 0 = bertentangan atau tak berdasar; "
          "menjawab_pertanyaan 2 = tuntas, 1 = sebagian, 0 = tidak menjawab.")


def muat_semantik(rag):
    """Embedding potongan data dan semua pertanyaan uji lewat Gemini asli. Keluar dengan pesan jelas kalau tidak bisa."""
    import os
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from google import genai
    except ImportError as e:
        sys.exit(f"--semantik butuh paket yang dipakai aplikasi (python-dotenv, google-genai): {e}")
    kunci = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not kunci:
        sys.exit("--semantik butuh GEMINI_API_KEY di file .env.")
    klien = genai.Client(api_key=kunci)
    try:
        vek = rag.vektor_wisata(klien, rag.tanda_rag())
        vq = dict(zip([q for q, _, _ in SET_UJI], rag.embed_teks(klien, [q for q, _, _ in SET_UJI], "RETRIEVAL_QUERY")))
    except Exception as e:
        sys.exit(f"Embedding gagal ({type(e).__name__}: {e}). Cek key, kuota, atau jaringan.")
    return vq, vek


def cetak_kalibrasi(rag, vq, vek):
    """Skor kemiripan tertinggi per pertanyaan TANPA ambang, untuk memilih RAG_SEM_MIN: ambang harus di atas skor negatif dan di bawah skor positif.
    Negatif yang sudah ditolak pengaman nama tempat (skor 0) tidak ikut, karena ambang tidak berperan untuk mereka."""
    skor = {"positif": [], "negatif": []}
    for q, _, jenis in SET_UJI:
        atas = rag.cari_konteks(q, 1, vektor=vq[q], vek_idx=vek, skor_min=-1.0)
        if atas and atas[0]["skor"] > 0:
            skor[jenis].append(atas[0]["skor"])
    pos, neg = sorted(skor["positif"]), sorted(skor["negatif"])
    print("\nKalibrasi RAG_SEM_MIN (skor kemiripan tertinggi per pertanyaan, tanpa ambang):")
    print(f"  positif: terendah {pos[0]:.2f}, median {pos[len(pos) // 2]:.2f}" if pos else "  positif: -")
    print(f"  negatif yang lolos pengaman tempat: {len(neg)}, tertinggi {neg[-1]:.2f}" if neg else
          "  negatif: semuanya sudah ditolak pengaman nama tempat, jadi ambang belum teruji oleh set uji ini")
    print(f"  Ambang sekarang {rag.RAG_SEM_MIN}. Pilih di antara negatif tertinggi dan positif terendah. Set uji kecil: anggap ini petunjuk.")


if __name__ == "__main__":
    if not APP.exists():
        sys.exit(f"app.py tidak ditemukan di {APP.parent}. Jalankan skrip ini dari folder proyek.")
    rag = muat_rag()
    semua, per_k = {}, {}
    for k in K_DIUJI:
        per_k[k] = nilai(rag, k)
        semua[k] = ringkas(per_k[k])
    cetak_ringkasan(semua)
    cetak_gagal(per_k[K_UTAMA], K_UTAMA)
    if "--semantik" in sys.argv:
        vq, vek = muat_semantik(rag)
        sem, sem_k = {}, {}
        for k in K_DIUJI:
            sem_k[k] = nilai(rag, k, vq, vek)
            sem[k] = ringkas(sem_k[k])
        print("\n===== PENCARIAN SEMANTIK (potongan data wisata, ambang RAG_SEM_MIN =", rag.RAG_SEM_MIN, ") =====")
        cetak_ringkasan(sem)
        cetak_gagal(sem_k[K_UTAMA], K_UTAMA)
        cetak_kalibrasi(rag, vq, vek)
    if "--csv" in sys.argv:
        tulis_csv(per_k[K_UTAMA])
    if "--lembar" in sys.argv:
        tulis_lembar(per_k[K_UTAMA])

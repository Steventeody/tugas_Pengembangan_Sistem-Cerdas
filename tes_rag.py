"""Tes unit untuk bagian RAG di app.py: _kata_rag, tempat_dalam, dan cari_konteks (BM25 dan semantik).

Jalankan dari folder proyek (yang berisi app.py):
    python -m unittest tes_rag -v        # bawaan Python, tanpa library tambahan
    python -m pytest tes_rag.py          # kalau kamu memakai pytest

Tanpa API, tanpa Streamlit, dan tanpa membaca data/wisata: semua tes memakai korpus kecil buatan di bawah, jadi hasilnya tidak berubah
ketika isi data/wisata kamu ubah. (Kualitas pengambilan pada data sungguhan diukur terpisah oleh evaluasi_rag.py.)
Fungsinya dimuat dari app.py lewat muat_rag() di evaluasi_rag.py.
"""
import unittest

from evaluasi_rag import muat_rag

rag = muat_rag()


def potongan(judul, teks, file="wisata_tes.md", kunci=""):
    return {"judul": judul, "teks": teks, "file": file, "tambahan": f"{kunci} {kunci}"}


KORPUS = [
    potongan("Candi Borobudur", "Candi Borobudur adalah candi Buddha di Magelang dengan relief panjang dan stupa di puncaknya."),
    potongan("Candi Prambanan", "Candi Prambanan adalah candi Hindu dengan tiga candi utama yang menjulang tinggi.", kunci="Prambanan"),
    potongan("Pantai Parangtritis", "Pantai Parangtritis terkenal dengan senja, ombak besar, dan gumuk pasir di sekitarnya."),
    potongan("Kawah Putih", "Kawah Putih di Ciwidey memiliki danau berwarna putih kehijauan dan udara sejuk.", file="wisata_bandung.md"),
    potongan("Ke Bandung dari Jakarta", "Dari Jakarta ke Bandung bisa naik kereta atau lewat tol. Stasiun Bandung dekat pusat kota.", file="wisata_bandung.md"),
    potongan("Transportasi di dalam kota Yogyakarta", "Di Yogyakarta bisa naik bus kota, ojek, atau sewa motor.", file="info_praktis_yogyakarta.md"),
    potongan("Harga tiket dan jam buka", "Harga tiket masuk dan jam buka tiap tempat wisata dapat berubah, periksa situs resmi pengelola.", file="info_umum.md"),
    potongan("Contoh susunan itinerari 3 hari di Yogyakarta", "Hari pertama candi, hari kedua pantai, hari ketiga kota. Itinerari bisa disesuaikan.", file="wisata_yogyakarta.md"),
]
IDX = rag._indeks_dari(KORPUS, 4)


def judul(hasil):
    return [c["judul"] for c in hasil]


class TesKataRag(unittest.TestCase):
    def test_huruf_kecil_dan_tanda_baca(self):
        self.assertEqual(rag._kata_rag("Kawah, PUTIH!"), rag._kata_rag("kawah putih"))

    def test_kata_umum_dibuang(self):
        self.assertEqual(rag._kata_rag("Apa saja yang bagus di Bandung?"), ["bandung"])

    def test_kata_terlalu_pendek_dibuang(self):
        self.assertNotIn("x", rag._kata_rag("x ke y z Bali"))
        self.assertEqual(rag._kata_rag("a b Bali"), ["bali"])

    def test_imbuhan_disederhanakan_sama_di_pertanyaan_dan_dokumen(self):
        self.assertEqual(rag._kata_rag("menjelajahi"), rag._kata_rag("jelajah"))
        self.assertEqual(rag._kata_rag("pantainya"), rag._kata_rag("pantai"))

    def test_kata_pendek_tidak_dipotong_habis(self):
        for kata in ("bis", "makan", "kota"):
            self.assertTrue(len(rag._kata_rag(kata)[0]) >= 3, kata)

    def test_angka_dua_digit_atau_lebih_dipertahankan(self):
        self.assertIn("2026", rag._kata_rag("liburan 2026"))

    def test_masukan_aneh_tidak_error(self):
        self.assertEqual(rag._kata_rag(""), [])
        self.assertEqual(rag._kata_rag(None), rag._kata_rag("None"))
        self.assertEqual(rag._kata_rag("?!... ---"), [])


class TesTempatDalam(unittest.TestCase):
    def test_nama_dikenal(self):
        kenal, asing = rag.tempat_dalam("Apa yang menarik di Candi Borobudur?", IDX["df"])
        self.assertEqual(kenal, [set(rag._kata_rag("Candi Borobudur"))])
        self.assertFalse(asing)

    def test_nama_tidak_ada_di_basis(self):
        kenal, asing = rag.tempat_dalam("Bagaimana wisata di Tokyo?", IDX["df"])
        self.assertEqual(kenal, [])
        self.assertTrue(asing)

    def test_campuran_dikenal_dan_asing(self):
        kenal, asing = rag.tempat_dalam("Bandingkan Candi Borobudur dengan Angkor Wat", IDX["df"])
        self.assertEqual(len(kenal), 1)
        self.assertTrue(asing)

    def test_huruf_besar_di_awal_kalimat_bukan_nama_tempat(self):
        self.assertEqual(rag.tempat_dalam("Rekomendasi wisata yang seru", IDX["df"]), ([], False))
        self.assertEqual(rag.tempat_dalam("Bagaimana cuaca hari ini?", IDX["df"]), ([], False))

    def test_pemicu_di_ke_dari_walau_huruf_kecil(self):
        kenal, asing = rag.tempat_dalam("wisata di tokyo", IDX["df"])
        self.assertTrue(asing)
        kenal, asing = rag.tempat_dalam("kuliner di bandung", IDX["df"])
        self.assertEqual((len(kenal), asing), (1, False))

    def test_nama_berdampingan_jadi_satu_nama(self):
        kenal, _ = rag.tempat_dalam("Cerita tentang Kawah Putih", IDX["df"])
        self.assertEqual(kenal, [set(rag._kata_rag("Kawah Putih"))])

    def test_kata_semua_huruf_besar_bukan_nama(self):
        self.assertEqual(rag.tempat_dalam("Apa arti WIB dan ATM", IDX["df"]), ([], False))


class TesCariKonteksBM25(unittest.TestCase):
    def cari(self, q, k=3, **kw):
        return rag.cari_konteks(q, k, idx=IDX, **kw)

    def test_potongan_paling_relevan_di_urutan_pertama(self):
        self.assertEqual(judul(self.cari("Pantai apa yang punya gumuk pasir?"))[0], "Pantai Parangtritis")

    def test_pertanyaan_di_luar_data_kosong(self):
        self.assertEqual(self.cari("Bagaimana cara membuat nasi goreng?"), [])

    def test_pertanyaan_kosong_atau_hanya_kata_umum(self):
        self.assertEqual(self.cari(""), [])
        self.assertEqual(self.cari("apa yang dan di"), [])

    def test_batas_k(self):
        hasil = self.cari("candi di Yogyakarta", k=1)
        self.assertLessEqual(len(hasil), 1)

    def test_hasil_berisi_skor_dan_isi_asli_tidak_berubah(self):
        asli = [dict(p) for p in KORPUS]
        hasil = self.cari("Candi Borobudur Buddha")
        self.assertTrue(all("skor" in c and c["skor"] > 0 for c in hasil))
        self.assertEqual(KORPUS, asli)                         # hasil adalah salinan; korpus tidak ikut diberi skor
        self.assertTrue(all("skor" not in p for p in IDX["potongan"]))

    def test_urutan_menurun_menurut_skor(self):
        skor = [c["skor"] for c in self.cari("candi Hindu Buddha relief", k=5) if not c["file"].startswith("info_umum")]
        self.assertEqual(skor, sorted(skor, reverse=True))

    def test_nama_tempat_membatasi_ke_potongan_tempat_itu(self):
        hasil = self.cari("Ceritakan Candi Prambanan", k=5)
        self.assertEqual(judul(hasil)[0], "Candi Prambanan")
        self.assertNotIn("Candi Borobudur", judul(hasil))

    def test_kota_yang_tidak_ada_di_data_tidak_dapat_konteks(self):
        self.assertEqual(self.cari("Rekomendasi wisata di Tokyo"), [])

    def test_kota_asal_perjalanan_bukan_tujuan_wisata(self):
        self.assertEqual(self.cari("Rekomendasi wisata di Jakarta"), [])

    def test_kota_asal_tetap_boleh_untuk_pertanyaan_akses(self):
        self.assertIn("Ke Bandung dari Jakarta", judul(self.cari("Naik kereta dari Jakarta ke Bandung bagaimana?")))

    def test_guard_tempat_dimatikan_untuk_dokumen(self):
        hasil = rag.cari_konteks("wisata di Tokyo candi", 3, idx=IDX, guard_tempat=False)
        self.assertTrue(hasil)

    def test_skor_min_dihormati(self):
        self.assertEqual(self.cari("Candi Borobudur", skor_min=1e6), [])
        self.assertTrue(self.cari("Candi Borobudur", skor_min=0.0))

    def test_info_umum_ikut_untuk_harga_dan_jam_buka(self):
        hasil = self.cari("Jam buka Candi Prambanan jam berapa?")
        self.assertEqual(judul(hasil)[0], "Candi Prambanan")
        self.assertEqual(judul(hasil)[-1], "Harga tiket dan jam buka")

    def test_info_umum_tidak_ikut_untuk_pertanyaan_lain(self):
        for q in ("Buatkan itinerari 3 hari di Yogyakarta", "Berapa jam naik kereta ke Bandung?", "Ceritakan Candi Borobudur"):
            self.assertNotIn("Harga tiket dan jam buka", judul(self.cari(q)), q)

    def test_info_umum_hanya_satu_dan_tidak_menyingkirkan_potongan_tempat(self):
        hasil = self.cari("Berapa harga tiket dan jam buka Kawah Putih?")
        self.assertEqual(sum(c["file"].startswith("info_umum") for c in hasil), 1)
        self.assertIn("Kawah Putih", judul(hasil))

    def test_pertanyaan_umum_yang_kebetulan_memuat_satu_kata_data_ditolak(self):
        for q in ("Terjemahkan kalimat ini ke bahasa Candi", "Jelaskan isi dokumen tersebut", "Apa metode yang dipakai penulis?"):
            self.assertEqual(self.cari(q), [], q)

    def test_pertanyaan_satu_kata_tetap_boleh(self):
        self.assertTrue(self.cari("Borobudur"))

    def test_kata_penunjuk_dokumen_bukan_topik(self):
        for kata in ("isi", "tersebut", "ringkas", "rangkum", "dokumen", "pdf", "file"):
            self.assertEqual(rag._kata_rag(kata), [], kata)

    def test_nama_tempat_melewati_syarat_cakupan(self):
        self.assertTrue(self.cari("Apa kabar Candi Prambanan hari ini ya?"))

    def test_indeks_kosong(self):
        self.assertEqual(rag.cari_konteks("candi", 3, idx=rag._indeks_dari([], 0)), [])


class TesCariKonteksSemantik(unittest.TestCase):
    """Vektor buatan tangan: tiap potongan satu sumbu, supaya urutan hasil bisa diprediksi tanpa API embedding."""

    n = len(KORPUS)

    def vek_idx(self):
        return [[1.0 if j == i else 0.0 for j in range(self.n)] for i in range(self.n)]

    def vektor(self, **bobot):
        v = [0.0] * self.n
        for nama, nilai in bobot.items():
            v[[p["judul"] for p in KORPUS].index(nama.replace("_", " "))] = nilai
        return v

    def cari(self, q, v, k=3, **kw):
        return rag.cari_konteks(q, k, idx=IDX, vektor=v, vek_idx=self.vek_idx(), **kw)

    def test_urutan_menurut_kemiripan_vektor(self):
        v = self.vektor(Pantai_Parangtritis=0.9, Kawah_Putih=0.5)
        self.assertEqual(judul(self.cari("tempat bermain air", v))[0], "Pantai Parangtritis")

    def test_di_bawah_ambang_semantik_kosong(self):
        v = self.vektor(Pantai_Parangtritis=rag.RAG_SEM_MIN - 0.05)
        self.assertEqual(self.cari("sesuatu", v), [])

    def test_batas_relatif_menyingkirkan_potongan_jauh_di_bawah_teratas(self):
        v = self.vektor(Pantai_Parangtritis=0.9, Kawah_Putih=0.62)
        self.assertEqual(judul(self.cari("sesuatu", v)), ["Pantai Parangtritis"])

    def test_dua_potongan_sama_dekat_keduanya_terambil(self):
        v = self.vektor(Pantai_Parangtritis=0.9, Kawah_Putih=0.88)
        self.assertEqual(sorted(judul(self.cari("sesuatu", v))), ["Kawah Putih", "Pantai Parangtritis"])

    def test_pengaman_nama_tempat_tetap_berlaku(self):
        v = self.vektor(Pantai_Parangtritis=0.95, Candi_Prambanan=0.7)
        self.assertEqual(judul(self.cari("Ceritakan Candi Prambanan", v)), ["Candi Prambanan"])

    def test_kota_asing_tetap_kosong_walau_vektor_mirip(self):
        v = self.vektor(Pantai_Parangtritis=0.99)
        self.assertEqual(self.cari("Pantai di Tokyo", v), [])

    def test_info_umum_tetap_butuh_kecocokan_kata(self):
        v = self.vektor(Candi_Borobudur=0.8, Harga_tiket_dan_jam_buka=0.99)
        self.assertNotIn("Harga tiket dan jam buka", judul(self.cari("Ceritakan Candi Borobudur", v)))
        hasil = self.cari("Jam buka Candi Borobudur", v)
        self.assertEqual(judul(hasil)[-1], "Harga tiket dan jam buka")

    def test_jumlah_vektor_tidak_cocok_jatuh_ke_bm25(self):
        pendek = self.vek_idx()[:3]
        sem = rag.cari_konteks("Ceritakan Candi Prambanan", 3, idx=IDX, vektor=[0.0] * self.n, vek_idx=pendek)
        self.assertEqual(judul(sem), judul(rag.cari_konteks("Ceritakan Candi Prambanan", 3, idx=IDX)))


def kota(judul_, teks, file, kategori="Wisata Kediri dan sekitarnya"):
    return {"judul": judul_, "teks": teks, "file": file, "tambahan": f"  {kategori}"}


KORPUS_KOTA = [
    kota("Monumen Simpang Lima Gumul", "Monumen besar di pusat Kabupaten Kediri yang ramai pada sore hari.", "wisata_kediri.md"),
    kota("Gunung Kelud", "Gunung berapi dengan kawah dan pemandangan di Kediri.", "wisata_kediri.md"),
    kota("Goa Selomangleng", "Goa batu bersejarah di Kota Kediri dengan taman asri.", "wisata_kediri.md"),
    kota("Kuliner khas Kediri", "Tahu takwa dan nasi pecel khas Kediri.", "wisata_kediri.md"),
    kota("Ke Kediri dan berkeliling", "Naik kereta ke stasiun Kediri lalu lanjut angkutan umum.", "wisata_kediri.md"),
    kota("Kuliner di sekitar pasar", "Aneka makanan di pasar Kediri.", "kuliner_kediri.md", "Kuliner Kediri"),
]
IDX_KOTA = rag._indeks_dari(KORPUS_KOTA, 2)


class TesRingkasanTempat(unittest.TestCase):
    def cari(self, q, k=3):
        return judul(rag.cari_konteks(q, k, idx=IDX_KOTA))

    def test_pertanyaan_umum_kota_mengambil_tempat_wisata_menurut_urutan_file(self):
        self.assertEqual(self.cari("Wisata paling populer di Kediri"), ["Monumen Simpang Lima Gumul", "Gunung Kelud", "Goa Selomangleng"])

    def test_kuliner_dan_akses_tidak_ikut(self):
        hasil = self.cari("Tempat wisata di Kediri", k=5)
        self.assertNotIn("Kuliner khas Kediri", hasil)
        self.assertNotIn("Ke Kediri dan berkeliling", hasil)

    def test_batas_k(self):
        self.assertEqual(len(self.cari("Wisata paling populer di Kediri", k=1)), 1)

    def test_pertanyaan_dengan_topik_lain_tetap_bm25(self):
        self.assertEqual(self.cari("Kuliner khas Kediri apa?")[0], "Kuliner khas Kediri")
        self.assertEqual(self.cari("Bagaimana naik kereta ke Kediri?")[0], "Ke Kediri dan berkeliling")

    def test_tanpa_kata_kategori_tempat_tidak_masuk_mode_ringkasan(self):
        self.assertNotIn("Monumen Simpang Lima Gumul", self.cari("Oleh-oleh apa yang populer dari Kediri?"))


class TesSaranDokumen(unittest.TestCase):
    def dok(self, *kata):
        return {"nama": "d.pdf", "hash": "h", "potongan": [{"judul": f"B{i}", "teks": " ".join(["kata"] * n), "file": "d.pdf", "tambahan": ""}
                                                           for i, n in enumerate(kata, 1)]}

    def test_bahan_berhenti_di_sekitar_batas_kata(self):
        self.assertEqual(len(rag.bahan_saran([self.dok(500, 500, 500, 500)], 1200)), 2)

    def test_bahan_minimal_satu_potongan(self):
        self.assertEqual(len(rag.bahan_saran([self.dok(5000)], 1200)), 1)
        self.assertEqual(rag.bahan_saran([{"potongan": []}]), [])

    def test_baca_saran_membersihkan_nomor_butir_dan_tanda_kutip(self):
        teks = '1. Apa tujuan penelitian ini?\n- Teknik apa yang dipakai?\n* **Berapa akurasinya?**\n"Apa kesimpulannya?"'
        self.assertEqual(rag.baca_saran(teks), ["Apa tujuan penelitian ini?", "Teknik apa yang dipakai?", "Berapa akurasinya?", "Apa kesimpulannya?"])

    def test_baca_saran_membuang_yang_bukan_pertanyaan_atau_duplikat(self):
        teks = "Berikut daftarnya:\nApa tujuan penelitian ini?\napa tujuan penelitian ini?\nOk?\n" + "Apa " + "x" * 200 + "?"
        self.assertEqual(rag.baca_saran(teks), ["Apa tujuan penelitian ini?"])

    def test_baca_saran_batas_jumlah(self):
        teks = "\n".join(f"Pertanyaan nomor {i} apa ini?" for i in range(10))
        self.assertEqual(len(rag.baca_saran(teks, 3)), 3)


if __name__ == "__main__":
    unittest.main()

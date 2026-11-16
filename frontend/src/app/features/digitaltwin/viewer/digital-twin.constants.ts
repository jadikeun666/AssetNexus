/**
 * DUPLIKASI EKSPLISIT dari config/assetnexus.py DIGITAL_TWIN (backend
 * Python) -- TypeScript tidak bisa import konstanta Python lintas bahasa,
 * tidak ada mekanisme share-config di project ini. Kalau backend berubah,
 * nilai ini HARUS diupdate manual di sini juga (didokumentasikan sebagai
 * risiko drift yang disengaja, bukan disembunyikan).
 *
 * Semua kunci di objek DIGITAL_TWIN di bawah ini punya padanan bernama
 * sama di config/assetnexus.py DIGITAL_TWIN, termasuk
 * ANOMALY_MARKER_OPACITY_MIN/MAX (ditambahkan di sisi Python pada Fase 4
 * langkah f-2; sebelumnya hanya ada di file ini). Perubahan nilai harus
 * dilakukan di KEDUA tempat.
 *
 * CS5_PULSE_PERIOD_MS: visualization.md §3 cuma menspesifikasikan RENTANG
 * intensitas (0.1<->0.4), TIDAK menspesifikasikan periode/kecepatan
 * osilasi -- 2000ms (2 detik per siklus penuh) dipilih dan disepakati
 * eksplisit dengan product owner, konsisten dengan kata "subtle" yang
 * dipakai dokumen (pulsing lambat/halus, bukan berkedip cepat/mencolok
 * yang akan bersaing visual dengan animasi timeline §4.2).
 */
export const DIGITAL_TWIN = {
  CS5_PULSE_PERIOD_MS: 2000,
  CS5_PULSE_EMISSIVE_MIN: 0.1,
  CS5_PULSE_EMISSIVE_MAX: 0.4,
  // visualization.md §4.2: transisi snap-to-green, SENGAJA TIDAK di-eased
  // (150ms cepat, bukan 800ms seperti transisi tahun biasa) -- sudah ada
  // di config/assetnexus.py DIGITAL_TWIN.INTERVENTION_SNAP_MS sejak awal
  // sesi Fase 3, baru dipakai sekarang di langkah 4e-5.
  INTERVENTION_SNAP_MS: 150,
  // visualization.md §6: marker anomaly "pulsing" tidak dispesifikasikan
  // dokumen (apa yang berosilasi, periode, rentang nilai) -- keputusan
  // eksplisit sesi Fase 4 langkah f-2: opacity Sprite berosilasi (bukan
  // scale, supaya posisi/ukuran marker presisi tidak terganggu dan biaya
  // per frame minimal -- alasan teknis, bukan kutipan standar), REUSE
  // CS5_PULSE_PERIOD_MS yang sama (konsistensi visual, bukan konstanta
  // baru tanpa alasan). Rentang opacity 0.4<->1.0 (BEDA dari CS5 emissive
  // 0.1<->0.4) -- marker anomaly harus selalu terlihat jelas (severity
  // critical/high tidak boleh "hampir hilang" seperti glow CS5 yang
  // memang dirancang subtle), cuma berdenyut ringan, bukan nyaris mati.
  ANOMALY_MARKER_OPACITY_MIN: 0.4,
  ANOMALY_MARKER_OPACITY_MAX: 1.0,
} as const;

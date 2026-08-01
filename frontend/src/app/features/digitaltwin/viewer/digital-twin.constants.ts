/**
 * DUPLIKASI EKSPLISIT dari config/assetnexus.py DIGITAL_TWIN (backend
 * Python) -- TypeScript tidak bisa import konstanta Python lintas bahasa,
 * tidak ada mekanisme share-config di project ini. Kalau backend berubah,
 * nilai ini HARUS diupdate manual di sini juga (didokumentasikan sebagai
 * risiko drift yang disengaja, bukan disembunyikan).
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
} as const;

/**
 * Fungsi MURNI (tanpa Three.js, tanpa DOM) untuk logic timeline degradasi
 * (visualization.md §3-4). Dipisah dari komponen viewer supaya testable
 * penuh tanpa mock WebGL -- jsdom TIDAK punya dukungan WebGL sama sekali
 * (beda dari Observable Plot yang jsdom-nya sebagian dukung SVG), jadi
 * fungsi warna/easing HARUS diverifikasi di sini, bukan lewat komponen.
 */

/**
 * visualization.md §3: gradient 3-stop FIXED, tidak boleh diubah
 * per-deployment.
 *   condition_score 100 -> 90  : #2E7D32 (hijau, CS1)
 *   condition_score  89 -> 50  : #F9A825 (amber, CS2-CS3, interpolasi
 *                                          hijau->amber->merah)
 *   condition_score  49 ->  0  : #C62828 (merah, CS4-CS5)
 */
const STOP_GREEN: readonly [number, number, number] = [0x2e, 0x7d, 0x32];
const STOP_AMBER: readonly [number, number, number] = [0xf9, 0xa8, 0x25];
const STOP_RED: readonly [number, number, number] = [0xc6, 0x28, 0x28];

export interface RgbColor {
  r: number;
  g: number;
  b: number;
}

function lerpChannel(a: number, b: number, t: number): number {
  return Math.round(a + (b - a) * t);
}

function lerpRgb(
  from: readonly [number, number, number],
  to: readonly [number, number, number],
  t: number,
): RgbColor {
  return {
    r: lerpChannel(from[0], to[0], t),
    g: lerpChannel(from[1], to[1], t),
    b: lerpChannel(from[2], to[2], t),
  };
}

/**
 * visualization.md §3: "THREE.Color.lerpColors() interpolation across the
 * three stops keyed by condition_score / 100". Interpretasi disepakati
 * eksplisit (product owner): gradasi KONTINU 2-segmen, [90,100] hijau
 * solid (tabel §3 eksplisit menyebut satu warna tunggal di rentang itu),
 * [50,90] gradasi hijau->amber, [0,50] gradasi amber->merah -- dipilih
 * karena §3 menyebut "linear interpolation green->amber->red" (3 warna
 * dalam SATU proses interpolasi), dan konsisten dengan tujuan animasi
 * timeline §4.2 ("watching the asset age") yang butuh transisi mulus,
 * bukan lompatan warna tajam di batas CS.
 */
export function conditionScoreToColor(conditionScore: number): RgbColor {
  const clamped = Math.max(0, Math.min(100, conditionScore));

  if (clamped >= 90) {
    return { r: STOP_GREEN[0], g: STOP_GREEN[1], b: STOP_GREEN[2] };
  }
  if (clamped >= 50) {
    // segmen hijau -> amber, t=0 di score=90, t=1 di score=50
    const t = (90 - clamped) / (90 - 50);
    return lerpRgb(STOP_GREEN, STOP_AMBER, t);
  }
  // segmen amber -> merah, t=0 di score=50, t=1 di score=0
  const t = (50 - clamped) / 50;
  return lerpRgb(STOP_AMBER, STOP_RED, t);
}

export function rgbToHex(color: RgbColor): string {
  const toHex = (channel: number) => channel.toString(16).padStart(2, '0');
  return `#${toHex(color.r)}${toHex(color.g)}${toHex(color.b)}`;
}

/**
 * visualization.md §4.2: "Play" animasi eased linear antara condition_score
 * tahun berurutan -- t dalam rentang [0, 1] mewakili progres dalam window
 * 800ms (DIGITAL_TWIN.PLAY_MS_PER_YEAR) satu tahun.
 */
export function easeConditionScore(scoreFrom: number, scoreTo: number, t: number): number {
  const clampedT = Math.max(0, Math.min(1, t));
  return scoreFrom + (scoreTo - scoreFrom) * clampedT;
}

/**
 * visualization.md §3: pulsing emissive glow KHUSUS komponen CS5 (score
 * 0-24, asset-registry.md §3.1), oscillating 0.1<->0.4. Dimodelkan sebagai
 * gelombang segitiga (bukan sinusoidal) supaya deterministik & mudah
 * ditest dengan nilai tangan -- "oscillating" di dokumen tidak
 * menspesifikasikan bentuk gelombang, segitiga dipilih sebagai
 * interpretasi paling sederhana yang tetap valid ("naik lalu turun
 * berulang antara dua batas").
 */
export function pulseEmissiveIntensity(
  elapsedMs: number,
  periodMs: number,
  min: number,
  max: number,
): number {
  const phase = (elapsedMs % periodMs) / periodMs; // 0..1
  const triangleT = phase < 0.5 ? phase * 2 : (1 - phase) * 2; // 0->1->0
  return min + (max - min) * triangleT;
}

export function isCriticalState(conditionScore: number): boolean {
  // asset-registry.md §3.1: CS5 = 0-24.
  return conditionScore >= 0 && conditionScore <= 24;
}

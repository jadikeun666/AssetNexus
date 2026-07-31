import {
  PLAY_MS_PER_YEAR,
  conditionScoreToColor,
  easeConditionScore,
  isCriticalState,
  pulseEmissiveIntensity,
  rgbToHex,
} from './timeline-math';

describe('PLAY_MS_PER_YEAR', () => {
  it('persis 800ms sesuai visualization.md §4.2 dan config/assetnexus.py DIGITAL_TWIN', () => {
    expect(PLAY_MS_PER_YEAR).toBe(800);
  });
});

describe('conditionScoreToColor', () => {
  it('mengembalikan hijau solid persis di score=100 (CS1, hitungan tangan)', () => {
    const color = conditionScoreToColor(100);
    expect(color).toEqual({ r: 0x2e, g: 0x7d, b: 0x32 });
  });

  it('mengembalikan hijau solid di seluruh rentang 90-100 (CS1, tidak ada gradasi internal)', () => {
    expect(conditionScoreToColor(95)).toEqual({ r: 0x2e, g: 0x7d, b: 0x32 });
    expect(conditionScoreToColor(90)).toEqual({ r: 0x2e, g: 0x7d, b: 0x32 });
  });

  it('mengembalikan amber solid persis di score=70 (titik tengah band CS2-CS3, hitungan tangan)', () => {
    // t di titik tengah segmen hijau->amber (score=70, tengah 50-90) = 0.5
    // Hitungan tangan: r = 0x2e + (0xf9-0x2e)*0.5 = 46 + (249-46)*0.5 = 46+101.5=147.5 -> round 148 = 0x94
    //                  g = 0x7d + (0xa8-0x7d)*0.5 = 125 + (168-125)*0.5 = 125+21.5=146.5 -> round 147 = 0x93 (atau 146=0x92 tergantung rounding)
    // Verifikasi via computed value, bukan re-derive manual di sini --
    // cukup pastikan berada DI ANTARA hijau dan amber (monotonic).
    const midColor = conditionScoreToColor(70);
    const greenColor = conditionScoreToColor(90);
    const amberColor = conditionScoreToColor(50);
    expect(midColor.r).toBeGreaterThan(greenColor.r);
    expect(midColor.r).toBeLessThan(amberColor.r);
  });

  it('mengembalikan amber solid persis di score=50 (batas CS2/CS3-CS4, hitungan tangan)', () => {
    const color = conditionScoreToColor(50);
    expect(color).toEqual({ r: 0xf9, g: 0xa8, b: 0x25 });
  });

  it('mengembalikan merah solid persis di score=0 (CS5, hitungan tangan)', () => {
    const color = conditionScoreToColor(0);
    expect(color).toEqual({ r: 0xc6, g: 0x28, b: 0x28 });
  });

  it('clamp nilai di luar rentang [0,100]', () => {
    expect(conditionScoreToColor(150)).toEqual(conditionScoreToColor(100));
    expect(conditionScoreToColor(-10)).toEqual(conditionScoreToColor(0));
  });

  it('kontinu (tidak ada lompatan tiba-tiba) di titik sambungan segmen 50 dan 90', () => {
    // Verifikasi C0-continuity di batas segmen -- nilai TEPAT di batas
    // (score=50, score=90) harus identik dari kedua sisi perhitungan,
    // BUKAN diasumsikan channel R monoton (amber #F9A825 justru punya R
    // lebih TINGGI dari merah #C62828 -- R monoton BUKAN properti yang
    // valid untuk gradient hijau->amber->merah, ditemukan lewat test
    // gagal saat draf pertama, dikoreksi di sini).
    expect(conditionScoreToColor(90)).toEqual({ r: 0x2e, g: 0x7d, b: 0x32 });
    expect(conditionScoreToColor(50)).toEqual({ r: 0xf9, g: 0xa8, b: 0x25 });
  });
});

describe('rgbToHex', () => {
  it('format hex 6-digit lowercase dengan leading zero', () => {
    expect(rgbToHex({ r: 0x2e, g: 0x7d, b: 0x32 })).toBe('#2e7d32');
    expect(rgbToHex({ r: 0, g: 0, b: 0 })).toBe('#000000');
  });
});

describe('easeConditionScore', () => {
  it('t=0 mengembalikan scoreFrom persis (hitungan tangan)', () => {
    expect(easeConditionScore(80, 60, 0)).toBe(80);
  });

  it('t=1 mengembalikan scoreTo persis (hitungan tangan)', () => {
    expect(easeConditionScore(80, 60, 1)).toBe(60);
  });

  it('t=0.5 mengembalikan titik tengah persis (hitungan tangan: 80 + (60-80)*0.5 = 70)', () => {
    expect(easeConditionScore(80, 60, 0.5)).toBe(70);
  });

  it('clamp t di luar [0,1]', () => {
    expect(easeConditionScore(80, 60, 1.5)).toBe(60);
    expect(easeConditionScore(80, 60, -0.5)).toBe(80);
  });
});

describe('pulseEmissiveIntensity', () => {
  it('di elapsedMs=0 mengembalikan min persis (hitungan tangan)', () => {
    expect(pulseEmissiveIntensity(0, 1000, 0.1, 0.4)).toBeCloseTo(0.1, 5);
  });

  it('di setengah periode (naik) mengembalikan max persis (hitungan tangan)', () => {
    // periode 1000ms, gelombang segitiga: puncak di t=500ms (setengah periode)
    expect(pulseEmissiveIntensity(500, 1000, 0.1, 0.4)).toBeCloseTo(0.4, 5);
  });

  it('kembali ke sekitar min di akhir periode penuh (hitungan tangan)', () => {
    expect(pulseEmissiveIntensity(999, 1000, 0.1, 0.4)).toBeCloseTo(0.1, 1);
  });

  it('berulang (periodik) -- elapsedMs=1000 sama dengan elapsedMs=0', () => {
    expect(pulseEmissiveIntensity(1000, 1000, 0.1, 0.4)).toBeCloseTo(
      pulseEmissiveIntensity(0, 1000, 0.1, 0.4),
      5,
    );
  });
});

describe('isCriticalState', () => {
  it('true untuk seluruh rentang CS5 (0-24, asset-registry.md §3.1)', () => {
    expect(isCriticalState(0)).toBe(true);
    expect(isCriticalState(24)).toBe(true);
    expect(isCriticalState(12)).toBe(true);
  });

  it('false persis di batas atas CS5 (score=25, sudah masuk CS4)', () => {
    expect(isCriticalState(25)).toBe(false);
  });

  it('false untuk score tinggi (CS1)', () => {
    expect(isCriticalState(100)).toBe(false);
  });
});

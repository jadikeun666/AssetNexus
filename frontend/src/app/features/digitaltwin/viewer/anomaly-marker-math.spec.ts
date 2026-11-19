import {
  ComponentHotspot,
  groupMarkersIntoHotspots,
  mergeAnomalyMarker,
  severityToColor,
  traceWindowAround,
  severityLabel,
  detectionMethodLabel,
} from './anomaly-marker-math';
import { AnomalyMarkerDto, AssetAlertsPayload } from '../../../core/models/digital-twin.model';

function makeMarker(overrides: Partial<AnomalyMarkerDto> = {}): AnomalyMarkerDto {
  return {
    anomaly_id: 'anomaly-1',
    device_id: 'device-1',
    component_id: 'component-1',
    component_type: 'girder',
    detected_at: '2026-08-19T00:00:00Z',
    detection_method: 'threshold',
    severity: 'medium',
    ...overrides,
  };
}

function makePayload(overrides: Partial<AssetAlertsPayload> = {}): AssetAlertsPayload {
  return {
    anomaly_id: 'anomaly-1',
    device_id: 'device-1',
    component_id: 'component-1',
    detected_at: '2026-08-19T00:00:00Z',
    detection_method: 'threshold',
    severity: 'medium',
    ...overrides,
  };
}

describe('severityToColor', () => {
  it('mengembalikan amber untuk medium, konsisten STOP_AMBER timeline-math', () => {
    expect(severityToColor('medium')).toBe('#F9A825');
  });

  it('mengembalikan merah untuk critical, sama dengan warna CS5 pulse', () => {
    expect(severityToColor('critical')).toBe('#C62828');
  });

  it('fallback ke warna medium untuk severity tidak dikenal (tidak pernah undefined)', () => {
    expect(severityToColor('unknown-severity')).toBe('#F9A825');
  });
});

describe('mergeAnomalyMarker', () => {
  it('menambah marker baru dengan component_type dari lookup', () => {
    const lookup = (componentId: string) => (componentId === 'component-1' ? 'girder' : undefined);
    const result = mergeAnomalyMarker([], makePayload(), lookup);
    expect(result).toHaveLength(1);
    expect(result[0].component_type).toBe('girder');
  });

  it('tidak menduplikasi anomaly_id yang sudah ada (mis. WebSocket reconnect)', () => {
    const existing = [makeMarker()];
    const lookup = () => 'girder';
    const result = mergeAnomalyMarker(existing, makePayload(), lookup);
    expect(result).toHaveLength(1);
    expect(result).toBe(existing); // referensi sama, bukan array baru
  });

  it('drop diam-diam kalau component_id tidak dikenal lookup (belum ada viewer-payload)', () => {
    const lookup = () => undefined;
    const result = mergeAnomalyMarker([], makePayload(), lookup);
    expect(result).toEqual([]);
  });
});

describe('groupMarkersIntoHotspots', () => {
  it('satu component_type dengan satu event menghasilkan satu hotspot', () => {
    const hotspots = groupMarkersIntoHotspots([makeMarker({ severity: 'high' })]);
    expect(hotspots).toEqual<ComponentHotspot[]>([
      { componentType: 'girder', worstSeverity: 'high', eventCount: 1 },
    ]);
  });

  it('banyak event di component_type SAMA digabung jadi satu hotspot, worstSeverity = tertinggi', () => {
    const hotspots = groupMarkersIntoHotspots([
      makeMarker({ anomaly_id: 'a1', severity: 'medium' }),
      makeMarker({ anomaly_id: 'a2', severity: 'critical' }),
      makeMarker({ anomaly_id: 'a3', severity: 'high' }),
    ]);
    expect(hotspots).toHaveLength(1);
    expect(hotspots[0].worstSeverity).toBe('critical');
    expect(hotspots[0].eventCount).toBe(3);
  });

  it('component_type berbeda menghasilkan hotspot terpisah', () => {
    const hotspots = groupMarkersIntoHotspots([
      makeMarker({ anomaly_id: 'a1', component_type: 'girder', severity: 'medium' }),
      makeMarker({ anomaly_id: 'a2', component_type: 'pier', severity: 'critical' }),
    ]);
    expect(hotspots).toHaveLength(2);
    const girder = hotspots.find((h) => h.componentType === 'girder');
    const pier = hotspots.find((h) => h.componentType === 'pier');
    expect(girder?.worstSeverity).toBe('medium');
    expect(pier?.worstSeverity).toBe('critical');
  });

  it('array kosong menghasilkan hotspot kosong', () => {
    expect(groupMarkersIntoHotspots([])).toEqual([]);
  });
});

describe('traceWindowAround', () => {
  it('membuat jendela +/- 1 jam dan mempertahankan milidetik', () => {
    expect(traceWindowAround('2026-09-11T06:16:52.604Z')).toEqual({
      start: '2026-09-11T05:16:52.604Z',
      end: '2026-09-11T07:16:52.604Z',
    });
  });

  it('melewati tengah malam dengan benar', () => {
    expect(traceWindowAround('2026-08-19T00:00:00Z')).toEqual({
      start: '2026-08-18T23:00:00.000Z',
      end: '2026-08-19T01:00:00.000Z',
    });
  });

  it('menormalkan offset zona waktu ke UTC', () => {
    expect(traceWindowAround('2026-09-11T13:16:52+07:00')).toEqual({
      start: '2026-09-11T05:16:52.000Z',
      end: '2026-09-11T07:16:52.000Z',
    });
  });

  it('lebar total jendela tepat 2 jam', () => {
    const w = traceWindowAround('2026-09-11T06:16:52Z');
    expect(new Date(w.end).getTime() - new Date(w.start).getTime()).toBe(7_200_000);
  });
});

describe('severityLabel', () => {
  it('memetakan keempat severity ke label Indonesia', () => {
    expect(severityLabel('low')).toBe('Rendah');
    expect(severityLabel('medium')).toBe('Sedang');
    expect(severityLabel('high')).toBe('Tinggi');
    expect(severityLabel('critical')).toBe('Kritis');
  });

  it('mengembalikan nilai asli untuk severity tak dikenal', () => {
    expect(severityLabel('mystery')).toBe('mystery');
  });
});

describe('detectionMethodLabel', () => {
  it('memetakan metode deteksi yang dikenal', () => {
    expect(detectionMethodLabel('threshold')).toBe('Ambang statistik');
    expect(detectionMethodLabel('kalman_residual')).toBe('Residual Kalman');
    expect(detectionMethodLabel('pinn_residual')).toBe('Residual PINN');
  });

  it('mengembalikan nilai asli untuk metode tak dikenal', () => {
    expect(detectionMethodLabel('x')).toBe('x');
  });
});

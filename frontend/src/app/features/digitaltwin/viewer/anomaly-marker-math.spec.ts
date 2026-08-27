import {
  ComponentHotspot,
  groupMarkersIntoHotspots,
  mergeAnomalyMarker,
  severityToColor,
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

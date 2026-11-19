/**
 * Fungsi MURNI (tanpa Three.js) untuk anomaly hotspot marker
 * (visualization.md §6). Dipisah dari komponen viewer -- pola sama
 * timeline-math.ts -- supaya testable tanpa mock WebGL/canvas.
 */
import { AnomalyMarkerDto, AssetAlertsPayload } from '../../../core/models/digital-twin.model';
import { DIGITAL_TWIN } from './digital-twin.constants';

const SEVERITY_RANK: Record<string, number> = {
  medium: 1,
  high: 2,
  critical: 3,
};

/**
 * visualization.md §6 tidak menspesifikasikan warna marker per severity
 * (hanya "warning icon texture") -- palet ini dipilih KONSISTEN dengan
 * skema warna condition-state yang sudah dipakai di seluruh viewer
 * (visualization.md §3: amber utk peringatan sedang, merah utk kritis),
 * bukan warna baru yang tidak terkait sama sekali. medium memakai amber
 * yang sama dengan STOP_AMBER (timeline-math.ts) untuk konsistensi
 * visual lintas fitur.
 */
const SEVERITY_COLOR: Record<string, string> = {
  medium: '#F9A825',
  high: '#EF6C00',
  critical: '#C62828',
};

export function severityToColor(severity: string): string {
  return SEVERITY_COLOR[severity] ?? SEVERITY_COLOR['medium'];
}

/**
 * Gabungkan pesan WebSocket baru (architecture.md §5) ke array marker
 * yang sudah ada -- dedupe by anomaly_id (kalau device push event yang
 * SAMA dua kali, mis. reconnect WebSocket, tidak boleh dobel). Payload
 * WebSocket TIDAK punya component_type (lihat AssetAlertsPayload) --
 * fallback componentTypeLookup WAJIB disediakan caller (dari
 * forecastByComponent yang sudah di-fetch viewer-payload, join by
 * component_id).
 */
export function mergeAnomalyMarker(
  existing: AnomalyMarkerDto[],
  incoming: AssetAlertsPayload,
  componentTypeLookup: (componentId: string) => string | undefined,
): AnomalyMarkerDto[] {
  if (existing.some((marker) => marker.anomaly_id === incoming.anomaly_id)) {
    return existing; // sudah ada, tidak dobel
  }
  const componentType = componentTypeLookup(incoming.component_id);
  if (componentType === undefined) {
    // component_id tidak dikenal (mis. asset belum sempat fetch
    // viewer-payload) -- drop diam-diam, TIDAK bisa render marker tanpa
    // component_type (join key ke node glTF, visualization.md §1).
    return existing;
  }
  const newMarker: AnomalyMarkerDto = {
    anomaly_id: incoming.anomaly_id,
    device_id: incoming.device_id,
    component_id: incoming.component_id,
    component_type: componentType,
    detected_at: incoming.detected_at,
    detection_method: incoming.detection_method,
    severity: incoming.severity,
  };
  return [...existing, newMarker];
}

export interface ComponentHotspot {
  componentType: string;
  worstSeverity: string;
  eventCount: number;
}

/**
 * SATU hotspot Sprite per component_type (bukan per event) -- keputusan
 * desain eksplisit: viewer menampilkan titik kritis per komponen, bukan
 * menumpuk sprite kalau satu komponen punya banyak unresolved event.
 * worstSeverity dipakai untuk warna+ukuran sprite (representasi paling
 * informatif untuk sekilas pandang).
 */
export function groupMarkersIntoHotspots(markers: AnomalyMarkerDto[]): ComponentHotspot[] {
  const byComponent = new Map<string, AnomalyMarkerDto[]>();
  for (const marker of markers) {
    const list = byComponent.get(marker.component_type) ?? [];
    list.push(marker);
    byComponent.set(marker.component_type, list);
  }

  return Array.from(byComponent.entries()).map(([componentType, events]) => {
    const worstSeverity = events.reduce((worst, event) =>
      (SEVERITY_RANK[event.severity] ?? 0) > (SEVERITY_RANK[worst] ?? 0) ? event.severity : worst,
    events[0].severity);
    return { componentType, worstSeverity, eventCount: events.length };
  });
}

export interface TraceWindow {
  start: string;
  end: string;
}

/**
 * visualization.md §6: jendela grafik sensor trace di sekitar detected_at,
 * +/- ANOMALY_TRACE_HALF_WINDOW_MINUTES. Output selalu ISO 8601 UTC ('Z'),
 * apa pun offset input -- backend menolak waktu tanpa zona.
 */
export function traceWindowAround(detectedAt: string): TraceWindow {
  const center = new Date(detectedAt).getTime();
  const half = DIGITAL_TWIN.ANOMALY_TRACE_HALF_WINDOW_MINUTES * 60_000;
  return {
    start: new Date(center - half).toISOString(),
    end: new Date(center + half).toISOString(),
  };
}

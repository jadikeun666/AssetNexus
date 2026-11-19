/**
 * DTO snake_case, persis field JSON dari apps/digitaltwin/schemas.py --
 * pola sama dengan forecast-chart.model.ts (Fase 1).
 */
export interface DigitalTwinModelDto {
  id: string;
  file_ref: string;
  version: number;
}

export interface ComponentForecastDto {
  component_id: string;
  // visualization.md §1: join key ke node glTF -- nama node HARUS
  // persis sama dengan component_type ini.
  component_type: string;
  // { forecast_year (string): condition_score } -- key JSON selalu
  // string, forecast_year di-parse ke number saat dipakai.
  year_scores: Record<string, number>;
}

export interface ViewerPayloadDto {
  asset_id: string;
  digital_twin_model: DigitalTwinModelDto | null;
  forecast_by_component: ComponentForecastDto[];
}

export interface MaintenanceMarkerDto {
  component_id: string;
  component_type: string;
  scheduled_year: number;
  intervention_name: string;
  expected_state_after: string;
}

export interface DigitalTwinUploadResponseDto {
  id: string;
  asset_id: string;
  file_ref: string;
  version: number;
}

/**
 * visualization.md §6: anomaly hotspot marker -- AnomalyEvent unresolved
 * severity>=medium, dari GET /digitaltwin/assets/{asset_id}/anomaly-markers/
 * (fetch awal) DAN dari WebSocket /ws/assets/{asset_id}/alerts (push
 * real-time, langkah e Fase 4) -- payload WebSocket TIDAK persis sama
 * shape-nya dengan endpoint REST (lihat AssetAlertsPayload di bawah),
 * dinormalisasi ke AnomalyMarkerDto ini di viewer component sebelum
 * dipakai, supaya satu tipe data internal konsisten dari kedua sumber.
 */
export interface AnomalyMarkerDto {
  anomaly_id: string;
  device_id: string;
  component_id: string;
  component_type: string;
  detected_at: string;
  detection_method: string;
  severity: string;
}

/**
 * architecture.md §5: payload persis yang dikirim
 * apps/sensors/jobs.py push_anomaly_alert_job lewat Channels group_send
 * -- TIDAK punya device_id/component_id terpisah sebagai field top-level
 * beda urutan dari AnomalyMarkerDto (kebetulan sama isinya sekarang,
 * tapi dideklarasikan sebagai tipe terpisah karena keduanya berasal dari
 * KONTRAK berbeda -- REST response Ninja Schema vs WebSocket JSON manual
 * -- yang bisa berevolusi independen).
 */
export interface AssetAlertsPayload {
  anomaly_id: string;
  device_id: string;
  component_id: string;
  detected_at: string;
  detection_method: string;
  severity: string;
}

/** GET /digitaltwin/assets/{id}/anomaly-events/ (visualization.md §6, panel detail). */
export interface AnomalyEventDetailDto {
  anomaly_id: string;
  device_id: string;
  detected_at: string;
  detection_method: string;
  severity: string;
  resolved: boolean;
  resolution_notes: string;
}

export interface SensorReadingDto {
  timestamp: string;
  value: number;
  unit: string;
  quality_flag: string;
}

/** GET /sensors/devices/{id}/readings/ (visualization.md §6, sensor trace). */
export interface SensorTraceDto {
  device_id: string;
  start: string;
  end: string;
  truncated: boolean;
  readings: SensorReadingDto[];
}

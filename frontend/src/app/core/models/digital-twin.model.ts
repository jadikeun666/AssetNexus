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

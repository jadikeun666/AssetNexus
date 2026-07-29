/**
 * DTO snake_case, persis field JSON dari apps/digitaltwin/schemas.py --
 * pola sama dengan forecast-chart.model.ts (Fase 1).
 */
export interface DigitalTwinModelDto {
  id: string;
  file_ref: string;
  version: number;
}

export interface ViewerPayloadDto {
  asset_id: string;
  digital_twin_model: DigitalTwinModelDto | null;
  // { component_id: { forecast_year (string): condition_score } }
  // -- key JSON selalu string, forecast_year di-parse ke number saat dipakai.
  forecast_by_component: Record<string, Record<string, number>>;
}

export interface DigitalTwinUploadResponseDto {
  id: string;
  asset_id: string;
  file_ref: string;
  version: number;
}

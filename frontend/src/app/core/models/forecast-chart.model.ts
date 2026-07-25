/**
 * DTO ini SENGAJA snake_case, persis field JSON dari Django Ninja
 * (apps/deterioration/schemas.py) -- Ninja tidak dikonfigurasi konversi
 * camelCase otomatis. Mapping manual ke camelCase di layer ini cuma
 * menambah permukaan bug tanpa manfaat nyata untuk DTO yang murni
 * read-only seperti ini.
 */
export interface ForecastPointDto {
  forecast_year: number;
  condition_score: number;
  confidence_lower: number | null;
  confidence_upper: number | null;
}

export interface ComponentForecastChartDto {
  component_id: string;
  component_type: string;
  model_type: '' | 'discrete_markov' | 'ctmc_latent' | 'fuzzy_markov';
  model_version: number;
  points: ForecastPointDto[];
}

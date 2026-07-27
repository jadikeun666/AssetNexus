/**
 * DTO SENGAJA snake_case (persis field JSON Django Ninja,
 * apps/maintenance/schemas.py) -- pola sama forecast-chart.model.ts.
 *
 * cost/budget/allocated_cost bertipe string (bukan number) karena
 * backend mengirim representasi Decimal Python apa adanya (termasuk
 * presisi panjang untuk pembagian tidak genap, mis. budget_total/horizon) --
 * dikonversi ke number hanya di titik pemakaian (rendering chart), tidak
 * disimpan sebagai number di level DTO (engineering-rules.md §4: jangan
 * diam-diam kehilangan presisi).
 */
export interface GanttRowDto {
  component_id: string;
  component_label: string;
  scheduled_year: number;
  duration_years: number;
  intervention_name: string;
  intervention_type: 'minor' | 'major' | 'replacement';
  cost: string;
  expected_state_after: 'CS1' | 'CS2' | 'CS3' | 'CS4' | 'CS5';
}

export interface GanttChartDto {
  run_id: string;
  plan_id: string;
  plan_name: string;
  rows: GanttRowDto[];
}

export interface BudgetYearDto {
  year: number;
  allocated_cost: string;
  budget: string;
}

export interface BudgetChartDto {
  run_id: string;
  plan_id: string;
  plan_name: string;
  years: BudgetYearDto[];
}

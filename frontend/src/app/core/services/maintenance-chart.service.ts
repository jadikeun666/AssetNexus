import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { BudgetChartDto, GanttChartDto } from '../models/maintenance-chart.model';

@Injectable({ providedIn: 'root' })
export class MaintenanceChartService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/maintenance`;

  /**
   * organizationId dikirim manual lewat header X-Organization-Id --
   * pola identik DeteriorationChartService (stub auth, engineering-rules.md
   * §8, akan dipindah ke HttpInterceptor setelah Keycloak realm setup).
   */
  getGanttChart(organizationId: string, runId: string): Observable<GanttChartDto> {
    return this.http.get<GanttChartDto>(
      `${this.baseUrl}/runs/${runId}/gantt-chart/`,
      { headers: { 'X-Organization-Id': organizationId } },
    );
  }

  getBudgetChart(organizationId: string, runId: string): Observable<BudgetChartDto> {
    return this.http.get<BudgetChartDto>(
      `${this.baseUrl}/runs/${runId}/budget-chart/`,
      { headers: { 'X-Organization-Id': organizationId } },
    );
  }
}

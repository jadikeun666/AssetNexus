import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { environment } from '../../../environments/environment';
import { ComponentForecastChartDto } from '../models/forecast-chart.model';

@Injectable({ providedIn: 'root' })
export class DeteriorationChartService {
  private readonly http = inject(HttpClient);
  private readonly baseUrl = `${environment.apiBaseUrl}/deterioration`;

  /**
   * organizationId dikirim manual lewat header X-Organization-Id karena
   * backend masih pakai stub auth (_current_org_stub, engineering-rules.md
   * §8 -- akan diganti klaim Keycloak asli setelah realm setup selesai).
   * Setelah itu, header ini sebaiknya dipindah ke HttpInterceptor global,
   * bukan diteruskan manual di tiap service call seperti sekarang.
   */
  getForecastChart(
    organizationId: string,
    componentId: string,
  ): Observable<ComponentForecastChartDto> {
    return this.http.get<ComponentForecastChartDto>(
      `${this.baseUrl}/components/${componentId}/forecast-chart/`,
      { headers: { 'X-Organization-Id': organizationId } },
    );
  }
}

import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { DeteriorationChartService } from './deterioration-chart.service';
import { environment } from '../../../environments/environment';

/**
 * Vitest adalah default test runner Angular 21 (menggantikan Karma/Jasmine)
 * -- describe/it/expect/vi tersedia global lewat tsconfig.spec.json
 * ("types": ["vitest/globals"]), TIDAK perlu import eksplisit dari
 * 'vitest'. Belum diverifikasi jalan di project sungguhan -- ditulis
 * mengikuti dokumentasi resmi yang dicek saat penulisan, cek ulang
 * begitu `ng test` pertama kali dijalankan besok.
 */
describe('DeteriorationChartService', () => {
  let service: DeteriorationChartService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(DeteriorationChartService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
  });

  it('mengirim GET ke endpoint yang benar dengan header X-Organization-Id', () => {
    const orgId = 'org-123';
    const componentId = 'comp-456';

    service.getForecastChart(orgId, componentId).subscribe();

    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/deterioration/components/${componentId}/forecast-chart/`,
    );
    expect(req.request.method).toBe('GET');
    expect(req.request.headers.get('X-Organization-Id')).toBe(orgId);

    req.flush({
      component_id: componentId,
      component_type: 'girder',
      model_type: 'ctmc_latent',
      model_version: 1,
      points: [],
    });
  });

  it('meneruskan error HTTP apa adanya ke subscriber (tidak menelan error secara diam-diam)', () => {
    const orgId = 'org-123';
    const componentId = 'comp-404';
    let capturedError: unknown = null;

    service.getForecastChart(orgId, componentId).subscribe({
      error: (err) => {
        capturedError = err;
      },
    });

    const req = httpMock.expectOne(
      `${environment.apiBaseUrl}/deterioration/components/${componentId}/forecast-chart/`,
    );
    req.flush('Not Found', { status: 404, statusText: 'Not Found' });

    expect(capturedError).not.toBeNull();
  });
});

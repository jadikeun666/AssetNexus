import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { ConditionTrendChartComponent } from './condition-trend-chart.component';
import { DeteriorationChartService } from '../../../core/services/deterioration-chart.service';
import { ComponentForecastChartDto } from '../../../core/models/forecast-chart.model';

/**
 * CATATAN JUJUR (belum terverifikasi jalan): Observable Plot merender SVG
 * lewat DOM measurement API (getBBox, dsb) yang TIDAK didukung penuh oleh
 * jsdom (environment default Vitest, bukan browser sungguhan). Kalau
 * `Plot.plot()` asli dipanggil apa adanya di test ini, kemungkinan besar
 * akan error atau perlu konfigurasi tambahan (mis. jalankan test mode
 * browser Vitest, bukan jsdom).
 *
 * Untuk unit test komponen ini, `@observablehq/plot` di-mock penuh --
 * kita test LOGIC komponen (loading/error state, hasConfidenceBand,
 * modelLabel), BUKAN verifikasi visual chart benar-benar tergambar.
 * Verifikasi visual sebaiknya manual di browser dulu (`ng serve`), bukan
 * lewat unit test jsdom -- ini batasan nyata, bukan sesuatu yang saya
 * sembunyikan.
 */
vi.mock('@observablehq/plot', () => ({
  plot: vi.fn(() => document.createElement('div')),
  lineY: vi.fn(),
  areaY: vi.fn(),
  dot: vi.fn(),
  gridY: vi.fn(),
  ruleY: vi.fn(),
  tip: vi.fn(),
  pointer: vi.fn(),
}));

// jsdom tidak menyediakan ResizeObserver -- komponen memakainya di
// ngAfterViewInit, jadi perlu stub global sebelum TestBed membuat fixture.
class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

describe('ConditionTrendChartComponent', () => {
  let fixture: ComponentFixture<ConditionTrendChartComponent>;
  let component: ConditionTrendChartComponent;
  let chartServiceMock: { getForecastChart: ReturnType<typeof vi.fn> };

  const buildResponse = (
    overrides: Partial<ComponentForecastChartDto> = {},
  ): ComponentForecastChartDto => ({
    component_id: 'comp-1',
    component_type: 'girder',
    model_type: 'ctmc_latent',
    model_version: 1,
    points: [
      { forecast_year: 2026, condition_score: 80, confidence_lower: 75, confidence_upper: 85 },
      { forecast_year: 2027, condition_score: 78, confidence_lower: 70, confidence_upper: 86 },
    ],
    ...overrides,
  });

  beforeEach(async () => {
    (globalThis as any).ResizeObserver = ResizeObserverStub;
    chartServiceMock = { getForecastChart: vi.fn() };

    await TestBed.configureTestingModule({
      imports: [ConditionTrendChartComponent],
      providers: [{ provide: DeteriorationChartService, useValue: chartServiceMock }],
    }).compileComponents();

    fixture = TestBed.createComponent(ConditionTrendChartComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('organizationId', 'org-1');
    fixture.componentRef.setInput('componentId', 'comp-1');
  });

  it('memuat data dan mematikan status loading setelah request sukses', () => {
    chartServiceMock.getForecastChart.mockReturnValue(of(buildResponse()));

    fixture.detectChanges();

    expect(component.loading()).toBe(false);
    expect(component.chartData()).toEqual(buildResponse());
    expect(chartServiceMock.getForecastChart).toHaveBeenCalledWith('org-1', 'comp-1');
  });

  it('menampilkan pesan error saat request gagal (bukan silent failure)', () => {
    chartServiceMock.getForecastChart.mockReturnValue(
      throwError(() => new Error('network error')),
    );

    fixture.detectChanges();

    expect(component.loading()).toBe(false);
    expect(component.errorMessage()).toContain('tidak dapat dimuat');
  });

  it('hasConfidenceBand=false untuk model DTMC (confidence_lower semua null)', () => {
    chartServiceMock.getForecastChart.mockReturnValue(
      of(
        buildResponse({
          model_type: 'discrete_markov',
          points: [
            {
              forecast_year: 2026,
              condition_score: 80,
              confidence_lower: null,
              confidence_upper: null,
            },
          ],
        }),
      ),
    );

    fixture.detectChanges();

    expect(component.hasConfidenceBand()).toBe(false);
    expect(component.modelLabel()).toBe('Model dasar (DTMC)');
  });

  it('hasConfidenceBand=true saat model CTMC+Fuzzy punya band', () => {
    chartServiceMock.getForecastChart.mockReturnValue(of(buildResponse()));

    fixture.detectChanges();

    expect(component.hasConfidenceBand()).toBe(true);
    expect(component.modelLabel()).toBe('Model lanjutan (CTMC + Fuzzy)');
  });

  it('menangani chart kosong (belum ada forecast) tanpa error', () => {
    chartServiceMock.getForecastChart.mockReturnValue(
      of(buildResponse({ model_type: '', model_version: 0, points: [] })),
    );

    expect(() => fixture.detectChanges()).not.toThrow();
    expect(component.chartData()?.points).toEqual([]);
    expect(component.modelLabel()).toBe('Belum ada model');
  });
});

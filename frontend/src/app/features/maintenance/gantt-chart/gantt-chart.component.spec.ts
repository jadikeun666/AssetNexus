import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { GanttChartComponent } from './gantt-chart.component';
import { MaintenanceChartService } from '../../../core/services/maintenance-chart.service';
import { GanttChartDto } from '../../../core/models/maintenance-chart.model';

/**
 * Pola identik condition-trend-chart.component.spec.ts (Fase 1):
 * @observablehq/plot di-mock penuh -- jsdom tidak dukung DOM measurement
 * API yang dipakai Plot.plot(). Test LOGIC komponen (loading/error state),
 * bukan verifikasi visual chart benar-benar tergambar (itu manual ng serve).
 */
vi.mock('@observablehq/plot', () => ({
  plot: vi.fn(() => document.createElement('div')),
  barX: vi.fn(),
  gridX: vi.fn(),
  tip: vi.fn(),
  pointer: vi.fn(),
}));

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

describe('GanttChartComponent', () => {
  let fixture: ComponentFixture<GanttChartComponent>;
  let component: GanttChartComponent;
  let chartServiceMock: { getGanttChart: ReturnType<typeof vi.fn> };

  const buildResponse = (overrides: Partial<GanttChartDto> = {}): GanttChartDto => ({
    run_id: 'run-1',
    plan_id: 'plan-1',
    plan_name: 'Rencana Test',
    rows: [
      {
        component_id: 'comp-1',
        component_label: 'Jembatan A — girder',
        scheduled_year: 2026,
        duration_years: 0.08,
        intervention_name: 'Perbaikan Girder Major',
        intervention_type: 'major',
        cost: '30000000.00',
        expected_state_after: 'CS2',
      },
    ],
    ...overrides,
  });

  beforeEach(async () => {
    (globalThis as any).ResizeObserver = ResizeObserverStub;
    chartServiceMock = { getGanttChart: vi.fn() };

    await TestBed.configureTestingModule({
      imports: [GanttChartComponent],
      providers: [{ provide: MaintenanceChartService, useValue: chartServiceMock }],
    }).compileComponents();

    fixture = TestBed.createComponent(GanttChartComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('organizationId', 'org-1');
    fixture.componentRef.setInput('runId', 'run-1');
  });

  it('memuat data dan mematikan status loading setelah request sukses', () => {
    chartServiceMock.getGanttChart.mockReturnValue(of(buildResponse()));

    fixture.detectChanges();

    expect(component.loading()).toBe(false);
    expect(component.chartData()).toEqual(buildResponse());
    expect(chartServiceMock.getGanttChart).toHaveBeenCalledWith('org-1', 'run-1');
  });

  it('menampilkan pesan error saat request gagal (bukan silent failure)', () => {
    chartServiceMock.getGanttChart.mockReturnValue(
      throwError(() => new Error('network error')),
    );

    fixture.detectChanges();

    expect(component.loading()).toBe(false);
    expect(component.errorMessage()).toContain('tidak dapat dimuat');
  });

  it('menangani rows kosong (belum ada intervensi terjadwal) tanpa error', () => {
    chartServiceMock.getGanttChart.mockReturnValue(of(buildResponse({ rows: [] })));

    expect(() => fixture.detectChanges()).not.toThrow();
    expect(component.chartData()?.rows).toEqual([]);
  });
});

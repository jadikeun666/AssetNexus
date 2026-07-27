import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { BudgetChartComponent } from './budget-chart.component';
import { MaintenanceChartService } from '../../../core/services/maintenance-chart.service';
import { BudgetChartDto } from '../../../core/models/maintenance-chart.model';

vi.mock('@observablehq/plot', () => ({
  plot: vi.fn(() => document.createElement('div')),
  barY: vi.fn(),
  line: vi.fn(),
  tip: vi.fn(),
  pointer: vi.fn(),
}));

class ResizeObserverStub {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

describe('BudgetChartComponent', () => {
  let fixture: ComponentFixture<BudgetChartComponent>;
  let component: BudgetChartComponent;
  let chartServiceMock: { getBudgetChart: ReturnType<typeof vi.fn> };

  const buildResponse = (overrides: Partial<BudgetChartDto> = {}): BudgetChartDto => ({
    run_id: 'run-1',
    plan_id: 'plan-1',
    plan_name: 'Rencana Test',
    years: [
      { year: 2026, allocated_cost: '30000000.00', budget: '33333333.33' },
      { year: 2027, allocated_cost: '0.00', budget: '33333333.33' },
      { year: 2028, allocated_cost: '0.00', budget: '33333333.33' },
    ],
    ...overrides,
  });

  beforeEach(async () => {
    (globalThis as any).ResizeObserver = ResizeObserverStub;
    chartServiceMock = { getBudgetChart: vi.fn() };

    await TestBed.configureTestingModule({
      imports: [BudgetChartComponent],
      providers: [{ provide: MaintenanceChartService, useValue: chartServiceMock }],
    }).compileComponents();

    fixture = TestBed.createComponent(BudgetChartComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('organizationId', 'org-1');
    fixture.componentRef.setInput('runId', 'run-1');
  });

  it('memuat data dan mematikan status loading setelah request sukses', () => {
    chartServiceMock.getBudgetChart.mockReturnValue(of(buildResponse()));

    fixture.detectChanges();

    expect(component.loading()).toBe(false);
    expect(component.chartData()).toEqual(buildResponse());
    expect(chartServiceMock.getBudgetChart).toHaveBeenCalledWith('org-1', 'run-1');
  });

  it('menampilkan pesan error saat request gagal (bukan silent failure)', () => {
    chartServiceMock.getBudgetChart.mockReturnValue(
      throwError(() => new Error('network error')),
    );

    fixture.detectChanges();

    expect(component.loading()).toBe(false);
    expect(component.errorMessage()).toContain('tidak dapat dimuat');
  });

  it('menangani years kosong (belum ada data anggaran) tanpa error', () => {
    chartServiceMock.getBudgetChart.mockReturnValue(of(buildResponse({ years: [] })));

    expect(() => fixture.detectChanges()).not.toThrow();
    expect(component.chartData()?.years).toEqual([]);
  });
});

import { TestBed } from '@angular/core/testing';

import { AnomalyEventDetailDto } from '../../../core/models/digital-twin.model';
import { AnomalyDetailPanelComponent } from './anomaly-detail-panel.component';

function makeEvent(overrides: Partial<AnomalyEventDetailDto> = {}): AnomalyEventDetailDto {
  return {
    anomaly_id: 'a-1',
    device_id: 'device-1',
    detected_at: '2026-09-11T06:16:52.604Z',
    detection_method: 'kalman_residual',
    severity: 'critical',
    resolved: false,
    resolution_notes: '',
    ...overrides,
  };
}

async function setup(inputs: Record<string, unknown>) {
  await TestBed.configureTestingModule({ imports: [AnomalyDetailPanelComponent] }).compileComponents();
  const fixture = TestBed.createComponent(AnomalyDetailPanelComponent);
  const base = {
    componentType: 'girder',
    worstSeverity: 'critical',
    events: [],
    eventsStatus: 'ready',
  };
  for (const [key, value] of Object.entries({ ...base, ...inputs })) {
    fixture.componentRef.setInput(key, value);
  }
  fixture.detectChanges();
  await fixture.whenStable();
  return fixture;
}

describe('AnomalyDetailPanelComponent', () => {
  it('menampilkan label severitas, status, dan catatan penyelesaian', async () => {
    const fixture = await setup({
      events: [
        makeEvent({ resolved: true, resolution_notes: 'Sensor dikalibrasi ulang' }),
        makeEvent({ anomaly_id: 'a-2', severity: 'low', detection_method: 'threshold' }),
      ],
    });
    const text: string = fixture.nativeElement.textContent;
    expect(text).toContain('Kritis');
    expect(text).toContain('Rendah');
    expect(text).toContain('Sudah ditangani');
    expect(text).toContain('Belum ditangani');
    expect(text).toContain('Catatan penyelesaian: Sensor dikalibrasi ulang');
  });

  it('menampilkan pesan kosong bila tidak ada event', async () => {
    const fixture = await setup({ events: [] });
    expect(fixture.nativeElement.textContent).toContain('Belum ada kejadian anomali');
  });

  it('memancarkan eventSelected dengan anomaly_id saat baris diklik', async () => {
    const fixture = await setup({ events: [makeEvent({ anomaly_id: 'a-9' })] });
    let selected: string | undefined;
    fixture.componentInstance.eventSelected.subscribe((id) => (selected = id));
    (fixture.nativeElement.querySelector('button.event') as HTMLButtonElement).click();
    expect(selected).toBe('a-9');
  });

  it('memancarkan closed saat Escape ditekan di dalam panel', async () => {
    const fixture = await setup({ events: [makeEvent()] });
    let closedCount = 0;
    fixture.componentInstance.closed.subscribe(() => closedCount++);
    fixture.nativeElement
      .querySelector('aside')
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    expect(closedCount).toBe(1);
  });

  it('merender grafik dan peringatan terpotong saat trace tersedia', async () => {
    const fixture = await setup({
      events: [makeEvent()],
      selectedAnomalyId: 'a-1',
      traceStatus: 'ready',
      trace: {
        device_id: 'device-1',
        start: '2026-09-11T05:16:52Z',
        end: '2026-09-11T07:16:52Z',
        truncated: true,
        readings: [
          { timestamp: '2026-09-11T06:10:00Z', value: 1, unit: 'm/s2', quality_flag: 'ok' },
          { timestamp: '2026-09-11T06:20:00Z', value: 5000, unit: 'm/s2', quality_flag: 'ok' },
        ],
      },
    });
    expect(fixture.nativeElement.querySelector('.trace-chart svg')).not.toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Data dipotong');
  });
});

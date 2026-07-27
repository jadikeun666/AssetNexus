import { TestBed } from '@angular/core/testing';
import { App } from './app';

describe('App', () => {
  beforeEach(async () => {
    await TestBed.configureTestingModule({
      imports: [App],
    }).compileComponents();
  });

  it('should create the app', () => {
    const fixture = TestBed.createComponent(App);
    const app = fixture.componentInstance;
    expect(app).toBeTruthy();
  });

  it('should render the router outlet', async () => {
    // App murni composition root untuk routing (app.html hanya berisi
    // <router-outlet />, sejak scaffold Fase 1 menambahkan routing ke
    // asset-detail-demo) -- assertion lama menguji judul "Hello, frontend"
    // dari template default ng new yang sudah tidak ada, diganti test yang
    // relevan dengan kondisi component saat ini.
    const fixture = TestBed.createComponent(App);
    await fixture.whenStable();
    const compiled = fixture.nativeElement as HTMLElement;
    expect(compiled.querySelector('router-outlet')).toBeTruthy();
  });
});

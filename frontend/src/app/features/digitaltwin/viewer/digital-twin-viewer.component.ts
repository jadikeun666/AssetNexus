import {
  AfterViewInit,
  Component,
  ElementRef,
  OnDestroy,
  ViewChild,
  input,
} from '@angular/core';
import * as THREE from 'three';

/**
 * visualization.md §2: viewer stack Three.js -- WebGLRenderer + GLTFLoader
 * + OrbitControls, dibungkus lifecycle ngOnInit/ngOnDestroy TANPA
 * dependency framework Three-Angular khusus (pola sama Observable Plot
 * di ConditionTrendChartComponent, Fase 1).
 *
 * RENDER-ON-DEMAND (keputusan disepakati eksplisit product owner, sesi
 * Fase 3): visualization.md §7 membatasi HANYA 2 requestAnimationFrame
 * loop KONTINU di seluruh viewer (eased color transition §4.2, pulse CS5
 * §3). Render dasar Three.js TIDAK dijadikan loop rAF kontinu ketiga --
 * this.render() dipanggil eksplisit HANYA saat ada perubahan nyata (init,
 * resize container, OrbitControls 'change' event di langkah 4b, atau saat
 * salah satu dari 2 loop resmi itu aktif). Saat idle, TIDAK ADA rAF
 * berjalan sama sekali -- mematuhi §7 secara ketat, sekaligus praktik
 * performa standar industri untuk viewer 3D non-game (hemat CPU/GPU saat
 * scene statis, bukan render 60fps buta terus-menerus).
 *
 * LANGKAH 4a (scaffold minimal): scene kosong, background warna solid --
 * TUJUAN cuma verifikasi WebGLRenderer benar-benar merender ke <canvas>
 * di browser sebelum menambah GLTFLoader/OrbitControls/heatmap
 * (langkah 4b-4e, disepakati bertahap dengan product owner).
 */
@Component({
  selector: 'app-digital-twin-viewer',
  standalone: true,
  templateUrl: './digital-twin-viewer.component.html',
  styleUrl: './digital-twin-viewer.component.scss',
})
export class DigitalTwinViewerComponent implements AfterViewInit, OnDestroy {
  readonly organizationId = input.required<string>();
  readonly assetId = input.required<string>();

  @ViewChild('canvasContainer', { static: true })
  private canvasContainer!: ElementRef<HTMLDivElement>;

  private renderer?: THREE.WebGLRenderer;
  private scene?: THREE.Scene;
  private camera?: THREE.PerspectiveCamera;
  private resizeObserver?: ResizeObserver;

  ngAfterViewInit(): void {
    this.initScene();
    this.render();

    this.resizeObserver = new ResizeObserver(() => this.handleResize());
    this.resizeObserver.observe(this.canvasContainer.nativeElement);
  }

  ngOnDestroy(): void {
    this.resizeObserver?.disconnect();
    this.renderer?.dispose();
  }

  private initScene(): void {
    const container = this.canvasContainer.nativeElement;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x1a1a1a);

    this.camera = new THREE.PerspectiveCamera(
      50,
      container.clientWidth / container.clientHeight,
      0.1,
      1000,
    );
    this.camera.position.set(0, 2, 5);

    this.renderer = new THREE.WebGLRenderer({ antialias: true });
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    container.appendChild(this.renderer.domElement);
  }

  private handleResize(): void {
    const container = this.canvasContainer.nativeElement;
    if (!this.renderer || !this.camera || container.clientWidth === 0) return;

    this.camera.aspect = container.clientWidth / container.clientHeight;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(container.clientWidth, container.clientHeight);
    this.render();
  }

  /** Render-on-demand: satu-satunya titik panggil renderer.render(). */
  private render(): void {
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }
}

import * as THREE from 'three';

/**
 * visualization.md §6: anomaly hotspot marker = Sprite with a warning icon
 * texture. The icon is drawn procedurally (no image asset, no new
 * dependency), so it stays crisp when zoomed and is versioned with the code.
 *
 * Design: a WHITE rounded warning triangle with a DARK exclamation mark.
 * SpriteMaterial.color multiplies the texture, so the triangle takes the
 * severity color (severityToColor) while the glyph stays dark and legible.
 * One shared texture serves every severity. Shape + color together keep the
 * marker recognizable without relying on color alone (color-blind safety).
 *
 * Not unit-testable: jsdom has no 2D canvas. Verified visually in the browser.
 */
export const ANOMALY_ICON_SIZE_PX = 128;

/**
 * Returns null when a 2D canvas context is unavailable, so the caller can
 * fall back to a plain colored sprite instead of breaking the viewer.
 * The caller owns the returned texture and must call dispose() once.
 */
export function createWarningTriangleTexture(): THREE.CanvasTexture | null {
  const size = ANOMALY_ICON_SIZE_PX;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;

  ctx.clearRect(0, 0, size, size);

  // Triangle; round joins soften the corners.
  ctx.fillStyle = '#ffffff';
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 8;
  ctx.lineJoin = 'round';
  ctx.beginPath();
  ctx.moveTo(64, 12);
  ctx.lineTo(116, 106);
  ctx.lineTo(12, 106);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // Exclamation mark: stem + dot.
  ctx.fillStyle = '#1a1a1a';
  ctx.beginPath();
  ctx.roundRect(57, 46, 14, 34, 7);
  ctx.fill();
  ctx.beginPath();
  ctx.arc(64, 94, 7, 0, Math.PI * 2);
  ctx.fill();

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

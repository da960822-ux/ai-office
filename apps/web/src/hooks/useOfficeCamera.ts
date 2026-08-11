import { useRef, useState } from 'react';
import type { Employee } from '../api';

export type Camera = { zoom: number; x: number; y: number };

/**
 * Office canvas camera: zoom/pan state plus every control that moves it
 * (pointer drag, zoom buttons, keyboard arrows/WASD, zone focus/locate).
 * Kept framework-thin so a future game-feel layer can read `camera` and
 * `focusedId`/`focusedZone` without re-deriving them.
 */
export function useOfficeCamera(employees: Employee[], deskPositions: Record<string, [number, number]>, teamForAgent: (id: string) => string, zoneIds: string[]) {
  const [focusedId, setFocusedId] = useState('');
  const [focusedZone, setFocusedZone] = useState('');
  const [camera, setCamera] = useState<Camera>({ zoom: 1, x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragOrigin = useRef<{ pointerX: number; pointerY: number; x: number; y: number } | null>(null);

  const focusZone = (zone: string) => {
    setFocusedId('');
    setFocusedZone(zone);
  };
  const focusEmployee = (id: string) => {
    setFocusedZone('');
    setFocusedId(id);
  };
  const locateZone = (zone: string) => {
    const members = employees.filter(employee => teamForAgent(employee.id) === zone);
    const points = members.map(employee => deskPositions[employee.id]).filter(Boolean);
    if (!points.length) return;
    const x = points.reduce((sum, point) => sum + point[0], 0) / points.length;
    const y = points.reduce((sum, point) => sum + point[1], 0) / points.length;
    setCamera({ zoom: 1.55, x: (50 - x) * .55, y: (50 - y) * .55 });
  };
  const showAllOffice = () => { setCamera({ zoom: 1, x: 0, y: 0 }); setFocusedZone(''); setFocusedId(''); };
  const moveTeam = (direction: number) => {
    const current = Math.max(0, zoneIds.indexOf(focusedZone));
    focusZone(zoneIds[(current + direction + zoneIds.length) % zoneIds.length]);
  };
  const zoomCamera = (delta: number) => setCamera(current => ({ ...current, zoom: Math.max(1, Math.min(2.35, current.zoom + delta)) }));
  const beginPan = (event: React.PointerEvent<HTMLDivElement>) => {
    if ((event.target as HTMLElement).closest('button')) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    dragOrigin.current = { pointerX: event.clientX, pointerY: event.clientY, x: camera.x, y: camera.y };
    setDragging(true);
  };
  const panOffice = (event: React.PointerEvent<HTMLDivElement>) => {
    const origin = dragOrigin.current;
    if (!origin) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    const limit = Math.max(0, (camera.zoom - 1) * 42);
    setCamera(current => ({ ...current, x: Math.max(-limit, Math.min(limit, origin.x + (event.clientX - origin.pointerX) / bounds.width * 100)), y: Math.max(-limit, Math.min(limit, origin.y + (event.clientY - origin.pointerY) / bounds.height * 100)) }));
  };
  const endPan = () => { dragOrigin.current = null; setDragging(false); };

  const keyPanStep = 6;
  const keyMap: Record<string, [number, number]> = {
    ArrowLeft: [1, 0], ArrowRight: [-1, 0], ArrowUp: [0, 1], ArrowDown: [0, -1],
    a: [1, 0], d: [-1, 0], w: [0, 1], s: [0, -1],
  };
  const panByKeyboard = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const delta = keyMap[event.key];
    if (!delta) return;
    event.preventDefault();
    const [dx, dy] = delta;
    setCamera(current => {
      const limit = Math.max(0, (current.zoom - 1) * 42);
      return { ...current, x: Math.max(-limit, Math.min(limit, current.x + dx * keyPanStep)), y: Math.max(-limit, Math.min(limit, current.y + dy * keyPanStep)) };
    });
  };

  return {
    camera, dragging, focusedId, focusedZone, setFocusedId, setFocusedZone,
    focusZone, focusEmployee, locateZone, showAllOffice, moveTeam,
    zoomCamera, beginPan, panOffice, endPan, panByKeyboard,
  };
}

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from pathlib import Path


MM = float


@dataclass(frozen=True)
class Rect:
    x: MM
    y: MM
    w: MM
    h: MM

    def contains_point(self, x: MM, y: MM) -> bool:
        return self.x <= x <= self.x + self.w and self.y <= y <= self.y + self.h


class Mesh:
    def __init__(self) -> None:
        self.triangles: list[tuple[tuple[float, float, float], ...]] = []

    def add_box(self, x: MM, y: MM, z: MM, w: MM, d: MM, h: MM) -> None:
        x0, x1 = x, x + w
        y0, y1 = y, y + d
        z0, z1 = z, z + h

        p000 = (x0, y0, z0)
        p100 = (x1, y0, z0)
        p110 = (x1, y1, z0)
        p010 = (x0, y1, z0)
        p001 = (x0, y0, z1)
        p101 = (x1, y0, z1)
        p111 = (x1, y1, z1)
        p011 = (x0, y1, z1)

        self._quad(p000, p100, p110, p010)
        self._quad(p001, p011, p111, p101)
        self._quad(p000, p001, p101, p100)
        self._quad(p100, p101, p111, p110)
        self._quad(p110, p111, p011, p010)
        self._quad(p010, p011, p001, p000)

    def add_panel_xy_with_holes(
        self,
        x: MM,
        y: MM,
        z: MM,
        w: MM,
        d: MM,
        t: MM,
        holes: list[Rect],
    ) -> None:
        xs = _split_axis(x, x + w, [(hole.x, hole.x + hole.w) for hole in holes])
        ys = _split_axis(y, y + d, [(hole.y, hole.y + hole.h) for hole in holes])
        for x0, x1 in zip(xs, xs[1:]):
            for y0, y1 in zip(ys, ys[1:]):
                cx = (x0 + x1) / 2
                cy = (y0 + y1) / 2
                if any(hole.contains_point(cx, cy) for hole in holes):
                    continue
                self.add_box(x0, y0, z, x1 - x0, y1 - y0, t)

    def add_panel_xz_with_holes(
        self,
        x: MM,
        y: MM,
        z: MM,
        w: MM,
        h: MM,
        t: MM,
        holes: list[Rect],
    ) -> None:
        xs = _split_axis(x, x + w, [(hole.x, hole.x + hole.w) for hole in holes])
        zs = _split_axis(z, z + h, [(hole.y, hole.y + hole.h) for hole in holes])
        for x0, x1 in zip(xs, xs[1:]):
            for z0, z1 in zip(zs, zs[1:]):
                cx = (x0 + x1) / 2
                cz = (z0 + z1) / 2
                if any(hole.contains_point(cx, cz) for hole in holes):
                    continue
                self.add_box(x0, y, z0, x1 - x0, t, z1 - z0)

    def add_panel_yz_with_holes(
        self,
        x: MM,
        y: MM,
        z: MM,
        d: MM,
        h: MM,
        t: MM,
        holes: list[Rect],
    ) -> None:
        ys = _split_axis(y, y + d, [(hole.x, hole.x + hole.w) for hole in holes])
        zs = _split_axis(z, z + h, [(hole.y, hole.y + hole.h) for hole in holes])
        for y0, y1 in zip(ys, ys[1:]):
            for z0, z1 in zip(zs, zs[1:]):
                cy = (y0 + y1) / 2
                cz = (z0 + z1) / 2
                if any(hole.contains_point(cy, cz) for hole in holes):
                    continue
                self.add_box(x, y0, z0, t, y1 - y0, z1 - z0)

    def add_square_tube_z(
        self,
        cx: MM,
        cy: MM,
        z: MM,
        outer: MM,
        inner: MM,
        h: MM,
    ) -> None:
        x0 = cx - outer / 2
        y0 = cy - outer / 2
        wall = (outer - inner) / 2
        self.add_box(x0, y0, z, outer, wall, h)
        self.add_box(x0, y0 + outer - wall, z, outer, wall, h)
        self.add_box(x0, y0 + wall, z, wall, inner, h)
        self.add_box(x0 + outer - wall, y0 + wall, z, wall, inner, h)

    def add_square_tube_y(
        self,
        cx: MM,
        y: MM,
        cz: MM,
        outer: MM,
        inner: MM,
        d: MM,
    ) -> None:
        x0 = cx - outer / 2
        z0 = cz - outer / 2
        wall = (outer - inner) / 2
        self.add_box(x0, y, z0, outer, d, wall)
        self.add_box(x0, y, z0 + outer - wall, outer, d, wall)
        self.add_box(x0, y, z0 + wall, wall, d, inner)
        self.add_box(x0 + outer - wall, y, z0 + wall, wall, d, inner)

    def extend(self, other: "Mesh") -> None:
        self.triangles.extend(other.triangles)

    def write_stl(self, path: Path, name: str) -> None:
        with path.open("w", encoding="ascii", newline="\n") as stl:
            stl.write(f"solid {name}\n")
            for triangle in self.triangles:
                normal = _normal(*triangle)
                stl.write(f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}\n")
                stl.write("    outer loop\n")
                for vertex in triangle:
                    stl.write(f"      vertex {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}\n")
                stl.write("    endloop\n")
                stl.write("  endfacet\n")
            stl.write(f"endsolid {name}\n")

    def _quad(self, a: tuple[float, float, float], b: tuple[float, float, float], c: tuple[float, float, float], d: tuple[float, float, float]) -> None:
        self.triangles.append((a, b, c))
        self.triangles.append((a, c, d))


OUTER_W = 170.0
OUTER_D = 110.0
OUTER_H = 58.0
WALL = 3.0
BOTTOM = 3.0
M2_CLEARANCE = 2.4
M2_NUT_POCKET = 4.7
M2_NUT_DEPTH = 2.2

# The scanner needs the short optical end facing the front, which makes the
# SEN-18088 body deeper in the enclosure. The Pi is shifted right to keep both
# boards flat in the bottom without overlapping.
PI_X = 54.0
PI_Y = 42.0
PI_W = 85.0
PI_D = 56.0
PI_HOLE_SPAN_X = 58.0
PI_HOLE_SPAN_Y = 49.0
PI_HOLE_OFFSET = 3.5

SCANNER_BOARD_X = 18.0
SCANNER_BOARD_Y = WALL + 4.0
SCANNER_BOARD_Z = 8.0
SCANNER_BOARD_W = 25.4
SCANNER_BOARD_D = 44.45
SCANNER_MOUNT_HOLES = (
    (SCANNER_BOARD_X + 2.54, SCANNER_BOARD_Y + SCANNER_BOARD_D - 2.54),
    (SCANNER_BOARD_X + 22.86, SCANNER_BOARD_Y + SCANNER_BOARD_D - 2.54),
)

SCANNER_WINDOW = Rect(SCANNER_BOARD_X - 6.0, 8.0, SCANNER_BOARD_W + 12.0, 32.0)
CAMERA_WINDOW = Rect(101.0, 15.0, 36.0, 36.0)
USB_C_POWER_ENTRY = Rect(62.0, 12.0, 35.0, 18.0)
SIDE_VENTS = tuple(Rect(18.0 + index * 8.0, 39.0, 4.0, 13.0) for index in range(8))
BOTTOM_VENTS = tuple(Rect(48.0 + index * 8.0, 74.0, 4.0, 24.0) for index in range(8))

CAMERA_LENS_CENTER_X = CAMERA_WINDOW.x + CAMERA_WINDOW.w / 2
CAMERA_LENS_CENTER_Z = CAMERA_WINDOW.y + CAMERA_WINDOW.h / 2
CAMERA_MOUNT_OUTLINE_X = CAMERA_LENS_CENTER_X - 18.0
CAMERA_MOUNT_OUTLINE_Z = CAMERA_LENS_CENTER_Z - 18.0
CAMERA_MOUNT_OUTLINE_SIZE = 36.0
CAMERA_HOLE_OFFSET_X = 10.5
CAMERA_HOLE_OFFSET_Z = 10.0
CAMERA_MOUNT_HOLES = (
    (CAMERA_LENS_CENTER_X - CAMERA_HOLE_OFFSET_X, CAMERA_LENS_CENTER_Z - CAMERA_HOLE_OFFSET_Z),
    (CAMERA_LENS_CENTER_X + CAMERA_HOLE_OFFSET_X, CAMERA_LENS_CENTER_Z - CAMERA_HOLE_OFFSET_Z),
    (CAMERA_LENS_CENTER_X - CAMERA_HOLE_OFFSET_X, CAMERA_LENS_CENTER_Z + CAMERA_HOLE_OFFSET_Z),
    (CAMERA_LENS_CENTER_X + CAMERA_HOLE_OFFSET_X, CAMERA_LENS_CENTER_Z + CAMERA_HOLE_OFFSET_Z),
)


def build_base() -> Mesh:
    mesh = Mesh()

    mesh.add_panel_xy_with_holes(0, 0, 0, OUTER_W, OUTER_D, BOTTOM, list(BOTTOM_VENTS))
    mesh.add_panel_yz_with_holes(
        0,
        WALL,
        0,
        OUTER_D - WALL,
        OUTER_H,
        WALL,
        list(SIDE_VENTS),
    )
    mesh.add_panel_yz_with_holes(
        OUTER_W - WALL,
        WALL,
        0,
        OUTER_D - WALL,
        OUTER_H,
        WALL,
        [USB_C_POWER_ENTRY],
    )
    mesh.add_box(0, OUTER_D - WALL, 0, OUTER_W, WALL, OUTER_H)
    mesh.add_panel_xz_with_holes(
        0,
        0,
        0,
        OUTER_W,
        OUTER_H,
        WALL,
        [SCANNER_WINDOW, CAMERA_WINDOW],
    )

    add_lid_posts(mesh)
    add_pi_standoffs(mesh)
    add_scanner_cradle(mesh)
    add_camera_cradle(mesh)
    add_usb_c_strain_relief(mesh)
    add_wall_mount_flange(mesh)
    add_front_frames(mesh)
    return mesh


def add_lid_posts(mesh: Mesh) -> None:
    for cx, cy in (
        (10, 10),
        (OUTER_W - 10, 10),
        (10, OUTER_D - 10),
        (OUTER_W - 10, OUTER_D - 10),
    ):
        add_m2_standoff_z(mesh, cx, cy, BOTTOM, OUTER_H - BOTTOM - 2, outer=10.0)


def add_pi_standoffs(mesh: Mesh) -> None:
    hole_points = (
        (PI_X + PI_HOLE_OFFSET, PI_Y + PI_HOLE_OFFSET),
        (PI_X + PI_HOLE_OFFSET + PI_HOLE_SPAN_X, PI_Y + PI_HOLE_OFFSET),
        (PI_X + PI_HOLE_OFFSET, PI_Y + PI_HOLE_OFFSET + PI_HOLE_SPAN_Y),
        (PI_X + PI_HOLE_OFFSET + PI_HOLE_SPAN_X, PI_Y + PI_HOLE_OFFSET + PI_HOLE_SPAN_Y),
    )
    for cx, cy in hole_points:
        add_m2_standoff_z(mesh, cx, cy, BOTTOM, 8.0, outer=8.0)

    # Low keep-out outline for the Pi board footprint.
    mesh.add_box(PI_X, PI_Y, BOTTOM, PI_W, 1.2, 2.0)
    mesh.add_box(PI_X, PI_Y + PI_D - 1.2, BOTTOM, PI_W, 1.2, 2.0)
    mesh.add_box(PI_X, PI_Y, BOTTOM, 1.2, PI_D, 2.0)
    mesh.add_box(PI_X + PI_W - 1.2, PI_Y, BOTTOM, 1.2, PI_D, 2.0)


def add_scanner_cradle(mesh: Mesh) -> None:
    # The SEN-18088 scans out through the short optical end of the breakout.
    # The PCB is rotated in the bottom so that short end faces the front
    # window; the long body extends back into the enclosure.
    for cx, cy in SCANNER_MOUNT_HOLES:
        add_m2_standoff_z(mesh, cx, cy, BOTTOM, SCANNER_BOARD_Z - BOTTOM, outer=8.0)

    side_stop_d = 20.0
    mesh.add_box(
        SCANNER_BOARD_X - 3,
        SCANNER_BOARD_Y - 3,
        BOTTOM,
        SCANNER_BOARD_W + 6,
        3,
        3,
    )
    mesh.add_box(
        SCANNER_BOARD_X - 3,
        SCANNER_BOARD_Y - 3,
        BOTTOM,
        3,
        side_stop_d,
        3,
    )
    mesh.add_box(
        SCANNER_BOARD_X + SCANNER_BOARD_W,
        SCANNER_BOARD_Y - 3,
        BOTTOM,
        3,
        side_stop_d,
        3,
    )


def add_camera_cradle(mesh: Mesh) -> None:
    # Camera Module 3 board can be installed normal or rotated 90 degrees. Both
    # patterns share the same lens center, which is useful when the enclosure is
    # mounted upright at the wrapping machine.
    mesh.add_box(
        CAMERA_MOUNT_OUTLINE_X,
        WALL,
        CAMERA_MOUNT_OUTLINE_Z,
        CAMERA_MOUNT_OUTLINE_SIZE,
        8,
        3,
    )
    mesh.add_box(
        CAMERA_MOUNT_OUTLINE_X,
        WALL,
        CAMERA_MOUNT_OUTLINE_Z + CAMERA_MOUNT_OUTLINE_SIZE - 3,
        CAMERA_MOUNT_OUTLINE_SIZE,
        8,
        3,
    )
    for cx, cz in CAMERA_MOUNT_HOLES:
        add_m2_mount_y(mesh, cx, WALL, cz, d=13.0, outer=7.0)


def add_usb_c_strain_relief(mesh: Mesh) -> None:
    # Power enters through the right-side USB-C slot. These paired posts are for
    # a small zip tie around the cable jacket inside the enclosure.
    mesh.add_box(139, 68, BOTTOM, 5, 8, 8)
    mesh.add_box(139, 84, BOTTOM, 5, 8, 8)
    mesh.add_box(153, 68, BOTTOM, 5, 8, 8)
    mesh.add_box(153, 84, BOTTOM, 5, 8, 8)
    mesh.add_box(144, 70, 11, 9, 4, 3)
    mesh.add_box(144, 86, 11, 9, 4, 3)


def add_wall_mount_flange(mesh: Mesh) -> None:
    # External back flange, intended for drilling or using washers through the rectangular slots.
    mesh.add_box(18, OUTER_D, 12, 134, 4, 8)
    mesh.add_box(18, OUTER_D, 38, 134, 4, 8)
    mesh.add_box(18, OUTER_D, 12, 8, 4, 34)
    mesh.add_box(144, OUTER_D, 12, 8, 4, 34)


def add_front_frames(mesh: Mesh) -> None:
    # Raised front lips protect the optical openings and make the unit read less like a prototype.
    mesh.add_box(12, -2, 8, 66, 2, 4)
    mesh.add_box(12, -2, 48, 66, 2, 4)
    mesh.add_box(12, -2, 8, 4, 2, 44)
    mesh.add_box(74, -2, 8, 4, 2, 44)

    mesh.add_box(102, -2, 16, 34, 2, 4)
    mesh.add_box(102, -2, 46, 34, 2, 4)
    mesh.add_box(102, -2, 16, 4, 2, 34)
    mesh.add_box(132, -2, 16, 4, 2, 34)


def build_lid() -> Mesh:
    mesh = Mesh()
    holes = [
        Rect(8.6, 7.5, 2.8, 6.0),
        Rect(OUTER_W - 11.4, 7.5, 2.8, 6.0),
        Rect(8.6, OUTER_D - 13.5, 2.8, 6.0),
        Rect(OUTER_W - 11.4, OUTER_D - 13.5, 2.8, 6.0),
    ]
    for index in range(7):
        holes.append(Rect(52, 18 + index * 7, 72, 3.0))
    for index in range(5):
        holes.append(Rect(128, 22 + index * 9, 24, 3.0))

    mesh.add_panel_xy_with_holes(0, 0, 0, OUTER_W, OUTER_D, 3.0, holes)
    mesh.add_box(6, 6, -4, OUTER_W - 12, 2, 4)
    mesh.add_box(6, OUTER_D - 8, -4, OUTER_W - 12, 2, 4)
    mesh.add_box(6, 8, -4, 2, OUTER_D - 16, 4)
    mesh.add_box(OUTER_W - 8, 8, -4, 2, OUTER_D - 16, 4)
    return mesh


def build_mount_plate() -> Mesh:
    mesh = Mesh()
    holes = [
        Rect(16, 14, 8, 18),
        Rect(116, 14, 8, 18),
        Rect(16, 58, 8, 18),
        Rect(116, 58, 8, 18),
        Rect(44, 42, 52, 8),
    ]
    mesh.add_panel_xy_with_holes(0, 0, 0, 140, 90, 5, holes)
    mesh.add_box(5, 5, 5, 130, 4, 4)
    mesh.add_box(5, 81, 5, 130, 4, 4)
    mesh.add_box(5, 9, 5, 4, 72, 4)
    mesh.add_box(131, 9, 5, 4, 72, 4)
    return mesh


def add_m2_standoff_z(mesh: Mesh, cx: MM, cy: MM, z: MM, h: MM, outer: MM) -> None:
    nut_height = min(M2_NUT_DEPTH, h)
    if h > nut_height:
        mesh.add_square_tube_z(cx, cy, z, outer=outer, inner=M2_NUT_POCKET, h=nut_height)
        mesh.add_square_tube_z(
            cx,
            cy,
            z + nut_height,
            outer=outer,
            inner=M2_CLEARANCE,
            h=h - nut_height,
        )
    else:
        mesh.add_square_tube_z(cx, cy, z, outer=outer, inner=M2_CLEARANCE, h=h)


def add_m2_mount_y(mesh: Mesh, cx: MM, y: MM, cz: MM, d: MM, outer: MM) -> None:
    nut_depth = min(M2_NUT_DEPTH, d)
    screw_depth = max(0.0, d - nut_depth)
    if screw_depth > 0:
        mesh.add_square_tube_y(cx, y, cz, outer=outer, inner=M2_CLEARANCE, d=screw_depth)
    mesh.add_square_tube_y(
        cx,
        y + screw_depth,
        cz,
        outer=outer,
        inner=M2_NUT_POCKET,
        d=nut_depth,
    )


def _split_axis(start: MM, end: MM, blocked_ranges: list[tuple[MM, MM]]) -> list[MM]:
    points = {start, end}
    for block_start, block_end in blocked_ranges:
        points.add(max(start, min(end, block_start)))
        points.add(max(start, min(end, block_end)))
    return sorted(points)


def _normal(
    a: tuple[float, float, float],
    b: tuple[float, float, float],
    c: tuple[float, float, float],
) -> tuple[float, float, float]:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = sqrt(nx * nx + ny * ny + nz * nz)
    if length == 0:
        return 0.0, 0.0, 0.0
    return nx / length, ny / length, nz / length


def main() -> None:
    cad_dir = Path(__file__).resolve().parent
    output_dir = cad_dir / "stl"
    output_dir.mkdir(parents=True, exist_ok=True)

    base = build_base()
    lid = build_lid()
    mount = build_mount_plate()

    base.write_stl(output_dir / "palletproof_enclosure_base.stl", "palletproof_enclosure_base")
    lid.write_stl(output_dir / "palletproof_enclosure_lid.stl", "palletproof_enclosure_lid")
    mount.write_stl(output_dir / "palletproof_wall_mount_plate.stl", "palletproof_wall_mount_plate")

    preview = Mesh()
    preview.extend(base)
    preview.extend(lid)
    preview.extend(mount)
    preview.write_stl(output_dir / "palletproof_enclosure_assembly_preview.stl", "palletproof_enclosure_assembly_preview")

    print(f"Wrote STL files to {output_dir}")


if __name__ == "__main__":
    main()

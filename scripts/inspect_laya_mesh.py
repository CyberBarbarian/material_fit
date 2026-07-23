"""Read vertex and index counts from LAYAMODEL 05-family ``.lm`` files."""

from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path


class Reader:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.pos = 0

    def u16(self) -> int:
        value = struct.unpack_from("<H", self.payload, self.pos)[0]
        self.pos += 2
        return int(value)

    def i16(self) -> int:
        value = struct.unpack_from("<h", self.payload, self.pos)[0]
        self.pos += 2
        return int(value)

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.payload, self.pos)[0]
        self.pos += 4
        return int(value)

    def utf(self) -> str:
        size = self.u16()
        value = self.payload[self.pos : self.pos + size].decode("utf-8")
        self.pos += size
        return value


def inspect(path: Path) -> dict[str, object]:
    reader = Reader(path.read_bytes())
    version = reader.utf()
    if version not in {
        "LAYAMODEL:05",
        "LAYAMODEL:0501",
        "LAYAMODEL:0502",
        "LAYAMODEL:COMPRESSION_05",
        "LAYAMODEL:COMPRESSION_0501",
    }:
        raise ValueError(f"unsupported model version {version}: {path}")
    data_offset = reader.u32()
    reader.u32()  # data size
    block_count = reader.u16()
    block_starts: list[int] = []
    for _ in range(block_count):
        block_starts.append(reader.u32())
        reader.u32()  # block length
    strings_offset = reader.u32()
    string_count = reader.u16()
    saved_pos = reader.pos
    reader.pos = data_offset + strings_offset
    strings = [reader.utf() for _ in range(string_count)]
    reader.pos = saved_pos

    for block_start in block_starts:
        reader.pos = block_start
        block_name = strings[reader.u16()]
        if block_name != "MESH":
            continue
        mesh_name = strings[reader.u16()]
        vertex_buffer_count = reader.i16()
        vertex_counts: list[int] = []
        vertex_flags: list[str] = []
        for _ in range(vertex_buffer_count):
            reader.u32()  # vertex-buffer data offset
            vertex_counts.append(reader.u32())
            vertex_flags.append(strings[reader.u16()])
        reader.u32()  # index-buffer data offset
        index_byte_length = reader.u32()
        vertex_count = sum(vertex_counts)
        index_stride = 4 if vertex_count > 65535 else 2
        index_count = index_byte_length // index_stride
        return {
            "path": str(path.resolve()),
            "version": version,
            "mesh_name": mesh_name,
            "vertex_count": vertex_count,
            "index_count": index_count,
            "triangle_count": index_count // 3,
            "vertex_flags": vertex_flags,
        }
    raise ValueError(f"no MESH block found: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--unity-metadata", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows: list[dict[str, object]] = []
    for raw_path in args.paths:
        paths = sorted(raw_path.glob("*.lm")) if raw_path.is_dir() else [raw_path]
        rows.extend(inspect(path) for path in paths)
    laya_vertices = sum(int(row["vertex_count"]) for row in rows)
    laya_triangles = sum(int(row["triangle_count"]) for row in rows)
    payload: dict[str, object] = {
        "contract": "material_fit_laya_mesh_geometry_audit_v1",
        "laya": {
            "mesh_count": len(rows),
            "total_vertex_count": laya_vertices,
            "total_triangle_count": laya_triangles,
            "meshes": rows,
        },
    }
    if args.unity_metadata:
        metadata_path = args.unity_metadata.resolve()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        geometry = metadata.get("modelGeometry", {})
        unity_vertices = int(geometry.get("totalVertexCount") or 0)
        unity_triangles = int(geometry.get("totalTriangleCount") or 0)
        payload["unity"] = {
            "metadata_path": str(metadata_path),
            "total_vertex_count": unity_vertices,
            "total_triangle_count": unity_triangles,
        }
        payload["comparison"] = {
            "same_geometry_counts": (
                laya_vertices == unity_vertices and laya_triangles == unity_triangles
            ),
            "laya_to_unity_vertex_ratio": (
                laya_vertices / unity_vertices if unity_vertices else None
            ),
            "laya_to_unity_triangle_ratio": (
                laya_triangles / unity_triangles if unity_triangles else None
            ),
        }
    rendered = json.dumps(payload, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

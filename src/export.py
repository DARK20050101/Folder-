"""Export functionality for DiskExplorer scan results."""

from __future__ import annotations

import csv
import io
import json
import os
import time
from pathlib import Path
from typing import List, Optional

from .models import FileNode, format_size


class ExportHandler:
    """Exports scan results to various formats (HTML, CSV, JSON)."""

    # ------------------------------------------------------------------
    # CSV
    # ------------------------------------------------------------------

    def export_csv(self, node: FileNode, output_path: str, max_depth: int = 3) -> None:
        """Export the directory tree to a CSV file.

        Columns: Path, Name, Type, Size (Bytes), Size (Human), Modified Time, File Count
        """
        rows = self._collect_rows(node, 0, max_depth)
        with open(output_path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["path", "name", "type", "size_bytes", "size_human",
                             "mod_time", "file_count"],
            )
            writer.writeheader()
            writer.writerows(rows)

    def export_csv_string(self, node: FileNode, max_depth: int = 3) -> str:
        """Return a CSV-formatted string of the directory tree."""
        rows = self._collect_rows(node, 0, max_depth)
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=["path", "name", "type", "size_bytes", "size_human",
                        "mod_time", "file_count"],
        )
        writer.writeheader()
        writer.writerows(rows)
        return buf.getvalue()

    # ------------------------------------------------------------------
    # JSON
    # ------------------------------------------------------------------

    def export_json(self, node: FileNode, output_path: str, max_depth: int = 5) -> None:
        """Export the directory tree to a JSON file."""
        data = self._node_to_dict(node, 0, max_depth)
        with open(output_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    def export_json_string(self, node: FileNode, max_depth: int = 5) -> str:
        """Return a JSON-formatted string of the directory tree."""
        data = self._node_to_dict(node, 0, max_depth)
        return json.dumps(data, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------
    # HTML
    # ------------------------------------------------------------------

    def export_html(self, node: FileNode, output_path: str, max_depth: int = 3) -> None:
        """Export a standalone HTML report of the directory tree."""
        html = self._build_html(node, max_depth)
        with open(output_path, "w", encoding="utf-8") as fh:
            fh.write(html)

    def export_html_string(self, node: FileNode, max_depth: int = 3) -> str:
        """Return an HTML-formatted report of the directory tree."""
        return self._build_html(node, max_depth)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _collect_rows(
        self, node: FileNode, depth: int, max_depth: int
    ) -> List[dict]:
        rows = []
        row = {
            "path": node.path,
            "name": node.name,
            "type": "directory" if node.is_dir else "file",
            "size_bytes": node.size,
            "size_human": node.formatted_size,
            "mod_time": time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(node.mod_time)) if node.mod_time else "",
            "file_count": node.file_count,
        }
        rows.append(row)
        if node.is_dir and depth < max_depth:
            for child in node.get_children_sorted("size"):
                rows.extend(self._collect_rows(child, depth + 1, max_depth))
        return rows

    def _node_to_dict(self, node: FileNode, depth: int, max_depth: int) -> dict:
        d = {
            "name": node.name,
            "path": node.path,
            "type": "directory" if node.is_dir else "file",
            "size_bytes": node.size,
            "size_human": node.formatted_size,
            "mod_time": node.mod_time,
            "file_count": node.file_count,
        }
        if node.is_dir and depth < max_depth:
            d["children"] = [
                self._node_to_dict(child, depth + 1, max_depth)
                for child in node.get_children_sorted("size")
            ]
        return d

    def _build_html(self, node: FileNode, max_depth: int) -> str:
        rows_html = self._build_html_rows(node, 0, max_depth)
        report_time = time.strftime("%Y-%m-%d %H:%M:%S")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DiskExplorer Report – {node.path}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; color: #333; }}
  h1 {{ color: #2c5282; }}
  .meta {{ color: #666; font-size: 0.9em; margin-bottom: 20px; }}
  table {{ border-collapse: collapse; width: 100%; background: white;
           box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  th {{ background: #2c5282; color: white; padding: 10px 12px; text-align: left; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #eef2ff; }}
  .dir {{ font-weight: bold; }}
  .bar-container {{ background: #e2e8f0; border-radius: 4px; height: 12px;
                    min-width: 60px; display: inline-block; vertical-align: middle; }}
  .bar {{ background: #4299e1; border-radius: 4px; height: 12px; }}
  .indent {{ display: inline-block; }}
</style>
</head>
<body>
<h1>DiskExplorer Report</h1>
<div class="meta">
  Path: <strong>{node.path}</strong> &nbsp;|&nbsp;
  Total Size: <strong>{node.formatted_size}</strong> &nbsp;|&nbsp;
  Generated: {report_time}
</div>
<table>
  <thead>
    <tr>
      <th>Name</th>
      <th>Size</th>
      <th>Usage</th>
      <th>Type</th>
      <th>Modified</th>
      <th>Files</th>
    </tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
</body>
</html>"""

    def _build_html_rows(self, node: FileNode, depth: int, max_depth: int) -> str:
        indent_px = depth * 20
        name_class = "dir" if node.is_dir else ""
        mod_time_str = (
            time.strftime("%Y-%m-%d %H:%M", time.localtime(node.mod_time))
            if node.mod_time
            else ""
        )
        node_type = "Directory" if node.is_dir else (node.extension or "File")

        # Size bar (percentage of root size, root=100%)
        root_size = self._get_root_size(node)
        pct = (node.size / root_size * 100) if root_size > 0 else 0
        bar_width = min(pct, 100)

        rows = (
            f'    <tr>\n'
            f'      <td><span class="indent" style="padding-left:{indent_px}px"></span>'
            f'<span class="{name_class}">{node.name}</span></td>\n'
            f'      <td>{node.formatted_size}</td>\n'
            f'      <td><div class="bar-container"><div class="bar" '
            f'style="width:{bar_width:.1f}%"></div></div> {pct:.1f}%</td>\n'
            f'      <td>{node_type}</td>\n'
            f'      <td>{mod_time_str}</td>\n'
            f'      <td>{node.file_count}</td>\n'
            f'    </tr>\n'
        )

        if node.is_dir and depth < max_depth:
            for child in node.get_children_sorted("size"):
                rows += self._build_html_rows(child, depth + 1, max_depth)

        return rows

    @staticmethod
    def _get_root_size(node: FileNode) -> int:
        """Return the node's own size (used as 100% baseline for bar widths)."""
        return node.size if node.size > 0 else 1

# DiskExplorer – Disk Space Analysis Tool

A lightweight, high-performance local disk space analyser that visualises disk
usage in a hierarchical tree view, helping you quickly identify and manage
storage space.

## Features

- **Tree-based directory view** – hierarchical display of folders and files
  with sizes, percentages, modification times and file counts
- **Pie & bar charts** – visual size distribution for any selected directory
- **Fast multi-threaded scanning** – uses a thread pool for large directories
- **Result caching** – persists scan results so re-opening is instant
- **Export reports** – CSV, JSON and standalone HTML output
- **Right-click context menu** – open in file manager, copy path
- **Zero cloud dependency** – all data stays on your machine

## Requirements

| Component | Minimum |
|-----------|---------|
| Python    | 3.9+    |
| PyQt6     | 6.4.0+  |
| psutil    | 5.9.0+  |
| OS        | Windows 10 / macOS 10.15 / Linux |

## Quick Start

```bash
# 1. Clone the repo
git clone https://github.com/DARK20050101/Folder.git
cd Folder

# 2. Create and activate a virtual environment
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Launch the application
python main.py
```

## Project Structure

```
DiskExplorer/
├── main.py              # Application entry point
├── requirements.txt     # Runtime dependencies
├── setup.py             # Packaging configuration
├── src/
│   ├── models.py        # FileNode & DiskDataModel data structures
│   ├── scanner.py       # FileSystemScanner (multi-threaded)
│   ├── cache.py         # ScanCache (pickle serialisation)
│   ├── export.py        # ExportHandler (CSV / JSON / HTML)
│   └── ui/
│       ├── main_window.py   # MainWindow (PyQt6)
│       ├── tree_view.py     # FileSystemTreeView & FileNodeModel
│       └── chart_widget.py  # PieChartWidget, BarChartWidget, SizeChartWidget
└── tests/
    ├── test_models.py
    ├── test_scanner.py
    ├── test_cache.py
    └── test_export.py
```

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

## Packaging (Windows)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name DiskExplorer main.py
```

The resulting `dist/DiskExplorer.exe` is a standalone portable executable.

## Architecture

```
┌─────────────────────────────────┐
│  UI Layer (PyQt6)               │
│  MainWindow → TreeView + Charts │
├─────────────────────────────────┤
│  Logic Layer                    │
│  ScanManager · CacheManager     │
│  ExportHandler                  │
├─────────────────────────────────┤
│  Data Layer                     │
│  FileSystemScanner (psutil/os)  │
│  FileNode · DiskDataModel       │
└─────────────────────────────────┘
```

## Roadmap

| Version | Planned Features |
|---------|-----------------|
| V1.1 | Duplicate file detection, network drive support, multi-language |
| V2.0 | Real-time monitoring, advanced search, batch operations |
| V3.0 | Multi-machine management, scheduled reports, API |

## License

MIT

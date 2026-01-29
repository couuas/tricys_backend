# Tricys Backend

Tricys Backend is a high-performance RESTful API service designed to manage and execute Tritium Integrated Cycle Simulations (Tricys). It provides a robust infrastructure for task scheduling, real-time monitoring, and advanced data retrieval.

## 🚀 Key Features

- **Task Lifecycle Management**: Asynchronous task submission, scheduling (FIFO queue), and execution tracking.
- **Real-time Observability**: Live log streaming and progress updates via WebSockets.
- **Advanced Data Services**: High-performance HDF5 data slicing and querying for multi-job simulations.
- **Robustness & Engineering**: Built-in crash recovery, automatic workspace cleanup, and archive management.
- **Spec-Compliant API**: Fully documented RESTful endpoints for seamless frontend integration.

## 🛠 Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Asynchronous, High Performance)
- **Database**: [SQLModel](https://sqlmodel.tiangolo.com/) (SQLite) for metadata persistence.
- **Scheduling**: Internal `asyncio.Queue` for lightweight task orchestration.
- **Engine**: Integrates directly with the `tricys` CLI core.

## 📥 Installation

```bash
# Clone the repository 
git clone https://github.com/asipp-neutronics/tricys_backend.git

# Install dependencies
pip install -r requirements.txt
```

## 🚥 Quick Start

1. **Start the Server**:
   ```bash
   python main.py
   # OR
   uvicorn tricys_backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Access API Documentation**:
   Visit `http://localhost:8000/docs` for the interactive Swagger UI.

3. **Check Health**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

## 📂 Project Structure

- `api/`: API route definitions and logic.
- `core/`: Global configurations and system events.
- `models/`: Database schemas and data validation models.
- `services/`: Core business logic (Engine, Queue, File Manager, HDF5 Reader).
- `utils/`: Common utilities (WebSocket manager, logical loggers).

---

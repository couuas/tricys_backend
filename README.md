# TRICYS Backend

> **High-performance RESTful API service for managing Tritium Integrated Cycle Simulations (TRICYS)**

TRICYS Backend provides a robust, asynchronous infrastructure for task scheduling, real-time monitoring, and advanced data retrieval, serving as the bridge between the TRICYS core simulation engine and the visual frontend.

## Key Features

- ** Task Lifecycle Management**: Full support for asynchronous task submission, intelligent scheduling (FIFO queues), and execution state tracking.
- ** Real-time Observability**: Live log streaming and simulation progress updates pushed directly to the frontend via WebSockets.
- ** Advanced Data Services**: High-performance HDF5 data slicing and querying endpoints designed for multi-job parameter sweep simulations.
- ** Robustness & Engineering**: Built-in crash recovery mechanisms, automatic workspace cleanup, and secure result archiving.
- ** Spec-Compliant API**: Fully documented, OpenAPI-compliant RESTful endpoints for seamless integration.

## Tech Stack

- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (Asynchronous, High-Performance)
- **Database**: [SQLModel](https://sqlmodel.tiangolo.com/) (SQLite) for lightweight metadata persistence.
- **Task Scheduling**: Internal `asyncio.Queue` for lightweight and efficient task orchestration.
- **Simulation Core**: Integrates directly with the `tricys` CLI engine.

## Installation

```bash
# Clone the repository 
git clone https://github.com/asipp-neutronics/tricys.git
cd tricys/tricys_backend

# Install dependencies
pip install -r requirements.txt
```

## Quick Start

1. **Start the Server**:
   ```bash
   python main.py
   # OR run directly via uvicorn
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

2. **Access API Documentation**:
   Navigate to `http://localhost:8000/docs` in your browser to interact with the Swagger UI.

3. **Check Service Health**:
   ```bash
   curl http://localhost:8000/api/v1/health
   ```

## Project Architecture

- `api/`: RESTful API route definitions and endpoint logic.
- `core/`: Global configurations, lifecycle events, and security settings.
- `models/`: Database schemas and Pydantic data validation models.
- `services/`: Core business logic (Engine Management, Queue Dispatcher, File Manager, HDF5 Reader).
- `utils/`: Common utilities (WebSocket Connection Manager, specialized context loggers).

## License

This project is licensed under the [APACHE 2.0](LICENSE) License.

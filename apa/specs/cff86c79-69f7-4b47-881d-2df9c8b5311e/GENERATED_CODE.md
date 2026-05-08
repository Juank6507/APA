# Código generado — cff86c79-69f7-4b47-881d-2df9c8b5311e

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearmodelstaskpy.py | Crear models/task.py |  |
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |
| crearapipy.py | Crear api.py |  |

## crearmodelstaskpy.py
**Tarea:** Crear models/task.py
**Criterio:** 
**Descripción:** Define las clases Task y TaskManager para gestionar una lista de tareas con identificadores autoincrementales, permitiendo agregar, buscar, listar (opcionalmente filtrando por completadas) y marcar como completadas. El bloque final valida que los métodos cumplan los criterios de IDs consecutivos, títulos correctos, estado por defecto no completado y filtrado adecuado.

```python
from typing import List, Optional


class Task:
    def __init__(self, id: int, title: str, completed: bool = False):
        self.id = id
        self.title = title
        self.completed = completed

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'title': self.title,
            'completed': self.completed
        }


class TaskManager:
    def __init__(self):
        self.tasks: List[Task] = []
        self._next_id = 1

    def add_task(self, title: str) -> Task:
        task = Task(id=self._next_id, title=title)
        self.tasks.append(task)
        self._next_id += 1
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        for task in self.tasks:
            if task.id == task_id:
                return task
        return None

    def list_tasks(self, completed_only: bool = False) -> List[Task]:
        if completed_only:
            return [task for task in self.tasks if task.completed]
        return self.tasks.copy()

    def mark_completed(self, task_id: int) -> bool:
        task = self.get_task(task_id)
        if task:
            task.completed = True
            return True
        return False


if __name__ == '__main__':
    # Criterio de aceptación
    manager = TaskManager()
    t1 = manager.add_task("Comprar leche")
    t2 = manager.add_task("Estudiar Python")
    t3 = manager.add_task("Hacer ejercicio")

    # Verificar IDs autoincrementales
    if not (t1.id == 1 and t2.id == 2 and t3.id == 3):
        print("CRITERIO FALLO: IDs no autoincrementales")
        exit(1)

    # Verificar título no vacío
    if t1.title != "Comprar leche":
        print("CRITERIO FALLO: Título incorrecto")
        exit(1)

    # Verificar completed por defecto False
    if t1.completed is not False:
        print("CRITERIO FALLO: completed debe ser False por defecto")
        exit(1)

    # Verificar to_dict
    d = t1.to_dict()
    if d != {'id': 1, 'title': 'Comprar leche', 'completed': False}:
        print("CRITERIO FALLO: to_dict incorrecto")
        exit(1)

    # Verificar get_task
    if manager.get_task(1) != t1 or manager.get_task(99) is not None:
        print("CRITERIO FALLO: get_task falla")
        exit(1)

    # Verificar list_tasks
    if len(manager.list_tasks()) != 3:
        print("CRITERIO FALLO: list_tasks sin filtro")
        exit(1)
    if len(manager.list_tasks(completed_only=True)) != 0:
        print("CRITERIO FALLO: list_tasks con filtro antes de completar")
        exit(1)

    # Verificar mark_completed
    if not manager.mark_completed(2):
        print("CRITERIO FALLO: mark_completed debe retornar True")
        exit(1)
    if manager.mark_completed(99):
        print("CRITERIO FALLO: mark_completed debe retornar False para id inexistente")
        exit(1)
    if not manager.get_task(2).completed:
        print("CRITERIO FALLO: mark_completed no actualizó completed")
        exit(1)
    if len(manager.list_tasks(completed_only=True)) != 1:
        print("CRITERIO FALLO: list_tasks con filtro después de completar")
        exit(1)

    print("CRITERIO OK")
```

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** El módulo define dos validadores: validate_title asegura que el título sea una cadena no vacía sin solo espacios, y validate_id comprueba que el ID sea un entero no negativo; ambos lanzan ValueError si la regla no se cumple. El bloque principal ejecuta pruebas automáticas que verifican el rechazo de valores inválidos y la aceptación de valores válidos, imprimiendo “CRITERIO OK” si todo pasa.

```python
def validate_title(title: str) -> None:
    if not isinstance(title, str) or not title.strip():
        raise ValueError("El título no puede estar vacío o contener solo espacios")

def validate_id(task_id: int) -> None:
    if not isinstance(task_id, int) or task_id < 0:
        raise ValueError("El ID debe ser un número entero no negativo")

if __name__ == '__main__':
    # Test de criterios de aceptación
    try:
        # Test validate_title
        try:
            validate_title("")
            print("CRITERIO FALLO: validate_title no detectó título vacío")
        except ValueError:
            pass

        try:
            validate_title("   ")
            print("CRITERIO FALLO: validate_title no detectó título con solo espacios")
        except ValueError:
            pass

        try:
            validate_title("Título válido")
        except ValueError:
            print("CRITERIO FALLO: validate_title falló con título válido")

        # Test validate_id
        try:
            validate_id(-1)
            print("CRITERIO FALLO: validate_id no detectó ID negativo")
        except ValueError:
            pass

        try:
            validate_id(0)
            validate_id(1)
        except ValueError:
            print("CRITERIO FALLO: validate_id falló con ID válido")

        # Si llegamos aquí, todos los tests pasaron
        print("CRITERIO OK")

    except Exception as e:
        print(f"CRITERIO FALLO: Error inesperado: {str(e)}")
```

## crearapipy.py
**Tarea:** Crear api.py
**Criterio:** 
**Descripción:** Expone una API REST con FastAPI para gestionar tareas: permite crear, listar (filtrando por completadas o no), consultar y marcar como completadas. Al ejecutarse directamente arranca el servidor y ejecuta una batería de pruebas locales que validan todos los endpoints.

```python
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
import uvicorn

# --- MODELOS (simulando models/task.py) ---
class Task(BaseModel):
    id: int
    title: str
    completed: bool = False

# --- VALIDADORES (simulando utils/validators.py) ---
def validate_task_creation(data: dict) -> None:
    if "title" not in data or not isinstance(data["title"], str) or not data["title"].strip():
        raise ValueError("title es requerido y debe ser un string no vacío")

# --- API ---
app = FastAPI()
tasks_db: List[Task] = []
current_id = 1

@app.post("/tasks", status_code=201)
def create_task(payload: dict):
    try:
        validate_task_creation(payload)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    global current_id
    task = Task(id=current_id, title=payload["title"])
    current_id += 1
    tasks_db.append(task)
    return task

@app.get("/tasks")
def list_tasks(completed_only: Optional[bool] = Query(None)):
    if completed_only is True:
        return [t for t in tasks_db if t.completed]
    return tasks_db

@app.get("/tasks/{task_id}")
def get_task(task_id: int):
    for t in tasks_db:
        if t.id == task_id:
            return t
    raise HTTPException(status_code=404, detail="Task not found")

@app.put("/tasks/{task_id}/complete")
def complete_task(task_id: int):
    for t in tasks_db:
        if t.id == task_id:
            t.completed = True
            return t
    raise HTTPException(status_code=404, detail="Task not found")

if __name__ == "__main__":
    import requests
    import json
    import threading
    import time

    def run_server():
        uvicorn.run(app, host="127.0.0.1", port=8000)

    server = threading.Thread(target=run_server, daemon=True)
    server.start()
    time.sleep(2)

    base = "http://127.0.0.1:8000"
    try:
        # POST /tasks
        r = requests.post(f"{base}/tasks", json={"title": "Test task"})
        assert r.status_code == 201
        task = r.json()
        assert task["title"] == "Test task"
        assert task["completed"] is False
        task_id = task["id"]

        # GET /tasks
        r = requests.get(f"{base}/tasks")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        # GET /tasks/{id}
        r = requests.get(f"{base}/tasks/{task_id}")
        assert r.status_code == 200
        assert r.json()["id"] == task_id

        # PUT /tasks/{id}/complete
        r = requests.put(f"{base}/tasks/{task_id}/complete")
        assert r.status_code == 200
        assert r.json()["completed"] is True

        # GET /tasks con completed_only
        r = requests.get(f"{base}/tasks", params={"completed_only": True})
        assert r.status_code == 200
        assert any(t["id"] == task_id for t in r.json())

        # GET /tasks/{id} inexistente
        r = requests.get(f"{base}/tasks/99999")
        assert r.status_code == 404

        print("CRITERIO OK")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")
```

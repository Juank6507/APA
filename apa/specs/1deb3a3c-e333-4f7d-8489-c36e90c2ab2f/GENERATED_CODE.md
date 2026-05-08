# Código generado — 1deb3a3c-e333-4f7d-8489-c36e90c2ab2f

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearmodelstaskpy.py | Crear models/task.py |  |
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |
| crearapipy.py | Crear api.py |  |

## crearmodelstaskpy.py
**Tarea:** Crear models/task.py
**Criterio:** 
**Descripción:** Define las clases Task y TaskManager para gestionar una lista de tareas con identificadores únicos, permitiendo añadir, consultar, filtrar por estado y marcar como completadas. Incluye un script de prueba que valida todas las operaciones básicas.

```python
from typing import Optional, List


class Task:
    _next_id = 1

    def __init__(self, title: str, completed: bool = False):
        if not title:
            raise ValueError("title must be non-empty")
        self.id: int = Task._next_id
        Task._next_id += 1
        self.title: str = title
        self.completed: bool = completed

    def to_dict(self) -> dict:
        return {"id": self.id, "title": self.title, "completed": self.completed}


class TaskManager:
    def __init__(self):
        self._tasks: List[Task] = []

    def add_task(self, title: str) -> Task:
        task = Task(title)
        self._tasks.append(task)
        return task

    def get_task(self, task_id: int) -> Optional[Task]:
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None

    def list_tasks(self, completed_only: bool = False) -> List[Task]:
        if completed_only:
            return [t for t in self._tasks if t.completed]
        return self._tasks.copy()

    def mark_completed(self, task_id: int) -> bool:
        task = self.get_task(task_id)
        if task:
            task.completed = True
            return True
        return False


if __name__ == "__main__":
    try:
        tm = TaskManager()
        # add tasks
        t1 = tm.add_task("Primera tarea")
        t2 = tm.add_task("Segunda tarea")
        # check ids
        assert t1.id == 1 and t2.id == 2, "IDs incorrectos"
        # get_task
        assert tm.get_task(1) is t1, "get_task falló"
        assert tm.get_task(999) is None, "get_task debería devolver None"
        # list_tasks
        assert len(tm.list_tasks()) == 2, "list_tasks debería devolver 2 tareas"
        assert len(tm.list_tasks(completed_only=True)) == 0, "list_tasks completadas debería estar vacío"
        # mark_completed
        assert tm.mark_completed(1) is True, "mark_completed debería devolver True"
        assert t1.completed is True, "tarea no marcada como completada"
        assert tm.mark_completed(999) is False, "mark_completed debería devolver False para id inexistente"
        assert len(tm.list_tasks(completed_only=True)) == 1, "debería haber 1 tarea completada"
        # to_dict
        d = t1.to_dict()
        assert d == {"id": 1, "title": "Primera tarea", "completed": True}, "to_dict incorrecto"
        print("CRITERIO OK")
    except AssertionError as e:
        print(f"CRITERIO FALLO: {e}")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")
```

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** Define dos funciones de validación: validate_title verifica que un título no esté vacío ni compuesto solo de espacios, y validate_id asegura que un identificador no sea negativo, lanzando ValueError en caso contrario. El bloque principal ejecuta pruebas automatizadas para confirmar que ambas funciones rechazan valores inválidos y aceptan valores válidos, imprimiendo "CRITERIO OK" si todas las validaciones funcionan correctamente.

```python
import os
import sys

def validate_title(title: str) -> None:
    if not title or not title.strip():
        raise ValueError("Title cannot be empty or whitespace only")

def validate_id(task_id: int) -> None:
    if task_id < 0:
        raise ValueError("ID cannot be negative")

if __name__ == '__main__':
    try:
        validate_title("Valid Title")
        validate_title("  Valid Title  ")
        validate_title("")
    except ValueError as e:
        if str(e) != "Title cannot be empty or whitespace only":
            print("CRITERIO FALLO: validate_title no lanza ValueError esperado")
            sys.exit(1)
    else:
        print("CRITERIO FALLO: validate_title no lanza ValueError con título vacío")
        sys.exit(1)

    try:
        validate_title("   ")
    except ValueError as e:
        if str(e) != "Title cannot be empty or whitespace only":
            print("CRITERIO FALLO: validate_title no lanza ValueError esperado con espacios")
            sys.exit(1)
    else:
        print("CRITERIO FALLO: validate_title no lanza ValueError con espacios")
        sys.exit(1)

    try:
        validate_id(0)
        validate_id(5)
        validate_id(-1)
    except ValueError as e:
        if str(e) != "ID cannot be negative":
            print("CRITERIO FALLO: validate_id no lanza ValueError esperado")
            sys.exit(1)
    else:
        print("CRITERIO FALLO: validate_id no lanza ValueError con id negativo")
        sys.exit(1)

    print("CRITERIO OK")
```

## crearapipy.py
**Tarea:** Crear api.py
**Criterio:** 
**Descripción:** Expone una API REST con FastAPI para gestionar tareas: permite crear, listar (filtrando por completadas o no), consultar individualmente y marcar como completada una tarea. Incluye validación de títulos no vacíos y pruebas automatizadas que verifican todos los endpoints antes de levantar el servidor.

```python
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field
from typing import List, Optional
import uvicorn

# models/task.py
class Task(BaseModel):
    id: int
    title: str
    completed: bool = False

# utils/validators.py
def validate_task_title(title: str) -> str:
    if not title or not title.strip():
        raise ValueError("Title cannot be empty")
    return title.strip()

# api.py
app = FastAPI()
tasks_db = []
current_id = 1

class TaskCreate(BaseModel):
    title: str

@app.post("/tasks", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(task: TaskCreate):
    global current_id
    title = validate_task_title(task.title)
    new_task = Task(id=current_id, title=title)
    tasks_db.append(new_task)
    current_id += 1
    return new_task

@app.get("/tasks", response_model=List[Task])
def get_tasks(completed_only: Optional[bool] = None):
    if completed_only is True:
        return [t for t in tasks_db if t.completed]
    return tasks_db

@app.get("/tasks/{task_id}", response_model=Task)
def get_task(task_id: int):
    for t in tasks_db:
        if t.id == task_id:
            return t
    raise HTTPException(status_code=404, detail="Task not found")

@app.put("/tasks/{task_id}/complete", response_model=Task)
def complete_task(task_id: int):
    for t in tasks_db:
        if t.id == task_id:
            t.completed = True
            return t
    raise HTTPException(status_code=404, detail="Task not found")

if __name__ == "__main__":
    # Test criterio de aceptación
    from fastapi.testclient import TestClient
    client = TestClient(app)

    # POST /tasks
    r = client.post("/tasks", json={"title": "Test task"})
    assert r.status_code == 201
    data = r.json()
    assert data["title"] == "Test task"
    assert data["completed"] is False
    task_id = data["id"]

    # GET /tasks
    r = client.get("/tasks")
    assert r.status_code == 200
    assert len(r.json()) == 1

    # GET /tasks/{task_id}
    r = client.get(f"/tasks/{task_id}")
    assert r.status_code == 200
    assert r.json()["id"] == task_id

    # GET /tasks/{task_id} 404
    r = client.get("/tasks/9999")
    assert r.status_code == 404

    # PUT /tasks/{task_id}/complete
    r = client.put(f"/tasks/{task_id}/complete")
    assert r.status_code == 200
    assert r.json()["completed"] is True

    # PUT /tasks/9999/complete 404
    r = client.put("/tasks/9999/complete")
    assert r.status_code == 404

    # GET /tasks?completed_only=true
    r = client.get("/tasks?completed_only=true")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["completed"] is True

    print("CRITERIO OK")
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

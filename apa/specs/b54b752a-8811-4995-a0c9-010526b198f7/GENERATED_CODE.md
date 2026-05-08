# Código generado — b54b752a-8811-4995-a0c9-010526b198f7

## Resumen

| Archivo | Tarea | Criterio cumplido |
|---------|-------|-----------------|
| crearmodelstaskpy.py | Crear models/task.py |  |
| crearutilsvalidatorspy.py | Crear utils/validators.py |  |
| crearapipy.py | Crear api.py |  |

## crearmodelstaskpy.py
**Tarea:** Crear models/task.py
**Criterio:** 
**Descripción:** Define un gestor de tareas en memoria: permite agregar tareas, marcarlas como completadas, listarlas filtrando por estado y recuperar una tarea por su id. Incluye pruebas que validan el comportamiento esperado.

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
    try:
        manager = TaskManager()
        t1 = manager.add_task("Comprar leche")
        t2 = manager.add_task("Estudiar Python")
        assert t1.id == 1
        assert t2.id == 2
        assert t1.title == "Comprar leche"
        assert t2.title == "Estudiar Python"
        assert t1.completed is False
        assert t2.completed is False

        assert manager.get_task(1) == t1
        assert manager.get_task(2) == t2
        assert manager.get_task(99) is None

        all_tasks = manager.list_tasks()
        assert len(all_tasks) == 2
        assert t1 in all_tasks and t2 in all_tasks

        completed_tasks = manager.list_tasks(completed_only=True)
        assert len(completed_tasks) == 0

        assert manager.mark_completed(1) is True
        assert t1.completed is True
        assert manager.mark_completed(99) is False

        completed_tasks = manager.list_tasks(completed_only=True)
        assert len(completed_tasks) == 1
        assert t1 in completed_tasks

        d = t1.to_dict()
        assert d == {'id': 1, 'title': 'Comprar leche', 'completed': True}

        print('CRITERIO OK')
    except Exception as e:
        print(f'CRITERIO FALLO: {e}')
```

## crearutilsvalidatorspy.py
**Tarea:** Crear utils/validators.py
**Criterio:** 
**Descripción:** El script define dos funciones de validación: validate_title verifica que un título no esté vacío ni compuesto solo por espacios, y validate_id asegura que un identificador no sea negativo. El bloque principal ejecuta pruebas unitarias que confirman que ambas funciones lanzan ValueError cuando se violan las reglas y no lanzan excepciones con valores válidos, imprimiendo "CRITERIO OK" si todas las pruebas pasan.

```python
import os
import sys

def validate_title(title: str) -> None:
    if not title or not title.strip():
        raise ValueError("Title cannot be empty or whitespace")

def validate_id(task_id: int) -> None:
    if task_id < 0:
        raise ValueError("ID cannot be negative")

if __name__ == '__main__':
    try:
        validate_title("Valid Title")
    except ValueError:
        print("CRITERIO FALLO: validate_title falló con título válido")
        sys.exit(1)
    
    try:
        validate_title("")
        print("CRITERIO FALLO: validate_title no lanzó ValueError con título vacío")
        sys.exit(1)
    except ValueError:
        pass
    
    try:
        validate_title("   ")
        print("CRITERIO FALLO: validate_title no lanzó ValueError con título solo espacios")
        sys.exit(1)
    except ValueError:
        pass
    
    try:
        validate_id(0)
    except ValueError:
        print("CRITERIO FALLO: validate_id falló con id 0")
        sys.exit(1)
    
    try:
        validate_id(5)
    except ValueError:
        print("CRITERIO FALLO: validate_id falló con id positivo")
        sys.exit(1)
    
    try:
        validate_id(-1)
        print("CRITERIO FALLO: validate_id no lanzó ValueError con id negativo")
        sys.exit(1)
    except ValueError:
        pass
    
    print("CRITERIO OK")
```

## crearapipy.py
**Tarea:** Crear api.py
**Criterio:** 
**Descripción:** Implementa una API REST con FastAPI para gestionar tareas pendientes: permite crear, listar (filtrando por completadas o no), consultar individualmente y marcar como completadas. Al ejecutarse como script principal arranca el servidor en segundo plano y ejecuta una batería de pruebas automáticas que validan todas las operaciones.

```python
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from typing import List, Optional
import uvicorn

class Task(BaseModel):
    id: int
    title: str
    completed: bool = False

def validate_title(title: str) -> str:
    if not title or not title.strip():
        raise ValueError("Title cannot be empty")
    return title.strip()

app = FastAPI()
tasks_db = []
task_counter = 1

class TaskCreate(BaseModel):
    title: str

@app.post("/tasks", status_code=201)
def create_task(task: TaskCreate):
    global task_counter
    title = validate_title(task.title)
    new_task = Task(id=task_counter, title=title)
    tasks_db.append(new_task)
    task_counter += 1
    return new_task

@app.get("/tasks")
def get_tasks(completed_only: Optional[bool] = Query(None)):
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
        uvicorn.run(app, host="127.0.0.1", port=8000, log_level="error")
    
    server = threading.Thread(target=run_server, daemon=True)
    server.start()
    time.sleep(2)
    
    base = "http://127.0.0.1:8000"
    try:
        # Test POST /tasks
        r = requests.post(f"{base}/tasks", json={"title": "Test task"})
        assert r.status_code == 201
        task = r.json()
        assert task["title"] == "Test task"
        assert task["completed"] is False
        
        # Test GET /tasks
        r = requests.get(f"{base}/tasks")
        assert r.status_code == 200
        tasks = r.json()
        assert len(tasks) == 1
        
        # Test GET /tasks/{id}
        r = requests.get(f"{base}/tasks/{task['id']}")
        assert r.status_code == 200
        assert r.json()["id"] == task["id"]
        
        # Test 404 on non-existent task
        r = requests.get(f"{base}/tasks/9999")
        assert r.status_code == 404
        
        # Test PUT /tasks/{id}/complete
        r = requests.put(f"{base}/tasks/{task['id']}/complete")
        assert r.status_code == 200
        updated = r.json()
        assert updated["completed"] is True
        
        # Test completed_only query
        r = requests.get(f"{base}/tasks", params={"completed_only": True})
        assert r.status_code == 200
        completed = r.json()
        assert len(completed) == 1
        
        print("CRITERIO OK")
    except Exception as e:
        print(f"CRITERIO FALLO: {e}")
```

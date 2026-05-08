# apa/mcp/server.py
import sys
import os
import json
import logging
import base64
import uuid
import subprocess
import time
import threading
import shlex

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from config.settings import settings

import paramiko

# Guardia anti-recursión a nivel de hilo
_execution_guard = threading.local()

logging.basicConfig(level=logging.ERROR)
for logger_name in ["__main__", "core.orchestrator", "core.planner", "core.checkpoint", "agents.generator", "core.router", "mcp.server", "agents.documenter"]:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)
logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(handler)


class NASConnector:
    def __init__(self):
        self.nas_host = settings.nas_host
        self.nas_user = settings.nas_user
        self.sandbox_dir = "/app/sandbox"
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        '''''
        self.client.connect(
            hostname=self.nas_host,
            username=self.nas_user,
            timeout=10
        )
        '''
        self.client.connect(
            hostname=settings.nas_host,
            username=settings.nas_user,
            timeout=20,
            banner_timeout=20,
            auth_timeout=20
        )

    def _call_mcp_tool(self, tool_name: str, arguments: dict) -> dict:
        payload = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments}
        }, ensure_ascii=False) + "\n"

        command = f"sudo /usr/local/bin/docker exec -i mcp-server python -u /app/server/server.py"
        stdin, stdout, stderr = self.client.exec_command(command, timeout=60)
        stdin.write(payload)
        stdin.flush()
        stdin.channel.shutdown_write()

        for line in stdout:
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
        err_out = stderr.read().decode('utf-8', errors='replace')
        return {"error": err_out or "No se recibió respuesta JSON válida"}

    def execute_code(self, code: str, language: str = "python") -> dict:
        # Guardia anti-recursión
        if getattr(_execution_guard, 'inside', False):
            raise RuntimeError("execute_code llamado recursivamente. Operación abortada para evitar bucle infinito.")
        _execution_guard.inside = True
        try:
            logger.info(f"Ejecutando código en NAS (language={language})...")

            lang_config = {
                "python": {"ext": ".py", "cmd": "python3 {file}"},
                "javascript": {"ext": ".js", "cmd": "node {file}"},
                "bash": {"ext": ".sh", "cmd": "bash -e {file}"},
                "sql": {"ext": ".sql", "cmd": "sqlite3 :memory:"},
                "cpp": {"ext": ".cpp", "cmd": None},
                "dart": {"ext": ".dart", "cmd": None}
            }

            if language not in lang_config:
                return {"success": False, "stdout": "", "stderr": f"Unsupported language: {language}"}

            config = lang_config[language]
            ext = config["ext"]
            filename = f"temp_{uuid.uuid4().hex}{ext}"
            sandbox_path = f"{self.sandbox_dir}/{filename}"

            try:
                encoded = base64.b64encode(code.encode('utf-8')).decode('utf-8')
                path_esc = sandbox_path.replace("'", "\\'")
                write_code = f"""
import os, base64
os.makedirs('{self.sandbox_dir}', exist_ok=True)
with open('{path_esc}', 'w', encoding='utf-8') as f:
    f.write(base64.b64decode('{encoded}').decode('utf-8'))
"""
                write_result = self._call_mcp_tool("ejecutar_en_nas", {"code": write_code})
                if "error" in write_result:
                    return {"stdout": "", "stderr": write_result.get("error", ""), "success": False}

                if language == "sql":
                    exec_code = f"""
import subprocess, sys
with open('{path_esc}', 'r', encoding='utf-8') as f:
    result = subprocess.run(
        ['sqlite3', ':memory:'],
        stdin=f,
        capture_output=True,
        text=True,
        timeout=30
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
    else:
        sys.stdout.write(result.stdout)
    sys.exit(result.returncode)
"""
                elif language == "cpp":
                    bin_path = sandbox_path.replace('.cpp', '.out')
                    bin_esc = bin_path.replace("'", "\\'")
                    exec_code = f"""
import subprocess, sys
compile_result = subprocess.run(
    ['g++', '-std=c++17', '-o', '{bin_esc}', '{path_esc}'],
    capture_output=True,
    text=True,
    timeout=30
)
if compile_result.returncode != 0:
    sys.stderr.write(compile_result.stderr)
    sys.exit(compile_result.returncode)
run_result = subprocess.run(['{bin_esc}'], capture_output=True, text=True, timeout=10)
if run_result.returncode != 0:
    sys.stderr.write(run_result.stderr)
else:
    sys.stdout.write(run_result.stdout)
sys.exit(run_result.returncode)
"""
                elif language == "dart":
                    exec_code = f"""
import subprocess, sys
result = subprocess.run(
    ['/opt/flutter/bin/dart', 'run', '{path_esc}'],
    capture_output=True,
    text=True,
    timeout=30
)
if result.returncode != 0:
    sys.stderr.write(result.stderr)
else:
    sys.stdout.write(result.stdout)
sys.exit(result.returncode)
"""
                else:
                    cmd = config["cmd"].replace("{file}", sandbox_path)
                    exec_code = f"""
import subprocess, sys
result = subprocess.run('{cmd}', shell=True, capture_output=True, text=True)
if result.returncode != 0:
    sys.stderr.write(result.stderr)
else:
    sys.stdout.write(result.stdout)
sys.exit(result.returncode)
"""
                response = self._call_mcp_tool("ejecutar_en_nas", {"code": exec_code})

                cleanup_code = f"""
import os
for f in ['{path_esc}', '{bin_esc if language == "cpp" else path_esc}']:
    if os.path.exists(f):
                        try:
                            os.remove(f)
                        except:
                            pass
"""
                self._call_mcp_tool("ejecutar_en_nas", {"code": cleanup_code})

                if "error" in response:
                    return {"stdout": "", "stderr": response.get("error", ""), "success": False}

                content_text = ""
                try:
                    content_text = response["result"]["content"][0]["text"]
                except (KeyError, IndexError, TypeError):
                    return {"stdout": "", "stderr": "Formato de respuesta inesperado", "success": False}

                return {"stdout": content_text, "stderr": "", "success": True}
            except subprocess.TimeoutExpired as e:
                err_msg = f"Timeout en ejecución de {language}: {e}"
                logger.error(err_msg)
                return {"stdout": "", "stderr": err_msg, "success": False}
            except Exception as e:
                err_msg = str(e)
                logger.error(f"Error en execute_code: {err_msg}")
                return {"stdout": "", "stderr": err_msg, "success": False}
        finally:
            _execution_guard.inside = False

    def read_file(self, path: str) -> dict:
        logger.info(f"Leyendo archivo: {path}")
        try:
            dir_path = os.path.dirname(path) or "/"
            self._call_mcp_tool("list_directory", {"path": dir_path})

            code = f"""
import os
if not os.path.exists('{path.replace(chr(39), chr(92)+chr(39))}'):
    raise FileNotFoundError("Archivo no encontrado")
with open('{path.replace(chr(39), chr(92)+chr(39))}', 'r', encoding='utf-8') as f:
    print(f.read(), end='')
"""
            result = self.execute_code(code)
            if result["success"]:
                return {"content": result["stdout"], "success": True}
            return {"content": result.get("stderr", ""), "success": False}
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error en read_file: {err_msg}")
            return {"content": "", "success": False}

    def write_file(self, path: str, content: str) -> dict:
        logger.info(f"Escribiendo archivo (MCP): {path}")
        try:
            encoded = base64.b64encode(content.encode('utf-8')).decode('utf-8')
            
            # Script Python que crea directorios y escribe el archivo (igual que execute_code)
            script = f"""
import os, base64
os.makedirs('{os.path.dirname(path)}', exist_ok=True)
with open('{path}', 'w', encoding='utf-8') as f:
    f.write(base64.b64decode('{encoded}').decode('utf-8'))
"""
            # Enviar al MCP server directamente (sin execute_code)
            result = self._call_mcp_tool("ejecutar_en_nas", {"code": script})
            if "error" in result:
                return {"path": path, "success": False, "error": result.get("error", "Error desconocido")}
            return {"path": path, "success": True}
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Error en write_file (MCP): {err_msg}")
            return {"path": path, "success": False, "error": err_msg}

    def validate_remote(self, code: str, language: str) -> tuple[bool, str]:
        """
        Valida estáticamente el código directamente en el NAS, de forma aislada y segura.
        Retorna (True, "") o (False, mensaje_de_error).
        """
        validation_cmds = {
            "javascript": ["node", "--check"],
            "bash": ["bash", "-n"],
            "cpp": ["g++", "-fsyntax-only", "-std=c++17", "-x", "c++", "-"],
            "python": ["python3", "-m", "py_compile"],
            "dart": ["/opt/flutter/bin/dart", "analyze"],
            "react-native": ["node", "--check"],
            "sql": None
        }
        if language not in validation_cmds or validation_cmds[language] is None:
            return True, ""

        ext_map = {"python": ".py", "javascript": ".js", "bash": ".sh", "sql": ".sql",
                   "cpp": ".cpp", "dart": ".dart", "react-native": ".js"}
        ext = ext_map.get(language, ".txt")
        remote_filename = f"temp_remote_val_{uuid.uuid4().hex}{ext}"
        remote_path = f"{self.sandbox_dir}/{remote_filename}"

        try:
            # 1. Transferir archivo por SFTP
            sftp = self.client.open_sftp()
            with sftp.file(remote_path, 'w') as f:
                f.write(code)
            sftp.close()

            # 2. Ejecutar validación por SSH directo
            cmd_parts = validation_cmds[language] + [remote_path]
            cmd_str = ' '.join(cmd_parts)
            stdin, stdout, stderr = self.client.exec_command(cmd_str, timeout=15)
            exit_status = stdout.channel.recv_exit_status()
            error_output = stderr.read().decode('utf-8', errors='replace')

            # 3. Limpiar archivo temporal
            self.client.exec_command(f"rm -f {remote_path}")

            return (exit_status == 0, error_output.strip())
        except Exception as e:
            logger.error(f"Error en validación remota para {language}: {e}")
            return True, ""  # Degradar gracefulmente


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    nas = NASConnector()

    print("PRUEBA 1:", nas.execute_code("print('CONEXION OK')"))

    result_w = nas.write_file("/app/sandbox/test_apa.txt", "APA funcionando")
    result_r = nas.read_file("/app/sandbox/test_apa.txt")
    print("PRUEBA 2 escritura:", result_w)
    print("PRUEBA 2 lectura:", result_r)
    print("PRUEBA 3:", nas.execute_code("raise Exception('error test')"))
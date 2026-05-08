# apa/core/device_manager.py
# Script de prueba para Metodología de Ensamblaje Atómico.

import time

class DeviceManager:
    """
    Gestiona dispositivos genéricos del sistema.
    """
    
    def __init__(self):
        self.devices = []
        self.status = "INIT"

    def scan_devices(self):
        """Escanea dispositivos en la red."""
        print("Escaneando dispositivos...")
        # Simulación de escaneo
        time.sleep(0.5)
        self.devices = ["Device_A", "Device_B"]
        return self.devices

    def get_status(self):
        """Retorna el estado actual del sistema."""
        return self.status


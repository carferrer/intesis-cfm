# IntesisBox CFM para Home Assistant

Integración local para interfaces IntesisBox compatibles con WMP (TCP 3310),
basada en [hass-intesisbox de jnimmo](https://github.com/jnimmo/hass-intesisbox).
No utiliza Intesis Cloud ni IntesisHome Cloud.

## Versión 2.1.0

Dirigida a Home Assistant **2026.9.2**. La configuración se realiza desde
**Ajustes → Dispositivos y servicios → Añadir integración → IntesisBox**,
introduciendo la IP o el nombre de host del equipo.

- Comprueba la conexión y las capacidades antes de guardar la configuración.
- Evita duplicados por host y MAC.
- Actualiza las entidades al recibir cambios del equipo. Conserva una consulta
  de respaldo cada cinco minutos y un keepalive cada 45 segundos.
- Limita la inicialización a 20 segundos. HA reintenta si el equipo está apagado.
- Tras una desconexión, reintenta con esperas de 5, 10, 20, 40 y 60 segundos.
- Lee correctamente mensajes TCP fragmentados y descarta líneas inválidas.
- Descarga diagnósticos sin incluir IP, MAC ni el título de la entrada.

## Actualizar una instalación existente

1. Haz una copia de seguridad de Home Assistant y de la carpeta anterior.
2. Sustituye `custom_components/intesisbox` por la carpeta del mismo nombre
   de esta versión y reinicia Home Assistant.
3. **No elimines ni vuelvas a añadir la integración.** Conserva su entrada actual.

Se mantienen el dominio `intesisbox`, los identificadores MAC originales,
los identificadores de dispositivo y los `unique_id` de las entidades.
No se cambia la versión del formato de configuración (v1).
Los nombres y `entity_id` personalizados continúan en el registro de HA.
También se conservan los valores de oscilación `Auto`, `Horizontal`, `Vertical`
y `Both`, y el mapeo de modo automático a `heat_cool`.
La plataforma YAML heredada sigue disponible; esta actualización se centra en UI.

Para cambiar una IP, utiliza **Reconfigurar** en el menú de la integración.
La nueva dirección debe responder con la misma MAC. Una entrada antigua sin MAC
necesita completar al menos un arranque antes de poder reconfigurarse.
Es recomendable reservar la IP del equipo en el router.

## Comprobación con el equipo real

Después de actualizar, comprueba que se conserva la entidad existente, cambia
temperatura/modo/ventilador y verifica los cambios desde el mando físico.
Prueba una desconexión y posterior reconexión del Intesis: la entidad debe pasar
a no disponible al detectarse la pérdida de conexión y recuperarse después.
Una pérdida de red sin cierre TCP puede tardar en ser detectada por el sistema.
Los comandos se reflejan cuando el dispositivo comunica su estado; no se simula
una confirmación del equipo.

Las pruebas automatizadas utilizan un servidor WMP simulado y Home Assistant
2026.9.2; no sustituyen la validación de cada modelo físico.

## Desarrollo y pruebas

Con Python 3.14.2 o posterior y Linux:

```sh
python -m pip install -r requirements-test.txt
ruff check .
ruff format --check custom_components/intesisbox tests
python -m unittest discover -s tests/protocol -v
pytest tests/ha -q
```

Las pruebas de protocolo también pueden ejecutarse sin Home Assistant usando
Python 3.12 o posterior. El emulador manual se inicia con
`python custom_components/intesisbox/IntesisBoxEmulator.py` y escucha únicamente
en `127.0.0.1:3310`.

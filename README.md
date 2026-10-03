# IntesisBox CFM para Home Assistant

![IntesisBox](custom_components/intesisbox/brand/icon.png)

[![Tests](https://github.com/carferrer/intesis-cfm/actions/workflows/tests.yml/badge.svg)](https://github.com/carferrer/intesis-cfm/actions/workflows/tests.yml)
[![Hassfest](https://github.com/carferrer/intesis-cfm/actions/workflows/hassfest.yml/badge.svg)](https://github.com/carferrer/intesis-cfm/actions/workflows/hassfest.yml)
[![HACS](https://github.com/carferrer/intesis-cfm/actions/workflows/validate.yml/badge.svg)](https://github.com/carferrer/intesis-cfm/actions/workflows/validate.yml)

Integración local para interfaces IntesisBox compatibles con WMP (TCP 3310),
basada en [hass-intesisbox de jnimmo](https://github.com/jnimmo/hass-intesisbox).
No utiliza Intesis Cloud ni IntesisHome Cloud.

## Instalar y actualizar con HACS

Cuando estos cambios estén integrados en la rama principal y exista una release
con el archivo `intesisbox.zip`:

1. Abre HACS y entra en **Repositorios personalizados** desde el menú.
2. Añade `https://github.com/carferrer/intesis-cfm` como **Integración**.
3. Busca **IntesisBox CFM**, descárgalo y reinicia Home Assistant.
4. Si ya tienes la integración configurada, conserva su entrada: no la elimines.
   Para instalaciones nuevas, añade **IntesisBox** desde Dispositivos y servicios.

Versión mínima declarada para esta edición: Home Assistant **2026.9.2**.
Este repositorio se añade como repositorio personalizado; no implica su inclusión
en el catálogo predeterminado de HACS. Evita gestionar simultáneamente dos
repositorios HACS que instalen el mismo dominio `intesisbox`.

## Comprobaciones y paquetes

En cada cambio y pull request se ejecutan:

- **Tests**: Ruff, formato, pruebas TCP y pruebas con HA 2026.9.2.
- **Hassfest**: validación del manifiesto y estructura de la integración.
- **HACS validation**: requisitos del repositorio para HACS.
- **Build ZIP for HACS**: genera y verifica `intesisbox.zip`, disponible como
  artefacto `intesisbox-hacs` en GitHub Actions.

Hassfest y HACS también se ejecutan diariamente y pueden lanzarse manualmente.
Renovate tiene una configuración para proponer actualizaciones de las acciones
y requisitos del manifiesto, sin fusionarlas automáticamente. Para que actúe,
la aplicación Renovate debe tener acceso a este repositorio.

Al publicar una release, el flujo comprueba que su etiqueta (por ejemplo,
`v2.1.0`) coincide con `manifest.json` y adjunta `intesisbox.zip`. El flujo no
crea releases por sí mismo. El ZIP HACS contiene `manifest.json` en su raíz y
se instala dentro de `custom_components/intesisbox`; no incluye pruebas ni el
emulador. Para generarlo localmente: `python scripts/build_zip.py`.

El código mantiene la licencia MIT de James Nimmo, incluida en `LICENSE`.
El icono procede del [repositorio de marcas de Home Assistant](https://github.com/home-assistant/brands/tree/master/custom_integrations/intesisbox)
y representa la marca Intesis de su titular.

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

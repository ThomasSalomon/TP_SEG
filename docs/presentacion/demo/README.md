# Demo de TiendaFicticia

La reproducción recrea diez minutos de la presentación del TPI. React y Motion usan los estilos de la app para mostrar cómo se ingresan las consultas y qué cambia entre los perfiles. Los casos se reproducen desde la línea de tiempo local y el MP4 se proyecta sin conexión. El guion está en [guion.md](../guion.md).

## Vista previa y exportación

Desde esta carpeta, con Node.js 22.14 o posterior:

```powershell
npm ci
npx playwright install chromium
npm run dev
```

Abrí la dirección local que imprime Vite. La barra inferior permite pausar y buscar una escena. Para verificar y exportar:

```powershell
npm run check
npm run export
```

Si ya tenés un Chromium compatible y querés usarlo, configurá `DEMO_CHROMIUM_PATH` con la ruta absoluta del ejecutable antes de correr los dos comandos. FFmpeg y FFprobe se instalan con las dependencias de npm.

La exportación genera `output/tiendaficticia-demo.mp4` en 1920 × 1080, H.264, 30 fps, 10:00 y sin audio. Playwright captura los estados en Chromium. FFmpeg usa la línea de tiempo para dar a cada captura su duración y FFprobe comprueba las propiedades del archivo. Si cambiás una escena o su duración, actualizá el guion y volvé a exportar.

## Edición

- [src/cases.js](src/cases.js) contiene los textos de los casos, la referencia visible al registro y los fragmentos de código.
- [src/timeline.js](src/timeline.js) fija el orden de escenas y los tiempos del cursor, el tipeo, el envío y la respuesta.
- [src/main.jsx](src/main.jsx) combina la interfaz de TiendaFicticia, los rótulos de perfil y las explicaciones de código.

`npm run check` comprueba que cada fragmento siga en el código del laboratorio y recorre los diez tramos en Chromium con las solicitudes externas bloqueadas. La procedencia de los efectos está al final del guion.

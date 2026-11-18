import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';

const project = fileURLToPath(new URL('.', import.meta.url));
const store = fileURLToPath(new URL('../../../app/static/', import.meta.url));

export default defineConfig({
  server: { fs: { allow: [project, store] } },
});

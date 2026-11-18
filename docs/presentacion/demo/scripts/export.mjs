import { execFile } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, mkdtemp, rename, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { promisify } from 'node:util';
import ffmpeg from '@ffmpeg-installer/ffmpeg';
import ffprobe from '@ffprobe-installer/ffprobe';
import { captureFrames, duration, fps } from '../src/timeline.js';
import { seek, withDemo } from './browser.mjs';

const run = promisify(execFile);
const outputDir = resolve('output');
const output = join(outputDir, 'tiendaficticia-demo.mp4');
const candidate = join(outputDir, `.tiendaficticia-demo-${randomUUID()}.mp4`);
const scratch = await mkdtemp(join(tmpdir(), 'tiendaficticia-demo-'));
const frames = captureFrames();
const manifest = ['ffconcat version 1.0'];
try {
  await mkdir(outputDir, { recursive: true });
  await withDemo(async page => {
    for (const [index, frame] of frames.entries()) {
      const name = `frame-${index}.jpg`;
      await seek(page, frame / fps);
      await page.screenshot({ path: join(scratch, name), type: 'jpeg', quality: 94 });
      const next = frames[index + 1] ?? duration * fps;
      manifest.push(`file '${name}'`, `duration ${(next - frame) / fps}`);
      if (index % 100 === 0) console.log(`Captura ${index + 1}/${frames.length}`);
    }
  });
  manifest.push(`file 'frame-${frames.length - 1}.jpg'`);
  const list = 'frames.ffconcat';
  await writeFile(join(scratch, list), manifest.join('\n') + '\n');
  console.log('Codificando el MP4 de diez minutos…');
  await run(ffmpeg.path, [
    '-hide_banner', '-loglevel', 'error', '-y', '-f', 'concat', '-safe', '0',
    '-i', list, '-vf', `fps=${fps}`, '-t', String(duration), '-c:v', 'libx264',
    '-threads', '4', '-preset', 'veryfast', '-crf', '19', '-pix_fmt', 'yuv420p',
    '-movflags', '+faststart', '-map', '0:v:0', candidate,
  ], { cwd: scratch });
  const { stdout } = await run(ffprobe.path, [
    '-v', 'error', '-show_streams', '-show_format', '-of', 'json', candidate,
  ]);
  const video = JSON.parse(stdout);
  const [stream] = video.streams;
  if (video.streams.length !== 1 || stream.codec_name !== 'h264'
    || stream.width !== 1920 || stream.height !== 1080 || stream.avg_frame_rate !== '30/1'
    || Number(stream.nb_frames) !== duration * fps || Number(video.format.duration) !== duration) {
    throw new Error(`El MP4 no cumple las especificaciones de exportación: ${stdout}`);
  }
  await rename(candidate, output);
  console.log(`Verificado: 1920 × 1080, H.264, 30 fps, 600 s.\n${output}`);
} finally {
  await Promise.all([rm(scratch, { recursive: true, force: true }), rm(candidate, { force: true })]);
}

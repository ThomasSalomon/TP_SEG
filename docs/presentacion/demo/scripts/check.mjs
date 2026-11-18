import { strict as assert } from 'node:assert';
import { readFile } from 'node:fs/promises';
import { cases } from '../src/cases.js';
import { captureFrames, duration, fps, scenes } from '../src/timeline.js';
import { seek, withDemo } from './browser.mjs';

const frames = captureFrames();
for (const scene of scenes) assert(frames.includes(scene.start * fps));
assert.equal(scenes.at(-1).end, duration);
for (const item of cases) {
  for (const { file, code } of item.excerpts) {
    const source = await readFile(new URL(`../../../../${file}`, import.meta.url), 'utf8');
    assert(source.replaceAll('\r\n', '\n').includes(code), `Fragmento desactualizado: ${file}`);
  }
}

await withDemo(async page => {
  const visible = selector => page.locator(selector).isVisible();
  const text = selector => page.locator(selector).textContent();
  const input = selector => page.locator(selector).inputValue();
  await seek(page, 7.1);
  assert(await visible('#login-user'));
  assert.equal(await input('#login-user'), '');
  await seek(page, 10.55);
  assert.match(await input('#login-user'), /^a/);
  await seek(page, 16);
  assert(await visible('.chat'));
  assert.equal(await page.locator('.messages .msg').count(), 1);

  for (const scene of scenes.filter(item => item.kind === 'chat')) {
    const { item, profile, script, start } = scene;
    await seek(page, start);
    assert.equal(await input('#chat-input'), '');
    assert.equal(await page.locator('.messages .msg').count(), 1);
    assert.match(await text('.profile'), profile ? /segura/ : /vulnerable/);
    if (item.review) {
      await seek(page, start + 7.3);
      assert(await visible('#review-text'));
      assert.match(await input('#review-text'), /^La entrega/);
      await seek(page, start + 11);
      assert.match(await text('.review-box [role=status]'), /publicada/);
    }
    const typing = script.typing.at(-1);
    await seek(page, start + typing.at + typing.seconds / 2);
    const partial = await input('#chat-input');
    assert(partial.length > 0 && partial.length < item.question.length);
    assert(item.question.startsWith(partial));
    assert.equal(await page.locator('.msg-user').count(), 0);
    await seek(page, start + script.chatAt + 0.4);
    assert.equal(await input('#chat-input'), '');
    assert.match(await text('.msg-system'), /Lumi está escribiendo/);
    assert.equal(await page.locator('.msg-assistant').count(), 1);
    assert(await page.locator('[data-target=chat-submit]').isDisabled());
    await seek(page, start + script.evidenceAt + 1);
    assert.equal(await page.locator('.msg-assistant').count(), 2);
    const reply = page.locator('.msg-assistant').last();
    const expectedReply = script.replyHeading ? `${script.replyHeading}\n${script.reply}` : script.reply;
    assert.equal(await reply.textContent(), expectedReply);
    assert.match(await text('.evidence .label'), item.records[profile] ? /registrado/ : /esperada/);
    assert.equal(await visible('.browser-dialog'), item.id === 'V5' && profile === 0);
    if (item.id === 'V5' && profile === 1) {
      assert.match(await reply.textContent(), /<strong>Información de envíos<\/strong>/);
      assert.equal(await reply.locator('strong').count(), 0);
    }
    assert.equal(await page.getByRole('button', { name: 'Confirmar reembolso' }).count(), 0);
  }
  await seek(page, 545);
  assert.equal(await page.locator('.closing li').count(), 5);
});
console.log('Verificados los diez tramos, los fragmentos de código y la reproducción sin solicitudes externas.');

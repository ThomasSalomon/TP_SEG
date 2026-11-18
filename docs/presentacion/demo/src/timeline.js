import { cases } from './cases.js';

export const duration = 600;
export const fps = 30;
const greeting = '¡Hola! Soy Lumi. ¿En qué te puedo ayudar?';
const opening = [
  { start: 0, end: 7, kind: 'title' },
  {
    start: 7, end: 45, kind: 'intro',
    question: '¿Dónde puedo consultar los plazos de envío?',
    reply: 'Puedo orientarte sobre los plazos y las opciones de envío.',
  },
];

export const scenes = [
  ...opening,
  ...cases.flatMap((item, index) => {
    const start = 45 + index * 100;
    return [
      { start, end: start + 35, kind: 'chat', item, profile: 0 },
      { start: start + 35, end: start + 70, kind: 'chat', item, profile: 1 },
      { start: start + 70, end: start + 100, kind: 'code', item },
    ];
  }),
  { start: 545, end: duration, kind: 'closing' },
];

function type(at, seconds, field, value) {
  return { at, seconds, field, value };
}

function cursor(at, target, click = false) {
  return { at, target, click };
}

function scriptFor(scene) {
  if (scene.kind === 'intro') {
    return {
      typing: [
        type(3.15, 0.85, 'login-user', 'alice'),
        type(5.35, 1.2, 'login-pass', '●●●●●●●●●●'),
        type(12, 3.4, 'chat-input', scene.question),
      ],
      pointers: [
        cursor(2.5, 'login-user', true), cursor(4.65, 'login-pass', true),
        cursor(7.5, 'login-submit', true), cursor(11.35, 'chat-input', true),
        cursor(16.65, 'chat-submit', true), cursor(20.5, 'chat-center'),
      ],
      loginAt: 7.72, chatAt: 16.85, replyAt: 18.85, evidenceAt: 23,
      reply: scene.reply,
    };
  }
  if (scene.kind !== 'chat') return null;
  const { item, profile } = scene;
  const hasReview = Boolean(item.review);
  const hasDialog = item.id === 'V5' && profile === 0;
  const messageAt = hasReview ? 18.6 : 7.2;
  const sendAt = hasReview ? 23.1 : 12;
  const replyAt = sendAt + 2.2;
  return {
    typing: [
      ...(hasReview ? [type(5.1, 4.2, 'review-text', item.review)] : []),
      type(messageAt, 3.8, 'chat-input', item.question),
    ],
    pointers: [
      ...(hasReview ? [
        cursor(2.4, 'review-toggle', true), cursor(4.5, 'review-text', true),
        cursor(10.15, 'review-submit', true), cursor(15.4, 'review-toggle', true),
      ] : []),
      cursor(messageAt - 0.6, 'chat-input', true), cursor(sendAt, 'chat-submit', true),
      ...(hasDialog ? [cursor(replyAt + 5.1, 'dialog-dismiss', true)] : []),
      cursor(replyAt + (hasDialog ? 6.3 : 1.4), 'chat-center'),
    ],
    loginAt: 0,
    chatAt: sendAt + 0.19,
    replyAt,
    evidenceAt: replyAt + 1,
    openReviewAt: hasReview ? 2.58 : Infinity,
    postReviewAt: hasReview ? 10.34 : Infinity,
    closeReviewAt: hasReview ? 15.59 : Infinity,
    dialogUntil: hasDialog ? replyAt + 5.29 : 0,
    reply: item.replies[profile],
    replyHeading: hasDialog ? item.replyHeading : undefined,
  };
}

for (const scene of scenes) scene.script = scriptFor(scene);

function typedValue(event, time) {
  const fraction = Math.min(1, Math.max(0, (time - event.at) / event.seconds));
  return event.value.slice(0, Math.floor(event.value.length * fraction));
}

export function stateAt(seconds) {
  const time = Math.min(Math.max(0, seconds), duration - 1 / fps);
  const scene = scenes.find(({ end }) => time < end);
  const offset = time - scene.start;
  const script = scene.script;
  if (!script) return { time, scene, offset };

  const draft = Object.fromEntries(script.typing.map(event => [
    event.field, typedValue(event, offset),
  ]));
  const loggedIn = offset >= script.loginAt;
  const sent = offset >= script.chatAt;
  const answered = offset >= script.replyAt;
  const messages = loggedIn ? [{ id: 'greeting', role: 'assistant', text: greeting }] : [];
  if (sent) {
    messages.push({
      id: 'message', role: 'user', text: scene.item?.question ?? scene.question,
    });
    messages.push(answered
      ? { id: 'reply', role: 'assistant', heading: script.replyHeading, text: script.reply }
      : { id: 'waiting', role: 'system', text: 'Lumi está escribiendo…' });
  }
  const pointerIndex = script.pointers.findLastIndex(event => offset >= event.at - 0.5);
  return {
    time, scene, offset, draft, loggedIn, sent, answered, messages, pointerIndex,
    reviewOpen: offset >= script.openReviewAt && offset < script.closeReviewAt,
    reviewPosted: offset >= script.postReviewAt,
    dialog: answered && offset < script.dialogUntil,
    evidence: offset >= script.evidenceAt,
  };
}

// Preserve every UI state and sample animated intervals at 15 fps. The exporter
// holds quiet frames for their full duration on the 30 fps output timeline.
export function captureFrames() {
  const frames = new Set([0]);
  function frameAt(time) {
    return Math.ceil(time * fps - 1e-7);
  }
  for (const scene of scenes) {
    const sample = seconds => frames.add(frameAt(scene.start + seconds));
    const animate = (start, end) => {
      for (let frame = frameAt(start); frame < frameAt(end); frame += 2) sample(frame / fps);
      sample(end);
    };
    animate(0, 0.47);
    const script = scene.script;
    if (!script) continue;
    for (const event of script.typing) animate(event.at, event.at + event.seconds);
    for (const event of script.pointers) animate(event.at - 0.5, event.at + 0.29);
    animate(script.evidenceAt, script.evidenceAt + 0.39);
    for (const at of [script.loginAt, script.chatAt, script.replyAt, script.openReviewAt,
      script.postReviewAt, script.closeReviewAt, script.dialogUntil]) {
      if (Number.isFinite(at)) sample(at);
    }
  }
  return [...frames].filter(frame => frame < duration * fps).sort((a, b) => a - b);
}

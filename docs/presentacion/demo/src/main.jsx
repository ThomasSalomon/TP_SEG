import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { flushSync } from 'react-dom';
import { motion, useMotionValue } from 'motion/react';
import '../../../../app/static/style.css';
import { cases } from './cases.js';
import { duration, stateAt } from './timeline.js';
import './presentation.css';

const capture = new URLSearchParams(location.search).has('capture');
const stageWidth = 1600;
const stageHeight = 900;
const keepScripted = event => event.preventDefault();

function timeLabel(time) {
  return `${Math.floor(time / 60)}:${String(Math.floor(time % 60)).padStart(2, '0')}`;
}

function ease(progress) {
  const bounded = Math.min(Math.max(0, progress), 1);
  return 1 - (1 - bounded) ** 3;
}

function typeField(state, field) {
  const script = state.scene.script;
  const pointer = script.pointers[state.pointerIndex];
  return {
    id: field,
    'data-target': field,
    'data-focused': pointer?.target === field && state.offset >= pointer.at ? '' : undefined,
    readOnly: true,
    value: state.draft[field] ?? '',
  };
}

function Pointer({ state, surface }) {
  const x = useMotionValue(545);
  const y = useMotionValue(155);
  const script = state.scene.script;
  const event = script.pointers[state.pointerIndex];
  useLayoutEffect(() => {
    const bounds = surface.current.getBoundingClientRect();
    const scale = bounds.width / stageWidth;
    function point(target) {
      const element = surface.current.querySelector(`[data-target="${target}"]`);
      const rect = element?.getBoundingClientRect();
      if (rect?.width && rect.height) {
        const dx = target.endsWith('input') || target === 'review-text' ? 24 : rect.width / scale / 2;
        return [(rect.left - bounds.left) / scale + dx, (rect.top - bounds.top + rect.height / 2) / scale];
      }
      return target === 'login-submit' ? [225, 411] : [520, 330];
    }
    if (!event) {
      x.set(545);
      y.set(155);
      return;
    }
    const from = point(script.pointers[state.pointerIndex - 1]?.target);
    const to = point(event.target);
    const progress = ease((state.offset - event.at + 0.5) / 0.5);
    x.set(from[0] + (to[0] - from[0]) * progress);
    y.set(from[1] + (to[1] - from[1]) * progress);
  }, [event, script, state.offset, state.pointerIndex, surface, x, y]);
  const clickAge = event?.click ? state.offset - event.at : -1;
  const click = clickAge >= 0 && clickAge < 0.29;
  return (
    <motion.div className="record-pointer" style={{ x, y }} aria-hidden="true">
      <motion.span className="click-ring" style={{
        opacity: click ? 0.8 * (1 - clickAge / 0.29) : 0,
        scale: click ? 0.55 + 2 * clickAge : 0.55,
      }} />
      <svg width="22" height="28" viewBox="0 0 22 28">
        <path d="M2 2v19l5-5 4 8 4-2-4-8h7z" fill="#161b21" stroke="white" strokeWidth="1.25" />
      </svg>
    </motion.div>
  );
}

function Store({ state }) {
  const scroll = useRef(null);
  const viewport = useRef(null);
  useLayoutEffect(() => {
    scroll.current?.scrollTo({ top: scroll.current.scrollHeight });
  }, [state.answered, state.sent, state.loggedIn]);
  useLayoutEffect(() => {
    const page = viewport.current;
    page.scrollTop = state.reviewOpen ? page.scrollHeight : 0;
  }, [state.reviewOpen, state.loggedIn]);

  return (
    <div className="browser" aria-label="Recreación de la pantalla de TiendaFicticia">
      <div className="browser-toolbar">
        <span className="browser-dots" aria-hidden="true"><i /><i /><i /></span>
        <span className="browser-tab">TiendaFicticia · Asistente</span>
        <span className="browser-address">127.0.0.1:{state.scene.profile === 1 ? '8002' : '8001'}</span>
      </div>
      <div className="store-viewport" ref={viewport}>
        <div className="store-page">
          <header className="topbar">
            <div className="brand">TiendaFicticia <span className="brand-sub">Atención al cliente</span></div>
            <div className="user-box" hidden={!state.loggedIn}>
              <span>alice</span><button type="button" className="link-btn" tabIndex={-1}>Salir</button>
            </div>
          </header>
          <p className="lab-warning">Laboratorio académico: esta aplicación es vulnerable a propósito. Datos y clientes ficticios.</p>
          <main>
            {!state.loggedIn ? (
              <section className="card">
                <h1>Iniciar sesión</h1>
                <form onSubmit={keepScripted}>
                  <label>Cliente <input {...typeField(state, 'login-user')} /></label>
                  <label>Contraseña <input {...typeField(state, 'login-pass')} type="password" /></label>
                  <button type="submit" data-target="login-submit">Entrar</button>
                  <p className="error" role="alert" />
                </form>
              </section>
            ) : (
              <section className="chat">
                <div className="messages" data-target="chat-center" ref={scroll} aria-live="polite">
                  {state.messages.map(message => (
                    <div className={`msg msg-${message.role}`} key={message.id}>
                      {message.heading && <><strong>{message.heading}</strong>{'\n'}</>}
                      {message.text}
                    </div>
                  ))}
                </div>
                <form className="composer" onSubmit={keepScripted}>
                  <input {...typeField(state, 'chat-input')} value={state.sent ? '' : state.draft['chat-input'] ?? ''} placeholder="Escribí tu consulta…" aria-label="Consulta" />
                  <button data-target="chat-submit" disabled={state.sent && !state.answered}>Enviar</button>
                </form>
                <details className="card review-box" open={state.reviewOpen}>
                  <summary data-target="review-toggle" onClick={keepScripted}>Dejar una reseña</summary>
                  <form onSubmit={keepScripted}>
                    <textarea {...typeField(state, 'review-text')} value={state.reviewPosted ? '' : state.draft['review-text'] ?? ''} rows={3} placeholder="¿Qué te pareció el producto?" aria-label="Reseña" />
                    <button data-target="review-submit">Publicar reseña</button>
                    <p className="muted" role="status">{state.reviewPosted ? '¡Gracias! Tu reseña fue publicada.' : ''}</p>
                  </form>
                </details>
              </section>
            )}
          </main>
        </div>
      </div>
      {state.dialog && (
        <div className="dialog-scrim">
          <div className="browser-dialog" role="dialog" aria-label="Diálogo recreado">
            <strong>127.0.0.1:8001 dice</strong>
            <p>1</p>
            <button type="button" data-target="dialog-dismiss">Aceptar</button>
          </div>
        </div>
      )}
    </div>
  );
}

function Comparison({ state, surface }) {
  const { scene } = state;
  const { item, profile } = scene;
  const recorded = item?.records[profile];
  const profileName = profile === 1 ? 'segura' : 'vulnerable';
  const provenance = recorded ? 'Resultado registrado' : item ? 'Salida esperada' : 'Interacción ilustrativa';
  const progress = ease((state.offset - scene.script.evidenceAt) / 0.39);
  return (
    <div className="comparison">
      <Store state={state} />
      <aside className="sidebar">
        <span className="label">{item ? item.id : 'El asistente'}</span>
        <h2>{item?.title ?? 'Un chat para TiendaFicticia'}</h2>
        <div className={`profile ${profileName}`}><span /> Perfil {profileName}</div>
        <p className="phase-note">
          {item ? profile === 0 ? 'Comportamiento original' : 'Mismo caso con las mitigaciones activas' : 'Tienda, clientes y pedidos ficticios.'}
        </p>
        {state.evidence && (
          <motion.section className="evidence" style={{ opacity: progress, y: (1 - progress) * 12 }}>
            <span className="label">{provenance}</span>
            <h3>{item?.outcomes[profile] ?? 'El cliente consulta desde el chat'}</h3>
            <p>{item?.detail[profile] ?? 'Lumi utiliza la base de conocimiento de la tienda para responder consultas.'}</p>
            {recorded && <span className="source-line">{recorded} · texto ilustrativo o resumido</span>}
          </motion.section>
        )}
      </aside>
      <Pointer state={state} surface={surface} />
    </div>
  );
}

function CodeScene({ item }) {
  return (
    <section className="code-scene">
      <div className="code-intro">
        <span className="label">{item.id} · Perfil segura</span>
        <h2>{item.control}</h2>
        <p>{item.explanation}</p>
      </div>
      <div className="excerpts">
        {item.excerpts.map(({ file, code }) => (
          <div className="editor" key={file}>
            <div className="editor-path">{file}</div>
            <pre><code>{code}</code></pre>
          </div>
        ))}
      </div>
    </section>
  );
}

function Title() {
  return (
    <section className="title-card">
      <span className="label">TPI · Seguridad en el Desarrollo de Software · UTN</span>
      <h2>Seguridad en<br />asistentes con LLM</h2>
      <p>El asistente de TiendaFicticia en sus perfiles vulnerable y segura.</p>
      <span className="title-caption">Recreación de la demo · entradas ilustrativas · esperas abreviadas</span>
    </section>
  );
}

function Closing() {
  return (
    <section className="closing">
      <span className="label">Mitigaciones implementadas</span>
      <h2>Qué cambia en el perfil segura</h2>
      <ul>
        {cases.map(item => <li key={item.id}><span>{item.id}</span>{item.control}</li>)}
      </ul>
      <p>Los registros mostrados son preliminares. El plan de medición final prevé 50 repeticiones válidas por caso y perfil.</p>
    </section>
  );
}

function Presentation() {
  const [seconds, setSeconds] = useState(0);
  const [playing, setPlaying] = useState(!capture);
  const [scale, setScale] = useState(1);
  const current = useRef(0);
  const stage = useRef(null);

  useLayoutEffect(() => {
    window.demoSeek = value => flushSync(() => setSeconds(value));
    const resize = () => setScale(Math.min(innerWidth / stageWidth, innerHeight / stageHeight));
    resize();
    addEventListener('resize', resize);
    return () => removeEventListener('resize', resize);
  }, []);

  useEffect(() => {
    if (!playing) return;
    const started = performance.now() - current.current * 1000;
    let frame;
    function tick(now) {
      const time = Math.min(duration, (now - started) / 1000);
      current.current = time;
      setSeconds(time);
      if (time < duration) frame = requestAnimationFrame(tick);
      else setPlaying(false);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  const state = stateAt(seconds);
  const { scene, offset } = state;
  const visible = scene.kind === 'title' ? 1 : 0.92 + 0.08 * ease(offset / 0.47);
  return (
    <>
      <div className="stage-fit" style={{ width: stageWidth * scale, height: stageHeight * scale }}>
        <div className="stage" ref={stage} style={{ transform: `scale(${scale})` }}>
          <header className="presentation-header">
            <strong>TiendaFicticia</strong><span>Recreación de la demo</span>
          </header>
          <motion.div className="scene" key={scene.start} style={{ opacity: visible }}>
            {scene.kind === 'title' && <Title />}
            {scene.script && <Comparison state={state} surface={stage} />}
            {scene.kind === 'code' && <CodeScene item={scene.item} />}
            {scene.kind === 'closing' && <Closing />}
          </motion.div>
          <footer className="presentation-footer">
            <span>Seguridad en el Desarrollo de Software · UTN</span>
            <span>{scene.item ? `${scene.item.id} / V5` : scene.kind === 'closing' ? 'Cierre' : 'Introducción'}</span>
          </footer>
        </div>
      </div>
      {!capture && (
        <div className="playback">
          <button type="button" onClick={() => {
            if (current.current >= duration) current.current = 0;
            setPlaying(!playing);
          }}>{playing ? 'Pausar' : 'Reproducir'}</button>
          <input type="range" min="0" max={duration} step="0.1" value={seconds} aria-label="Tiempo de reproducción" onChange={event => {
            setPlaying(false);
            current.current = Number(event.target.value);
            setSeconds(current.current);
          }} />
          <span>{timeLabel(seconds)} / 10:00</span>
        </div>
      )}
    </>
  );
}

createRoot(document.getElementById('root')).render(<Presentation />);

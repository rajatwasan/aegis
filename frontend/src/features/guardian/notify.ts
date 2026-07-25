/**
 * Notification tier for a new escalation while the guardian page is open:
 * vibration where the platform allows it (not iOS Safari) and a short beep
 * from a WebAudio oscillator (no audio file, no web push, no service
 * worker). iOS only lets audio start after a user gesture, so the page
 * primes the context on first touch.
 */

type AudioContextCtor = typeof AudioContext;

function audioContextCtor(): AudioContextCtor | null {
  if ("AudioContext" in window) return window.AudioContext;
  const legacy = (window as { webkitAudioContext?: AudioContextCtor })
    .webkitAudioContext;
  return legacy ?? null;
}

let context: AudioContext | null = null;

/** Call from any user gesture: unlocks audio for later event-driven beeps. */
export function primeAudio(): void {
  const Ctor = audioContextCtor();
  if (Ctor === null) return;
  context ??= new Ctor();
  if (context.state === "suspended") void context.resume();
}

function beep(): void {
  if (context === null || context.state !== "running") return;
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = 880;
  const now = context.currentTime;
  gain.gain.setValueAtTime(0.0001, now);
  gain.gain.exponentialRampToValueAtTime(0.2, now + 0.02);
  gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.3);
  oscillator.connect(gain).connect(context.destination);
  oscillator.start(now);
  oscillator.stop(now + 0.32);
}

/** Buzz + beep, both best-effort — silence is never an error. */
export function notifyNewProposal(): void {
  if (typeof navigator.vibrate === "function") {
    navigator.vibrate([200, 100, 200]);
  }
  beep();
}

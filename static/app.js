const sessionId = crypto.randomUUID();
const transcript = document.getElementById("transcript");
const stateView = document.getElementById("state-view");
const cards = document.getElementById("cards");
const status = document.getElementById("status");
const micButton = document.getElementById("mic");
const micLabel = document.getElementById("mic-label");
const textInput = document.getElementById("text-input");
const speakToggle = document.getElementById("speak");

let recognition = null;
let recorder = null;
let chunks = [];
let listening = false;
let busy = false;
let voiceBackend = "browser";
let player = null;
let callPoll = null;
// The hosted agent posts turns to /api/convai/turn, which defaults to this session id.
const CALL_SESSION = "convai";

function bubble(role, text, className = "") {
  const node = document.createElement("div");
  node.className = `bubble ${role} ${className}`.trim();
  node.textContent = text;
  transcript.appendChild(node);
  transcript.scrollTop = transcript.scrollHeight;
  return node;
}

function renderState(state, changed = []) {
  const shown = Object.fromEntries(
    Object.entries(state).filter(([, v]) => v !== null && v !== false && !(Array.isArray(v) && v.length === 0))
  );
  const json = JSON.stringify(shown, null, 2);
  stateView.innerHTML = json.replace(/"([a-z_]+)":/g, (match, key) =>
    changed.some((c) => key.includes(c.split(" ")[0])) ? `<span class="changed">"${key}":</span>` : match
  );
}

function renderRecommendations(items) {
  cards.innerHTML = "";
  items.forEach((item) => {
    const card = document.createElement("div");
    card.className = "card";
    const price = item.is_free ? "Free" : item.price_aed != null ? `~${item.price_aed} AED` : "Price not available";
    const hours = item.opening_hours ? ` · ${item.opening_hours}` : "";
    card.innerHTML = `
      <a href="${item.url}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>
      <div class="why">${escapeHtml(item.why || "")}</div>
      <div class="meta">${escapeHtml(price + hours)}${item.verified_at ? " · live-checked" : ""}</div>`;
    cards.appendChild(card);
  });
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

function browserSpeak(text) {
  if (!window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.05;
  utterance.lang = "en-US";
  window.speechSynthesis.speak(utterance);
}

async function speak(text) {
  if (!speakToggle.checked || !text) return;
  stopSpeaking();
  if (voiceBackend !== "elevenlabs") return browserSpeak(text);
  try {
    const response = await fetch("/api/speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!response.ok) throw new Error(await response.text());
    player = new Audio(URL.createObjectURL(await response.blob()));
    await player.play();
  } catch (error) {
    status.textContent = "voice fell back to the browser";
    browserSpeak(text);
  }
}

function stopSpeaking() {
  window.speechSynthesis?.cancel();
  if (player) {
    player.pause();
    player = null;
  }
}

function applyResult(data) {
  bubble("assistant", data.reply);
  if (data.state) renderState(data.state, data.changed || []);
  const results = data.recommendations || data.alternatives;
  if (results) renderRecommendations(results);
  speak(data.reply);
}

async function send(utterance) {
  if (!utterance.trim() || busy) return;
  busy = true;
  bubble("user", utterance);
  const pending = bubble("assistant", "Searching live listings…", "pending");
  status.textContent = "thinking…";
  try {
    const response = await fetch("/api/turn", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: sessionId, utterance }),
    });
    const data = await response.json();
    pending.remove();
    applyResult(data);
  } catch (error) {
    pending.remove();
    bubble("assistant", `Something went wrong: ${error.message}`);
  } finally {
    busy = false;
    status.textContent = "";
  }
}

async function sendAudio(blob) {
  if (busy) return;
  if (blob.size < 2000) {
    bubble("assistant", "I didn't catch that — hold the mic a moment longer?");
    return;
  }
  busy = true;
  const pending = bubble("assistant", "Listening back…", "pending");
  status.textContent = "transcribing…";
  try {
    const form = new FormData();
    form.append("audio", blob, "speech.webm");
    form.append("session_id", sessionId);
    const response = await fetch("/api/voice", { method: "POST", body: form });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    pending.remove();
    if (data.transcript) bubble("user", data.transcript);
    applyResult(data);
  } catch (error) {
    pending.remove();
    bubble("assistant", `Voice failed: ${error.message}`);
  } finally {
    busy = false;
    status.textContent = "";
  }
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recorder = new MediaRecorder(stream);
  chunks = [];
  recorder.ondataavailable = (event) => chunks.push(event.data);
  recorder.onstop = () => {
    stream.getTracks().forEach((track) => track.stop());
    sendAudio(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
  };
  recorder.start();
}

function setupSpeech() {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micButton.disabled = true;
    micLabel.textContent = "Voice unsupported";
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = false;
  recognition.continuous = false;

  recognition.onresult = (event) => {
    const text = event.results[event.results.length - 1][0].transcript;
    send(text);
  };
  recognition.onerror = (event) => {
    status.textContent = `mic: ${event.error}`;
  };
  recognition.onend = () => setListening(false);
}

function setListening(on) {
  listening = on;
  micButton.classList.toggle("listening", on);
  micLabel.textContent = on ? "Listening…" : "Talk";
}

micButton.addEventListener("click", async () => {
  if (listening) {
    if (voiceBackend === "elevenlabs") recorder?.stop();
    else recognition?.stop();
    setListening(false);
    return;
  }
  stopSpeaking();
  try {
    if (voiceBackend === "elevenlabs") await startRecording();
    else if (recognition) recognition.start();
    else return;
    setListening(true);
  } catch (error) {
    status.textContent = `mic: ${error.message}`;
  }
});

document.getElementById("send").addEventListener("click", () => {
  const value = textInput.value;
  textInput.value = "";
  send(value);
});

textInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") document.getElementById("send").click();
});

document.getElementById("reset").addEventListener("click", async () => {
  await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (callPoll) {
    clearInterval(callPoll);
    callPoll = null;
  }
  await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: CALL_SESSION }),
  });
  transcript.innerHTML = "";
  cards.innerHTML = "";
  stateView.textContent = "{}";
  bubble("assistant", "Fresh start. What are you in the mood for?");
});

async function startCall() {
  const config = await (await fetch("/api/convai/session")).json();
  const widget = document.createElement("elevenlabs-convai");
  if (config.signed_url) widget.setAttribute("signed-url", config.signed_url);
  else widget.setAttribute("agent-id", config.agent_id);
  widget.setAttribute("variant", "expanded");
  document.body.appendChild(widget);

  const script = document.createElement("script");
  script.src = "https://unpkg.com/@elevenlabs/convai-widget-embed";
  script.async = true;
  document.body.appendChild(script);

  bubble("assistant", "Live call open — talk to the agent; I'll mirror what it learns here.");
  // The agent drives the conversation, so follow the engine's session instead of posting turns.
  callPoll = setInterval(async () => {
    const snapshot = await (await fetch(`/api/session?session_id=${CALL_SESSION}`)).json();
    renderState(snapshot.state || {});
    if (snapshot.recommendations?.length) renderRecommendations(snapshot.recommendations);
  }, 2000);
}

document.getElementById("call").addEventListener("click", () => {
  const button = document.getElementById("call");
  button.disabled = true;
  startCall().catch((error) => {
    button.disabled = false;
    bubble("assistant", `Couldn't open the call: ${error.message}`);
  });
});

async function detectVoiceBackend() {
  try {
    const health = await (await fetch("/api/health")).json();
    voiceBackend = health.voice_backend || "browser";
    if (health.convai_agent) document.getElementById("call").hidden = false;
  } catch (error) {
    voiceBackend = "browser";
  }
  micButton.title = voiceBackend === "elevenlabs" ? "Talk (ElevenLabs voice)" : micButton.title;
  if (voiceBackend === "elevenlabs" && navigator.mediaDevices?.getUserMedia) {
    micButton.disabled = false;
    micLabel.textContent = "Talk";
  } else {
    setupSpeech();
  }
}

detectVoiceBackend();
bubble("assistant", "Hey! Got some free time? Tell me where you are, how long you've got, and what you feel like.");

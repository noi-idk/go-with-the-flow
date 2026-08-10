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
let listening = false;
let busy = false;

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
    const price = item.is_free ? "Free" : item.price_aed != null ? `~${item.price_aed} AED` : "price not listed";
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

function speak(text) {
  if (!speakToggle.checked || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.05;
  utterance.lang = "en-US";
  window.speechSynthesis.speak(utterance);
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
    bubble("assistant", data.reply);
    renderState(data.state, data.changed || []);
    renderRecommendations(data.recommendations || data.alternatives || []);
    speak(data.reply);
  } catch (error) {
    pending.remove();
    bubble("assistant", `Something went wrong: ${error.message}`);
  } finally {
    busy = false;
    status.textContent = "";
  }
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
  recognition.onend = () => {
    listening = false;
    micButton.classList.remove("listening");
    micLabel.textContent = "Talk";
  };
}

micButton.addEventListener("click", () => {
  if (!recognition) return;
  if (listening) {
    recognition.stop();
    return;
  }
  window.speechSynthesis?.cancel();
  recognition.start();
  listening = true;
  micButton.classList.add("listening");
  micLabel.textContent = "Listening…";
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
  transcript.innerHTML = "";
  cards.innerHTML = "";
  stateView.textContent = "{}";
  bubble("assistant", "Fresh start. What are you in the mood for?");
});

setupSpeech();
bubble("assistant", "Hey! Got some free time? Tell me where you are, how long you've got, and what you feel like.");

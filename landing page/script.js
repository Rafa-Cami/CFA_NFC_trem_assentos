const seats = Array.from(document.querySelectorAll(".seat"));
const simulator = document.querySelector(".simulator");
const scanButton = document.querySelector("#scan-button");
const resetButton = document.querySelector("#reset-button");
const statusOutput = document.querySelector("#simulator-status");

let scanning = false;
let activeSeat = null;

function updateSeat(seat, occupied) {
  seat.setAttribute("aria-pressed", String(occupied));
  seat.querySelector(".seat-state").textContent = occupied ? "Ocupado" : "Livre";
  seat.classList.remove("is-signaled");
  seat.setAttribute(
    "aria-label",
    `${seat.querySelector(".seat-label").textContent}: ${occupied ? "ocupado" : "livre"}`,
  );
}

function availableSeats() {
  return seats.filter((seat) => seat.getAttribute("aria-pressed") === "false");
}

function updateReadyMessage() {
  const count = availableSeats().length;
  if (count === 0) {
    statusOutput.textContent = "Nenhum assento disponível.";
  } else if (count === 1) {
    statusOutput.textContent = "Sistema pronto. Um assento disponível.";
  } else {
    statusOutput.textContent = `Sistema pronto. ${count} assentos disponíveis.`;
  }
}

function clearSignal() {
  if (activeSeat) {
    activeSeat.classList.remove("is-signaled");
    activeSeat = null;
  }
}

seats.forEach((seat) => {
  updateSeat(seat, seat.getAttribute("aria-pressed") === "true");

  seat.addEventListener("click", () => {
    if (scanning) return;

    const nextOccupied = seat.getAttribute("aria-pressed") !== "true";
    if (seat === activeSeat) clearSignal();
    updateSeat(seat, nextOccupied);
    updateReadyMessage();
  });
});

scanButton.addEventListener("click", () => {
  if (scanning) return;

  scanning = true;
  clearSignal();
  simulator.classList.add("is-scanning");
  scanButton.disabled = true;
  statusOutput.textContent = "Sinal NFC recebido. Buscando disponibilidade…";

  window.setTimeout(() => {
    const nextSeat = availableSeats()[0];

    if (nextSeat) {
      activeSeat = nextSeat;
      nextSeat.classList.add("is-signaled");
      statusOutput.textContent = `${nextSeat.querySelector(".seat-label").textContent} sinalizado.`;
    } else {
      statusOutput.textContent = "Nenhum assento livre para sinalizar.";
    }

    simulator.classList.remove("is-scanning");
    scanButton.disabled = false;
    scanning = false;
  }, 760);
});

resetButton.addEventListener("click", () => {
  scanning = false;
  simulator.classList.remove("is-scanning");
  scanButton.disabled = false;
  clearSignal();
  seats.forEach((seat, index) => updateSeat(seat, index === 1));
  updateReadyMessage();
});

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const reveals = document.querySelectorAll(".reveal");

if (reduceMotion || !("IntersectionObserver" in window)) {
  reveals.forEach((item) => item.classList.add("is-visible"));
} else {
  const revealObserver = new IntersectionObserver(
    (entries, observer) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        observer.unobserve(entry.target);
      });
    },
    { threshold: 0.14 },
  );

  reveals.forEach((item) => revealObserver.observe(item));
}

window.addEventListener("DOMContentLoaded", () => {
  if (window.lucide) {
    window.lucide.createIcons({ attrs: { "stroke-width": 1.8 } });
  }
});
